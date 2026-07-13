"""Export a clean, crux-conditioned creativity dataset.

Integrity rules are intentionally strict:

* TRAIN and non-frozen rows only, with exact/fuzzy-group deduplication;
* no statement-level overlap with the frozen eval split;
* AIME integer answers (0-999) by default;
* synthetic positives only after independent verification + human acceptance;
* one JSONL row per unique problem (quality is stored as ``sample_weight`` rather
  than materialized as duplicate rows);
* the actual crux and techniques appear in the user prompt, so the SFT task is
  genuinely insight-conditioned.

Run: ``PYTHONPATH=src python scripts/export_creative.py``
Env: ``CC_FLOOR`` (3.0), ``DIFF_FLOOR`` (3.0), ``MAX_WEIGHT`` (5.0),
``REQUIRE_AIME`` (1).
"""

from __future__ import annotations

import json
import os
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from sqlmodel import select

from mathforge import db
from mathforge.integrity import (
    answer_type,
    deduplicated_training_problems,
    is_export_eligible,
    normalize_aime_answer,
    normalize_solution_text,
    preferred_solution,
    techniques_for,
)
from mathforge.schema import Evaluation, Problem, Solution

OUT = Path("data/train_creative.jsonl")
CC_FLOOR = float(os.environ.get("CC_FLOOR", 3.0))
DIFF_FLOOR = float(os.environ.get("DIFF_FLOOR", 3.0))
MAX_WEIGHT = float(os.environ.get("MAX_WEIGHT", os.environ.get("MAX_COPIES", 5.0)))
REQUIRE_AIME = os.environ.get("REQUIRE_AIME", "1").lower() not in {"0", "false", "no"}
W_CC, W_INT, W_EL, W_DIFF = 0.45, 0.30, 0.15, 0.10


def _src(pid: str) -> str:
    for prefix, tag in [
        ("omni-math", "omni"),
        ("distill-rich", "rich"),
        ("distill-combo", "combo"),
        ("distill", "distill"),
        ("opus", "opus"),
        ("aime", "aime"),
        ("olymp", "olympiad"),
        ("math", "math"),
    ]:
        if pid.startswith(prefix):
            return tag
    return "other"


def _first_not_none(*values):
    return next((value for value in values if value is not None), None)


def _evaluation_priority(evaluation: Evaluation) -> tuple[int, int]:
    evaluator = (evaluation.evaluator or "").lower()
    if evaluator == "human":
        priority = 0
    elif evaluator == "opus-4.8-quality":
        priority = 1
    elif evaluator == "opus-4.8":
        priority = 2
    elif evaluator.startswith("judge_"):
        priority = 3
    elif evaluator == "solver_panel":
        priority = 4
    elif evaluator == "dataset":
        priority = 5
    else:
        priority = 9  # generator self-ratings are fallback-only
    return priority, -(evaluation.id or 0)


def build_prompt(topic: str | None, difficulty: float | None, crux: str,
                 techniques: list[str]) -> str:
    """The deployed task contract: the seed is input, never hidden in metadata."""

    parts = [
        "Compose one original, self-contained AIME-style competition math problem built around the supplied crux.",
        "The answer must be a unique integer from 0 to 999.",
        f"Seed crux: {crux.strip()}",
    ]
    if techniques:
        parts.append("Required techniques: " + ", ".join(techniques) + ".")
        parts.append("Every required technique must be load-bearing, but the statement must not name or telegraph them.")
    if topic:
        parts.append(f"Topic: {topic}.")
    if difficulty is not None:
        parts.append(f"Target difficulty (AoPS 1-10): {difficulty}.")
    parts.append("Give the problem statement, the key idea, a complete solution, and the final integer answer.")
    return " ".join(parts)


def build_completion(statement: str, crux: str, solution: str, answer: str | None) -> str:
    parts = [f"Problem:\n{statement.strip()}", f"\nKey idea:\n{crux.strip()}"]
    if solution:
        parts.append(f"\nSolution:\n{solution.strip()}")
    if answer is not None:
        parts.append(f"\nAnswer: {answer}")
    return "\n".join(parts)


def build_rows(session) -> tuple[list[dict], Counter]:
    """Build deterministic unique records and counters explaining exclusions."""

    solutions_by: dict[str, list[Solution]] = defaultdict(list)
    for solution in session.exec(select(Solution)).all():
        solutions_by[solution.problem_id].append(solution)

    evaluations_by: dict[str, list[Evaluation]] = defaultdict(list)
    for evaluation in session.exec(select(Evaluation)).all():
        evaluations_by[evaluation.problem_id].append(evaluation)

    rows: list[dict] = []
    skipped: Counter = Counter()
    for problem in deduplicated_training_problems(session):
        if not is_export_eligible(problem):
            skipped["synthetic_not_verified_and_accepted"] += 1
            continue

        solution = preferred_solution(problem, solutions_by.get(problem.id, []))
        if solution is None:
            skipped["missing_solution"] += 1
            continue

        provenance = problem.provenance or {}
        quality = provenance.get("quality") or {}
        crux = provenance.get("crux") or solution.crux_insight or ""
        if not crux.strip():
            skipped["missing_crux"] += 1
            continue

        evaluations = sorted(evaluations_by.get(problem.id, []), key=_evaluation_priority)
        evaluated_elegance = next(
            (e.elegance_score for e in evaluations if e.elegance_score is not None),
            None,
        )
        combo_faithfulness = (
            (provenance.get("preflight") or {}).get("faithfulness") or {}
        )
        combo_creativity_values = [
            combo_faithfulness.get("problem_creativity"),
            combo_faithfulness.get("interaction_creativity"),
        ]
        combo_creativity_values = [
            float(value)
            for value in combo_creativity_values
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        ]
        # A combination is only as creative as its weaker axis: the realized
        # problem and the interaction between its required techniques must both
        # clear the export floor.
        combo_creativity = (
            min(combo_creativity_values) if combo_creativity_values else None
        )
        creativity = _first_not_none(
            quality.get("crux_creativity"), combo_creativity
        )
        interestingness = quality.get("interestingness")
        elegance = _first_not_none(
            quality.get("problem_elegance"),
            (provenance.get("elegance") or {}).get("problem"),
            evaluated_elegance,
        )
        difficulty = problem.difficulty

        if creativity is None or creativity < CC_FLOOR:
            skipped["below_creativity_floor"] += 1
            continue
        if difficulty is not None and difficulty < DIFF_FLOOR:
            skipped["below_difficulty_floor"] += 1
            continue

        normalized_answer = normalize_aime_answer(problem.answer)
        if REQUIRE_AIME and normalized_answer is None:
            skipped["not_aime_integer"] += 1
            continue
        exported_answer = normalized_answer if normalized_answer is not None else problem.answer

        cc_score = creativity
        interest_score = _first_not_none(interestingness, elegance, 2.5)
        elegance_score = _first_not_none(elegance, 2.5)
        difficulty_score = min(difficulty, 10) if difficulty is not None else 5.0
        priority = (
            W_CC * (cc_score / 5)
            + W_INT * (interest_score / 5)
            + W_EL * (elegance_score / 5)
            + W_DIFF * (difficulty_score / 10)
        )
        sample_weight = 1.0 + max(0.0, priority) * max(0.0, MAX_WEIGHT - 1.0)
        techniques = techniques_for(problem, solution)
        prompt = build_prompt(problem.topic, difficulty, crux, techniques)
        completion = build_completion(
            problem.statement,
            crux,
            normalize_solution_text(solution.text),
            exported_answer,
        )
        meta = {
            "id": problem.id,
            "source": _src(problem.id),
            "topic": problem.topic,
            "difficulty": difficulty,
            "crux": crux,
            "techniques": techniques,
            "crux_creativity": creativity,
            "creativity_source": (
                "quality.crux_creativity"
                if quality.get("crux_creativity") is not None
                else "combo_preflight_min"
            ),
            "interestingness": interestingness,
            "problem_elegance": elegance,
            "answer": exported_answer,
            "answer_type": answer_type(exported_answer),
            "priority": round(priority, 3),
            "sample_weight": round(sample_weight, 3),
        }
        rows.append({
            "messages": [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": completion},
            ],
            "meta": meta,
        })

    rows.sort(key=lambda row: row["meta"]["id"])
    return rows, skipped


def main() -> None:
    db.init_db()
    OUT.parent.mkdir(exist_ok=True)
    with db.session_scope() as session:
        rows, skipped = build_rows(session)

    payload = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    OUT.write_text(payload + ("\n" if payload else ""), encoding="utf-8")

    by_source = Counter(row["meta"]["source"] for row in rows)
    creativity = [row["meta"]["crux_creativity"] for row in rows]
    print(f"exported {len(rows)} unique problems -> {OUT} (REQUIRE_AIME={REQUIRE_AIME})")
    print("  by source:", dict(by_source))
    print("  skipped:", dict(skipped))
    if creativity:
        print(
            f"  crux creativity: mean {statistics.mean(creativity):.2f} "
            f"(min {min(creativity)}, max {max(creativity)})"
        )


if __name__ == "__main__":
    main()
