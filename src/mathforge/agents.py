"""Strong math agents that QA distilled candidates: solve, verify, rate quality.

For each candidate problem, a strong solver is run as ``k`` independent agents
(``independent_solver_v1`` at temperature, so the agents explore different paths).
We then:

* **verify correctness** — take the strict-majority answer and check it against
  the stored answer (``verified``);
* **check well-posedness** — an adversarial rules-chair pass (``wellposedness_v1``)
  flags ambiguous / ill-posed / unsolvable statements; and
* **rate quality** — the difficulty (1-10) and elegance (0-5) judges.

Results are written back: ``Problem.verified``, an ``Evaluation`` with the judge
scores, a stored strong-agent ``Solution``, and an ``agent_qa`` provenance blob
that ``review`` surfaces. The human still makes the final accept/reject call.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from sqlmodel import select

from mathforge import db
from mathforge.distill import (
    _extract_json,
    judge_difficulty,
    judge_elegance,
    verify_answer,
)
from mathforge.llm import LLMClient
from mathforge.prompts import WELLPOSEDNESS_V1, render_prompt
from mathforge.schema import (
    Evaluation,
    Problem,
    ProblemSource,
    ReviewStatus,
    Solution,
    SolutionSource,
)
from mathforge.solver import check_answer, normalize_answer

__all__ = [
    "AgentQAReport",
    "judge_wellposedness",
    "run_agent_qa",
    "export_candidates",
    "apply_verdicts",
    "export_elegance_sample",
    "apply_elegance_ratings",
    "IN_CHAT_MODEL",
]

# Tag for verdicts produced by the in-chat model (e.g. Claude Opus) rather than
# an API solver.
IN_CHAT_MODEL = "claude-opus-4.8 (in-chat)"


def export_candidates(
    db_url: Optional[str] = None,
    statuses: tuple[str, ...] = ("pending", "needs_edit"),
    limit: Optional[int] = None,
) -> list[dict]:
    """Dump synthetic candidates awaiting verification (for in-chat solving)."""
    db.init_db(db_url)
    wanted = {ReviewStatus(s) for s in statuses}
    rows: list[dict] = []
    with db.session_scope(db_url) as session:
        for p in session.exec(
            select(Problem).where(Problem.source == ProblemSource.SYNTHETIC)
        ).all():
            if p.review_status not in wanted:
                continue
            rows.append(
                {
                    "id": p.id,
                    "topic": p.topic,
                    "status": p.review_status.value if p.review_status else None,
                    "stored_answer": p.answer,
                    "statement": p.statement,
                }
            )
    if limit is not None:
        rows = rows[:limit]
    return rows


def _valid_aime_answer(value) -> bool:
    """True iff ``value`` is an integer in the AIME range [0, 999]."""
    try:
        iv = int(str(value).strip())
    except (TypeError, ValueError):
        return False
    return 0 <= iv <= 999


def apply_verdicts(
    verdicts: list[dict],
    db_url: Optional[str] = None,
    apply_status: bool = False,
) -> dict:
    """Apply out-of-band (e.g. Opus in-chat) verification verdicts to the DB.

    Each verdict: ``{id, correct_answer?, wellposed, verified?, recommendation,
    reason, difficulty?, elegance?}``. ``recommendation`` ∈
    {accept, fix_answer, needs_edit, reject}. With ``apply_status``, the review
    status is also set from the recommendation; otherwise it's left for the human.
    """
    db.init_db(db_url)
    counts = {"applied": 0, "corrected": 0, "not_found": [], "by_rec": {}}
    status_map = {
        "accept": ReviewStatus.ACCEPTED,
        "fix_answer": ReviewStatus.ACCEPTED,
        "needs_edit": ReviewStatus.NEEDS_EDIT,
        "reject": ReviewStatus.REJECTED,
    }
    with db.session_scope(db_url) as session:
        for v in verdicts:
            pid = v["id"]
            p = session.get(Problem, pid) or session.get(Problem, f"distill-{pid}")
            if p is None:
                counts["not_found"].append(pid)
                continue
            rec = v.get("recommendation", "reject")
            correct = v.get("correct_answer")
            # Range guard: an accepted/fixed problem must have an integer answer
            # in [0, 999]. Otherwise force a reject regardless of the label.
            effective = correct if rec == "fix_answer" else p.answer
            if rec in ("accept", "fix_answer") and not _valid_aime_answer(effective):
                v = {**v, "reason": f"[auto] answer {effective} not an integer in [0,999]. "
                     + v.get("reason", "")}
                rec = "reject"
            counts["by_rec"][rec] = counts["by_rec"].get(rec, 0) + 1

            prov = dict(p.provenance or {})
            prov["agent_qa"] = {
                "solver_model": v.get("model", IN_CHAT_MODEL),
                "k": "exact",
                "consensus": correct,
                "agreement": 1.0,
                "verified": v.get("verified", rec in ("accept", "fix_answer")),
                "wellposedness": {"verdict": v.get("wellposed")},
                "difficulty": {"difficulty": v.get("difficulty")},
                "elegance": {"overall": v.get("elegance")},
                "recommendation": rec,
                "reason": v.get("reason", ""),
            }

            if rec == "fix_answer" and correct is not None:
                prov["answer_override"] = {"old": p.answer, "new": str(correct),
                                           "by": v.get("model", IN_CHAT_MODEL)}
                p.answer = str(correct)
                p.verified = True
                counts["corrected"] += 1
            else:
                p.verified = v.get("verified", rec == "accept")

            p.provenance = prov
            if apply_status and rec in status_map:
                p.review_status = status_map[rec]
            session.add(p)

            if v.get("difficulty") is not None:
                session.add(
                    Evaluation(
                        problem_id=p.id,
                        difficulty_score=v.get("difficulty"),
                        elegance_score=v.get("elegance"),
                        evaluator="opus-4.8",
                        rationale=(v.get("reason", ""))[:500],
                    )
                )
            if correct is not None:
                session.add(
                    Solution(
                        problem_id=p.id,
                        text=f"[in-chat verification] correct answer = {correct}. {v.get('reason','')}",
                        source=SolutionSource.SOLVER_PANEL,
                        extractor_model=v.get("model", IN_CHAT_MODEL),
                    )
                )
            counts["applied"] += 1
    return counts


def judge_wellposedness(
    judge: LLMClient,
    statement: str,
    answer: Optional[str],
    ambiguity_notes: str = "",
) -> dict:
    def evaluate(notes: str):
        response = judge.complete(
            render_prompt(
                WELLPOSEDNESS_V1,
                statement=statement,
                answer=answer if answer is not None else "unknown",
                ambiguity_notes=notes,
            ),
            system=(
                "You are a JSON-only competition rules evaluator. Return exactly "
                "the requested JSON object. Do not solve in prose before the JSON."
            ),
            purpose="qa-wellposedness",
            temperature=0.0,
        )
        return _extract_json(response.text), response.cost_usd

    data, cost = evaluate(ambiguity_notes)

    def inconsistent(value: Optional[dict]) -> bool:
        if not value:
            return True
        fatal = any(issue.get("severity") == "fatal" for issue in value.get("issues", []))
        return value.get("verdict") == "accept" and fatal

    if inconsistent(data):
        retry_note = " ".join(
            part for part in (
                ambiguity_notes,
                "A prior evaluation was missing or internally inconsistent. Return JSON only; "
                "accept requires zero fatal issues, and any fatal issue requires reject.",
            ) if part
        )
        retry, retry_cost = evaluate(retry_note)
        cost += retry_cost
        if retry:
            data = retry

    # Fail closed if the retry still contradicts its own issue severities.
    if data and data.get("verdict") == "accept" and any(
        issue.get("severity") == "fatal" for issue in data.get("issues", [])
    ):
        data = {**data, "verdict": "reject", "normalized_from_inconsistent_accept": True}
    return {"data": data, "cost": cost}


@dataclass
class AgentQAReport:
    processed: int = 0
    verified_correct: int = 0
    answer_mismatch: int = 0
    no_consensus: int = 0
    ill_posed: int = 0
    skipped: int = 0
    errors: int = 0
    last_error: Optional[str] = None
    cost_usd: float = 0.0
    records: list[dict] = field(default_factory=list)


def run_agent_qa(
    db_url: Optional[str] = None,
    *,
    solver: LLMClient,
    judge: Optional[LLMClient] = None,
    k: int = 4,
    statuses: tuple[str, ...] = ("pending", "needs_edit"),
    limit: Optional[int] = None,
    overwrite: bool = False,
    id_prefixes: Optional[tuple[str, ...]] = None,
) -> AgentQAReport:
    """Run strong solver agents + quality judges over synthetic candidates."""
    judge = judge or solver
    db.init_db(db_url)
    report = AgentQAReport()
    wanted = {ReviewStatus(s) for s in statuses}

    with db.session_scope(db_url) as session:
        candidates = [
            p
            for p in session.exec(
                select(Problem).where(Problem.source == ProblemSource.SYNTHETIC)
            ).all()
            if p.review_status in wanted
            and (not id_prefixes or any(p.id.startswith(prefix) for prefix in id_prefixes))
        ]
        if limit is not None:
            candidates = candidates[:limit]

        for problem in candidates:
          try:
            prov = dict(problem.provenance or {})
            if "agent_qa" in prov and not overwrite:
                report.skipped += 1
                continue

            # --- solve with k strong agents -------------------------------- #
            vr = verify_answer(solver, problem.statement, k=k)
            report.cost_usd += vr["cost"]
            consensus = vr["consensus"]
            counts = Counter(normalize_answer(a) for a in vr["answers"] if a)
            agreement = (counts.most_common(1)[0][1] / k) if counts else 0.0

            if consensus is None:
                report.no_consensus += 1
                answer_verified = False
            elif problem.answer is not None and check_answer(consensus, problem.answer):
                report.verified_correct += 1
                answer_verified = True
            else:
                report.answer_mismatch += 1
                answer_verified = False

            best_solution = _solution_for(vr, consensus)

            # --- quality: well-posedness + difficulty + elegance ----------- #
            ambiguity_notes = "; ".join(
                str(verdict.get("ambiguity_note") or "").strip()
                for verdict in vr.get("verdicts", [])
                if verdict.get("ambiguity_flag") or verdict.get("ambiguity_note")
            )
            wp = judge_wellposedness(
                judge, problem.statement, problem.answer, ambiguity_notes=ambiguity_notes
            )
            dj = judge_difficulty(
                judge, problem.statement, best_solution,
                solve_rates=f"strong agents {int(agreement * k)}/{k}",
            )
            ej = judge_elegance(judge, problem.statement, best_solution)
            report.cost_usd += wp["cost"] + dj["cost"] + ej["cost"]

            wp_verdict = (wp["data"] or {}).get("verdict")
            if wp_verdict == "reject":
                report.ill_posed += 1
            difficulty = (dj["data"] or {}).get("difficulty") or problem.difficulty
            elegance = (ej["data"] or {}).get("overall")
            verified = answer_verified and wp_verdict == "accept"

            # --- persist --------------------------------------------------- #
            problem.verified = verified
            if difficulty is not None:
                problem.difficulty = difficulty
            prov["agent_qa"] = {
                "solver_model": solver.model,
                "judge_model": judge.model,
                "k": k,
                "consensus": consensus,
                "agreement": agreement,
                "answers": vr["answers"],
                "verified": verified,
                "answer_verified": answer_verified,
                "wellposedness": wp["data"],
                "difficulty": dj["data"],
                "elegance": ej["data"],
            }
            problem.provenance = prov
            session.add(problem)

            if best_solution:
                session.add(
                    Solution(
                        problem_id=problem.id,
                        text=best_solution,
                        source=SolutionSource.SOLVER_PANEL,
                        extractor_model=solver.model,
                    )
                )
            session.add(
                Evaluation(
                    problem_id=problem.id,
                    difficulty_score=difficulty,
                    elegance_score=elegance,
                    evaluator="judge_v1",
                    rationale=f"agent-qa: wellposedness={wp_verdict}, agreement={agreement:.2f}",
                )
            )

            report.processed += 1
            report.records.append(
                {
                    "id": problem.id,
                    "verified": verified,
                    "consensus": consensus,
                    "stored_answer": problem.answer,
                    "agreement": round(agreement, 2),
                    "wellposed": wp_verdict,
                    "difficulty": difficulty,
                    "elegance": elegance,
                }
            )
          except Exception as exc:  # keep the batch alive on a single failure
              report.errors += 1
              report.last_error = f"{type(exc).__name__}: {exc}"
              continue

    return report


def export_elegance_sample(
    db_url: Optional[str] = None,
    target: int = 72,
    id_prefix: str = "omni-math-",
    seed: int = 0,
) -> list[dict]:
    """Stratified Omni-MATH sample (topic x difficulty band) for elegance rating.

    Skips problems already elegance-rated. Round-robin over strata gives coverage
    of every band (including the hard 7-9 tail the synthetic set lacks).
    """
    import random
    from collections import defaultdict

    from mathforge.schema import DataSplit, difficulty_band

    db.init_db(db_url)
    rng = random.Random(seed)
    with db.session_scope(db_url) as session:
        rated = {
            e.problem_id
            for e in session.exec(
                select(Evaluation).where(Evaluation.elegance_score.is_not(None))
            ).all()
        }
        probs = [
            p
            for p in session.exec(select(Problem).where(Problem.split == DataSplit.TRAIN)).all()
            if p.id.startswith(id_prefix)
            and p.id not in rated
            and p.difficulty is not None
            and p.topic
        ]
        strata: dict[tuple, list] = defaultdict(list)
        for p in probs:
            strata[(p.topic, difficulty_band(p.difficulty))].append(p)
        keys = sorted(strata)
        for k in keys:
            rng.shuffle(strata[k])

        selected, cursors, progress = [], {k: 0 for k in keys}, True
        while len(selected) < target and progress:
            progress = False
            for k in keys:
                if len(selected) >= target:
                    break
                c = cursors[k]
                if c < len(strata[k]):
                    selected.append(strata[k][c])
                    cursors[k] = c + 1
                    progress = True

        rows = []
        for p in selected:
            sol = session.exec(
                select(Solution).where(Solution.problem_id == p.id)
            ).first()
            rows.append({
                "id": p.id, "difficulty": p.difficulty, "topic": p.topic,
                "statement": p.statement,
                "official_solution": sol.text if sol else "",
            })
    return rows


def apply_elegance_ratings(
    ratings: list[dict], db_url: Optional[str] = None
) -> dict:
    """Write elegance-only ``Evaluation`` rows (evaluator=opus-4.8).

    Each rating: ``{id, elegance, reason?}``. Does not touch answer/verified/status.
    """
    db.init_db(db_url)
    counts = {"applied": 0, "not_found": []}
    with db.session_scope(db_url) as session:
        for r in ratings:
            p = session.get(Problem, r["id"])
            if p is None:
                counts["not_found"].append(r["id"])
                continue
            session.add(
                Evaluation(
                    problem_id=p.id,
                    difficulty_score=None,
                    elegance_score=float(r["elegance"]),
                    evaluator="opus-4.8",
                    rationale=(r.get("reason", ""))[:500],
                )
            )
            counts["applied"] += 1
    return counts


def _solution_for(vr: dict, consensus: Optional[str]) -> str:
    if consensus is not None:
        for a, s in zip(vr["answers"], vr["solutions"]):
            if a and normalize_answer(a) == normalize_answer(consensus):
                return s
    return vr["solutions"][0] if vr["solutions"] else ""
