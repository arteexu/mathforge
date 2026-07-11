"""Generate original problems by COMBINING a small number of techniques.

Samples 2 (sometimes 3) techniques that are compatible -- they share an object type
but use different mechanisms, so the combination creates a real twist rather than
redundancy -- then has Opus (max thinking) compose a WELL-POSED problem that genuinely
requires all of them (each technique load-bearing). Every candidate must pass an Opus
well-posedness gate before it is stored as a ``distill-combo-`` rich problem.

Usage: PYTHONPATH=src python scripts/generate_from_techniques.py <n_keep> [max_techniques]
"""

from __future__ import annotations

import json
import random
import re
import sys
import uuid
from pathlib import Path

from mathforge import db
from mathforge.llm import LLMClient, make_anthropic_backend
from mathforge.schema import (
    DataSplit, Evaluation, Problem, ProblemSource, ReviewStatus, Solution,
    SolutionSource, statement_hash,
)

MODEL = "claude-opus-4-8"
TECHS = json.loads(Path("data/techniques.json").read_text())
random.seed()


def _tag(n, t):
    m = re.search(rf"<{n}>\s*(.*?)\s*</{n}>", t or "", re.S | re.I)
    return m.group(1).strip() if m else None
def _num(x, lo, hi):
    if not x: return None
    m = re.search(r"-?\d+(\.\d+)?", x); v = float(m.group()) if m else None
    return v if (v is not None and lo <= v <= hi) else None
def _int(x):
    if not x: return None
    m = re.search(r"-?\d+", x); v = int(m.group()) if m else None
    return v if (v is not None and 0 <= v <= 999) else None


def compatible(a, b):
    if b["id"] in a.get("combinability", {}).get("avoid_with", []): return False
    if a["id"] in b.get("combinability", {}).get("avoid_with", []): return False
    shared = set(a.get("objects", [])) & set(b.get("objects", []))
    return bool(shared) and a.get("mechanism") != b.get("mechanism")


def sample_combo(max_k):
    """Pick 2 compatible techniques (3 with prob 0.25 if a mutually-compatible third exists)."""
    for _ in range(200):
        t1 = random.choice(TECHS)
        cands = [t for t in TECHS if t["id"] != t1["id"] and compatible(t1, t)]
        if not cands:
            continue
        t2 = random.choice(cands)
        combo = [t1, t2]
        if max_k >= 3 and random.random() < 0.25:
            third = [t for t in cands if t["id"] != t2["id"] and compatible(t2, t)]
            if third:
                combo.append(random.choice(third))
        return combo
    return None


GEN = """You are an elite olympiad problem composer. Use your extended thinking fully.

Compose ONE original competition problem that GENUINELY requires combining ALL of these techniques. Each must be load-bearing: if any one is removed, the intended solution should break.
{techlist}

Hard requirements:
- Fully self-contained, unambiguous, well-posed; every object defined; a single well-defined answer (prefer a unique integer in [0, 999]).
- The techniques must interact (not be two separable sub-problems stapled together).
- Solve it and DOUBLE-CHECK the answer a second way inside your thinking.

Output EXACTLY these tags:
<statement>the full problem</statement>
<answer>the integer 0-999</answer>
<topic>one of: Algebra|Combinatorics|Geometry|Number Theory|Precalculus|Probability</topic>
<difficulty>AoPS 1-10, one decimal</difficulty>
<crux>one sentence naming how the techniques interact</crux>
<solution>a complete rigorous solution ending at the integer answer</solution>
<problem_elegance>0.0-5.0</problem_elegance>"""

GATE = """You are a strict competition-math editor. Is the problem below well-posed
(every term defined, unambiguous, self-contained, not self-contradictory, a single
well-defined answer) and non-trivial? Verify briefly.

{cand}

Output EXACTLY:
<well_posed>0 or 1</well_posed>
<nontrivial>0 or 1</nontrivial>
<reason>one short sentence</reason>"""


def main():
    n_keep = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    max_k = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    db.init_db()
    gen = LLMClient(model=MODEL,
                    backend=make_anthropic_backend(MODEL, effort="high", max_output_tokens=10000, timeout=600.0),
                    purpose="combo-gen")
    judge = LLMClient(model=MODEL,
                      backend=make_anthropic_backend(MODEL, max_output_tokens=400, timeout=120.0),
                      purpose="combo-gate")
    kept, attempts = 0, 0
    while kept < n_keep and attempts < n_keep * 4:
        attempts += 1
        combo = sample_combo(max_k)
        if not combo:
            continue
        techlist = "\n".join(f"- {t['name']} ({t['area']}): {t.get('one_liner','')}" for t in combo)
        ids = [t["id"] for t in combo]
        try:
            t = gen.complete(GEN.format(techlist=techlist), purpose="combo-gen", effort="high").text
        except Exception as e:
            print(f"[{attempts}] gen error: {e}", flush=True); continue
        stmt, ans = _tag("statement", t), _int(_tag("answer", t))
        sol, crux = _tag("solution", t), _tag("crux", t) or ""
        if not (stmt and sol) or ans is None:
            print(f"[{attempts}] parse fail  ({'+'.join(ids)})", flush=True); continue
        # validity gate
        g = judge.complete(GATE.format(cand=(stmt + "\n\nSolution:\n" + sol)[:6000]), purpose="combo-gate").text
        if not (_num(_tag("well_posed", g), 0, 1) == 1 and _num(_tag("nontrivial", g), 0, 1) == 1):
            print(f"[{attempts}] gate REJECT ({'+'.join(ids)}) :: {_tag('reason', g)}", flush=True); continue
        pe = _num(_tag("problem_elegance", t), 0, 5)
        diff = _num(_tag("difficulty", t), 1, 10)
        topic = _tag("topic", t)
        pid = f"distill-combo-{uuid.uuid4().hex[:8]}"
        with db.session_scope() as s:
            s.add(Problem(id=pid, source=ProblemSource.SYNTHETIC, statement=stmt, answer=str(ans),
                          difficulty=diff, topic=topic, split=DataSplit.TRAIN,
                          review_status=ReviewStatus.PENDING,
                          provenance={"pipeline": "distill-combo", "techniques": ids, "crux": crux,
                                      "elegance": {"problem": pe}}).refresh_dedup_fields())
            s.add(Solution(problem_id=pid, text=sol, crux_insight=crux,
                           source=SolutionSource.MODEL, extractor_model=MODEL))
            if pe is not None or diff is not None:
                s.add(Evaluation(problem_id=pid, elegance_score=pe, difficulty_score=diff,
                                 evaluator="opus-4.8-combo"))
        kept += 1
        print(f"[{attempts}] KEPT {pid} ans={ans} PE={pe} d={diff} [{topic}] techs={'+'.join(ids)}", flush=True)
    print(f"done: kept {kept}/{attempts} attempts", flush=True)


if __name__ == "__main__":
    main()
