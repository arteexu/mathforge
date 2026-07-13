"""Retry only missing/internally inconsistent frontier well-posedness verdicts.

Existing independent solver consensus is reused; no expensive re-solving occurs.
"""

from __future__ import annotations

import argparse

from sqlmodel import select

from mathforge import db
from mathforge.agents import judge_wellposedness
from mathforge.llm import LLMClient, make_anthropic_backend
from mathforge.schema import Problem, ProblemSource
from mathforge.solver import check_answer


def _needs_recheck(problem: Problem) -> bool:
    qa = (problem.provenance or {}).get("agent_qa") or {}
    wp = qa.get("wellposedness")
    if not wp or not wp.get("verdict"):
        return bool(qa)
    return wp.get("verdict") == "accept" and any(
        issue.get("severity") == "fatal" for issue in wp.get("issues", [])
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", default="", help="comma-separated exact IDs; default=all inconsistent")
    parser.add_argument("--prefixes", default="distill-rich-,distill-combo-")
    parser.add_argument("--judge-model", default="claude-opus-4-8")
    args = parser.parse_args()
    exact_ids = {value.strip() for value in args.ids.split(",") if value.strip()}
    prefixes = tuple(value.strip() for value in args.prefixes.split(",") if value.strip())

    db.init_db()
    with db.session_scope() as session:
        candidates = [
            problem
            for problem in session.exec(
                select(Problem).where(Problem.source == ProblemSource.SYNTHETIC)
            ).all()
            if (problem.id in exact_ids if exact_ids else (
                any(problem.id.startswith(prefix) for prefix in prefixes) and _needs_recheck(problem)
            ))
        ]
    candidates.sort(key=lambda problem: problem.id)
    print(f"well-posedness recheck queue: {len(candidates)}", flush=True)

    judge = LLMClient(
        model=args.judge_model,
        backend=make_anthropic_backend(args.judge_model, max_output_tokens=1800, timeout=240.0),
        purpose="frontier-wellposedness-recheck",
    )
    for index, candidate in enumerate(candidates, 1):
        result = judge_wellposedness(judge, candidate.statement, candidate.answer)
        data = result.get("data")
        with db.session_scope() as session:
            problem = session.get(Problem, candidate.id)
            provenance = dict(problem.provenance or {})
            qa = dict(provenance.get("agent_qa") or {})
            answer_verified = qa.get("answer_verified")
            if answer_verified is None:
                answer_verified = check_answer(qa.get("consensus"), problem.answer)
            final_verified = bool(answer_verified and data and data.get("verdict") == "accept")
            qa["wellposedness"] = data
            qa["answer_verified"] = bool(answer_verified)
            qa["verified"] = final_verified
            qa["wellposedness_rechecked"] = True
            provenance["agent_qa"] = qa
            problem.provenance = provenance
            problem.verified = final_verified
            session.add(problem)
        verdict = data.get("verdict") if data else None
        print(f"[{index}/{len(candidates)}] {candidate.id}: verdict={verdict} verified={final_verified}", flush=True)


if __name__ == "__main__":
    main()
