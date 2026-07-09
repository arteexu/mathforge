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


def main() -> None:
    db.init_db()
    OUT_DIR.mkdir(exist_ok=True)
    chat_rows, pt_rows = [], []
    with db.session_scope() as ses:
        problems = ses.exec(select(Problem)).all()
        for p in problems:
            status = p.review_status.value if p.review_status else ""
            is_rich = p.id.startswith("distill-rich-")
            # keep accepted problems, plus the rich (thinking) problems even while pending
            if not (status == "accepted" or is_rich):
                continue
            sol = ses.exec(
                select(Solution).where(Solution.problem_id == p.id)
            ).first()
            evals = ses.exec(
                select(Evaluation).where(Evaluation.problem_id == p.id)
            ).all()
            pe, se = _elegance(p.provenance or {}, evals)
            prompt = build_prompt(p.topic, p.difficulty, pe, se)
            completion = build_completion(p.statement, sol.text if sol else None, p.answer)
            meta = {"id": p.id, "topic": p.topic, "difficulty": p.difficulty,
                    "problem_elegance": pe, "solution_elegance": se,
                    "answer": p.answer, "rich": is_rich}
            chat_rows.append({"messages": [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": completion}], "meta": meta})
            pt_rows.append({"prompt": prompt, "completion": completion, "meta": meta})

    (OUT_DIR / "train.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in chat_rows), encoding="utf-8")
    (OUT_DIR / "train_pt.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in pt_rows), encoding="utf-8")

    rich = sum(1 for r in chat_rows if r["meta"]["rich"])
    with_pe = sum(1 for r in chat_rows if r["meta"]["problem_elegance"] is not None)
    print(f"exported {len(chat_rows)} examples -> data/train.jsonl (+ train_pt.jsonl)")
    print(f"  rich (thinking) examples: {rich}; with problem-elegance label: {with_pe}")


if __name__ == "__main__":
    main()
