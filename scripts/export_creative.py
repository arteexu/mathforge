"""Export a CREATIVITY-weighted training set -> data/train_creative.jsonl.

Optimizes for what we actually want: a creative, interesting problem-proposer.
- priority = 0.45*crux_creativity + 0.30*interestingness + 0.15*elegance + 0.10*difficulty
- human sources (imports, Omni) must clear a crux_creativity floor (default 3.0);
  model-authored crux-first sources (distill-rich, distill-combo) are always kept.
- completions foreground the crux (Key idea) AND include the FULL solution -- validity
  is handled downstream (best-of-N), but full solutions still teach coherence.
- oversample by priority so the most creative/interesting problems dominate.

Run: PYTHONPATH=src python scripts/export_creative.py
Env: CC_FLOOR (3.0), DIFF_FLOOR (3.0), MAX_COPIES (5).
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path

from sqlmodel import select

from mathforge import db
from mathforge.schema import Evaluation, Problem, Solution

OUT = Path("data/train_creative.jsonl")
CC_FLOOR = float(os.environ.get("CC_FLOOR", 3.0))
DIFF_FLOOR = float(os.environ.get("DIFF_FLOOR", 3.0))
MAX_COPIES = int(os.environ.get("MAX_COPIES", 5))
W_CC, W_INT, W_EL, W_DIFF = 0.45, 0.30, 0.15, 0.10
ALWAYS = ("distill-rich", "distill-combo")


def _src(pid):
    for pre, tag in [("omni-math", "omni"), ("distill-rich", "rich"), ("distill-combo", "combo"),
                     ("distill", "distill"), ("opus", "opus"), ("aime", "aime"),
                     ("olymp", "olympiad"), ("math", "math")]:
        if pid.startswith(pre):
            return tag
    return "other"


def _atype(a):
    if a is None: return "none"
    a = str(a).strip()
    if re.fullmatch(r"-?\d+", a): return "integer" if 0 <= int(a) <= 999 else "integer_other"
    return "symbolic"


def build_prompt(topic, diff, cc, interest):
    bits = ["Compose one original competition math problem built on a SINGLE creative, non-obvious insight (a crux).",
            "Prioritize a surprising key idea and an interesting problem."]
    if topic: bits.append(f"Topic: {topic}.")
    if diff is not None: bits.append(f"Target difficulty (AoPS 1-10): {diff}.")
    if cc is not None: bits.append(f"Target crux-creativity (0-5): {cc}.")
    if interest is not None: bits.append(f"Target interestingness (0-5): {interest}.")
    bits.append("Give the statement, then the key idea, then a full solution.")
    return " ".join(bits)


def build_completion(stmt, crux, sol, ans):
    parts = [f"Problem:\n{stmt.strip()}"]
    if crux: parts.append(f"\nKey idea:\n{crux.strip()}")
    if sol: parts.append(f"\nSolution:\n{sol.strip()}")
    if ans is not None: parts.append(f"\nAnswer: {ans}")
    return "\n".join(parts)


def main():
    db.init_db()
    OUT.parent.mkdir(exist_ok=True)
    with db.session_scope() as ses:
        sols = {}
        for s in ses.exec(select(Solution)).all():
            sols.setdefault(s.problem_id, s)
        pe_eval = {e.problem_id: e.elegance_score for e in ses.exec(select(Evaluation)).all()
                   if e.elegance_score is not None}
        base = []
        for p in ses.exec(select(Problem)).all():
            sol = sols.get(p.id)
            if sol is None:
                continue
            prov = p.provenance or {}
            q = prov.get("quality") or {}
            cc = q.get("crux_creativity")
            interest = q.get("interestingness")
            pe = q.get("problem_elegance") or (prov.get("elegance") or {}).get("problem") or pe_eval.get(p.id)
            diff = p.difficulty
            crux = prov.get("crux") or ""
            always = p.id.startswith(ALWAYS)
            # gating: model crux-first sources always kept; human sources need creativity + a crux
            if not always:
                if cc is None or cc < CC_FLOOR or not crux:
                    continue
                if diff is not None and diff < DIFF_FLOOR:
                    continue
            # priority (fall back sensibly when an axis is missing)
            cc_ = cc if cc is not None else (pe or 2.5)
            int_ = interest if interest is not None else (pe or 2.5)
            el_ = pe if pe is not None else 2.5
            df_ = min(diff, 10) if diff is not None else 5.0
            priority = W_CC * (cc_ / 5) + W_INT * (int_ / 5) + W_EL * (el_ / 5) + W_DIFF * (df_ / 10)
            copies = max(1, round(priority * MAX_COPIES))
            prompt = build_prompt(p.topic, diff, cc, interest)
            completion = build_completion(p.statement, crux, sol.text, p.answer)
            meta = {"id": p.id, "source": _src(p.id), "topic": p.topic, "difficulty": diff,
                    "crux_creativity": cc, "interestingness": interest, "problem_elegance": pe,
                    "answer": p.answer, "answer_type": _atype(p.answer),
                    "priority": round(priority, 3), "copies": copies}
            base.append(({"messages": [{"role": "user", "content": prompt},
                                        {"role": "assistant", "content": completion}], "meta": meta}, copies))

    import random
    random.seed(13)
    weighted = []
    for row, c in base:
        weighted.extend([row] * c)
    random.shuffle(weighted)
    OUT.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in weighted), encoding="utf-8")

    import statistics
    by_src = Counter(r[0]["meta"]["source"] for r in base)
    ccs = [r[0]["meta"]["crux_creativity"] for r in base if r[0]["meta"]["crux_creativity"] is not None]
    print(f"kept {len(base)} problems (CC_FLOOR={CC_FLOOR}) -> {len(weighted)} weighted rows -> {OUT}")
    print("  by source:", dict(by_src))
    if ccs:
        print(f"  crux_creativity of kept: mean {statistics.mean(ccs):.2f} (min {min(ccs)}, max {max(ccs)})")
    print("  answer_type:", dict(Counter(r[0]["meta"]["answer_type"] for r in base)))


if __name__ == "__main__":
    main()
