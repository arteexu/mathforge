"""Label imported competition problems (Omni-Math, AIME, ...) with elegance.

For every selected problem that lacks an elegance rating, this asks the opus rater
(the SAME model that scored the rich set, so the 0-5 scale stays calibrated) for a
problem_elegance and a solution_elegance, plus a one-line reason each. Ratings are
stored as an Evaluation (elegance_score) AND folded into provenance["elegance"] so
the exporter can condition training prompts on them, exactly like the rich problems.

Rating is a judgement task, not a derivation, so it runs WITHOUT extended thinking
(fast + cheap) and with concurrent workers. Per-problem commit -> idempotent and
resumable: re-running only labels what is still missing.

Usage:
    PYTHONPATH=src python scripts/label_elegance.py <N> <workers> [prefix]
    # N=limit (0 = all remaining), workers=concurrency, prefix defaults to omni-math
"""

from __future__ import annotations

import re
import sys

from sqlmodel import select

from mathforge import db
from mathforge.llm import LLMClient, make_anthropic_backend
from mathforge.schema import Evaluation, Problem, Solution

MODEL = "claude-opus-4-8"
EVALUATOR = "opus-4.8-elegance"

PROMPT = r"""You are a discerning judge of competition-mathematics aesthetics. Rate the problem below on two axes, each 0.0-5.0 (one decimal).

- problem_elegance: beauty of the PROBLEM itself. 5 = striking, surprising, minimal setup resting on one deep idea; 3 = solid and clean; 1 = routine, contrived, or a grind.
- solution_elegance: beauty of the SOLUTION/idea needed. 5 = short and inevitable-feeling, one key insight; 3 = reasonable; 1 = heavy case-work or brute computation.

Judge intrinsic quality; ignore how hard it is. Be calibrated and willing to use the full range.

PROBLEM:
{statement}

SOLUTION (reference):
{solution}

Output EXACTLY these four tags and nothing else:
<problem_elegance>0-5</problem_elegance>
<problem_elegance_reason>one short sentence</problem_elegance_reason>
<solution_elegance>0-5</solution_elegance>
<solution_elegance_reason>one short sentence</solution_elegance_reason>
"""


def _tag(name: str, text: str):
    m = re.search(rf"<{name}>\s*(.*?)\s*</{name}>", text or "", re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else None


def _num(raw, lo, hi):
    if raw is None:
        return None
    m = re.search(r"-?\d+(\.\d+)?", raw)
    if not m:
        return None
    v = float(m.group())
    return v if lo <= v <= hi else None


def _select_targets(prefix: str, limit: int) -> list[str]:
    """IDs of problems with a solution but no elegance rating yet (resumable)."""
    with db.session_scope() as ses:
        have_elegance = {
            e.problem_id
            for e in ses.exec(select(Evaluation)).all()
            if e.elegance_score is not None
        }
        have_solution = {s.problem_id for s in ses.exec(select(Solution)).all()}
        ids = [
            p.id
            for p in ses.exec(db.training_problems_select()).all()
            if p.id.startswith(prefix)
            and p.id in have_solution
            and p.id not in have_elegance
        ]
    return ids if limit <= 0 else ids[:limit]


def _rate_one(client, statement: str, solution: str) -> str:
    prompt = PROMPT.format(statement=statement[:6000], solution=(solution or "")[:6000])
    try:
        return client.complete(prompt, purpose="label-elegance").text
    except Exception as e:  # noqa: BLE001
        return f"__ERR__{type(e).__name__}: {e}"


def _store(pid: str, t: str) -> bool:
    if t.startswith("__ERR__"):
        print(f"  {pid} error: {t[7:]}", flush=True)
        return False
    pe = _num(_tag("problem_elegance", t), 0, 5)
    se = _num(_tag("solution_elegance", t), 0, 5)
    if pe is None and se is None:
        print(f"  {pid} parse fail", flush=True)
        return False
    pe_reason = _tag("problem_elegance_reason", t) or ""
    se_reason = _tag("solution_elegance_reason", t) or ""
    with db.session_scope() as ses:
        p = ses.get(Problem, pid)
        prov = dict(p.provenance or {})
        prov["elegance"] = {
            "problem": pe, "problem_reason": pe_reason,
            "solution": se, "solution_reason": se_reason,
            "rated_by": EVALUATOR,
        }
        p.provenance = prov
        ses.add(p)
        ses.add(Evaluation(
            problem_id=pid, elegance_score=pe, evaluator=EVALUATOR,
            rationale=f"problem_elegance={pe} ({pe_reason}); solution_elegance={se} ({se_reason})"[:500]))
    print(f"  {pid} PE={pe} SE={se}", flush=True)
    return True


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    prefix = sys.argv[3] if len(sys.argv) > 3 else "omni-math"
    db.init_db()
    client = LLMClient(
        model=MODEL,
        backend=make_anthropic_backend(MODEL, max_output_tokens=400, timeout=120.0),
        purpose="label-elegance",
    )

    ids = _select_targets(prefix, limit)
    print(f"labeling {len(ids)} '{prefix}' problems with {workers} workers", flush=True)

    # preload statement + solution text for each id
    with db.session_scope() as ses:
        sols = {s.problem_id: s.text for s in ses.exec(select(Solution)).all()}
        stmts = {
            p.id: p.statement
            for p in ses.exec(db.training_problems_select()).all()
            if p.id in set(ids)
        }

    labeled = 0
    if workers <= 1:
        for pid in ids:
            if _store(pid, _rate_one(client, stmts.get(pid, ""), sols.get(pid, ""))):
                labeled += 1
    else:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {
                ex.submit(_rate_one, client, stmts.get(pid, ""), sols.get(pid, "")): pid
                for pid in ids
            }
            for fut in as_completed(futs):
                if _store(futs[fut], fut.result()):
                    labeled += 1

    print(f"done: labeled {labeled}/{len(ids)}", flush=True)


if __name__ == "__main__":
    main()
