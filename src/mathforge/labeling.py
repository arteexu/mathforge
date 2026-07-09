"""Human ground-truth labeling: the highest-leverage manual step.

Encodes the (only) AIME-experienced human's judgment as ``Evaluation`` rows with
``evaluator="human"`` — the ground truth every judge is calibrated against.

Design choices that matter for label quality:

* **Stratified** selection across difficulty bands x topics, so a few focused
  hours cover the space rather than 150 near-identical mid problems.
* **Anchor-free**: presentation order is randomized and *all* existing ratings
  (source difficulty, prior evaluations, teacher difficulty estimates, the
  problem id/source) are hidden while labeling — only the statement and its
  worked solutions are shown.
* **Resumable**: problems already carrying a human label are skipped.

The interactive terminal loop lives in ``cli.py``; this module holds the
testable, side-effect-light pieces.
"""

from __future__ import annotations

import random
from collections import defaultdict
from typing import Optional

from sqlmodel import select

from mathforge import db
from mathforge.schema import (
    DataSplit,
    Evaluation,
    Problem,
    Solution,
    SolutionSource,
    difficulty_band,
)

__all__ = [
    "HUMAN_EVALUATOR",
    "VISIBLE_SOLUTION_SOURCES",
    "already_labeled_ids",
    "select_label_batch",
    "visible_solutions",
    "parse_difficulty",
    "parse_elegance",
    "record_human_label",
    "human_label_count",
]

HUMAN_EVALUATOR = "human"
# Never show machine analysis (teacher rows carry a difficulty_estimate that
# would anchor the labeler); only real worked solutions.
VISIBLE_SOLUTION_SOURCES = (SolutionSource.OFFICIAL, SolutionSource.HUMAN)


def already_labeled_ids(session) -> set[str]:
    """Problem ids that already have a human evaluation (for resume/skip)."""
    rows = session.exec(
        select(Evaluation.problem_id).where(Evaluation.evaluator == HUMAN_EVALUATOR)
    ).all()
    return set(rows)


def _split_filter(stmt, split: str):
    if split == "all":
        return stmt
    return stmt.where(Problem.split == DataSplit(split))


def select_label_batch(
    session,
    count: int = 150,
    split: str = "train",
    seed: Optional[int] = None,
    exclude_labeled: bool = True,
) -> list[str]:
    """Choose ``count`` problem ids stratified over (topic, difficulty band).

    Round-robin over sorted strata guarantees coverage; the final order is then
    shuffled so the labeler isn't anchored by any grouping. ``seed`` makes the
    selection reproducible (tests / resuming a plan); leave ``None`` for a fresh
    random order each session.
    """
    labeled = already_labeled_ids(session) if exclude_labeled else set()
    rows = session.exec(_split_filter(select(Problem), split)).all()

    rng = random.Random(seed)
    strata: dict[tuple[str, str], list[str]] = defaultdict(list)
    for p in rows:
        if p.id in labeled:
            continue
        band = difficulty_band(p.difficulty)
        if band is None or not p.topic:
            continue
        strata[(p.topic, band)].append(p.id)

    keys = sorted(strata)
    for k in keys:
        rng.shuffle(strata[k])

    selected: list[str] = []
    cursors = {k: 0 for k in keys}
    progress = True
    while len(selected) < count and progress:
        progress = False
        for k in keys:
            if len(selected) >= count:
                break
            c = cursors[k]
            if c < len(strata[k]):
                selected.append(strata[k][c])
                cursors[k] = c + 1
                progress = True

    rng.shuffle(selected)
    return selected


def visible_solutions(session, problem_id: str) -> list[str]:
    """Worked-solution texts to show the labeler (excludes teacher analysis)."""
    sols = session.exec(
        select(Solution).where(Solution.problem_id == problem_id)
    ).all()
    return [
        s.text
        for s in sols
        if s.source in VISIBLE_SOLUTION_SOURCES and s.text and s.text.strip()
    ]


def parse_difficulty(raw: str) -> float:
    """Parse an AoPS-style difficulty in [1.0, 10.0] (one decimal)."""
    value = float(raw)
    if not (1.0 <= value <= 10.0):
        raise ValueError("difficulty must be between 1 and 10")
    return round(value, 1)


def parse_elegance(raw: str) -> float:
    """Parse an elegance score in [0.0, 5.0].

    5 = beautiful, top-tier · 4 = strong, elegant · 3 = elegant, quality ·
    2 = decent · 1 = poor · 0 = bad.
    """
    value = float(raw)
    if not (0.0 <= value <= 5.0):
        raise ValueError("elegance must be between 0 and 5")
    return value


def record_human_label(
    session,
    problem_id: str,
    difficulty: float,
    elegance: float,
    rationale: str = "",
) -> Evaluation:
    """Write a human ``Evaluation`` row (returns the persisted object)."""
    evaluation = Evaluation(
        problem_id=problem_id,
        difficulty_score=difficulty,
        elegance_score=elegance,
        evaluator=HUMAN_EVALUATOR,
        rationale=rationale,
    )
    session.add(evaluation)
    return evaluation


def human_label_count(db_url: Optional[str] = None) -> int:
    with db.session_scope(db_url) as session:
        return len(
            session.exec(
                select(Evaluation.id).where(Evaluation.evaluator == HUMAN_EVALUATOR)
            ).all()
        )
