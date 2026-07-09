"""Eval harness: rank problems by quality, elegance weighted first.

Philosophy: one deep, elegant problem beats fifty mediocre ones. So the harness
is *lexicographic* — elegance dominates, then difficulty, then crux economy and
an anti-step-stacking penalty — behind a hard **correctness gate** (a problem
that isn't verified/well-posed can't rank at all, no matter how pretty).

Attributes are pulled from the richest available signal per problem:
elegance/difficulty from ``Evaluation`` rows (human > opus > judge > dataset) or
the ``agent_qa`` blob; crux_count/routine_step_count from the solution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sqlmodel import select

from mathforge import db
from mathforge.schema import Evaluation, Problem, Solution

__all__ = [
    "QualityWeights",
    "Scored",
    "grade_for",
    "problem_attributes",
    "score_problem",
    "rank_problems",
]

# Preference order when several evaluators scored the same problem.
_EVALUATOR_PRIORITY = ["human", "opus-4.8", "judge_v1", "judge", "solver_panel", "dataset"]


# Official, consensus-vetted contest sources count as correct even without our
# own verify pass (used by the correctness gate as a "trusted" bypass).
TRUSTED_SOURCES: frozenset[str] = frozenset(
    {"aime", "amc", "usamo", "usajmo", "imo", "putnam", "other_competition"}
)


@dataclass
class QualityWeights:
    """Elegance-dominant weights. Ranking is lexicographic; the composite score
    is a human-readable summary using these."""

    elegance: float = 10.0     # dominant axis (0-5 -> 0-50)
    difficulty: float = 1.0    # secondary (1-10)
    crux: float = 2.0          # reward one-idea economy
    routine_penalty: float = 0.15  # per routine step beyond 4 (anti step-stacking)
    require_verified: bool = True
    elegance_floor: float = 3.0    # quality bar: below this is not a "keeper"
    difficulty_floor: float = 0.0  # optional depth bar
    # Sources trusted as correct without our verify pass (real contest problems).
    trusted_sources: frozenset[str] = TRUSTED_SOURCES


@dataclass
class Scored:
    problem_id: str
    topic: Optional[str]
    elegance: Optional[float]
    difficulty: Optional[float]
    crux_count: Optional[int]
    routine_step_count: Optional[int]
    verified: Optional[bool]
    wellposed: bool
    score: float
    grade: str
    passes_gate: bool
    rank_key: tuple = field(default_factory=tuple)


def grade_for(elegance: Optional[float]) -> str:
    """S/A/B/C/D quality tier from elegance (0-5)."""
    e = elegance if elegance is not None else -1
    if e >= 5:
        return "S"
    if e >= 4:
        return "A"
    if e >= 3:
        return "B"
    if e >= 2:
        return "C"
    return "D"


def _pick(evals: list[Evaluation], attr: str) -> Optional[float]:
    """Choose an attribute value by evaluator priority, then most recent."""
    def key(e: Evaluation):
        ev = (e.evaluator or "").lower()
        pr = next((i for i, p in enumerate(_EVALUATOR_PRIORITY)
                   if ev == p or (p == "judge" and ev.startswith("judge_"))), 99)
        return (pr, -(e.id or 0))

    for e in sorted(evals, key=key):
        v = getattr(e, attr)
        if v is not None:
            return v
    return None


def problem_attributes(session, problem: Problem) -> dict:
    """Gather (elegance, difficulty, crux_count, routine_step_count, wellposed)."""
    evals = session.exec(
        select(Evaluation).where(Evaluation.problem_id == problem.id)
    ).all()
    sols = session.exec(
        select(Solution).where(Solution.problem_id == problem.id)
    ).all()
    prov = problem.provenance or {}
    qa = prov.get("agent_qa") or {}

    elegance = _pick(evals, "elegance_score")
    if elegance is None:
        elegance = (qa.get("elegance") or {}).get("overall")
    difficulty = _pick(evals, "difficulty_score")
    if difficulty is None:
        difficulty = (qa.get("difficulty") or {}).get("difficulty")
    if difficulty is None:
        difficulty = problem.difficulty

    crux_count = next((s.crux_count for s in sols if s.crux_count), None)
    routine = next((s.routine_step_count for s in sols if s.routine_step_count), None)

    wellposed = (qa.get("wellposedness") or {}).get("verdict", "accept") != "reject"
    return {
        "elegance": elegance, "difficulty": difficulty,
        "crux_count": crux_count, "routine_step_count": routine,
        "wellposed": wellposed,
    }


def _crux_bonus(crux_count: Optional[int]) -> float:
    if crux_count == 1:
        return 1.0
    if crux_count == 2:
        return 0.3
    if crux_count and crux_count >= 3:
        return -0.5
    return 0.0


def score_problem(attrs: dict, w: QualityWeights) -> float:
    e = attrs["elegance"] or 0.0
    d = attrs["difficulty"] or 0.0
    routine = attrs["routine_step_count"] or 0
    penalty = max(0, routine - 4) * w.routine_penalty
    return w.elegance * e + w.difficulty * d + w.crux * _crux_bonus(attrs["crux_count"]) - penalty


def rank_problems(
    db_url: Optional[str] = None,
    weights: Optional[QualityWeights] = None,
    source: Optional[str] = None,
    statuses: Optional[tuple[str, ...]] = None,
    id_prefix: Optional[str] = None,
) -> list[Scored]:
    """Rank problems lexicographically: elegance, then difficulty, then crux
    economy, then fewer routine steps. Non-gated problems sort to the bottom."""
    w = weights or QualityWeights()
    db.init_db(db_url)
    out: list[Scored] = []
    with db.session_scope(db_url) as session:
        problems = session.exec(select(Problem)).all()
        for p in problems:
            if source and p.source.value != source:
                continue
            if statuses and (p.review_status.value if p.review_status else None) not in statuses:
                continue
            if id_prefix and not p.id.startswith(id_prefix):
                continue
            a = problem_attributes(session, p)
            correct = (
                not w.require_verified
                or p.verified is True
                or p.source.value in w.trusted_sources
            )
            gate = correct and a["wellposed"] \
                and (a["elegance"] or 0) >= w.elegance_floor \
                and (a["difficulty"] or 0) >= w.difficulty_floor
            sc = score_problem(a, w)
            out.append(Scored(
                problem_id=p.id, topic=p.topic, elegance=a["elegance"],
                difficulty=a["difficulty"], crux_count=a["crux_count"],
                routine_step_count=a["routine_step_count"], verified=p.verified,
                wellposed=a["wellposed"], score=sc, grade=grade_for(a["elegance"]),
                passes_gate=gate,
                rank_key=(
                    1 if gate else 0,
                    a["elegance"] or -1,          # elegance FIRST
                    a["difficulty"] or -1,        # then difficulty
                    _crux_bonus(a["crux_count"]),  # then crux economy
                    -(a["routine_step_count"] or 0),  # then fewer routine steps
                ),
            ))
    out.sort(key=lambda s: s.rank_key, reverse=True)
    return out
