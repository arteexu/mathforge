from __future__ import annotations

from sqlmodel import select

from mathforge import db
from mathforge.integrity import is_export_eligible, preferred_solution
from mathforge.schema import (
    Problem,
    ProblemSource,
    ReviewStatus,
    Solution,
    SolutionSource,
)
from scripts.apply_combo_batch_human_cleanup import (
    AUDIT_ID,
    CANDY_ID,
    POLYNOMIAL_ID,
    apply_cleanup,
)
from scripts.report_frontier_verification import classify_verification


def test_combo_batch_human_cleanup_is_auditable_and_idempotent(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'combo-cleanup.db'}"
    db.init_db(db_url)
    rejected_verdict = {
        "verdict": "reject",
        "issues": [{"severity": "fatal", "description": "false negative"}],
    }

    with db.session_scope(db_url) as session:
        session.add(
            Problem(
                id=CANDY_ID,
                source=ProblemSource.SYNTHETIC,
                statement="A routine stars-and-bars problem.",
                answer="163",
                verified=True,
                review_status=ReviewStatus.NEEDS_EDIT,
                provenance={"edit_note": "too classic"},
            )
        )
        session.add(
            Problem(
                id=POLYNOMIAL_ID,
                source=ProblemSource.SYNTHETIC,
                statement="A polynomial identity problem.",
                answer="302",
                verified=False,
                review_status=ReviewStatus.ACCEPTED,
                provenance={
                    "agent_qa": {
                        "verified": False,
                        "answer_verified": True,
                        "wellposedness": rejected_verdict,
                    }
                },
            )
        )
        session.add(
            Solution(
                problem_id=POLYNOMIAL_ID,
                text="Original flawed model solution.",
                source=SolutionSource.MODEL,
            )
        )
        session.add(
            Solution(
                problem_id=POLYNOMIAL_ID,
                text="Original incomplete solver-panel solution.",
                source=SolutionSource.SOLVER_PANEL,
            )
        )

    first = apply_cleanup(db_url)
    second = apply_cleanup(db_url)

    assert first["applied"] == [CANDY_ID, POLYNOMIAL_ID]
    assert second["already_applied"] == [CANDY_ID, POLYNOMIAL_ID]

    with db.session_scope(db_url) as session:
        candy = session.get(Problem, CANDY_ID)
        polynomial = session.get(Problem, POLYNOMIAL_ID)
        solutions = session.exec(
            select(Solution).where(Solution.problem_id == POLYNOMIAL_ID)
        ).all()

        assert candy.verified is True
        assert candy.review_status is ReviewStatus.REJECTED
        assert candy.provenance["human_review_history"][0]["audit_id"] == AUDIT_ID
        assert not is_export_eligible(candy)

        assert polynomial.verified is True
        assert polynomial.review_status is ReviewStatus.ACCEPTED
        assert polynomial.provenance["agent_qa"]["wellposedness"]["verdict"] == "accept"
        assert polynomial.provenance["agent_qa"]["adjudication_history"][0][
            "superseded"
        ]["wellposedness"] == rejected_verdict
        assert is_export_eligible(polynomial)
        category, _, issues = classify_verification(
            verified=polynomial.verified,
            stored_answer=polynomial.answer,
            qa=polynomial.provenance["agent_qa"],
        )
        assert category == "verified"
        assert issues == []

        # The original outputs remain, while the corrected human-approved proof
        # wins deterministic export selection.
        assert len(solutions) == 3
        corrected = [
            solution
            for solution in solutions
            if (solution.features or {}).get("audit_id") == AUDIT_ID
        ]
        assert len(corrected) == 1
        assert corrected[0].source is SolutionSource.HUMAN
        assert "degree at most" in corrected[0].text
        assert preferred_solution(polynomial, solutions).id == corrected[0].id
