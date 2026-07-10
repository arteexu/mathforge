"""Export an ELEGANCE+DIFFICULTY-weighted training set (correctness de-emphasized).

Design goal: train the generator to produce elegant, hard problems built on a deep
crux -- NOT to solve them. So we (1) curate to elegant+difficult problems, (2)
OVERSAMPLE the best ones (priority = elegance & difficulty) so the SFT loss weights
them more, and (3) retarget each completion to foreground the statement + key idea
(crux when we have it, else a short solution sketch) rather than a long derivation.

Run: PYTHONPATH=src python scripts/export_weighted.py
Tunables via env: PE_FLOOR, DIFF_FLOOR, W_ELEG, W_DIFF, MAX_COPIES, SKETCH_CHARS.
"""

from __future__ import annotations

import json
import os
import random
import re
from collections import Counter
from pathlib import Path

from sqlmodel import select

from mathforge import db
from mathforge.schema import Evaluation, Problem, Solution

OUT = Path("data/train_elegant.jsonl")
PE_FLOOR = float(os.environ.get("PE_FLOOR", 3.7))
DIFF_FLOOR = float(os.environ.get("DIFF_FLOOR", 4.5))
W_ELEG = float(os.environ.get("W_ELEG", 0.6))
W_DIFF = float(os.environ.get("W_DIFF", 0.4))
MAX_COPIES = int(os.environ.get("MAX_COPIES", 4))
SKETCH_CHARS = int(os.environ.get("SKETCH_CHARS", 500))
random.seed(13)


def _answer_type(answer) -> str:
    if answer is None:
        return "none"
    a = str(answer).strip()
    if re.fullmatch(r"-?\d+", a):
        return "integer" if 0 <= int(a) <= 999 else "integer_other"
    return "symbolic"


def _source(pid: str) -> str:
    for pre, tag in [("omni-math", "omni-math"), ("distill-rich", "rich"),
                     ("distill", "distill"), ("opus", "opus"), ("aime", "aime")]:
        if pid.startswith(pre):
            return tag
    return "other"


def build_prompt(topic, difficulty, pe) -> str:
    bits = ["Compose one original, elegant, and genuinely difficult AIME/olympiad-level",
            "competition math problem built on ONE deep, non-obvious insight (a crux).",
            "Prioritize elegance and difficulty; the setup should be minimal and the idea striking."]
    if topic:
        bits.append(f"Topic: {topic}.")
    if difficulty is not None:
        bits.append(f"Target difficulty (AoPS 1-10): {difficulty}.")
    if pe is not None:
        bits.append(f"Target problem-elegance (0-5): {pe}.")
    bits.append("Give the problem statement, then the key idea it turns on.")
    return " ".join(bits)


def _sketch(solution: str) -> str:
    s = " ".join((solution or "").split())
    if len(s) <= SKETCH_CHARS:
        return s
    cut = s[:SKETCH_CHARS]
    dot = cut.rfind(". ")
    return (cut[: dot + 1] if dot > 200 else cut) + " …"


def build_completion(stmt, crux, solution, answer) -> str:
    parts = [f"Problem:\n{stmt.strip()}"]
    if crux:
        parts.append(f"\nKey idea:\n{crux.strip()}")
    elif solution:
        parts.append(f"\nSolution sketch:\n{_sketch(solution)}")
    if answer is not None:
        parts.append(f"\nAnswer: {answer}")
    return "\n".join(parts)


def main() -> None:
    db.init_db()
    OUT.parent.mkdir(exist_ok=True)
    with db.session_scope() as ses:
        sols = {}
        for s in ses.exec(select(Solution)).all():
            sols.setdefault(s.problem_id, s)
        evals = {}
        for e in ses.exec(select(Evaluation)).all():
            d = evals.setdefault(e.problem_id, {})
            if e.elegance_score is not None:
                d["pe"] = e.elegance_score
            if e.difficulty_score is not None:
                d.setdefault("diff", e.difficulty_score)

        base_rows = []
        for p in ses.exec(select(Problem)).all():
            sol = sols.get(p.id)
            if sol is None:
                continue
            prov = p.provenance or {}
            pe = (prov.get("elegance") or {}).get("problem")
            if pe is None:
                pe = evals.get(p.id, {}).get("pe")
            diff = p.difficulty if p.difficulty is not None else evals.get(p.id, {}).get("diff")
            if pe is None or diff is None:
                continue
            if pe < PE_FLOOR or diff < DIFF_FLOOR:
                continue
            crux = prov.get("crux") or ""
            priority = W_ELEG * (pe / 5.0) + W_DIFF * (min(diff, 10) / 10.0)
            copies = max(1, round(priority * MAX_COPIES))
            prompt = build_prompt(p.topic, diff, pe)
            completion = build_completion(p.statement, crux, sol.text, p.answer)
            meta = {"id": p.id, "source": _source(p.id), "topic": p.topic, "difficulty": diff,
                    "problem_elegance": pe, "answer": p.answer, "answer_type": _answer_type(p.answer),
                    "has_crux": bool(crux), "priority": round(priority, 3), "copies": copies}
            base_rows.append(({"messages": [{"role": "user", "content": prompt},
                                            {"role": "assistant", "content": completion}],
                               "meta": meta}, copies))

    # oversample by copies, then shuffle so duplicates are spread across the epoch
    weighted = []
    for row, copies in base_rows:
        weighted.extend([row] * copies)
    random.shuffle(weighted)
    OUT.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in weighted), encoding="utf-8")

    print(f"curated {len(base_rows)} problems (PE>={PE_FLOOR}, diff>={DIFF_FLOOR}) "
          f"-> {len(weighted)} weighted rows -> {OUT}")
    print("  by source:", dict(Counter(r[0]['meta']['source'] for r in base_rows)))
    print("  with crux (key-idea target):", sum(1 for r in base_rows if r[0]['meta']['has_crux']))
    print("  answer_type:", dict(Counter(r[0]['meta']['answer_type'] for r in base_rows)))
    import statistics
    print(f"  mean elegance {statistics.mean(r[0]['meta']['problem_elegance'] for r in base_rows):.2f}, "
          f"mean difficulty {statistics.mean(r[0]['meta']['difficulty'] for r in base_rows):.2f}")


if __name__ == "__main__":
    main()
