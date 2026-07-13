from __future__ import annotations

from mathforge import db
from mathforge.schema import (
    DataSplit,
    Problem,
    ProblemSource,
    ReviewStatus,
)
from scripts.report_frontier_verification import build_report


def _candidate(
    problem_id: str,
    *,
    verified: bool | None,
    answer_verified: bool | None,
    wellposed: str | None,
    consensus: str | None = "42",
) -> Problem:
    qa = {
        "solver_model": "solver",
        "judge_model": "judge",
        "k": 3,
        "consensus": consensus,
        "agreement": 1.0 if consensus else 0.0,
        "answer_verified": answer_verified,
        "wellposedness": {"verdict": wellposed} if wellposed else {},
    }
    return Problem(
        id=problem_id,
        source=ProblemSource.SYNTHETIC,
        statement=problem_id,
        answer="42",
        split=DataSplit.TRAIN,
        verified=verified,
        review_status=ReviewStatus.PENDING,
        provenance={"agent_qa": qa},
    )


def test_cumulative_frontier_report_classifies_persisted_outcomes(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'frontier.db'}"
    db.init_db(db_url)
    with db.session_scope(db_url) as session:
        session.add(
            _candidate(
                "distill-rich-good",
                verified=True,
                answer_verified=True,
                wellposed="accept",
            )
        )
        session.add(
            _candidate(
                "distill-rich-answer",
                verified=False,
                answer_verified=False,
                wellposed="accept",
                consensus=None,
            )
        )
        session.add(
            _candidate(
                "distill-combo-reject",
                verified=False,
                answer_verified=True,
                wellposed="reject",
            )
        )
        session.add(
            _candidate(
                "distill-combo-missing",
                verified=False,
                answer_verified=True,
                wellposed=None,
            )
        )
        session.add(
            Problem(
                id="unrelated",
                source=ProblemSource.SYNTHETIC,
                statement="not a frontier candidate",
                split=DataSplit.TRAIN,
                provenance={},
            )
        )

    report = build_report(db_url=db_url)
    categories = {record["id"]: record["category"] for record in report["records"]}

    assert categories == {
        "distill-combo-missing": "missing_editorial_verdict",
        "distill-combo-reject": "wellposedness_rejection",
        "distill-rich-answer": "answer_failure",
        "distill-rich-good": "verified",
    }
    assert report["summary"]["total"] == 4
    assert report["summary"]["verified"] == 1
    assert report["summary"]["verification_unresolved"] == 3
    assert report["summary"]["awaiting_human_review"] == 4
    assert len(report["unresolved"]) == 3
