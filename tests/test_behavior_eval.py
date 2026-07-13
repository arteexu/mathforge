from __future__ import annotations

import csv
import json

import pytest

from mathforge.behavior_eval import (
    LABEL_FIELDS,
    blind_pairs,
    build_report,
    load_suite,
    parse_generation,
    render_scenario,
)


def _generation(scenario_id: str, repeat: int, arm: str) -> dict:
    text = (
        "<problem>Find an integer.</problem>"
        "<answer>007</answer>"
        "<solution>The unique answer is 7.</solution>"
        "<technique_analysis>Both required methods interact.</technique_analysis>"
    )
    return {
        "scenario_id": scenario_id,
        "family_id": scenario_id,
        "variant": "canonical",
        "topic": "Algebra",
        "target_difficulty": [5, 7],
        "technique_names": ["First", "Second"],
        "repeat_index": repeat,
        "arm": arm,
        "prompt": "Frozen prompt",
        "output": text,
        "parse": parse_generation(text),
    }


def test_basic_suite_is_valid_and_uses_canonical_techniques():
    suite, digest = load_suite("eval/behavior_suite_basic_v1.jsonl")
    taxonomy = {row["id"] for row in json.load(open("data/techniques.json"))}

    assert len(suite) == 12
    assert len(digest) == 64
    assert all(set(row["technique_ids"]) <= taxonomy for row in suite)
    rendered = render_scenario(suite[0])
    assert suite[0]["technique_names"][0] in rendered
    assert "<problem>" in rendered


def test_generation_parser_enforces_all_sections_and_integer_answer():
    valid = parse_generation(
        "<problem>P</problem><answer>42</answer><solution>S</solution>"
        "<technique_analysis>T</technique_analysis>"
    )
    invalid = parse_generation(
        "<problem>P</problem><answer>not an integer</answer><solution>S</solution>"
    )

    assert valid["format_pass"] is True
    assert valid["answer"] == "42"
    assert invalid["format_pass"] is False
    assert "invalid_technique_analysis_section" in invalid["issues"]
    assert "invalid_integer_answer" in invalid["issues"]


def test_blinding_requires_matched_generation_keys_and_is_deterministic():
    slm = [_generation("s1", 1, "slm"), _generation("s2", 1, "slm")]
    frontier = [
        _generation("s1", 1, "frontier"),
        _generation("s2", 1, "frontier"),
    ]

    pairs_a, key_a = blind_pairs(slm, frontier, seed=9)
    pairs_b, key_b = blind_pairs(slm, frontier, seed=9)

    assert pairs_a == pairs_b
    assert key_a == key_b
    assert all(set(value.values()) == {"slm", "frontier"} for value in key_a.values())
    with pytest.raises(ValueError, match="do not match"):
        blind_pairs(slm, frontier[:1])


def test_report_maps_blind_sides_and_computes_all_gate_delta(tmp_path):
    slm = [_generation("s1", 1, "slm"), _generation("s2", 1, "slm")]
    frontier = [
        _generation("s1", 1, "frontier"),
        _generation("s2", 1, "frontier"),
    ]
    pairs, key_rows = blind_pairs(slm, frontier, seed=3)
    labels_path = tmp_path / "labels.csv"
    with labels_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LABEL_FIELDS)
        writer.writeheader()
        for pair in pairs:
            mapping = key_rows[pair["pair_id"]]
            slm_side = "a" if mapping["a"] == "slm" else "b"
            frontier_side = "b" if slm_side == "a" else "a"
            row = {field: "" for field in LABEL_FIELDS}
            row["pair_id"] = pair["pair_id"]
            for side in ("a", "b"):
                row[f"interaction_{side}"] = "5" if side == slm_side else "1"
                row[f"novelty_{side}"] = "4" if side == slm_side else "1"
                row[f"elegance_{side}"] = "4" if side == slm_side else "1"
                row[f"difficulty_pass_{side}"] = "1"
            row[f"validity_{slm_side}"] = "valid"
            row[f"validity_{frontier_side}"] = "invalid"
            row["winner"] = slm_side.upper()
            writer.writerow(row)

    report = build_report(
        pairs, key_rows, labels_path, bootstrap_samples=100, seed=4
    )

    assert report["all_gates"]["slm_rate"] == 1.0
    assert report["all_gates"]["frontier_rate"] == 0.0
    assert report["all_gates"]["paired_delta"] == 1.0
    assert report["pairwise"] == {"slm": 2, "frontier": 0, "tie": 0}
