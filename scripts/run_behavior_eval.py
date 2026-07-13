#!/usr/bin/env python3
"""Run the basic frozen MathForge SLM-versus-frontier behavior benchmark."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from mathforge.behavior_eval import (
    blind_pairs,
    build_report,
    load_suite,
    parse_generation,
    read_jsonl,
    render_scenario,
    write_jsonl,
    write_label_template,
)
from mathforge.llm import make_anthropic_backend, make_openai_backend

DEFAULT_SUITE = Path("eval/behavior_suite_basic_v1.jsonl")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_path(output: Path) -> Path:
    return output.with_suffix(output.suffix + ".manifest.json")


def _prepare_output(
    output: Path, manifest: dict[str, Any], *, resume: bool
) -> list[dict[str, Any]]:
    manifest_path = _manifest_path(output)
    if output.exists() or manifest_path.exists():
        if not resume or not output.exists() or not manifest_path.exists():
            raise ValueError(f"output already exists; pass --resume: {output}")
        prior = json.loads(manifest_path.read_text(encoding="utf-8"))
        if prior != manifest:
            raise ValueError("existing generation manifest does not match this run")
        return read_jsonl(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    write_jsonl(output, [])
    return []


def _base_manifest(
    *,
    arm: str,
    model: str,
    suite_hash: str,
    repeats: int,
    temperature: float,
    top_p: float,
    max_new_tokens: int,
    seed: int,
) -> dict[str, Any]:
    return {
        "schema_version": "behavior-generation-run-v1",
        "suite_hash": suite_hash,
        "arm": arm,
        "model": model,
        "repeats": repeats,
        "temperature": temperature,
        "top_p": top_p,
        "max_new_tokens": max_new_tokens,
        "seed": seed,
    }


def _run_records(
    *,
    suite: list[dict[str, Any]],
    output: Path,
    existing: list[dict[str, Any]],
    arm: str,
    model: str,
    repeats: int,
    seed: int,
    generate: Callable[[str, int], tuple[str, dict[str, Any]]],
) -> None:
    records = list(existing)
    completed = {
        (str(row["scenario_id"]), int(row["repeat_index"])) for row in records
    }
    for scenario_index, scenario in enumerate(suite):
        prompt = render_scenario(scenario)
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        for repeat_index in range(1, repeats + 1):
            key = (scenario["scenario_id"], repeat_index)
            if key in completed:
                continue
            generation_seed = seed + scenario_index * 100 + repeat_index
            started = time.perf_counter()
            text, usage = generate(prompt, generation_seed)
            latency_ms = (time.perf_counter() - started) * 1000.0
            record = {
                "schema_version": "behavior-generation-v1",
                "arm": arm,
                "model": model,
                "scenario_id": scenario["scenario_id"],
                "family_id": scenario["family_id"],
                "variant": scenario["variant"],
                "topic": scenario["topic"],
                "target_difficulty": scenario["target_difficulty"],
                "technique_ids": scenario["technique_ids"],
                "technique_names": scenario["technique_names"],
                "repeat_index": repeat_index,
                "generation_seed": generation_seed if arm == "slm" else None,
                "prompt_sha256": prompt_hash,
                "prompt": prompt,
                "output": text,
                "parse": parse_generation(text),
                "latency_ms": round(latency_ms, 3),
                "usage": usage,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
            records.append(record)
            completed.add(key)
            write_jsonl(output, records)
            print(
                f"[{len(records):03d}/{len(suite) * repeats}] "
                f"{scenario['scenario_id']} r{repeat_index} "
                f"format={record['parse']['format_pass']}",
                flush=True,
            )


def command_slm(args: argparse.Namespace) -> None:
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    suite, suite_hash = load_suite(args.suite)
    adapter = Path(args.adapter)
    adapter_file = adapter / "adapter_model.safetensors"
    if not adapter_file.exists():
        raise FileNotFoundError(adapter_file)
    manifest = _base_manifest(
        arm="slm",
        model=args.base_model,
        suite_hash=suite_hash,
        repeats=args.repeats,
        temperature=args.temperature,
        top_p=args.top_p,
        max_new_tokens=args.max_new_tokens,
        seed=args.seed,
    )
    manifest.update(
        {
            "adapter": str(adapter),
            "adapter_sha256": _sha256_file(adapter_file),
        }
    )
    existing = _prepare_output(args.output, manifest, resume=args.resume)
    tokenizer = AutoTokenizer.from_pretrained(args.base_model)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    quantization = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=dtype,
        bnb_4bit_use_double_quant=True,
    )
    base = AutoModelForCausalLM.from_pretrained(
        args.base_model,
        quantization_config=quantization,
        device_map="auto",
        torch_dtype=dtype,
    )
    model = PeftModel.from_pretrained(base, adapter)
    model.eval()
    model.config.use_cache = True

    def generate(prompt: str, generation_seed: int) -> tuple[str, dict[str, Any]]:
        torch.manual_seed(generation_seed)
        torch.cuda.manual_seed_all(generation_seed)
        inputs = tokenizer.apply_chat_template(
            [{"role": "user", "content": prompt}],
            add_generation_prompt=True,
            return_tensors="pt",
            return_dict=True,
        ).to(model.device)
        with torch.no_grad():
            output = model.generate(
                **inputs,
                max_new_tokens=args.max_new_tokens,
                do_sample=True,
                temperature=args.temperature,
                top_p=args.top_p,
                pad_token_id=tokenizer.eos_token_id,
            )
        completion = output[0][inputs["input_ids"].shape[1] :]
        return tokenizer.decode(completion, skip_special_tokens=True), {
            "prompt_tokens": int(inputs["input_ids"].shape[1]),
            "completion_tokens": int(completion.shape[0]),
        }

    _run_records(
        suite=suite,
        output=args.output,
        existing=existing,
        arm="slm",
        model=args.base_model,
        repeats=args.repeats,
        seed=args.seed,
        generate=generate,
    )


def command_frontier(args: argparse.Namespace) -> None:
    suite, suite_hash = load_suite(args.suite)
    manifest = _base_manifest(
        arm="frontier",
        model=args.model,
        suite_hash=suite_hash,
        repeats=args.repeats,
        temperature=args.temperature,
        top_p=args.top_p,
        max_new_tokens=args.max_new_tokens,
        seed=args.seed,
    )
    manifest["provider"] = args.provider
    existing = _prepare_output(args.output, manifest, resume=args.resume)
    if args.provider == "anthropic":
        backend = make_anthropic_backend(
            args.model,
            max_output_tokens=args.max_new_tokens,
            default_temperature=args.temperature,
            timeout=args.timeout,
        )
    else:
        backend = make_openai_backend(
            args.model,
            max_output_tokens=args.max_new_tokens,
            default_temperature=args.temperature,
        )

    def generate(prompt: str, _: int) -> tuple[str, dict[str, Any]]:
        completion = backend(
            prompt, temperature=args.temperature, top_p=args.top_p
        )
        raw = completion.raw if isinstance(completion.raw, dict) else {}
        return completion.text, {
            "prompt_tokens": completion.prompt_tokens,
            "completion_tokens": completion.completion_tokens,
            "request_id": raw.get("request_id"),
            "stop_reason": raw.get("stop_reason") or raw.get("finish_reason"),
        }

    _run_records(
        suite=suite,
        output=args.output,
        existing=existing,
        arm="frontier",
        model=args.model,
        repeats=args.repeats,
        seed=args.seed,
        generate=generate,
    )


def command_blind(args: argparse.Namespace) -> None:
    output = args.output_dir
    if output.exists() and any(output.iterdir()) and not args.force:
        raise ValueError(f"blind output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    pairs, key_rows = blind_pairs(
        read_jsonl(args.slm), read_jsonl(args.frontier), seed=args.seed
    )
    write_jsonl(output / "blind_pairs.jsonl", pairs)
    (output / "blind_key.json").write_text(
        json.dumps(key_rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    write_label_template(output / "human_labels.csv", pairs)
    packet = [
        "# Blind MathForge behavior review",
        "",
        "For each side, label validity as `valid`, `repairable`, or `invalid`; score technique interaction, novelty, and elegance from 1-5; and mark difficulty pass as 0 or 1. A materially invalid output must lose to a valid output. Record the overall winner as A, B, or TIE in `human_labels.csv`.",
        "",
    ]
    for pair in pairs:
        packet.extend(
            [
                f"## {pair['pair_id']}",
                "",
                f"Topic: {pair['topic']}  ",
                f"Target difficulty: {pair['target_difficulty']}  ",
                f"Required techniques: {pair['required_techniques']}",
                "",
                "### Output A",
                "",
                pair["output_a"],
                "",
                "### Output B",
                "",
                pair["output_b"],
                "",
            ]
        )
    (output / "review_packet.md").write_text(
        "\n".join(packet), encoding="utf-8"
    )
    print(f"wrote {len(pairs)} blind pairs and label template to {output}")


def command_report(args: argparse.Namespace) -> None:
    pairs = read_jsonl(args.blind_dir / "blind_pairs.jsonl")
    key_rows = json.loads(
        (args.blind_dir / "blind_key.json").read_text(encoding="utf-8")
    )
    summary = build_report(
        pairs,
        key_rows,
        args.blind_dir / "human_labels.csv",
        bootstrap_samples=args.bootstrap_samples,
        seed=args.seed,
    )
    (args.blind_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    gates = summary["all_gates"]
    lines = [
        "# Basic MathForge behavior evaluation",
        "",
        f"Pairs: {summary['pairs']} across {summary['families']} families",
        "",
        f"- SLM all-gates: {gates['slm_passes']}/{summary['pairs']} ({100*gates['slm_rate']:.1f}%)",
        f"- Frontier all-gates: {gates['frontier_passes']}/{summary['pairs']} ({100*gates['frontier_rate']:.1f}%)",
        f"- Paired delta: {100*gates['paired_delta']:.1f} percentage points",
        f"- Family-bootstrap 95% CI: [{100*gates['family_bootstrap_95_ci'][0]:.1f}, {100*gates['family_bootstrap_95_ci'][1]:.1f}] points",
        f"- Pairwise: {summary['pairwise']}",
        "",
    ]
    (args.blind_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    common.add_argument("--repeats", type=int, default=2)
    common.add_argument("--temperature", type=float, default=0.8)
    common.add_argument("--top-p", type=float, default=0.95)
    common.add_argument("--max-new-tokens", type=int, default=1200)
    common.add_argument("--seed", type=int, default=20260712)
    common.add_argument("--resume", action="store_true")

    slm = subparsers.add_parser("slm", parents=[common])
    slm.add_argument("--base-model", default="Qwen/Qwen2.5-Math-7B-Instruct")
    slm.add_argument("--adapter", required=True)
    slm.add_argument("--output", type=Path, required=True)
    slm.set_defaults(func=command_slm)

    frontier = subparsers.add_parser("frontier", parents=[common])
    frontier.add_argument("--provider", choices=("anthropic", "openai"), default="anthropic")
    frontier.add_argument("--model", required=True)
    frontier.add_argument("--timeout", type=float, default=360.0)
    frontier.add_argument("--output", type=Path, required=True)
    frontier.set_defaults(func=command_frontier)

    blind = subparsers.add_parser("blind")
    blind.add_argument("--slm", type=Path, required=True)
    blind.add_argument("--frontier", type=Path, required=True)
    blind.add_argument("--output-dir", type=Path, required=True)
    blind.add_argument("--seed", type=int, default=20260712)
    blind.add_argument("--force", action="store_true")
    blind.set_defaults(func=command_blind)

    report = subparsers.add_parser("report")
    report.add_argument("--blind-dir", type=Path, required=True)
    report.add_argument("--bootstrap-samples", type=int, default=5000)
    report.add_argument("--seed", type=int, default=20260712)
    report.set_defaults(func=command_report)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        args.func(args)
    except (ValueError, FileNotFoundError) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
