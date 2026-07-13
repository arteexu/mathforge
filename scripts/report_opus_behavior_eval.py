#!/usr/bin/env python3
"""Build a transparent report from blinded Opus behavior judgments."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any

from mathforge.behavior_eval import LABEL_FIELDS, read_jsonl

from judge_behavior_eval_opus import render_judge_prompt


DIMENSIONS = ("interaction", "novelty", "elegance")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blind-dir", type=Path, required=True)
    parser.add_argument("--judgments", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    pairs = read_jsonl(args.blind_dir / "blind_pairs.jsonl")
    key = json.loads((args.blind_dir / "blind_key.json").read_text())
    judgments = {row["pair_id"]: row for row in read_jsonl(args.judgments)}
    pair_ids = {pair["pair_id"] for pair in pairs}
    if set(judgments) != pair_ids or set(key) != pair_ids:
        raise SystemExit("pair IDs in pairs, key, and judgments do not match")

    for pair in pairs:
        expected = hashlib.sha256(render_judge_prompt(pair).encode()).hexdigest()
        if judgments[pair["pair_id"]].get("prompt_sha256") != expected:
            raise SystemExit(f"judge prompt hash mismatch: {pair['pair_id']}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    labels_path = args.output_dir / "opus_labels.csv"
    with labels_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LABEL_FIELDS)
        writer.writeheader()
        for pair in pairs:
            writer.writerow(
                {"pair_id": pair["pair_id"], **judgments[pair["pair_id"]]["label"]}
            )

    stats: dict[str, dict[str, Any]] = {
        arm: {
            "validity": Counter(),
            "interaction": [],
            "novelty": [],
            "elegance": [],
            "difficulty_passes": 0,
            "content_gate_passes": 0,
            "strict_format_passes": 0,
            "strict_all_gate_passes": 0,
        }
        for arm in ("slm", "frontier")
    }
    wins = Counter()
    outcomes = []
    for pair in pairs:
        pair_id = pair["pair_id"]
        label = judgments[pair_id]["label"]
        mapping = key[pair_id]
        winner = label["winner"].lower()
        winner_arm = "tie" if winner == "tie" else mapping[winner]
        wins[winner_arm] += 1
        row: dict[str, Any] = {"pair_id": pair_id, "winner": winner_arm}
        for side, arm in mapping.items():
            validity = label[f"validity_{side}"]
            values = {name: int(label[f"{name}_{side}"]) for name in DIMENSIONS}
            difficulty = int(label[f"difficulty_pass_{side}"])
            format_pass = bool(pair[f"parse_{side}"]["format_pass"])
            content_pass = (
                validity == "valid"
                and values["interaction"] >= 4
                and values["novelty"] >= 3
                and values["elegance"] >= 3
                and difficulty == 1
            )
            arm_stats = stats[arm]
            arm_stats["validity"][validity] += 1
            for name, value in values.items():
                arm_stats[name].append(value)
            arm_stats["difficulty_passes"] += difficulty
            arm_stats["content_gate_passes"] += int(content_pass)
            arm_stats["strict_format_passes"] += int(format_pass)
            arm_stats["strict_all_gate_passes"] += int(content_pass and format_pass)
            row[arm] = {
                "validity": validity,
                **values,
                "difficulty_pass": difficulty,
                "format_pass": format_pass,
                "content_gate_pass": content_pass,
            }
        outcomes.append(row)

    arm_summary = {}
    for arm, values in stats.items():
        arm_summary[arm] = {
            "validity": {
                name: values["validity"].get(name, 0)
                for name in ("valid", "repairable", "invalid")
            },
            "mean_interaction": round(mean(values["interaction"]), 3),
            "mean_novelty": round(mean(values["novelty"]), 3),
            "mean_elegance": round(mean(values["elegance"]), 3),
            "difficulty_passes": values["difficulty_passes"],
            "content_gate_passes": values["content_gate_passes"],
            "strict_format_passes": values["strict_format_passes"],
            "strict_all_gate_passes": values["strict_all_gate_passes"],
        }

    judge_models = sorted({row["judge_model"] for row in judgments.values()})
    summary = {
        "schema_version": "behavior-opus-report-v1",
        "pairs": len(pairs),
        "families": len({pair["family_id"] for pair in pairs}),
        "judge_models": judge_models,
        "frontier_generator_model": "claude-opus-4-8",
        "self_judge_caveat": True,
        "pairwise": {
            "slm_wins": wins["slm"],
            "frontier_wins": wins["frontier"],
            "ties": wins["tie"],
        },
        "arms": arm_summary,
        "outcomes": outcomes,
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    slm, frontier = arm_summary["slm"], arm_summary["frontier"]
    report = f"""# MathForge basic behavior evaluation — Opus-blind-judged pilot

## Result

This 24-pair pilot does **not** show the SLM beating the frontier model. Claude
Opus 4.8 preferred the frontier output in {wins['frontier']}/24 pairs, the SLM in
{wins['slm']}/24, with {wins['tie']} ties. All four SLM wins occurred when both
outputs were still judged mathematically invalid.

| Metric | SLM | Frontier |
|---|---:|---:|
| Valid | {slm['validity']['valid']}/24 | {frontier['validity']['valid']}/24 |
| Repairable | {slm['validity']['repairable']}/24 | {frontier['validity']['repairable']}/24 |
| Invalid | {slm['validity']['invalid']}/24 | {frontier['validity']['invalid']}/24 |
| Mean technique interaction (1–5) | {slm['mean_interaction']:.3f} | {frontier['mean_interaction']:.3f} |
| Mean novelty (1–5) | {slm['mean_novelty']:.3f} | {frontier['mean_novelty']:.3f} |
| Mean elegance (1–5) | {slm['mean_elegance']:.3f} | {frontier['mean_elegance']:.3f} |
| Difficulty pass | {slm['difficulty_passes']}/24 | {frontier['difficulty_passes']}/24 |
| Content-gate pass | {slm['content_gate_passes']}/24 | {frontier['content_gate_passes']}/24 |
| Strict format pass | {slm['strict_format_passes']}/24 | {frontier['strict_format_passes']}/24 |
| Strict all-gates pass | {slm['strict_all_gate_passes']}/24 | {frontier['strict_all_gate_passes']}/24 |

## Interpretation

The dominant failure is mathematical validity, not merely formatting. Opus
marked every SLM output invalid. Its notes repeatedly cite wrong or unsupported
answers, incoherent or duplicated solution text, failure to use the requested
techniques, and incomplete generations. Frontier outputs showed stronger
technique interaction, but only one was fully valid; truncation and incorrect or
unsupported final answers remained common.

Strict format is a separate failure: neither model produced a parser-passing
response. Accordingly, the formal all-gates result is 0/24 for both arms. The
content-only scores above are included diagnostically and do not replace the
frozen strict metric.

## Method and limitations

- Frozen suite: 12 technique-interaction briefs, two repetitions each.
- Generation: identical rendered prompts and a 1,200-token output ceiling.
- Pairing: A/B order randomized before judgment.
- Judge: {', '.join(judge_models)}; identities hidden during judging.
- Prompt hashes for all 24 judgments match the preserved blind pairs.
- The frontier generator and judge are both Opus 4.8. This creates a material
  self-preference risk, so the result is an exploratory model-judged pilot, not
  an independent or human evaluation.
- The suite is small and public. It is unsuitable for a superiority claim.

## Demo-safe conclusion

On this pilot, the trained SLM did not beat Opus 4.8. The experiment identified
a concrete bottleneck: the current adapter does not reliably follow the target
generation schema or produce mathematically valid, technique-faithful problems.
The next iteration should prioritize clean target formatting, shorter complete
solutions, validity-filtered training examples, and a rerun with an independent
judge family.
"""
    (args.output_dir / "report.md").write_text(report, encoding="utf-8")
    print(f"wrote report artifacts to {args.output_dir}")


if __name__ == "__main__":
    main()
