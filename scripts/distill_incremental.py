"""Incremental distill generation via the Anthropic gateway.

Same generation path as `mathforge distill --no-verify` (uses
prompts/distill_generation_v1 with topic/difficulty rotation and an avoid-list),
but COMMITS EACH PROBLEM IMMEDIATELY in its own transaction, so a timeout or
session teardown never discards completed work. Verification is done separately,
out-of-band, by exact computation.
"""

from __future__ import annotations

import sys
import uuid

from sqlmodel import select

from mathforge import db
from mathforge.distill import (
    DIVERSITY_TOPICS,
    _avoid_block,
    _rotate_target,
    generate_problem,
    is_banned_template,
    is_garbled,
    is_near_duplicate,
    token_set,
)
from mathforge.llm import LLMClient, make_anthropic_backend
from mathforge.schema import (
    DataSplit,
    Problem,
    ProblemSource,
    ReviewStatus,
    Solution,
    SolutionSource,
    statement_hash,
)

MODEL = "claude-opus-4-8"


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    db.init_db()
    client = LLMClient(model=MODEL, backend=make_anthropic_backend(MODEL), purpose="distill")

    with db.session_scope() as ses:
        seen = set(ses.exec(select(Problem.statement_hash)).all())
        seen_sigs = [token_set(s) for s in ses.exec(select(Problem.statement)).all() if s]

    recent: list[str] = []
    stored = 0
    i = 0
    while stored < n and i < n * 3:
        target = _rotate_target(i, DIVERSITY_TOPICS)
        i += 1
        try:
            g = generate_problem(client, target, avoid=_avoid_block(recent))
        except Exception as e:  # keep going on a single failure
            print(f"[{i}] gen error: {type(e).__name__}: {e}", flush=True)
            continue
        if not g["ok"] or g["answer"] is None:
            print(f"[{i}] parse fail", flush=True)
            continue
        if is_banned_template(g["statement"]):
            print(f"[{i}] banned template, skipped", flush=True)
            recent.append(f"[{g['topic']}] {g['statement'][:100]}")
            continue
        if is_garbled(g["statement"]):
            print(f"[{i}] garbled statement, skipped", flush=True)
            recent.append(f"[{g['topic']}] {g['statement'][:100]}")
            continue
        sig = token_set(g["statement"])
        if is_near_duplicate(sig, seen_sigs):
            print(f"[{i}] near-duplicate, skipped", flush=True)
            recent.append(f"[{g['topic']}] {g['statement'][:100]}")
            continue
        recent.append(f"[{g['topic']}] {g['statement'][:100]}")
        sh = statement_hash(g["statement"])
        if sh in seen:
            print(f"[{i}] duplicate, skipped", flush=True)
            continue
        seen.add(sh); seen_sigs.append(sig)

        pid = f"distill-{uuid.uuid4().hex[:8]}"
        with db.session_scope() as ses:  # commit THIS problem immediately
            ses.add(
                Problem(
                    id=pid, source=ProblemSource.SYNTHETIC, statement=g["statement"],
                    answer=str(g["answer"]), difficulty=g["difficulty"], topic=g["topic"],
                    split=DataSplit.TRAIN, verified=None, review_status=ReviewStatus.PENDING,
                    possibly_memorized=False,
                    provenance={
                        "pipeline": "distill", "mode": "generation_only",
                        "generator_model": MODEL, "target": target,
                        "generated_answer": str(g["answer"]), "crux": g["crux"],
                    },
                ).refresh_dedup_fields()
            )
            ses.add(Solution(problem_id=pid, text=g["solution"], crux_insight=g["crux"],
                             source=SolutionSource.MODEL, extractor_model=MODEL))
        stored += 1
        print(f"[{i}] STORED {pid} ans={g['answer']} topic={g['topic']} "
              f"diff={g['difficulty']} :: {g['statement'][:70]}", flush=True)

    print(f"done: stored {stored} new problems", flush=True)


if __name__ == "__main__":
    main()
