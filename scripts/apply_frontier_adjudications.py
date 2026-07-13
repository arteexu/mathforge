"""Apply the July 2026 proof audit for disputed frontier candidates.

The original solver and rules-chair outputs remain in
``agent_qa.adjudication_history``.  This script only updates the operational
verification verdict; it deliberately leaves human ``review_status`` unchanged.

Usage:
    PYTHONPATH=src python scripts/apply_frontier_adjudications.py
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from typing import Any, Optional

from sqlmodel import select

from mathforge import db
from mathforge.schema import Evaluation, Problem, Solution, SolutionSource

AUDIT_ID = "frontier-proof-audit-2026-07-11-v1"
AUDITOR = "codex-proof-adjudication"

ADJUDICATIONS: dict[str, dict[str, str]] = {
    "distill-combo-c1aff7a9": {
        "answer": "795",
        "proof": (
            "Averaging lattice-point indicators over a unit-square translation "
            "gives E[N]=area(S). The isoperimetric inequality for every "
            "rectifiable Jordan curve gives 4*pi*area(S)<=100^2, with equality "
            "for a circle. Thus M=2500/pi and floor(M)=795. The prior reject "
            "incorrectly claimed the area was unbounded and omitted the factor 4."
        ),
    },
    "distill-rich-0a05b8f0": {
        "answer": "900",
        "proof": (
            "Writing consecutive terms as x,y gives the next three terms "
            "(y+1)/x, (x+y+1)/(xy), and (x+1)/y, after which x,y repeat; hence "
            "the recurrence is 5-periodic. At a minimum term m, its neighbors "
            "have product m+1 and are at least m, so m^2<=m+1 and m=1. Its "
            "neighbors are 1 and 2, forcing a rotation of (1,1,2,3,2), whose "
            "sum is 9. Therefore 500 terms sum to 100*9=900."
        ),
    },
    "distill-rich-552f530c": {
        "answer": "250",
        "proof": (
            "Because 7 is 1 modulo 6, S(n) is congruent to n modulo 6. Because "
            "7 is -1 modulo 8, A(n) is congruent to n modulo 8. Both conditions "
            "therefore hold exactly when lcm(6,8)=24 divides n, and "
            "floor(6000/24)=250. Direct enumeration independently returned 250."
        ),
    },
    "distill-rich-d0f2da7b": {
        "answer": "991",
        "proof": (
            "A Catalan number C_n is odd exactly when n=2^j-1. In 1<=n<=1000 "
            "these are 1,3,7,15,31,63,127,255,511: nine indices. Hence exactly "
            "1000-9=991 Catalan numbers are even. The prior reject mistakenly "
            "treated 991 as outside the AIME range."
        ),
    },
    "distill-rich-ec2a1d2d": {
        "answer": "49",
        "proof": (
            "The idempotents modulo 10^10 are 0, 1, 1787109376, and 8212890625 "
            "by CRT modulo 2^10 and 5^10. Exactly the last two are ten-digit, "
            "and the even one is 1787109376, whose digit sum is 49. The prior "
            "reject identified the odd solution as the even one."
        ),
    },
    "distill-rich-f582f84d": {
        "answer": "768",
        "verdict": "reject",
        "answer_verified": True,
        "proof": (
            "Place A=(0,0), B=(s,0), and C=(s/2,sqrt(3)s/2). The three stated "
            "distances force x=(s^2-16)/(2s), y=(s^2-64)/(2sqrt(3)s), and then "
            "x^2+y^2=9 gives q^2-83q+1216=0 for q=s^2. Thus q is 64 or 19. "
            "For q=64, y=0 and P lies on AB; for q=19, y<0 and P lies outside "
            "the triangle. No interior point P exists, so the problem is "
            "inconsistent as stated. The stored 768 is the boundary case only."
        ),
    },
}


def apply_adjudications(
    db_url: Optional[str] = None,
    adjudications: dict[str, dict[str, str]] = ADJUDICATIONS,
) -> dict[str, Any]:
    """Apply adjudications idempotently and return an audit summary."""
    db.init_db(db_url)
    result: dict[str, Any] = {
        "audit_id": AUDIT_ID,
        "applied": [],
        "already_applied": [],
        "not_found": [],
    }

    with db.session_scope(db_url) as session:
        for problem_id, verdict in adjudications.items():
            problem = session.get(Problem, problem_id)
            if problem is None:
                result["not_found"].append(problem_id)
                continue
            if str(problem.answer) != verdict["answer"]:
                raise ValueError(
                    f"{problem_id}: stored answer {problem.answer!r} does not match "
                    f"audited answer {verdict['answer']!r}"
                )

            provenance = dict(problem.provenance or {})
            qa = dict(provenance.get("agent_qa") or {})
            history = list(qa.get("adjudication_history") or [])
            if any(item.get("audit_id") == AUDIT_ID for item in history):
                result["already_applied"].append(problem_id)
                continue

            decision = verdict.get("verdict", "accept")
            if decision not in {"accept", "reject"}:
                raise ValueError(f"{problem_id}: unsupported verdict {decision!r}")
            accepted = decision == "accept"
            answer_verified = bool(verdict.get("answer_verified", accepted))
            entry = {
                "audit_id": AUDIT_ID,
                "adjudicated_at": datetime.now(timezone.utc).isoformat(),
                "auditor": AUDITOR,
                "answer": verdict["answer"],
                "verdict": decision,
                "proof": verdict["proof"],
                "superseded": {
                    "verified": qa.get("verified"),
                    "answer_verified": qa.get("answer_verified"),
                    "wellposedness": qa.get("wellposedness"),
                },
            }
            history.append(entry)
            issues = [] if accepted else [
                {
                    "category": "inconsistency",
                    "severity": "fatal",
                    "description": verdict["proof"],
                }
            ]
            qa.update(
                {
                    "verified": accepted,
                    "answer_verified": answer_verified,
                    "wellposedness": {
                        "verdict": decision,
                        "issues": issues,
                        "adjudicated": True,
                        "audit_id": AUDIT_ID,
                        "reason": verdict["proof"],
                    },
                    "verification_basis": "exact_proof_and_independent_computation",
                    "adjudication_history": history,
                }
            )
            provenance["agent_qa"] = qa
            problem.provenance = provenance
            problem.verified = accepted
            session.add(problem)

            session.add(
                Solution(
                    problem_id=problem_id,
                    text=f"[{AUDIT_ID}] {verdict['proof']}",
                    source=SolutionSource.SOLVER_PANEL,
                    extractor_model=AUDITOR,
                    features={"audit_id": AUDIT_ID, "proof_adjudication": True},
                )
            )
            session.add(
                Evaluation(
                    problem_id=problem_id,
                    evaluator="judge_v2",
                    rationale=f"{AUDIT_ID}: {verdict['proof']}",
                )
            )
            result["applied"].append(problem_id)

    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-url", default=None)
    args = parser.parse_args()
    result = apply_adjudications(db_url=args.db_url)
    print(f"audit: {result['audit_id']}")
    print(f"applied: {len(result['applied'])}")
    print(f"already applied: {len(result['already_applied'])}")
    print(f"not found: {len(result['not_found'])}")


if __name__ == "__main__":
    main()
