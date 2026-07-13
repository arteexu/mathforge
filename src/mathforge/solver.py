"""The solver panel: behavioral difficulty signal from what models actually do.

Two solvers run the ``independent_solver_v1`` prompt on each problem:

* a **weak** solver (~7B open model, 8 attempts), and
* a **strong** solver (frontier model, 4 attempts).

We store per-attempt results (cached so a problem is *never solved twice* — the
dominant API cost) and an aggregate :class:`~mathforge.schema.SolverPanel` with
both solve rates. The rate pair locates the problem:

* weak succeeds often            -> ``exercise``
* weak fails but strong succeeds  -> ``target`` (hard-but-well-posed)
* both fail                       -> ``broken`` (probably ill-posed)

Famous-contest problems get ``possibly_memorized`` set (contest fame OR a solver
flagging ``recognized_as_existing``); the difficulty judge discounts solver
success when it is set.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Optional

from sqlmodel import select

from mathforge import db
from mathforge.llm import LLMClient
from mathforge.prompts import INDEPENDENT_SOLVER_V1, render_prompt
from mathforge.schema import (
    DataSplit,
    Problem,
    ProblemSource,
    SolverAttempt,
    SolverClassification,
    SolverPanel,
    SolverRole,
    utcnow,
)

__all__ = [
    "SolverConfig",
    "DEFAULT_WEAK",
    "DEFAULT_STRONG",
    "FAMOUS_SOURCES",
    "is_possibly_memorized",
    "normalize_answer",
    "check_answer",
    "parse_solver_verdict",
    "classify",
    "make_llm_solver",
    "run_solver_panel",
    "PanelReport",
    "SolverOutput",
]


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SolverConfig:
    role: SolverRole
    model: str
    attempts: int
    prompt_version: str = INDEPENDENT_SOLVER_V1
    temperature: float = 0.7


DEFAULT_WEAK = SolverConfig(SolverRole.WEAK, "qwen2.5-7b-instruct", attempts=8, temperature=0.7)
DEFAULT_STRONG = SolverConfig(SolverRole.STRONG, "o3", attempts=4, temperature=0.6)

# Well-known contests whose problems a model may reproduce from memory.
FAMOUS_SOURCES = {
    ProblemSource.AIME,
    ProblemSource.AMC,
    ProblemSource.USAJMO,
    ProblemSource.USAMO,
    ProblemSource.IMO,
    ProblemSource.PUTNAM,
}


def is_possibly_memorized(source: ProblemSource) -> bool:
    return source in FAMOUS_SOURCES


# --------------------------------------------------------------------------- #
# Answer checking
# --------------------------------------------------------------------------- #
_BOXED_RE = re.compile(r"\\boxed\{([^}]*)\}")


def normalize_answer(value: Optional[str]) -> str:
    if value is None:
        return ""
    v = value.strip()
    m = _BOXED_RE.search(v)
    if m:
        v = m.group(1)
    v = v.replace("$", "").replace(",", "").replace(" ", "")
    v = v.strip().lstrip("+").rstrip(".")
    return v


def check_answer(predicted: Optional[str], gold: Optional[str]) -> bool:
    """Best-effort correctness. Reliable for integer answers (e.g. AIME)."""
    if gold is None:
        return False
    p, g = normalize_answer(predicted), normalize_answer(gold)
    if not p or p.upper() == "NONE":
        return False
    try:
        return int(p) == int(g)
    except ValueError:
        return p.lower() == g.lower()


# --------------------------------------------------------------------------- #
# Verdict parsing (independent_solver_v1 output block)
# --------------------------------------------------------------------------- #
_VERDICT_RE = re.compile(r"<verdict>(.*?)</verdict>", re.DOTALL | re.IGNORECASE)
_FIELD_RE = re.compile(r"^\s*([a-z_]+)\s*:\s*(.*?)\s*$", re.IGNORECASE)


def _as_bool(s: str) -> bool:
    return s.strip().strip('"').lower() == "true"


def parse_solver_verdict(text: str) -> dict:
    """Extract final_answer/confidence/ambiguity_flag/recognized_as_existing."""
    block = text or ""
    m = _VERDICT_RE.search(block)
    if m:
        block = m.group(1)

    fields: dict[str, str] = {}
    for line in block.splitlines():
        fm = _FIELD_RE.match(line)
        if fm:
            fields[fm.group(1).lower()] = fm.group(2)

    raw_answer = fields.get("final_answer", "").strip().strip('"')
    final_answer = None if raw_answer.upper() in ("", "NONE") else raw_answer
    return {
        "final_answer": final_answer,
        "confidence": (fields.get("confidence") or "").strip().strip('"') or None,
        "ambiguity_flag": _as_bool(fields.get("ambiguity_flag", "false")),
        "ambiguity_note": (fields.get("ambiguity_note") or "").strip().strip('"'),
        "recognized_as_existing": _as_bool(fields.get("recognized_as_existing", "false")),
    }


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #
def classify(
    weak_rate: float, strong_rate: float, weak_exercise_threshold: float = 0.5
) -> SolverClassification:
    if weak_rate >= weak_exercise_threshold:
        return SolverClassification.EXERCISE
    if strong_rate > 0:
        return SolverClassification.TARGET
    if weak_rate == 0:
        return SolverClassification.BROKEN
    return SolverClassification.INCONCLUSIVE


# --------------------------------------------------------------------------- #
# Solver backends
# --------------------------------------------------------------------------- #
@dataclass
class SolverOutput:
    """One raw solver attempt: the transcript plus its logged LLM call id/cost."""

    text: str
    llm_call_id: Optional[int] = None
    cost_usd: float = 0.0


# A solver backend maps (problem, attempt_index) -> SolverOutput.
SolverFn = Callable[[Problem, int], SolverOutput]


def make_llm_solver(config: SolverConfig, db_url: Optional[str] = None) -> SolverFn:
    """Build an LLM-backed solver that runs ``independent_solver_v1`` (logs cost)."""
    client = LLMClient(model=config.model, purpose="solve", db_url=db_url)

    def _solve(problem: Problem, attempt_index: int) -> SolverOutput:
        prompt = render_prompt(INDEPENDENT_SOLVER_V1, statement=problem.statement)
        resp = client.complete(
            prompt,
            purpose="solve",
            related_id=problem.id,
            temperature=config.temperature,
            meta={"role": config.role.value, "attempt_index": attempt_index},
        )
        return SolverOutput(text=resp.text, llm_call_id=resp.call_id, cost_usd=resp.cost_usd)

    return _solve


# --------------------------------------------------------------------------- #
# Panel runner (with aggressive caching)
# --------------------------------------------------------------------------- #
@dataclass
class PanelReport:
    problems: int = 0
    attempts_run: int = 0  # new API calls this pass
    attempts_cached: int = 0  # reused, no API call
    cost_usd: float = 0.0
    by_classification: dict[str, int] = field(default_factory=dict)
    possibly_memorized: int = 0


def _get_or_run_attempts(
    session,
    problem: Problem,
    config: SolverConfig,
    solver_fn: SolverFn,
    overwrite: bool,
    report: PanelReport,
) -> list[SolverAttempt]:
    existing = session.exec(
        select(SolverAttempt).where(
            SolverAttempt.problem_id == problem.id,
            SolverAttempt.model == config.model,
            SolverAttempt.prompt_version == config.prompt_version,
        )
    ).all()
    by_index = {a.attempt_index: a for a in existing}

    attempts: list[SolverAttempt] = []
    for i in range(config.attempts):
        cached = by_index.get(i)
        if cached is not None and not overwrite:
            report.attempts_cached += 1
            attempts.append(cached)
            continue

        out = solver_fn(problem, i)
        verdict = parse_solver_verdict(out.text)
        attempt = SolverAttempt(
            problem_id=problem.id,
            role=config.role,
            model=config.model,
            prompt_version=config.prompt_version,
            attempt_index=i,
            final_answer=verdict["final_answer"],
            correct=check_answer(verdict["final_answer"], problem.answer),
            confidence=verdict["confidence"],
            ambiguity_flag=verdict["ambiguity_flag"],
            recognized_as_existing=verdict["recognized_as_existing"],
            llm_call_id=out.llm_call_id,
        )
        session.add(attempt)
        report.attempts_run += 1
        report.cost_usd += out.cost_usd
        attempts.append(attempt)

    return attempts


def _upsert_panel(session, problem_id: str, prompt_version: str, **values) -> None:
    panel = session.exec(
        select(SolverPanel).where(
            SolverPanel.problem_id == problem_id,
            SolverPanel.prompt_version == prompt_version,
        )
    ).first()
    if panel is None:
        panel = SolverPanel(problem_id=problem_id, prompt_version=prompt_version)
    for key, val in values.items():
        setattr(panel, key, val)
    panel.updated_at = utcnow()
    session.add(panel)


def run_solver_panel(
    db_url: Optional[str] = None,
    weak_config: SolverConfig = DEFAULT_WEAK,
    strong_config: SolverConfig = DEFAULT_STRONG,
    limit: Optional[int] = 50,
    split: str = "train",
    weak_solver: Optional[SolverFn] = None,
    strong_solver: Optional[SolverFn] = None,
    overwrite: bool = False,
    weak_exercise_threshold: float = 0.5,
) -> PanelReport:
    """Run (or reuse cached) weak+strong attempts and store solve-rate panels.

    Only problems with a checkable ``answer`` are included. Defaults to the TRAIN
    split so the frozen eval set is untouched unless ``split="eval"`` is passed.
    """
    if weak_config.prompt_version != strong_config.prompt_version:
        raise ValueError("weak and strong solvers must share a prompt_version")

    db.init_db(db_url)
    report = PanelReport()
    weak_solver = weak_solver or make_llm_solver(weak_config, db_url)
    strong_solver = strong_solver or make_llm_solver(strong_config, db_url)
    prompt_version = weak_config.prompt_version

    with db.session_scope(db_url) as session:
        stmt = select(Problem).where(Problem.split == DataSplit(split))
        problems = [p for p in session.exec(stmt).all() if p.answer]
        if limit is not None:
            problems = problems[:limit]

        for problem in problems:
            weak = _get_or_run_attempts(
                session, problem, weak_config, weak_solver, overwrite, report
            )
            strong = _get_or_run_attempts(
                session, problem, strong_config, strong_solver, overwrite, report
            )

            weak_succ = sum(1 for a in weak if a.correct)
            strong_succ = sum(1 for a in strong if a.correct)
            weak_rate = weak_succ / len(weak) if weak else 0.0
            strong_rate = strong_succ / len(strong) if strong else 0.0

            any_recognized = any(
                a.recognized_as_existing for a in (*weak, *strong)
            )
            ambiguity = sum(1 for a in (*weak, *strong) if a.ambiguity_flag)
            fame = is_possibly_memorized(problem.source)
            memorized = fame or any_recognized
            problem.possibly_memorized = fame
            session.add(problem)

            classification = classify(weak_rate, strong_rate, weak_exercise_threshold)
            _upsert_panel(
                session,
                problem.id,
                prompt_version,
                weak_model=weak_config.model,
                weak_attempts=len(weak),
                weak_successes=weak_succ,
                weak_solve_rate=weak_rate,
                strong_model=strong_config.model,
                strong_attempts=len(strong),
                strong_successes=strong_succ,
                strong_solve_rate=strong_rate,
                possibly_memorized=memorized,
                any_recognized=any_recognized,
                ambiguity_count=ambiguity,
                classification=classification,
            )

            report.problems += 1
            report.by_classification[classification.value] = (
                report.by_classification.get(classification.value, 0) + 1
            )
            if memorized:
                report.possibly_memorized += 1

    return report
