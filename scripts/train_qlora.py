"""QLoRA fine-tune a small instruct model to GENERATE elegant competition problems.

Colab-ready and built for an unattended OVERNIGHT run:
  * every knob is an env var, so the notebook sets config without editing this file
  * trains only on elegant keepers by default (MIN_PROBLEM_ELEGANCE=3.5)
  * holds out a small eval split so you can watch eval_loss for overfitting
  * checkpoints every SAVE_STEPS and AUTO-RESUMES from the last checkpoint, so a
    Colab disconnect at 3am costs you minutes, not the whole run
  * point OUT at a Google Drive folder to survive a VM reset

It adapts a model that already knows math + prose (LoRA on a 4-bit base); it does
NOT train from scratch. Requires a CUDA GPU (bitsandbytes 4-bit) -> use Colab, not a Mac.

Colab (see notebooks/mathforge_qlora_colab.ipynb):
    !pip install -q -U transformers peft trl bitsandbytes accelerate datasets
    !git clone https://github.com/arteexu/mathforge.git && cd mathforge
    !python scripts/train_qlora.py
"""

from __future__ import annotations

import os

import torch
from datasets import load_dataset
from peft import LoraConfig
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from transformers.trainer_utils import get_last_checkpoint
from trl import SFTConfig, SFTTrainer


def _env(name, default, cast=str):
    v = os.environ.get(name)
    return cast(v) if v is not None and v != "" else default


# --- config (all overridable via env) -------------------------------------- #
BASE_MODEL = _env("BASE_MODEL", "Qwen/Qwen2.5-1.5B-Instruct")  # 3B on A100/L4
DATA = _env("DATA", "data/train.jsonl")
OUT = _env("OUT", "mathforge-qlora")                 # set to a Drive path to persist
MIN_PROBLEM_ELEGANCE = _env("MIN_PROBLEM_ELEGANCE", 3.5, float)
ANSWER_TYPE = _env("ANSWER_TYPE", "")                # "integer" to keep AIME-style only
EPOCHS = _env("EPOCHS", 3, float)
LR = _env("LR", 2e-4, float)
MAX_SEQ_LEN = _env("MAX_SEQ_LEN", 2048, int)
BATCH = _env("BATCH", 1, int)
GRAD_ACCUM = _env("GRAD_ACCUM", 8, int)
LORA_R = _env("LORA_R", 16, int)
EVAL_FRACTION = _env("EVAL_FRACTION", 0.03, float)
SAVE_STEPS = _env("SAVE_STEPS", 50, int)
SEED = _env("SEED", 42, int)


def main() -> None:
    tok = AutoTokenizer.from_pretrained(BASE_MODEL)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

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
    model.gradient_checkpointing_enable()  # trade compute for memory on a small GPU

    lora = LoraConfig(
        r=LORA_R, lora_alpha=2 * LORA_R, lora_dropout=0.05, bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
    )

    ds = load_dataset("json", data_files=DATA, split="train")
    n_all = len(ds)
    if MIN_PROBLEM_ELEGANCE > 0:
        ds = ds.filter(lambda r: (r["meta"].get("problem_elegance") or 0) >= MIN_PROBLEM_ELEGANCE)
    if ANSWER_TYPE:
        ds = ds.filter(lambda r: r["meta"].get("answer_type") == ANSWER_TYPE)

    def fmt(r):
        return {"text": tok.apply_chat_template(r["messages"], tokenize=False)}
    ds = ds.map(fmt, remove_columns=ds.column_names)

    # small held-out eval split to watch for overfitting overnight
    split = ds.train_test_split(test_size=EVAL_FRACTION, seed=SEED)
    train_ds, eval_ds = split["train"], split["test"]
    print(f"data: {n_all} total -> {len(ds)} after filters "
          f"(PE>={MIN_PROBLEM_ELEGANCE}, answer_type='{ANSWER_TYPE or 'any'}') "
          f"-> train {len(train_ds)} / eval {len(eval_ds)}", flush=True)

    cfg = SFTConfig(
        output_dir=OUT,
        num_train_epochs=EPOCHS,
        per_device_train_batch_size=BATCH,
        gradient_accumulation_steps=GRAD_ACCUM,
        learning_rate=LR,
        warmup_ratio=0.05,
        lr_scheduler_type="cosine",
        logging_steps=5,
        eval_strategy="steps",
        eval_steps=SAVE_STEPS,
        save_strategy="steps",
        save_steps=SAVE_STEPS,
        save_total_limit=3,
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        bf16=True,
        max_length=MAX_SEQ_LEN,
        packing=False,
        dataset_text_field="text",
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        seed=SEED,
        report_to="none",
    )
    trainer = SFTTrainer(
        model=model, args=cfg, train_dataset=train_ds,
        eval_dataset=eval_ds, peft_config=lora,
    )

    # auto-resume: if OUT already holds checkpoints (Colab reconnect), continue.
    resume = None
    if os.path.isdir(OUT):
        resume = get_last_checkpoint(OUT)
        if resume:
            print(f"resuming from checkpoint: {resume}", flush=True)
    trainer.train(resume_from_checkpoint=resume)

    trainer.save_model(OUT)
    tok.save_pretrained(OUT)
    print(f"saved LoRA adapter to {OUT}/", flush=True)

    # quick smoke sample so you wake up to evidence it learned something
    model.config.use_cache = True
    prompt = ("Compose one original, elegant AIME/olympiad-level competition math problem "
              "with a single integer answer in [0, 999]. Topic: Number Theory. "
              "Target difficulty (AoPS 1-10): 6.5. Target problem-elegance (0-5): 4.5. "
              "Give the statement, then a clean solution ending in the integer answer.")
    ids = tok.apply_chat_template(
        [{"role": "user", "content": prompt}],
        add_generation_prompt=True, return_tensors="pt",
    ).to(model.device)
    out = model.generate(ids, max_new_tokens=600, do_sample=True, temperature=0.9, top_p=0.95)
    print("\n=== SAMPLE GENERATION ===\n" + tok.decode(out[0][ids.shape[1]:], skip_special_tokens=True))


if __name__ == "__main__":
    main()
