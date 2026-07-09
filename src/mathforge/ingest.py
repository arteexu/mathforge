"""Ingest source datasets into the SQLite database.

Right now the focus is **Omni-MATH** (detailed solutions + human difficulty
ratings), split into two labeled sections by difficulty:

* ``tier == "easy"``  -> difficulty ``< threshold``
* ``tier == "hard"``  -> difficulty ``>= threshold``  (default threshold 4.0)

NuminaMath-1.5 is downloaded/cached but intentionally left for a later pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sqlmodel import select

from mathforge import db
from mathforge.datasets import load_omni_math, omni_row_to_records
from mathforge.schema import DEFAULT_TIER_THRESHOLD, Problem, ProblemTier

__all__ = ["IngestReport", "ingest_omni_math"]


@dataclass
class IngestReport:
    """Summary of an ingest run."""

    problems: int = 0
    solutions: int = 0
    evaluations: int = 0
    skipped_duplicates: int = 0
    per_tier: dict[str, int] = field(
        default_factory=lambda: {t.value: 0 for t in ProblemTier}
    )

    def as_dict(self) -> dict[str, object]:
        return {
            "problems": self.problems,
            "solutions": self.solutions,
            "evaluations": self.evaluations,
            "skipped_duplicates": self.skipped_duplicates,
            "per_tier": self.per_tier,
        }


def ingest_omni_math(
    threshold: float = DEFAULT_TIER_THRESHOLD,
    limit: Optional[int] = None,
    db_url: Optional[str] = None,
) -> IngestReport:
    """Load Omni-MATH into the DB, deduped by statement hash and tier-labeled.

    Re-running is safe: problems whose normalized statement already exists are
    skipped, so the two sections accumulate without duplication.
    """
    dataset = load_omni_math()
    db.init_db(db_url)
    report = IngestReport()

    count = len(dataset) if limit is None else min(limit, len(dataset))

    with db.session_scope(db_url) as session:
        seen: set[Optional[str]] = set(
            session.exec(select(Problem.statement_hash)).all()
        )

        for idx in range(count):
            problem, solution, evaluation = omni_row_to_records(
                dataset[idx], idx, threshold=threshold
            )

            if problem.statement_hash in seen:
                report.skipped_duplicates += 1
                continue
            seen.add(problem.statement_hash)

            session.add(problem)
            report.problems += 1
            if problem.tier is not None:
                report.per_tier[problem.tier.value] += 1
            if solution is not None:
                session.add(solution)
                report.solutions += 1
            if evaluation is not None:
                session.add(evaluation)
                report.evaluations += 1

    return report
