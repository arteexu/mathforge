"""QLoRA fine-tune a small instruct model to GENERATE elegant competition problems.

Colab-ready. Recommended runtime: T4 (free) for 1.5B, A100/L4 (Pro) for 3B-7B.
This trains LoRA adapters on top of a 4-bit base model using the chat-format
dataset produced by scripts/export_dataset.py (conditioned on target
difficulty + elegance). It does NOT train from scratch -- with ~200 examples that
would be hopeless; we adapt a model that already knows math and prose.

Colab setup (run once, in a cell):
    !pip install -q -U transformers peft trl bitsandbytes accelerate datasets
    !git clone https://github.com/arteexu/mathforge.git
    %cd mathforge
    # data/train.jsonl is committed in the repo, so it's ready to use.
    # (To rebuild it from a fresh mathforge.db locally: PYTHONPATH=src python scripts/export_dataset.py)

Then: python scripts/train_qlora.py
"""

from __future__ import annotations

import torch
from datasets import load_dataset
from peft import LoraConfig
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from trl import SFTConfig, SFTTrainer

# --- config ---------------------------------------------------------------- #
BASE_MODEL = "Qwen/Qwen2.5-1.5B-Instruct"   # -> "Qwen/Qwen2.5-3B-Instruct" on A100
DATA = "data/train.jsonl"                    # chat-format {"messages":[...], "meta":{...}}
OUT = "mathforge-qlora"
MIN_PROBLEM_ELEGANCE = 0.0                    # e.g. 3.5 to train only on elegant keepers
EPOCHS = 3
MAX_SEQ_LEN = 2048


def main() -> None:
    tok = AutoTokenizer.from_pretrained(BASE_MODEL)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    # 4-bit base (QLoRA)
    bnb = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )
    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL, quantization_config=bnb, device_map="auto",
        torch_dtype=torch.bfloat16,
    )
    model.config.use_cache = False

    # LoRA: low rank keeps a tiny dataset from overfitting the base model.
    lora = LoraConfig(
        r=16, lora_alpha=32, lora_dropout=0.05, bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
    )

    ds = load_dataset("json", data_files=DATA, split="train")
    if MIN_PROBLEM_ELEGANCE > 0:
        ds = ds.filter(lambda r: (r["meta"].get("problem_elegance") or 0) >= MIN_PROBLEM_ELEGANCE)
    # render chat -> single training string via the model's chat template
    def fmt(r):
        return {"text": tok.apply_chat_template(r["messages"], tokenize=False)}
    ds = ds.map(fmt, remove_columns=ds.column_names)
    print(f"training on {len(ds)} examples")

    cfg = SFTConfig(
        output_dir=OUT,
        num_train_epochs=EPOCHS,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=8,
        learning_rate=2e-4,
        warmup_ratio=0.05,
        lr_scheduler_type="cosine",
        logging_steps=5,
        save_strategy="epoch",
        bf16=True,
        max_seq_length=MAX_SEQ_LEN,
        packing=False,
        dataset_text_field="text",
        report_to="none",
    )
    trainer = SFTTrainer(model=model, args=cfg, train_dataset=ds, peft_config=lora)
    trainer.train()
    trainer.save_model(OUT)
    tok.save_pretrained(OUT)
    print(f"saved LoRA adapter to {OUT}/")

    # quick smoke sample
    model.config.use_cache = True
    prompt = ("Compose one original, elegant AIME/olympiad-level competition math problem "
              "with a single integer answer in [0, 999]. Topic: Number Theory. "
              "Target difficulty (AoPS 1-10): 6.5. Target problem-elegance (0-5): 4.5. "
              "Give the statement, then a clean solution ending in the integer answer.")
    msgs = [{"role": "user", "content": prompt}]
    ids = tok.apply_chat_template(msgs, add_generation_prompt=True, return_tensors="pt").to(model.device)
    out = model.generate(ids, max_new_tokens=600, do_sample=True, temperature=0.9, top_p=0.95)
    print(tok.decode(out[0][ids.shape[1]:], skip_special_tokens=True))


if __name__ == "__main__":
    main()
