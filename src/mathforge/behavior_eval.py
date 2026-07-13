"""Small, reproducible behavior benchmark helpers for problem generators."""

from __future__ import annotations

import csv
import hashlib
import json
import random
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from mathforge.integrity import normalize_aime_answer
from mathforge.prompts import render_prompt

SUITE_VERSION = "behavior-suite-basic-v1"
PROMPT_VERSION = "behavior_generation_v1"
LABEL_FIELDS = [
    "pair_id",
    "validity_a",
    "interaction_a",
    "novelty_a",
    "elegance_a",
    "difficulty_pass_a",
    "validity_b",
    "interaction_b",
    "novelty_b",
    "elegance_b",
    "difficulty_pass_b",
    "winner",
    "notes",
]


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def read_jsonl(path: Path | str) -> list[dict[str, Any]]:
    rows = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON on line {line_number}: {path}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"line {line_number} must contain an object")
        rows.append(value)
    return rows


def write_jsonl(path: Path | str, rows: Iterable[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def load_suite(path: Path | str) -> tuple[list[dict[str, Any]], str]:
    rows = read_jsonl(path)
    if not rows:
        raise ValueError("behavior suite is empty")
    seen: set[str] = set()
    for row in rows:
        scenario_id = str(row.get("scenario_id") or "")
        if not scenario_id or scenario_id in seen:
            raise ValueError(f"missing or duplicate scenario_id: {scenario_id!r}")
        seen.add(scenario_id)
        if row.get("suite_version") != SUITE_VERSION:
            raise ValueError(f"unsupported suite version for {scenario_id}")
        ids = row.get("technique_ids")
        names = row.get("technique_names")
        if not isinstance(ids, list) or len(ids) != 2 or len(set(ids)) != 2:
            raise ValueError(f"{scenario_id} must require two distinct techniques")
        if not isinstance(names, list) or len(names) != 2:
            raise ValueError(f"{scenario_id} must name both techniques")
        band = row.get("target_difficulty")
        if not isinstance(band, list) or len(band) != 2:
            raise ValueError(f"{scenario_id} has an invalid difficulty band")
        low, high = float(band[0]), float(band[1])
        if not 1 <= low <= high <= 10:
            raise ValueError(f"{scenario_id} has an invalid difficulty band")
    return rows, _stable_hash(rows)


def render_scenario(scenario: dict[str, Any]) -> str:
    low, high = scenario["target_difficulty"]
    return render_prompt(
        PROMPT_VERSION,
        topic=scenario["topic"],
        target_difficulty=f"{float(low):g}-{float(high):g}",
        technique_1=scenario["technique_names"][0],
        technique_2=scenario["technique_names"][1],
        crux_brief=scenario["crux_brief"],
        extra_constraint=scenario["extra_constraint"],
    )


def parse_generation(text: str) -> dict[str, Any]:
    fields: dict[str, str] = {}
    issues: list[str] = []
    residual = text or ""
    for tag in ("problem", "answer", "solution", "technique_analysis"):
        pattern = rf"<{tag}>\s*(.*?)\s*</{tag}>"
        matches = re.findall(
            pattern, text or "", flags=re.DOTALL | re.IGNORECASE
        )
        residual = re.sub(
            pattern, "", residual, flags=re.DOTALL | re.IGNORECASE
        )
        if len(matches) != 1 or not matches[0].strip():
            issues.append(f"invalid_{tag}_section")
        else:
            fields[tag] = matches[0].strip()
    answer = normalize_aime_answer(fields.get("answer"))
    if answer is None:
        issues.append("invalid_integer_answer")
    if residual.strip():
        issues.append("text_outside_sections")
    return {
        "format_pass": not issues,
        "issues": issues,
        "problem": fields.get("problem"),
        "answer": answer,
        "solution": fields.get("solution"),
        "technique_analysis": fields.get("technique_analysis"),
    }


def blind_pairs(
    slm_rows: list[dict[str, Any]],
    frontier_rows: list[dict[str, Any]],
    *,
    seed: int = 20260712,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]]]:
    def index(rows: list[dict[str, Any]]) -> dict[tuple[str, int], dict[str, Any]]:
        result = {}
        for row in rows:
            key = (str(row["scenario_id"]), int(row["repeat_index"]))
            if key in result:
                raise ValueError(f"duplicate generation key: {key}")
            result[key] = row
        return result

    slm = index(slm_rows)
    frontier = index(frontier_rows)
    if set(slm) != set(frontier):
        raise ValueError("SLM and frontier generation keys do not match")
    rng = random.Random(seed)
    pairs = []
    key_rows: dict[str, dict[str, str]] = {}
    for scenario_id, repeat_index in sorted(slm):
        pair_id = f"{scenario_id}-r{repeat_index}"
        a_arm = "slm" if rng.random() < 0.5 else "frontier"
        b_arm = "frontier" if a_arm == "slm" else "slm"
        records = {"slm": slm[(scenario_id, repeat_index)], "frontier": frontier[(scenario_id, repeat_index)]}
        a, b = records[a_arm], records[b_arm]
        pairs.append(
            {
                "pair_id": pair_id,
                "scenario_id": scenario_id,
                "family_id": a.get("family_id", scenario_id),
                "variant": a.get("variant", "canonical"),
                "topic": a.get("topic"),
                "target_difficulty": a.get("target_difficulty"),
                "required_techniques": a.get("technique_names"),
                "prompt": a["prompt"],
                "output_a": a["output"],
                "parse_a": a["parse"],
                "output_b": b["output"],
                "parse_b": b["parse"],
            }
        )
        key_rows[pair_id] = {"a": a_arm, "b": b_arm}
    return pairs, key_rows


def write_label_template(path: Path | str, pairs: list[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LABEL_FIELDS)
        writer.writeheader()
        for pair in pairs:
            writer.writerow({"pair_id": pair["pair_id"]})


def _score_pass(label: dict[str, str], side: str, parse_pass: bool) -> bool:
    try:
        return bool(
            parse_pass
            and label[f"validity_{side}"] == "valid"
            and int(label[f"interaction_{side}"]) >= 4
            and int(label[f"novelty_{side}"]) >= 3
            and int(label[f"elegance_{side}"]) >= 3
            and int(label[f"difficulty_pass_{side}"]) == 1
        )
    except (KeyError, TypeError, ValueError):
        return False


def _validate_label(pair_id: str, label: dict[str, str]) -> None:
    for side in ("a", "b"):
        if label.get(f"validity_{side}") not in {"valid", "repairable", "invalid"}:
            raise ValueError(f"invalid validity label for {pair_id} side {side.upper()}")
        for dimension in ("interaction", "novelty", "elegance"):
            try:
                score = int(label[f"{dimension}_{side}"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"invalid {dimension} score for {pair_id} side {side.upper()}"
                ) from exc
            if not 1 <= score <= 5:
                raise ValueError(
                    f"invalid {dimension} score for {pair_id} side {side.upper()}"
                )
        if label.get(f"difficulty_pass_{side}") not in {"0", "1"}:
            raise ValueError(f"invalid difficulty label for {pair_id} side {side.upper()}")


def _quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * q)))
    return ordered[index]


def build_report(
    pairs: list[dict[str, Any]],
    key_rows: dict[str, dict[str, str]],
    labels_path: Path | str,
    *,
    bootstrap_samples: int = 5000,
    seed: int = 20260712,
) -> dict[str, Any]:
    with Path(labels_path).open(encoding="utf-8", newline="") as handle:
        labels = {row["pair_id"]: row for row in csv.DictReader(handle)}
    if set(labels) != {pair["pair_id"] for pair in pairs}:
        raise ValueError("label rows do not match blind pairs")
    outcomes = []
    wins = {"slm": 0, "frontier": 0, "tie": 0}
    for pair in pairs:
        pair_id = pair["pair_id"]
        label = labels[pair_id]
        _validate_label(pair_id, label)
        mapping = key_rows[pair_id]
        winner = label.get("winner", "").strip().upper()
        if winner not in {"A", "B", "TIE"}:
            raise ValueError(f"invalid winner for {pair_id}: {winner!r}")
        winner_arm = "tie" if winner == "TIE" else mapping[winner.lower()]
        wins[winner_arm] += 1
        side_for = {arm: side for side, arm in mapping.items()}
        slm_side, frontier_side = side_for["slm"], side_for["frontier"]
        outcomes.append(
            {
                "pair_id": pair_id,
                "family_id": pair["family_id"],
                "slm_valid": label[f"validity_{slm_side}"] == "valid",
                "frontier_valid": label[f"validity_{frontier_side}"] == "valid",
                "slm_all_gates": _score_pass(label, slm_side, bool(pair[f"parse_{slm_side}"]["format_pass"])),
                "frontier_all_gates": _score_pass(label, frontier_side, bool(pair[f"parse_{frontier_side}"]["format_pass"])),
                "winner": winner_arm,
            }
        )
    total = len(outcomes)
    slm_pass = sum(row["slm_all_gates"] for row in outcomes)
    frontier_pass = sum(row["frontier_all_gates"] for row in outcomes)
    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in outcomes:
        by_family[row["family_id"]].append(row)
    family_ids = sorted(by_family)
    rng = random.Random(seed)
    deltas = []
    for _ in range(bootstrap_samples):
        sampled = [rng.choice(family_ids) for _ in family_ids]
        rows = [row for family_id in sampled for row in by_family[family_id]]
        deltas.append(
            sum(row["slm_all_gates"] for row in rows) / len(rows)
            - sum(row["frontier_all_gates"] for row in rows) / len(rows)
        )
    delta = slm_pass / total - frontier_pass / total
    return {
        "schema_version": "behavior-eval-summary-v1",
        "pairs": total,
        "families": len(family_ids),
        "all_gates": {
            "slm_passes": slm_pass,
            "slm_rate": round(slm_pass / total, 6),
            "frontier_passes": frontier_pass,
            "frontier_rate": round(frontier_pass / total, 6),
            "paired_delta": round(delta, 6),
            "family_bootstrap_95_ci": [
                round(_quantile(deltas, 0.025), 6),
                round(_quantile(deltas, 0.975), 6),
            ],
        },
        "fully_valid": {
            "slm": sum(row["slm_valid"] for row in outcomes),
            "frontier": sum(row["frontier_valid"] for row in outcomes),
        },
        "pairwise": wins,
        "outcomes": outcomes,
    }
