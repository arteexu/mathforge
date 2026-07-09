"""Per-solution difficulty feature extraction (teacher model + heuristic).

For each problem we produce a *teacher* :class:`~mathforge.schema.Solution` row
carrying the features that feed the difficulty predictor:

* ``techniques``            — methods used
* ``crux_insight``          — the key idea
* ``crux_count``            — number of genuine insight leaps
* ``routine_step_count``    — number of routine/mechanical steps
* ``prerequisite_level``    — required background, 1 (elementary) .. 5 (olympiad-deep)
* ``standard_method_solves``— does a standard/textbook method solve it?

Two extractors are provided:

* ``"llm"``       — a teacher LLM (via :class:`mathforge.llm.LLMClient`, which
  logs every call's tokens/cost). Expects a strict-JSON response.
* ``"heuristic"`` — a dependency-free fallback so the pipeline runs offline and
  is testable. Also used as the fallback if the LLM response can't be parsed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from pydantic import BaseModel, Field as PydField, field_validator
from sqlmodel import select

from mathforge import db
from mathforge.llm import LLMClient
from mathforge.schema import (
    DataSplit,
    Problem,
    Solution,
    SolutionSource,
    difficulty_band,
    utcnow,
)

__all__ = [
    "SolutionFeatures",
    "TECHNIQUE_LEXICON",
    "FEATURE_SYSTEM_PROMPT",
    "build_feature_prompt",
    "parse_feature_response",
    "heuristic_features",
    "extract_features",
    "run_extraction",
    "ExtractionReport",
    "feature_rows",
]


# --------------------------------------------------------------------------- #
# Teacher output contract
# --------------------------------------------------------------------------- #
class SolutionFeatures(BaseModel):
    """Structured features the teacher must return (and the heuristic mimics)."""

    techniques: list[str] = PydField(default_factory=list)
    crux_insight: str = ""
    crux_count: int = 0
    routine_step_count: int = 0
    prerequisite_level: int = 3
    standard_method_solves: bool = False
    # Optional extras — kept in Solution.features.
    solution_sketch: str = ""
    prerequisite_topics: list[str] = PydField(default_factory=list)
    difficulty_estimate: Optional[float] = None
    confidence: Optional[float] = None

    @field_validator("crux_count", "routine_step_count")
    @classmethod
    def _non_negative(cls, v: int) -> int:
        return max(0, int(v))

    @field_validator("prerequisite_level")
    @classmethod
    def _clamp_level(cls, v: int) -> int:
        return max(1, min(5, int(v)))


# --------------------------------------------------------------------------- #
# LLM teacher prompt
# --------------------------------------------------------------------------- #
FEATURE_SYSTEM_PROMPT = (
    "You are an expert competition-math coach grading how HARD a problem is. "
    "Given a problem and (optionally) a reference solution, analyze what it "
    "takes to solve. Respond with STRICT JSON only (no prose, no code fences) "
    "matching this schema:\n"
    "{\n"
    '  "techniques": [string],           // named methods used\n'
    '  "crux_insight": string,           // the single key idea that unlocks it\n'
    '  "crux_count": integer,            // number of genuine insight leaps (0-5)\n'
    '  "routine_step_count": integer,    // number of routine/mechanical steps\n'
    '  "prerequisite_level": integer,    // 1 elementary .. 5 olympiad-deep\n'
    '  "standard_method_solves": boolean,// true if a standard method suffices\n'
    '  "solution_sketch": string,        // 1-3 sentence sketch\n'
    '  "prerequisite_topics": [string],  // background needed\n'
    '  "difficulty_estimate": number,    // your 1-10 difficulty guess\n'
    '  "confidence": number              // 0-1\n'
    "}"
)


def build_feature_prompt(statement: str, reference_solution: Optional[str]) -> str:
    parts = [f"PROBLEM:\n{statement.strip()}"]
    if reference_solution:
        parts.append(f"\nREFERENCE SOLUTION:\n{reference_solution.strip()}")
    parts.append("\nReturn the STRICT JSON described above.")
    return "\n".join(parts)


_JSON_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_feature_response(text: str) -> SolutionFeatures:
    """Parse a teacher JSON response into :class:`SolutionFeatures`.

    Tolerant of code fences and surrounding prose; raises ``ValueError`` if no
    JSON object can be recovered.
    """
    match = _JSON_OBJ_RE.search(text or "")
    if not match:
        raise ValueError("no JSON object found in teacher response")
    data = json.loads(match.group())
    return SolutionFeatures.model_validate(data)


# --------------------------------------------------------------------------- #
# Heuristic (offline) extractor
# --------------------------------------------------------------------------- #
TECHNIQUE_LEXICON: list[str] = [
    "induction", "pigeonhole", "invariant", "generating function", "modular arithmetic",
    "complex number", "vieta", "telescoping", "am-gm", "cauchy-schwarz", "substitution",
    "casework", "symmetry", "coordinate geometry", "trigonometry", "recursion",
    "combinatorial identity", "probability", "inequality", "polynomial",
    "functional equation", "graph theory", "bijection", "extremal principle",
    "roots of unity", "law of cosines", "similar triangles", "power of a point",
    "chinese remainder theorem", "fermat", "binomial theorem", "geometric series",
]

_CRUX_MARKERS = ("notice", "observe", "key idea", "the trick", "claim", "crucial",
                 "insight", "clever", "the key")
_STEP_MARKERS = ("therefore", "thus", "hence", "so that", "we get", "it follows",
                 "then", "=>", "\\implies")


def _prereq_level_from_difficulty(difficulty: Optional[float]) -> int:
    if difficulty is None:
        return 3
    # map 1-10 difficulty onto 1-5 prerequisite levels
    return max(1, min(5, int(round(difficulty / 2))))


def heuristic_features(
    statement: str, reference_solution: Optional[str], difficulty: Optional[float]
) -> SolutionFeatures:
    """Deterministic, dependency-free feature guess from text + difficulty."""
    sol = reference_solution or ""
    blob = f"{statement}\n{sol}".lower()

    techniques = [t for t in TECHNIQUE_LEXICON if t in blob]

    crux_count = sum(blob.count(m) for m in _CRUX_MARKERS)
    crux_count = max(1, min(crux_count, 4))

    step_hits = sum(blob.count(m) for m in _STEP_MARKERS)
    line_steps = len([ln for ln in sol.splitlines() if ln.strip()])
    routine_step_count = max(step_hits, line_steps)

    first_line = next((ln.strip() for ln in sol.splitlines() if ln.strip()), "")
    crux_insight = first_line[:200]

    prerequisite_level = _prereq_level_from_difficulty(difficulty)
    # A "standard method" likely suffices for easier problems.
    standard_method_solves = (difficulty is not None and difficulty < 5.0)

    return SolutionFeatures(
        techniques=techniques,
        crux_insight=crux_insight,
        crux_count=crux_count,
        routine_step_count=routine_step_count,
        prerequisite_level=prerequisite_level,
        standard_method_solves=standard_method_solves,
        solution_sketch=first_line[:280],
        difficulty_estimate=difficulty,
        confidence=0.3,
    )


# --------------------------------------------------------------------------- #
# Dispatcher
# --------------------------------------------------------------------------- #
def extract_features(
    problem: Problem,
    reference_solution: Optional[str],
    *,
    extractor: str = "heuristic",
    client: Optional[LLMClient] = None,
) -> tuple[SolutionFeatures, dict[str, Any]]:
    """Return (features, extras) for one problem.

    ``extras`` records provenance such as ``{"parse_error": True}`` when an LLM
    response could not be parsed and the heuristic was used as a fallback.
    """
    extras: dict[str, Any] = {"extractor": extractor}

    if extractor == "llm":
        if client is None:
            raise ValueError("extractor='llm' requires an LLMClient")
        prompt = build_feature_prompt(problem.statement, reference_solution)
        resp = client.complete(
            prompt,
            system=FEATURE_SYSTEM_PROMPT,
            purpose="extract-features",
            related_id=problem.id,
        )
        extras["llm_call_id"] = resp.call_id
        extras["cost_usd"] = resp.cost_usd
        try:
            return parse_feature_response(resp.text), extras
        except (ValueError, json.JSONDecodeError) as exc:
            extras["parse_error"] = str(exc)
            # fall through to heuristic

    feats = heuristic_features(
        problem.statement, reference_solution, problem.difficulty
    )
    return feats, extras


# --------------------------------------------------------------------------- #
# Batch runner
# --------------------------------------------------------------------------- #
@dataclass
class ExtractionReport:
    extracted: int = 0
    skipped_existing: int = 0
    parse_errors: int = 0
    extractor: str = "heuristic"
    model: str = ""
    llm_cost_usd: float = 0.0
    per_level: dict[int, int] = field(default_factory=dict)


def run_extraction(
    extractor: str = "heuristic",
    model: str = "echo",
    limit: Optional[int] = 100,
    split: str = "train",
    db_url: Optional[str] = None,
    overwrite: bool = False,
) -> ExtractionReport:
    """Extract features for problems in ``split`` and store teacher Solution rows.

    Idempotent: a problem that already has a teacher extraction from ``model`` is
    skipped unless ``overwrite=True``. Defaults to the TRAIN split so the frozen
    eval set is untouched.
    """
    db.init_db(db_url)
    # The stored extractor tag: real model name for LLM, "heuristic" otherwise.
    extractor_model = model if extractor == "llm" else "heuristic"
    report = ExtractionReport(extractor=extractor, model=extractor_model)
    client = (
        LLMClient(model=model, purpose="extract-features", db_url=db_url)
        if extractor == "llm"
        else None
    )

    with db.session_scope(db_url) as session:
        if split == "train":
            stmt = db.training_problems_select()
        else:
            stmt = select(Problem).where(Problem.split == DataSplit(split))
        problems = session.exec(stmt).all()

        # Reference (official/human) solution text per problem.
        ref_by_pid: dict[str, str] = {}
        existing_teacher: set[str] = set()
        for sol in session.exec(select(Solution)).all():
            if sol.source in (SolutionSource.OFFICIAL, SolutionSource.HUMAN) and (
                sol.problem_id not in ref_by_pid
            ):
                ref_by_pid[sol.problem_id] = sol.text
            if sol.source == SolutionSource.TEACHER and (
                sol.extractor_model == extractor_model
            ):
                existing_teacher.add(sol.problem_id)

        now = utcnow()
        done = 0
        for problem in problems:
            if limit is not None and done >= limit:
                break
            if problem.id in existing_teacher and not overwrite:
                report.skipped_existing += 1
                continue

            feats, extras = extract_features(
                problem,
                ref_by_pid.get(problem.id),
                extractor=extractor,
                client=client,
            )
            if extras.get("parse_error"):
                report.parse_errors += 1
            report.llm_cost_usd += float(extras.get("cost_usd") or 0.0)

            session.add(
                Solution(
                    problem_id=problem.id,
                    text=feats.solution_sketch or (ref_by_pid.get(problem.id, "")[:280]),
                    techniques=feats.techniques,
                    crux_insight=feats.crux_insight,
                    crux_count=feats.crux_count,
                    routine_step_count=feats.routine_step_count,
                    prerequisite_level=feats.prerequisite_level,
                    standard_method_solves=feats.standard_method_solves,
                    extractor_model=extractor_model,
                    extracted_at=now,
                    features={
                        **extras,
                        "prerequisite_topics": feats.prerequisite_topics,
                        "difficulty_estimate": feats.difficulty_estimate,
                        "confidence": feats.confidence,
                    },
                    source=SolutionSource.TEACHER,
                )
            )
            report.per_level[feats.prerequisite_level] = (
                report.per_level.get(feats.prerequisite_level, 0) + 1
            )
            report.extracted += 1
            done += 1

    return report


# --------------------------------------------------------------------------- #
# Bridge to the predictor: feature matrix + difficulty label
# --------------------------------------------------------------------------- #
def feature_rows(
    db_url: Optional[str] = None,
    split: str = "train",
    model: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Join teacher features with the difficulty label for predictor training.

    Returns one dict per (problem, teacher-solution) with numeric features and
    the target ``difficulty`` (plus ``difficulty_band``). Only problems that have
    a difficulty label are included.
    """
    db.init_db(db_url)
    rows: list[dict[str, Any]] = []
    with db.session_scope(db_url) as session:
        problems = {
            p.id: p
            for p in session.exec(
                select(Problem).where(Problem.split == DataSplit(split))
            ).all()
        }
        for sol in session.exec(
            select(Solution).where(Solution.source == SolutionSource.TEACHER)
        ).all():
            if model is not None and sol.extractor_model != model:
                continue
            problem = problems.get(sol.problem_id)
            if problem is None or problem.difficulty is None:
                continue
            rows.append(
                {
                    "problem_id": problem.id,
                    "num_techniques": len(sol.techniques or []),
                    "crux_count": sol.crux_count,
                    "routine_step_count": sol.routine_step_count,
                    "prerequisite_level": sol.prerequisite_level,
                    "standard_method_solves": int(bool(sol.standard_method_solves)),
                    "difficulty_estimate": (sol.features or {}).get("difficulty_estimate"),
                    "difficulty": problem.difficulty,
                    "difficulty_band": difficulty_band(problem.difficulty),
                }
            )
    return rows
