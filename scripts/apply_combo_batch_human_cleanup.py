"""Apply the final human cleanup for ``combo-batch-20260711-v2``.

The cleanup is deliberately narrow and idempotent:

* reject the routine stars-and-bars candidate that the human reviewer marked as
  needing a more original concept; and
* override a false-negative well-posedness verdict for the polynomial candidate,
  while adding a corrected, human-approved solution.  Earlier model and solver
  outputs are retained for provenance.

Usage:
    PYTHONPATH=src python scripts/apply_combo_batch_human_cleanup.py
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from typing import Any, Optional

from sqlmodel import select

from mathforge import db
from mathforge.schema import (
    DataSplit,
    Problem,
    ProblemSource,
    ReviewStatus,
    Solution,
    SolutionSource,
)

AUDIT_ID = "combo-batch-20260711-v2-human-cleanup-v1"
AUDITOR = "codex-proof-adjudication-with-human-approval"

CANDY_ID = "distill-combo-813e320cde03"
POLYNOMIAL_ID = "distill-combo-ee5caba7d031"

CANDY_REJECTION_REASON = (
    "Human creativity review: this is a standard stars-and-bars plus linearity "
    "of expectation exercise, so the technique combination is too familiar for "
    "the creativity-focused synthetic set. Regenerate the concept rather than "
    "performing a cosmetic statement edit."
)

POLYNOMIAL_ADJUDICATION_REASON = (
    "The prior rules-chair verdict confused non-uniqueness of the polynomial "
    "triple with non-uniqueness of the requested value. The identity at every "
    "integer is a polynomial identity. A mod-3 infinite descent on the leading "
    "coefficients rules out degree at least two; the linear coefficient then "
    "forces A(100)+B(100)=302 for every admissible triple."
)

POLYNOMIAL_SOLUTION = r"""Let
\[
F(x)=A(x)^2+B(x)^2-3C(x)^2-(6x^2+6x+2).
\]
The hypothesis gives \(F(n)=0\) for every integer \(n\). Since a nonzero
polynomial has only finitely many roots, \(F\equiv 0\). Thus
\[
A(x)^2+B(x)^2-3C(x)^2=6x^2+6x+2. \tag{1}
\]

We first prove that \(A,B,C\) all have degree at most \(1\). Suppose instead
that
\[
m=\max(\deg A,\deg B,\deg C)\ge 2,
\]
and let \(a,b,c\) be their respective coefficients of \(x^m\), allowing some
of these coefficients to be zero. They are not all zero. Because the right
side of (1) has degree \(2<2m\), comparison of the \(x^{2m}\)-coefficients
gives
\[
a^2+b^2=3c^2. \tag{2}
\]
Modulo \(3\), equation (2) forces \(3\mid a\) and \(3\mid b\), since the only
quadratic residues modulo \(3\) are \(0\) and \(1\). Write
\(a=3a_1\) and \(b=3b_1\). Then
\[
c^2=3(a_1^2+b_1^2),
\]
so \(3\mid c\); write \(c=3c_1\). Dividing (2) by \(9\) produces the same
equation for \((a_1,b_1,c_1)\). Repeating would make \(a,b,c\) divisible by
every power of \(3\), which is impossible unless all three are zero. This
contradicts the definition of \(m\). Hence \(m\le 1\).

Using the prescribed constant terms, write
\[
A(x)=ax+1,\qquad B(x)=bx+1,\qquad C(x)=cx
\]
for integers \(a,b,c\). Comparing the coefficients of \(x\) in (1) gives
\[
2a+2b=6,
\]
so \(a+b=3\). Therefore
\[
A(100)+B(100)=100(a+b)+2=100\cdot 3+2=\boxed{302}.
\]

Finally, admissible polynomials do exist: \(A(x)=3x+1\), \(B(x)=1\), and
\(C(x)=x\) satisfy every condition. Thus the requested value is fixed,
although the triple \((A,B,C)\) itself need not be unique."""


def _history_entry(
    *, decision: str, reason: str, prior_status: ReviewStatus | None, prior_verified: bool | None
) -> dict[str, Any]:
    return {
        "audit_id": AUDIT_ID,
        "adjudicated_at": datetime.now(timezone.utc).isoformat(),
        "auditor": AUDITOR,
        "decision": decision,
        "reason": reason,
        "superseded": {
            "review_status": prior_status.value if prior_status else None,
            "verified": prior_verified,
        },
    }


def apply_cleanup(db_url: Optional[str] = None) -> dict[str, Any]:
    """Apply both human decisions and return a compact audit summary."""
    db.init_db(db_url)
    result: dict[str, Any] = {
        "audit_id": AUDIT_ID,
        "applied": [],
        "already_applied": [],
        "not_found": [],
    }

    with db.session_scope(db_url) as session:
        candy = session.get(Problem, CANDY_ID)
        polynomial = session.get(Problem, POLYNOMIAL_ID)

        for problem_id, problem in ((CANDY_ID, candy), (POLYNOMIAL_ID, polynomial)):
            if problem is None:
                result["not_found"].append(problem_id)
            elif problem.source != ProblemSource.SYNTHETIC:
                raise ValueError(f"{problem_id}: expected a synthetic problem")
            elif problem.split != DataSplit.TRAIN or problem.frozen:
                raise ValueError(f"{problem_id}: refused to mutate eval/frozen data")

        if candy is not None:
            if str(candy.answer) != "163":
                raise ValueError(
                    f"{CANDY_ID}: expected answer '163', got {candy.answer!r}"
                )
            provenance = dict(candy.provenance or {})
            history = list(provenance.get("human_review_history") or [])
            if any(item.get("audit_id") == AUDIT_ID for item in history):
                result["already_applied"].append(CANDY_ID)
            else:
                history.append(
                    _history_entry(
                        decision="reject_for_creativity",
                        reason=CANDY_REJECTION_REASON,
                        prior_status=candy.review_status,
                        prior_verified=candy.verified,
                    )
                )
                provenance["human_review_history"] = history
                provenance["human_rejection_reason"] = CANDY_REJECTION_REASON
                candy.provenance = provenance
                # It remains mathematically verified; the human rejection is a
                # quality/originality decision, not a correctness reversal.
                candy.review_status = ReviewStatus.REJECTED
                session.add(candy)
                result["applied"].append(CANDY_ID)

        if polynomial is not None:
            if str(polynomial.answer) != "302":
                raise ValueError(
                    f"{POLYNOMIAL_ID}: expected answer '302', got {polynomial.answer!r}"
                )

            provenance = dict(polynomial.provenance or {})
            human_history = list(provenance.get("human_review_history") or [])
            already_adjudicated = any(
                item.get("audit_id") == AUDIT_ID for item in human_history
            )

            existing_solutions = session.exec(
                select(Solution).where(Solution.problem_id == POLYNOMIAL_ID)
            ).all()
            has_corrected_solution = any(
                (solution.features or {}).get("audit_id") == AUDIT_ID
                for solution in existing_solutions
            )

            changed = False
            if not already_adjudicated:
                human_history.append(
                    _history_entry(
                        decision="accept_and_verify",
                        reason=POLYNOMIAL_ADJUDICATION_REASON,
                        prior_status=polynomial.review_status,
                        prior_verified=polynomial.verified,
                    )
                )
                provenance["human_review_history"] = human_history
                changed = True

            qa = dict(provenance.get("agent_qa") or {})
            qa_history = list(qa.get("adjudication_history") or [])
            if not any(item.get("audit_id") == AUDIT_ID for item in qa_history):
                qa_history.append(
                    {
                        "audit_id": AUDIT_ID,
                        "adjudicated_at": datetime.now(timezone.utc).isoformat(),
                        "auditor": AUDITOR,
                        "answer": "302",
                        "verdict": "accept",
                        "proof": POLYNOMIAL_ADJUDICATION_REASON,
                        "superseded": {
                            "verified": qa.get("verified"),
                            "answer_verified": qa.get("answer_verified"),
                            "wellposedness": qa.get("wellposedness"),
                        },
                    }
                )
                changed = True
            qa.update(
                {
                    "verified": True,
                    "answer_verified": True,
                    "wellposedness": {
                        "verdict": "accept",
                        "issues": [],
                        "adjudicated": True,
                        "audit_id": AUDIT_ID,
                        "reason": POLYNOMIAL_ADJUDICATION_REASON,
                    },
                    "verification_basis": "human_approved_exact_proof",
                    "adjudication_history": qa_history,
                }
            )
            provenance["agent_qa"] = qa
            polynomial.provenance = provenance
            polynomial.verified = True
            polynomial.review_status = ReviewStatus.ACCEPTED
            session.add(polynomial)

            if not has_corrected_solution:
                session.add(
                    Solution(
                        problem_id=POLYNOMIAL_ID,
                        text=POLYNOMIAL_SOLUTION,
                        techniques=[
                            "alg.poly_infinite_roots",
                            "nt.infinite_descent",
                        ],
                        crux_insight=(
                            "Promote the equality on all integers to a polynomial "
                            "identity, then use mod-3 descent on the leading "
                            "coefficients to force all degrees down to one."
                        ),
                        crux_count=2,
                        routine_step_count=3,
                        source=SolutionSource.HUMAN,
                        extractor_model=AUDITOR,
                        features={
                            "audit_id": AUDIT_ID,
                            "proof_adjudication": True,
                            "human_approved": True,
                            "retains_original_outputs": True,
                        },
                    )
                )
                changed = True

            if changed:
                result["applied"].append(POLYNOMIAL_ID)
            else:
                result["already_applied"].append(POLYNOMIAL_ID)

    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-url", default=None)
    args = parser.parse_args()
    result = apply_cleanup(db_url=args.db_url)
    print(f"audit: {result['audit_id']}")
    print(f"applied: {len(result['applied'])}")
    print(f"already applied: {len(result['already_applied'])}")
    print(f"not found: {len(result['not_found'])}")


if __name__ == "__main__":
    main()
