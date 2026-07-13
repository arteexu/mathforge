"""Cross-family verification for pending frontier-generated candidates.

GPT independently solves each statement ``k`` times. Claude separately checks
well-posedness, difficulty, and elegance. Results are committed per problem and a
resumable summary is written after every candidate.

The script does not auto-accept or auto-reject; human review status is preserved.

Usage (after loading ``.env.local``):
  PYTHONPATH=src python scripts/verify_frontier_candidates.py --limit 2
  PYTHONPATH=src python scripts/verify_frontier_candidates.py
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlmodel import select

from mathforge import db
from mathforge.agents import run_agent_qa
from mathforge.llm import LLMClient, make_anthropic_backend, make_openai_backend
from mathforge.schema import Problem, ProblemSource, ReviewStatus

REPORT_PATH = Path("data/frontier_verification_report.json")


def _candidate_ids(prefixes: tuple[str, ...], overwrite: bool) -> list[str]:
    wanted = {ReviewStatus.PENDING, ReviewStatus.NEEDS_EDIT}
    with db.session_scope() as session:
        rows = session.exec(
            select(Problem).where(Problem.source == ProblemSource.SYNTHETIC)
        ).all()
    return sorted(
        problem.id
        for problem in rows
        if problem.review_status in wanted
        and any(problem.id.startswith(prefix) for prefix in prefixes)
        and (overwrite or not (problem.provenance or {}).get("agent_qa"))
    )


def _write_report(payload: dict) -> None:
    REPORT_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="0 means all remaining candidates")
    parser.add_argument("--k", type=int, default=3, help="independent solver attempts per problem")
    parser.add_argument("--prefixes", default="distill-rich-,distill-combo-")
    parser.add_argument("--solver-model", default="gpt-5.4")
    parser.add_argument("--solver-backend", choices=("openai", "anthropic"), default="openai")
    parser.add_argument("--judge-model", default="claude-opus-4-8")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    prefixes = tuple(value.strip() for value in args.prefixes.split(",") if value.strip())
    db.init_db()
    ids = _candidate_ids(prefixes, args.overwrite)
    if args.limit > 0:
        ids = ids[:args.limit]
    print(f"frontier verification queue: {len(ids)} candidates; prefixes={prefixes}; k={args.k}", flush=True)
    if args.dry_run:
        for problem_id in ids:
            print(problem_id)
        return

    if args.solver_backend == "openai":
        solver_backend = make_openai_backend(args.solver_model, max_output_tokens=8000)
    else:
        solver_backend = make_anthropic_backend(
            args.solver_model,
            max_output_tokens=10000,
            timeout=300.0,
        )
    solver = LLMClient(
        model=args.solver_model,
        backend=solver_backend,
        purpose="frontier-verify-solver",
    )
    judge = LLMClient(
        model=args.judge_model,
        backend=make_anthropic_backend(
            args.judge_model,
            max_output_tokens=1800,
            timeout=240.0,
        ),
        purpose="frontier-verify-judge",
    )

    payload = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "solver_model": args.solver_model,
        "solver_backend": args.solver_backend,
        "judge_model": args.judge_model,
        "k": args.k,
        "prefixes": list(prefixes),
        "selected": ids,
        "records": [],
        "errors": [],
    }
    _write_report(payload)

    for index, problem_id in enumerate(ids, 1):
        report = run_agent_qa(
            solver=solver,
            judge=judge,
            k=args.k,
            statuses=("pending", "needs_edit"),
            overwrite=args.overwrite,
            id_prefixes=(problem_id,),
            limit=1,
        )
        if report.records:
            record = report.records[0]
            payload["records"].append(record)
            state = "PASS" if record["verified"] else "FAIL"
            print(
                f"[{index}/{len(ids)}] {state} {problem_id}: "
                f"answers={record['agreement']:.2f} consensus={record['consensus']} "
                f"stored={record['stored_answer']} wellposed={record['wellposed']}",
                flush=True,
            )
        else:
            error = report.last_error or "candidate skipped or produced no record"
            payload["errors"].append({"id": problem_id, "error": error})
            print(f"[{index}/{len(ids)}] ERROR {problem_id}: {error}", flush=True)
        _write_report(payload)

    payload["completed_at"] = datetime.now(timezone.utc).isoformat()
    payload["summary"] = {
        "selected": len(ids),
        "processed": len(payload["records"]),
        "verified": sum(bool(record.get("verified")) for record in payload["records"]),
        "answer_mismatch_or_no_consensus": sum(
            not bool(record.get("verified")) for record in payload["records"]
        ),
        "wellposed_accept": sum(record.get("wellposed") == "accept" for record in payload["records"]),
        "wellposed_repair": sum(record.get("wellposed") == "repair" for record in payload["records"]),
        "wellposed_reject": sum(record.get("wellposed") == "reject" for record in payload["records"]),
        "errors": len(payload["errors"]),
    }
    _write_report(payload)
    print(json.dumps(payload["summary"], indent=2), flush=True)
    print(f"wrote {REPORT_PATH}", flush=True)


if __name__ == "__main__":
    main()
