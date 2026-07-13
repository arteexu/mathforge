#!/usr/bin/env python3
"""Blindly pre-label behavior-eval pairs with an Anthropic-compatible judge.

This intentionally writes ``opus_labels.csv`` rather than ``human_labels.csv``.
The labels are model judgments and should be human-reviewed before the standard
behavior report is presented as a human evaluation.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from mathforge.behavior_eval import LABEL_FIELDS, read_jsonl, write_jsonl
from mathforge.llm import make_anthropic_backend


VALIDITY = {"valid", "repairable", "invalid"}


def _tag(name: str, text: str) -> str | None:
    matches = re.findall(
        rf"<{name}>\s*(.*?)\s*</{name}>", text or "", flags=re.I | re.S
    )
    return matches[0].strip() if len(matches) == 1 else None


def _structured_value(name: str, text: str) -> str | None:
    tagged = _tag(name, text)
    if tagged is not None:
        return tagged

    # Accept a strict JSON/Python object if the judge chose that format despite
    # the XML request.
    start, end = (text or "").find("{"), (text or "").rfind("}")
    if 0 <= start < end:
        candidate = (text or "")[start : end + 1]
        for loader in (json.loads, ast.literal_eval):
            try:
                payload = loader(candidate)
            except (ValueError, SyntaxError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict) and name in payload:
                return str(payload[name]).strip()

    # Last-resort support for `validity_a: valid` and similar concise fields.
    flexible_name = re.escape(name).replace("_", r"[_\s-]*")
    match = re.search(
        rf"[\"']?{flexible_name}[\"']?\s*[:=]\s*[\"']?([^\s,;\"'<}}]+)",
        text or "",
        flags=re.I,
    )
    return match.group(1).strip() if match else None


def parse_judgment(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for side in ("a", "b"):
        validity = (_structured_value(f"validity_{side}", text) or "").lower()
        if validity not in VALIDITY:
            raise ValueError(f"invalid validity_{side}: {validity!r}")
        result[f"validity_{side}"] = validity

        for dimension in ("interaction", "novelty", "elegance"):
            raw = _structured_value(f"{dimension}_{side}", text)
            try:
                score = int(raw or "")
            except ValueError as exc:
                raise ValueError(
                    f"invalid {dimension}_{side}: {raw!r}"
                ) from exc
            if score not in range(1, 6):
                raise ValueError(f"invalid {dimension}_{side}: {score}")
            result[f"{dimension}_{side}"] = str(score)

        raw_difficulty = _structured_value(f"difficulty_pass_{side}", text)
        if raw_difficulty not in {"0", "1"}:
            raise ValueError(
                f"invalid difficulty_pass_{side}: {raw_difficulty!r}"
            )
        result[f"difficulty_pass_{side}"] = raw_difficulty

    winner = (_structured_value("winner", text) or "").upper()
    if winner not in {"A", "B", "TIE"}:
        raise ValueError(f"invalid winner: {winner!r}")
    result["winner"] = winner
    result["notes"] = _structured_value("notes", text) or ""
    return result


def render_judge_prompt(pair: dict[str, Any]) -> str:
    return f"""You are the blinded evaluator for a competition-math problem-generation benchmark.
Do not infer which model produced either output. Independently check the mathematics.

Validity rubric:
- valid: the problem is self-contained and well-posed, has the claimed unique integer answer, and the supplied solution is correct.
- repairable: one localized issue can be fixed without changing the central construction or answer.
- invalid: a substantive mathematical, uniqueness, statement, answer, or solution failure exists.

For each output, score technique interaction, novelty, and elegance from 1 to 5.
Difficulty pass is 1 only when the requested band is met. Mathematical validity is
the hard gate. XML-format adherence is recorded separately by the benchmark, so do
not call an otherwise correct problem mathematically invalid solely for missing tags.
Choose the overall winner validity-first, then by genuine technique interaction,
difficulty fit, novelty, elegance, and instruction fulfillment. A materially invalid
output must lose to a valid output.

GENERATION BRIEF
{pair['prompt']}

OUTPUT A
{pair['output_a']}

OUTPUT B
{pair['output_b']}

Return exactly these tags with no Markdown fence:
<validity_a>valid|repairable|invalid</validity_a>
<interaction_a>1|2|3|4|5</interaction_a>
<novelty_a>1|2|3|4|5</novelty_a>
<elegance_a>1|2|3|4|5</elegance_a>
<difficulty_pass_a>0|1</difficulty_pass_a>
<validity_b>valid|repairable|invalid</validity_b>
<interaction_b>1|2|3|4|5</interaction_b>
<novelty_b>1|2|3|4|5</novelty_b>
<elegance_b>1|2|3|4|5</elegance_b>
<difficulty_pass_b>0|1</difficulty_pass_b>
<winner>A|B|TIE</winner>
<notes>brief mathematical justification, including any decisive flaw</notes>"""


def _write_csv(path: Path, pairs: list[dict[str, Any]], records: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LABEL_FIELDS)
        writer.writeheader()
        for pair in pairs:
            pair_id = pair["pair_id"]
            if pair_id in records:
                writer.writerow({"pair_id": pair_id, **records[pair_id]["label"]})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blind-dir", type=Path, required=True)
    parser.add_argument("--judge-model", default="claude-opus-4-8")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--journal", type=Path)
    parser.add_argument("--max-output-tokens", type=int, default=900)
    parser.add_argument("--timeout", type=float, default=360.0)
    parser.add_argument("--attempts", type=int, default=2)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    pairs = read_jsonl(args.blind_dir / "blind_pairs.jsonl")
    output = args.output or args.blind_dir / "opus_labels.csv"
    journal = args.journal or args.blind_dir / "opus_judgments.jsonl"

    if journal.exists() and not args.resume:
        raise SystemExit(f"journal already exists; pass --resume: {journal}")
    prior = read_jsonl(journal) if journal.exists() else []
    records = {str(row["pair_id"]): row for row in prior}
    if any(row.get("judge_model") != args.judge_model for row in prior):
        raise SystemExit("existing journal uses a different judge model")

    backend = make_anthropic_backend(
        args.judge_model,
        max_output_tokens=args.max_output_tokens,
        timeout=args.timeout,
    )

    for index, pair in enumerate(pairs, 1):
        pair_id = str(pair["pair_id"])
        if pair_id in records:
            print(f"[{index:02d}/{len(pairs)}] {pair_id} already judged", flush=True)
            continue
        prompt = render_judge_prompt(pair)
        error: Exception | None = None
        failure_path = args.blind_dir / "opus_parse_failures.jsonl"
        attempt_prompt = prompt
        for attempt in range(1, args.attempts + 1):
            completion = backend(attempt_prompt)
            try:
                label = parse_judgment(completion.text)
            except ValueError as exc:
                error = exc
                with failure_path.open("a", encoding="utf-8") as handle:
                    handle.write(
                        json.dumps(
                            {
                                "pair_id": pair_id,
                                "attempt": attempt,
                                "error": str(exc),
                                "raw_response": completion.text,
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                print(
                    f"[{index:02d}/{len(pairs)}] {pair_id} parse attempt "
                    f"{attempt}/{args.attempts}: {exc}",
                    flush=True,
                )
                attempt_prompt = (
                    "Your prior answer could not be parsed. Do not explain your "
                    "reasoning and do not use JSON or Markdown. Re-evaluate the same "
                    "blind pair below, then emit the twelve requested XML tags "
                    "immediately and exactly once.\n\n" + prompt
                )
                continue
            raw = completion.raw if isinstance(completion.raw, dict) else {}
            record = {
                "schema_version": "behavior-opus-judgment-v1",
                "pair_id": pair_id,
                "judge_model": args.judge_model,
                "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                "label": label,
                "raw_response": completion.text,
                "request_id": raw.get("request_id"),
                "prompt_tokens": completion.prompt_tokens,
                "completion_tokens": completion.completion_tokens,
            }
            records[pair_id] = record
            write_jsonl(journal, [records[p["pair_id"]] for p in pairs if p["pair_id"] in records])
            _write_csv(output, pairs, records)
            print(f"[{index:02d}/{len(pairs)}] {pair_id} judged", flush=True)
            break
        else:
            raise SystemExit(f"could not parse judgment for {pair_id}: {error}")

    _write_csv(output, pairs, records)
    print(f"wrote {len(records)} blind model judgments to {output}")
    print("Human-review this prefill before renaming it human_labels.csv.")


if __name__ == "__main__":
    main()
