"""Export the curated problem set to a training-ready JSONL for fine-tuning.

Each record is an instruction->completion pair that CONDITIONS generation on the
target quality (topic, difficulty, and problem/solution elegance) so the model
learns to produce problems at a requested elegance -- the whole point of carrying
the dual elegance labels. Includes accepted problems and the rich (thinking)
problems, each with whatever elegance/difficulty signal we have.

Writes data/train.jsonl (chat-format messages) + data/train_pt.jsonl (plain
prompt/completion). Run: PYTHONPATH=src python scripts/export_dataset.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from sqlmodel import select

from mathforge import db
from mathforge.schema import Evaluation, Problem, Solution

OUT_DIR = Path("data")


def _elegance(prov: dict, evals: list[Evaluation]) -> tuple:
    el = (prov or {}).get("elegance") or {}
    pe = el.get("problem")
    se = el.get("solution")
    if pe is None:
        pe = next((e.elegance_score for e in evals if e.elegance_score is not None), None)
    return pe, se


def build_prompt(topic, difficulty, pe, se) -> str:
    bits = ["Compose one original, elegant AIME/olympiad-level competition math problem",
            "with a single integer answer in [0, 999]."]
    if topic:
        bits.append(f"Topic: {topic}.")
    if difficulty is not None:
        bits.append(f"Target difficulty (AoPS 1-10): {difficulty}.")
    if pe is not None:
        bits.append(f"Target problem-elegance (0-5): {pe}.")
    if se is not None:
        bits.append(f"Target solution-elegance (0-5): {se}.")
    bits.append("Give the statement, then a clean solution ending in the integer answer.")
    return " ".join(bits)


def build_completion(stmt, solution, answer) -> str:
    parts = [f"Problem:\n{stmt.strip()}"]
    if solution:
        parts.append(f"\nSolution:\n{solution.strip()}")
    if answer is not None:
        parts.append(f"\nAnswer: {answer}")
    return "\n".join(parts)


def _source_tag(p) -> str:
    if p.id.startswith("omni-math"):
        return "omni-math"
    if p.id.startswith("distill-rich"):
        return "rich"
    if p.id.startswith("distill"):
        return "distill"
    if p.id.startswith("opus"):
        return "opus"
    if p.id.startswith("aime"):
        return "aime"
    return str(p.source).split(".")[-1].lower() if p.source else "other"


def _answer_type(answer) -> str:
    if answer is None:
        return "none"
    a = str(answer).strip()
    if re.fullmatch(r"-?\d+", a):
        v = int(a)
        return "integer" if 0 <= v <= 999 else "integer_other"
    return "symbolic"


def main() -> None:
    db.init_db()
    OUT_DIR.mkdir(exist_ok=True)
    chat_rows, pt_rows = [], []
    with db.session_scope() as ses:
        problems = ses.exec(select(Problem)).all()
        # Preload solutions + evaluations once (avoids per-problem queries over ~5k rows).
        sols: dict = {}
        for s in ses.exec(select(Solution)).all():
            sols.setdefault(s.problem_id, s)  # first solution per problem
        evals_by: dict = {}
        for e in ses.exec(select(Evaluation)).all():
            evals_by.setdefault(e.problem_id, []).append(e)

        for p in problems:
            status = p.review_status.value if p.review_status else ""
            is_rich = p.id.startswith("distill-rich-")
            sol = sols.get(p.id)
            pe, se = _elegance(p.provenance or {}, evals_by.get(p.id, []))
            has_elegance = pe is not None or se is not None
            # Include: accepted problems, the rich set, and any problem we have both
            # an elegance label AND a written solution for (the labeled Omni-Math etc).
            keep = status == "accepted" or is_rich or (has_elegance and sol is not None)
            if not keep or sol is None:
                continue
            prompt = build_prompt(p.topic, p.difficulty, pe, se)
            completion = build_completion(p.statement, sol.text if sol else None, p.answer)
            meta = {"id": p.id, "source": _source_tag(p), "topic": p.topic,
                    "difficulty": p.difficulty, "problem_elegance": pe,
                    "solution_elegance": se, "answer": p.answer,
                    "answer_type": _answer_type(p.answer), "rich": is_rich}
            chat_rows.append({"messages": [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": completion}], "meta": meta})
            pt_rows.append({"prompt": prompt, "completion": completion, "meta": meta})

    (OUT_DIR / "train.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in chat_rows), encoding="utf-8")
    (OUT_DIR / "train_pt.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in pt_rows), encoding="utf-8")

    from collections import Counter
    by_src = Counter(r["meta"]["source"] for r in chat_rows)
    by_atype = Counter(r["meta"]["answer_type"] for r in chat_rows)
    with_pe = sum(1 for r in chat_rows if r["meta"]["problem_elegance"] is not None)
    print(f"exported {len(chat_rows)} examples -> data/train.jsonl (+ train_pt.jsonl)")
    print(f"  by source: {dict(by_src)}")
    print(f"  by answer_type: {dict(by_atype)}")
    print(f"  with problem-elegance label: {with_pe}")


if __name__ == "__main__":
    main()
