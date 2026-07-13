from __future__ import annotations

from sqlmodel import select

from mathforge import db
from mathforge.schema import Evaluation, Problem, ProblemSource, ReviewStatus, Solution
from scripts.apply_frontier_adjudications import AUDIT_ID, apply_adjudications


def test_proof_adjudication_preserves_bad_verdict_and_review_status(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'adjudication.db'}"
    db.init_db(db_url)
    problem_id = "distill-rich-test"
    original = {
        "verdict": "reject",
        "issues": [{"severity": "fatal", "description": "incorrect judge claim"}],
    }
    with db.session_scope(db_url) as session:
        session.add(
            Problem(
                id=problem_id,
                source=ProblemSource.SYNTHETIC,
                statement="A valid problem.",
                answer="42",
                verified=False,
                review_status=ReviewStatus.PENDING,
                provenance={
                    "agent_qa": {
                        "verified": False,
                        "answer_verified": True,
                        "wellposedness": original,
                    }
                },
            )
        )

    verdicts = {problem_id: {"answer": "42", "proof": "Exact proof of 42."}}
    first = apply_adjudications(db_url, verdicts)
    second = apply_adjudications(db_url, verdicts)

    assert first["applied"] == [problem_id]
    assert second["already_applied"] == [problem_id]
    with db.session_scope(db_url) as session:
        problem = session.get(Problem, problem_id)
        qa = problem.provenance["agent_qa"]
        assert problem.verified is True
        assert problem.review_status is ReviewStatus.PENDING
        assert qa["wellposedness"]["verdict"] == "accept"
        assert qa["adjudication_history"][0]["audit_id"] == AUDIT_ID
        assert qa["adjudication_history"][0]["superseded"]["wellposedness"] == original
        assert len(session.exec(select(Solution)).all()) == 1
        assert len(session.exec(select(Evaluation)).all()) == 1


def test_proof_adjudication_can_reject_a_false_positive(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'rejection.db'}"
    db.init_db(db_url)
    problem_id = "distill-rich-false-positive"
    with db.session_scope(db_url) as session:
        session.add(
            Problem(
                id=problem_id,
                source=ProblemSource.SYNTHETIC,
                statement="An inconsistent geometry premise.",
                answer="768",
                verified=True,
                review_status=ReviewStatus.PENDING,
                provenance={
                    "agent_qa": {
                        "verified": True,
                        "answer_verified": True,
                        "wellposedness": {"verdict": "accept", "issues": []},
                    }
                },
            )
        )

    verdicts = {
        problem_id: {
            "answer": "768",
            "verdict": "reject",
            "answer_verified": True,
            "proof": "The only configuration puts P on the boundary.",
        }
    }
    result = apply_adjudications(db_url, verdicts)

    assert result["applied"] == [problem_id]
    with db.session_scope(db_url) as session:
        problem = session.get(Problem, problem_id)
        qa = problem.provenance["agent_qa"]
        assert problem.verified is False
        assert problem.review_status is ReviewStatus.PENDING
        assert qa["answer_verified"] is True
        assert qa["wellposedness"]["verdict"] == "reject"
        assert qa["wellposedness"]["issues"][0]["severity"] == "fatal"
