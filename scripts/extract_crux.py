"""Extract a one-line CRUX (key insight) for curated problems that lack one.

For every problem in the elegant+hard curation band that has a solution but no
stored crux, ask Opus to name — in a single sentence — the identity/invariant/
bijection/symmetry/reformulation that makes the problem work. Stored into
provenance["crux"] and Solution.crux_insight so export_weighted can foreground it
as the "Key idea" learning target. Concurrent, per-problem commit, idempotent.

Usage: PYTHONPATH=src python scripts/extract_crux.py <N> <workers>
Env: PE_FLOOR (3.7), DIFF_FLOOR (4.5).
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

MODEL = "claude-opus-4-8"
PE_FLOOR = float(os.environ.get("PE_FLOOR", 3.7))
DIFF_FLOOR = float(os.environ.get("DIFF_FLOOR", 4.5))

PROMPT = """Read this competition math problem and its solution. In ONE sentence, name the single key insight (the crux) that makes it work — the identity, invariant, bijection, symmetry, generating function, or reformulation that collapses the problem once seen. Be specific and concise; do not restate the whole solution.

PROBLEM:
{stmt}

SOLUTION:
{sol}

Output EXACTLY:
<crux>one sentence naming the key insight</crux>"""


def _tag(name, t):
    m = re.search(rf"<{name}>\s*(.*?)\s*</{name}>", t or "", re.S | re.I)
    return m.group(1).strip() if m else None


def _select(limit, prefix=None):
    """Targets = problems with a solution and no crux. With ``prefix`` (e.g. 'math',
    'olymp'), select imported competition problems regardless of elegance; otherwise
    fall back to the curated elegant+hard band (PE/DIFF floors)."""
    with db.session_scope() as ses:
        sols = {s.problem_id: s.text for s in ses.exec(select(Solution)).all()}
        pe_diff = {}
        for e in ses.exec(select(Evaluation)).all():
            d = pe_diff.setdefault(e.problem_id, {})
            if e.elegance_score is not None:
                d["pe"] = e.elegance_score
            if e.difficulty_score is not None:
                d.setdefault("diff", e.difficulty_score)
        targets = []
        for p in ses.exec(select(Problem)).all():
            if p.id not in sols or (p.provenance or {}).get("crux"):
                continue
            if prefix:
                if not any(p.id.startswith(pf) for pf in prefix.split(",")):
                    continue
            else:
                prov = p.provenance or {}
                pe = (prov.get("elegance") or {}).get("problem") or pe_diff.get(p.id, {}).get("pe")
                diff = p.difficulty if p.difficulty is not None else pe_diff.get(p.id, {}).get("diff")
                if pe is None or diff is None or pe < PE_FLOOR or diff < DIFF_FLOOR:
                    continue
            targets.append((p.id, p.statement, sols[p.id]))
    return targets if limit <= 0 else targets[:limit]


def _extract(client, pid, stmt, sol):
    try:
        t = client.complete(PROMPT.format(stmt=stmt[:5000], sol=(sol or "")[:6000]),
                            purpose="extract-crux").text
        return pid, _tag("crux", t)
    except Exception as e:  # noqa: BLE001
        return pid, f"__ERR__{type(e).__name__}: {e}"


def _store(pid, crux):
    if not crux or crux.startswith("__ERR__"):
        print(f"  {pid} {'err '+crux[7:] if crux else 'no crux'}", flush=True)
        return False
    with db.session_scope() as ses:
        p = ses.get(Problem, pid)
        prov = dict(p.provenance or {})
        prov["crux"] = crux
        prov["crux_by"] = "opus-4.8-crux"
        p.provenance = prov
        ses.add(p)
        s = ses.exec(select(Solution).where(Solution.problem_id == pid)).first()
        if s and not s.crux_insight:
            s.crux_insight = crux
            ses.add(s)
    return True


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    db.init_db()
    client = LLMClient(model=MODEL,
                       backend=make_anthropic_backend(MODEL, max_output_tokens=300, timeout=120.0),
                       purpose="extract-crux")
    prefix = sys.argv[3] if len(sys.argv) > 3 else None
    targets = _select(limit, prefix)
    print(f"extracting crux for {len(targets)} problems (prefix={prefix}) with {workers} workers", flush=True)
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(_extract, client, pid, stmt, sol) for pid, stmt, sol in targets]
        for f in as_completed(futs):
            pid, crux = f.result()
            if _store(pid, crux):
                done += 1
                if done % 50 == 0:
                    print(f"  ...{done} stored", flush=True)
    print(f"done: extracted {done}/{len(targets)}", flush=True)


if __name__ == "__main__":
    main()
