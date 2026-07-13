"""Label problems on the axes that matter for a CREATIVE problem-proposer:
crux_creativity and interestingness (weighted highest downstream), plus
problem_elegance and solution_elegance. Runs over problems that already have a
crux (so crux_creativity is judged on the real insight).

Stored in provenance["quality"] AND provenance["elegance"] (problem/solution, for
export compatibility) + an Evaluation row. Concurrent, per-row commit, idempotent.

Usage: PYTHONPATH=src python scripts/label_quality.py <limit> <workers> [prefixes]
e.g.  PYTHONPATH=src python scripts/label_quality.py 0 12 math,olymp,aime
"""

from __future__ import annotations

import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from sqlmodel import select

from mathforge import db
from mathforge.llm import LLMClient, make_anthropic_backend
from mathforge.schema import Evaluation, Problem, Solution

MIN_PE = float(os.environ.get("MIN_PE", 0))   # only (re)label problems already this elegant

MODEL = "claude-opus-4-8"
EVALUATOR = "opus-4.8-quality"

PROMPT = """You are a discerning judge for a system that PROPOSES original competition problems. Judge the problem below (statement + its key insight + solution). We care most about whether the KEY INSIGHT is creative and the PROBLEM is interesting -- not about how rigorous the write-up is.

Rate each 0.0-5.0 (one decimal), using the full range:
- crux_creativity: how novel, surprising, and non-obvious the key insight is (5 = a genuinely clever, unexpected idea; 1 = a routine/standard move).
- interestingness: how engaging and appealing the problem is to a strong solver (5 = you'd want to share it; 1 = a dull exercise).
- problem_elegance: beauty of the problem (striking, minimal setup, one deep crux).
- solution_elegance: beauty of the solution (short, one key idea vs heavy casework).

PROBLEM:
{stmt}

KEY INSIGHT (crux):
{crux}

SOLUTION:
{sol}

Output EXACTLY:
<crux_creativity>0-5</crux_creativity>
<interestingness>0-5</interestingness>
<problem_elegance>0-5</problem_elegance>
<solution_elegance>0-5</solution_elegance>
<reason>one short sentence</reason>"""


def _tag(n, t):
    m = re.search(rf"<{n}>\s*(.*?)\s*</{n}>", t or "", re.S | re.I)
    return m.group(1).strip() if m else None
def _num(x, lo, hi):
    if not x: return None
    m = re.search(r"-?\d+(\.\d+)?", x); v = float(m.group()) if m else None
    return v if (v is not None and lo <= v <= hi) else None


def _select(limit, prefixes):
    with db.session_scope() as ses:
        sols = {s.problem_id: s.text for s in ses.exec(select(Solution)).all()}
        pe_eval = {e.problem_id: e.elegance_score for e in ses.exec(select(Evaluation)).all()
                   if e.elegance_score is not None}
        rows = []
        for p in ses.exec(db.training_problems_select()).all():
            prov = p.provenance or {}
            if p.id not in sols or not prov.get("crux") or prov.get("quality"):
                continue
            if prefixes and not any(p.id.startswith(pf) for pf in prefixes):
                continue
            if MIN_PE > 0:                                     # target only the already-elegant
                pe = (prov.get("elegance") or {}).get("problem") or pe_eval.get(p.id)
                if pe is None or pe < MIN_PE:
                    continue
            rows.append((p.id, p.statement, prov["crux"], sols[p.id]))
    return rows if limit <= 0 else rows[:limit]


def _rate(client, pid, stmt, crux, sol):
    try:
        t = client.complete(
            PROMPT.format(stmt=stmt[:4500], crux=crux[:800], sol=(sol or "")[:5000]),
            purpose="label-quality").text
        return pid, dict(crux_creativity=_num(_tag("crux_creativity", t), 0, 5),
                         interestingness=_num(_tag("interestingness", t), 0, 5),
                         problem=_num(_tag("problem_elegance", t), 0, 5),
                         solution=_num(_tag("solution_elegance", t), 0, 5),
                         reason=_tag("reason", t))
    except Exception as e:  # noqa: BLE001
        return pid, {"error": str(e)}


def _store(pid, q):
    if q.get("error") or (q.get("crux_creativity") is None and q.get("problem") is None):
        print(f"  {pid} skip ({q.get('error','parse fail')})", flush=True)
        return False
    with db.session_scope() as ses:
        p = ses.get(Problem, pid)
        prov = dict(p.provenance or {})
        prov["quality"] = {"crux_creativity": q["crux_creativity"], "interestingness": q["interestingness"],
                           "problem_elegance": q["problem"], "solution_elegance": q["solution"],
                           "rated_by": EVALUATOR}
        prov["elegance"] = {"problem": q["problem"], "solution": q["solution"], "rated_by": EVALUATOR}
        p.provenance = prov
        ses.add(p)
        ses.add(Evaluation(problem_id=pid, elegance_score=q["problem"], evaluator=EVALUATOR,
                           rationale=f"crux_creativity={q['crux_creativity']}, interestingness={q['interestingness']} "
                                     f"({q.get('reason','')})"[:500]))
    return True


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    prefixes = sys.argv[3].split(",") if len(sys.argv) > 3 else None
    db.init_db()
    client = LLMClient(model=MODEL,
                       backend=make_anthropic_backend(MODEL, max_output_tokens=400, timeout=120.0),
                       purpose="label-quality")
    rows = _select(limit, prefixes)
    print(f"labeling {len(rows)} problems (prefixes={prefixes}) with {workers} workers", flush=True)
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(_rate, client, pid, s, c, sol) for pid, s, c, sol in rows]
        for f in as_completed(futs):
            pid, q = f.result()
            if _store(pid, q):
                done += 1
                if done % 100 == 0:
                    print(f"  ...{done} labeled", flush=True)
    print(f"done: labeled {done}/{len(rows)}", flush=True)


if __name__ == "__main__":
    main()
