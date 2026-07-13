"""Rebuild the cumulative frontier-candidate verification report from the DB.

``verify_frontier_candidates.py`` writes an invocation-level progress file.  That
file is intentionally useful while a batch is running, but a later invocation
replaces it.  This script treats the persisted ``Problem.provenance.agent_qa``
records as the source of truth and recreates one report covering every rich and
technique-combination candidate.

The database is read-only: this script changes neither verification fields nor
human review statuses.  Only the JSON report file is written.

Usage:
    PYTHONPATH=src python scripts/report_frontier_verification.py
    PYTHONPATH=src python scripts/report_frontier_verification.py --stdout
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from sqlmodel import Session, select

from mathforge import db
from mathforge.schema import Evaluation, Problem, Solution

DEFAULT_PREFIXES = ("distill-rich-", "distill-combo-")
DEFAULT_REPORT_PATH = Path("data/frontier_verification_report.json")


def _value(value: Any) -> Any:
    """Return an enum's serialized value, otherwise the value unchanged."""
    return getattr(value, "value", value)


def _family(problem_id: str, prefixes: tuple[str, ...]) -> str:
    if problem_id.startswith("distill-rich-"):
        return "rich"
    if problem_id.startswith("distill-combo-"):
        return "combo"
    for prefix in prefixes:
        if problem_id.startswith(prefix):
            return prefix.rstrip("-")
    return "other"


def classify_verification(
    *,
    verified: Optional[bool],
    stored_answer: Optional[str],
    qa: Optional[dict[str, Any]],
) -> tuple[str, str, list[str]]:
    """Return ``(category, reason, issues)`` for one persisted QA record.

    The primary category is deliberately coarse and stable for reporting.  The
    issues list retains secondary failures when, for example, both answer
    agreement and the editorial well-posedness decision are missing.
    """
    if not qa:
        return (
            "qa_missing",
            "No persisted agent_qa record.",
            ["agent_qa_missing"],
        )

    consensus = qa.get("consensus")
    answer_verified = qa.get("answer_verified")
    if answer_verified is None:
        # Older out-of-band verdicts persisted only the combined QA decision.
        answer_verified = qa.get("verified")

    wellposedness = qa.get("wellposedness") or {}
    wellposed = wellposedness.get("verdict")
    issues: list[str] = []

    if answer_verified is not True:
        if consensus in (None, ""):
            issues.append("no_solver_consensus")
        else:
            issues.append("stored_answer_does_not_match_consensus")

    if wellposed == "reject":
        issues.append("wellposedness_rejected")
    elif wellposed == "repair":
        issues.append("wellposedness_needs_repair")
    elif wellposed != "accept":
        issues.append("missing_editorial_verdict")

    if verified is True and issues:
        return (
            "inconsistent_verified_record",
            "Problem.verified is true but persisted QA contains: " + ", ".join(issues) + ".",
            issues,
        )
    if verified is True:
        return (
            "verified",
            "Stored answer independently verified and well-posedness accepted.",
            [],
        )
    if answer_verified is not True:
        if consensus in (None, ""):
            reason = "Independent solvers produced no strict-majority answer."
        else:
            reason = (
                f"Solver consensus {consensus!r} does not verify stored answer "
                f"{stored_answer!r}."
            )
        return "answer_failure", reason, issues
    if wellposed == "reject":
        return (
            "wellposedness_rejection",
            "The answer verified, but the editorial well-posedness verdict was reject.",
            issues,
        )
    if wellposed == "repair":
        return (
            "wellposedness_repair",
            "The answer verified, but the statement requires editorial repair.",
            issues,
        )
    if wellposed != "accept":
        return (
            "missing_editorial_verdict",
            "The answer verified, but no usable editorial well-posedness verdict was persisted.",
            issues,
        )
    return (
        "verification_failed",
        "Persisted fields do not explain why the combined verification flag is false.",
        issues,
    )


def _counts(values: Iterable[str]) -> dict[str, int]:
    return dict(sorted(Counter(values).items()))


def _summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    categories = _counts(record["category"] for record in records)
    statuses = _counts(record["review_status"] for record in records)
    families: dict[str, Any] = {}
    for family in sorted({record["family"] for record in records}):
        subset = [record for record in records if record["family"] == family]
        families[family] = {
            "total": len(subset),
            "qa_persisted": sum(record["qa_persisted"] for record in subset),
            "verified": sum(record["category"] == "verified" for record in subset),
            "verification_unresolved": sum(
                record["category"] != "verified" for record in subset
            ),
            "category_counts": _counts(record["category"] for record in subset),
            "review_status_counts": _counts(
                record["review_status"] for record in subset
            ),
        }

    return {
        "total": len(records),
        "qa_persisted": sum(record["qa_persisted"] for record in records),
        "qa_missing": sum(not record["qa_persisted"] for record in records),
        "verified": categories.get("verified", 0),
        "verification_unresolved": sum(
            record["category"] != "verified" for record in records
        ),
        "awaiting_human_review": sum(
            record["review_status"] in {"pending", "needs_edit"}
            for record in records
        ),
        "category_counts": categories,
        "review_status_counts": statuses,
        "families": families,
    }


def build_report(
    db_url: Optional[str] = None,
    prefixes: tuple[str, ...] = DEFAULT_PREFIXES,
) -> dict[str, Any]:
    """Read all matching candidates and return a cumulative JSON-ready report."""
    engine = db.get_engine(db_url)
    with Session(engine) as session:
        problems = [
            problem
            for problem in session.exec(select(Problem)).all()
            if any(problem.id.startswith(prefix) for prefix in prefixes)
        ]
        problems.sort(key=lambda problem: (_family(problem.id, prefixes), problem.id))
        ids = [problem.id for problem in problems]

        solutions = (
            session.exec(select(Solution).where(Solution.problem_id.in_(ids))).all()
            if ids
            else []
        )
        evaluations = (
            session.exec(select(Evaluation).where(Evaluation.problem_id.in_(ids))).all()
            if ids
            else []
        )

    solution_counts: dict[str, Counter[str]] = {}
    for solution in solutions:
        counts = solution_counts.setdefault(solution.problem_id, Counter())
        counts["total"] += 1
        counts[str(_value(solution.source))] += 1

    evaluation_counts: dict[str, Counter[str]] = {}
    for evaluation in evaluations:
        counts = evaluation_counts.setdefault(evaluation.problem_id, Counter())
        counts["total"] += 1
        counts[evaluation.evaluator] += 1

    records: list[dict[str, Any]] = []
    for problem in problems:
        provenance = problem.provenance or {}
        qa = provenance.get("agent_qa")
        category, reason, issues = classify_verification(
            verified=problem.verified,
            stored_answer=problem.answer,
            qa=qa,
        )
        qa = qa or {}
        wellposedness = qa.get("wellposedness") or {}
        difficulty = qa.get("difficulty") or {}
        elegance = qa.get("elegance") or {}
        status = _value(problem.review_status) or "unreviewed"

        records.append(
            {
                "id": problem.id,
                "family": _family(problem.id, prefixes),
                "source": _value(problem.source),
                "review_status": status,
                "verified": problem.verified,
                "category": category,
                "reason": reason,
                "issues": issues,
                "stored_answer": problem.answer,
                "consensus": qa.get("consensus"),
                "agreement": qa.get("agreement"),
                "answer_verified": qa.get("answer_verified"),
                "wellposedness_verdict": wellposedness.get("verdict"),
                "solver_model": qa.get("solver_model"),
                "judge_model": qa.get("judge_model"),
                "k": qa.get("k"),
                "qa_difficulty": difficulty.get("difficulty"),
                "qa_elegance": elegance.get("overall"),
                "qa_persisted": bool(provenance.get("agent_qa")),
                "generator_model": provenance.get("generator_model"),
                "techniques": provenance.get("techniques") or [],
                "crux": provenance.get("crux"),
                "solution_counts": dict(sorted(solution_counts.get(problem.id, {}).items())),
                "evaluation_counts": dict(
                    sorted(evaluation_counts.get(problem.id, {}).items())
                ),
                "created_at": problem.created_at.isoformat(),
            }
        )

    return {
        "report_type": "frontier_verification_cumulative",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_of_truth": "Problem.provenance.agent_qa and persisted DB fields",
        "prefixes": list(prefixes),
        "summary": _summarize(records),
        "unresolved": [
            record for record in records if record["category"] != "verified"
        ],
        "records": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-url", default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument(
        "--prefixes",
        default=",".join(DEFAULT_PREFIXES),
        help="comma-separated candidate ID prefixes",
    )
    parser.add_argument("--stdout", action="store_true")
    args = parser.parse_args()

    prefixes = tuple(value.strip() for value in args.prefixes.split(",") if value.strip())
    report = build_report(db_url=args.db_url, prefixes=prefixes)
    rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")

    if args.stdout:
        print(rendered, end="")
    else:
        print(json.dumps(report["summary"], indent=2), flush=True)
        print(f"wrote cumulative report to {args.output}", flush=True)


if __name__ == "__main__":
    main()
