"""Core data models for MathForge.

These are SQLModel classes, which means they are simultaneously:

* Pydantic v2 models (validation, ``model_dump``/``model_validate`` round-tripping), and
* SQLAlchemy ORM tables (persisted to SQLite via :mod:`mathforge.db`).

The domain: a pipeline that mines *elegant ideas* (``Insight``) from strong
competition problems, generates new ``Problem``s around those ideas, collects
``Solution``s, and scores everything with ``Evaluation``s. ``LLMCall`` gives us a
full audit trail (tokens + cost) of every model call.
"""

import hashlib
import re
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from sqlalchemy import Column, UniqueConstraint
from sqlmodel import JSON, Field, Relationship, SQLModel

__all__ = [
    "ProblemSource",
    "SolutionSource",
    "DifficultyBand",
    "EvaluatorKind",
    "ProblemTier",
    "DataSplit",
    "SolverRole",
    "SolverClassification",
    "ReviewStatus",
    "CombinationJobStatus",
    "DEFAULT_TIER_THRESHOLD",
    "tier_for_difficulty",
    "difficulty_band",
    "Problem",
    "Solution",
    "Evaluation",
    "Insight",
    "CombinationJob",
    "CombinationStatementClaim",
    "CombinationStorageLock",
    "LLMCall",
    "SolverAttempt",
    "SolverPanel",
    "normalize_statement",
    "statement_hash",
    "new_id",
    "utcnow",
    "parse_evaluator",
]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def utcnow() -> datetime:
    """Timezone-aware UTC now (used as a default factory)."""
    return datetime.now(timezone.utc)


def new_id() -> str:
    """A short, URL-safe unique id for synthetic rows."""
    return uuid.uuid4().hex


_WS_RE = re.compile(r"\s+")


def normalize_statement(statement: str) -> str:
    """Canonicalize a problem statement for dedup.

    Lowercases, collapses all whitespace, and strips. This is intentionally
    aggressive: two statements that differ only in formatting map to the same
    normalized form (and therefore the same :func:`statement_hash`).
    """
    return _WS_RE.sub(" ", statement.strip().lower())


def statement_hash(statement: str) -> str:
    """A stable content hash of the normalized statement (exact-dup key)."""
    return hashlib.sha256(normalize_statement(statement).encode("utf-8")).hexdigest()


_JUDGE_RE = re.compile(r"^judge_v\d+$")


def parse_evaluator(value: str) -> str:
    """Validate/normalize an ``Evaluation.evaluator`` string.

    Allowed forms: ``"human"``, ``"solver_panel"``, ``"dataset"`` (source-provided
    ratings, e.g. Omni-MATH), or a versioned judge such as ``"judge_v1"``,
    ``"judge_v2"`` ... Raises ``ValueError`` otherwise.
    """
    v = value.strip().lower()
    if v in (
        EvaluatorKind.HUMAN.value,
        EvaluatorKind.SOLVER_PANEL.value,
        EvaluatorKind.DATASET.value,
    ):
        return v
    if _JUDGE_RE.match(v):
        return v
    raise ValueError(
        "evaluator must be 'human', 'solver_panel', 'dataset', or 'judge_v<N>' "
        f"(got {value!r})"
    )


# --------------------------------------------------------------------------- #
# Controlled vocabularies
# --------------------------------------------------------------------------- #
class ProblemSource(str, Enum):
    """Where a problem came from."""

    AMC = "amc"
    AIME = "aime"
    USAJMO = "usajmo"
    USAMO = "usamo"
    IMO = "imo"
    PUTNAM = "putnam"
    OTHER_COMPETITION = "other_competition"
    SYNTHETIC = "synthetic"


class SolutionSource(str, Enum):
    """Who/what produced a solution (or solution-level analysis)."""

    HUMAN = "human"
    OFFICIAL = "official"
    MODEL = "model"
    SOLVER_PANEL = "solver_panel"
    TEACHER = "teacher"  # LLM feature-extraction pass over a problem/solution


class DifficultyBand(str, Enum):
    """Coarse difficulty banding shared by insights and problems.

    Aligned to the user's target: AIME-easy vs AIME-hard (problems 10+), plus a
    band for proof-based olympiad material.
    """

    AMC = "amc"
    AIME_EASY = "aime_easy"  # roughly problems 1-9
    AIME_HARD = "aime_hard"  # problems 10-15, the primary target
    OLYMPIAD = "olympiad"  # USAJMO/USAMO/IMO proof-based


class EvaluatorKind(str, Enum):
    """Base evaluator kinds. ``JUDGE`` is versioned as ``judge_v<N>``."""

    HUMAN = "human"  # the in-the-loop human labeler (ground truth)
    JUDGE = "judge"
    SOLVER_PANEL = "solver_panel"
    DATASET = "dataset"  # source-provided rating (e.g. Omni-MATH difficulty)


class ProblemTier(str, Enum):
    """Coarse section a problem belongs to, driven by source difficulty.

    The two tiers are kept as *separate sections* because the problems we want to
    generate from each are qualitatively different (gentler warmups vs. the
    creative, AIME-hard style targets).
    """

    EASY = "easy"  # source difficulty below the threshold
    HARD = "hard"  # source difficulty at/above the threshold


class DataSplit(str, Enum):
    """Train vs. held-out eval. Eval rows are frozen and never used upstream."""

    TRAIN = "train"
    EVAL = "eval"


class SolverRole(str, Enum):
    """Which member of the solver panel produced an attempt."""

    WEAK = "weak"  # ~7B open model, many attempts
    STRONG = "strong"  # frontier model, fewer attempts


class SolverClassification(str, Enum):
    """Where the (weak_rate, strong_rate) pair locates a problem."""

    EXERCISE = "exercise"  # weak solver succeeds often
    TARGET = "target"  # weak fails but strong succeeds: hard-but-well-posed
    BROKEN = "broken"  # both fail: probably broken / ill-posed
    INCONCLUSIVE = "inconclusive"  # ambiguous signal


class ReviewStatus(str, Enum):
    """Human review state for distilled (synthetic) problems."""

    PENDING = "pending"  # verified by the machine loop, awaiting human check
    ACCEPTED = "accepted"  # human approved
    REJECTED = "rejected"  # human rejected (or failed verification)
    NEEDS_EDIT = "needs_edit"  # good candidate, but the problem needs fixing


class CombinationJobStatus(str, Enum):
    """Lifecycle state for one durable technique-pair generation attempt."""

    PENDING = "pending"
    INFLIGHT = "inflight"
    STORED = "stored"
    REJECTED = "rejected"
    EXHAUSTED = "exhausted"


# Default Omni-MATH difficulty cutoff: < 4 is easy, >= 4 is hard.
DEFAULT_TIER_THRESHOLD = 4.0


def tier_for_difficulty(
    difficulty: Optional[float], threshold: float = DEFAULT_TIER_THRESHOLD
) -> Optional[ProblemTier]:
    """Map a numeric difficulty to a :class:`ProblemTier` (``None`` if unrated)."""
    if difficulty is None:
        return None
    return ProblemTier.HARD if difficulty >= threshold else ProblemTier.EASY


def difficulty_band(difficulty: Optional[float]) -> Optional[str]:
    """Coarse band label used for stratification (rounded 1-10, e.g. ``"d7"``)."""
    if difficulty is None:
        return None
    return f"d{int(round(difficulty))}"


# --------------------------------------------------------------------------- #
# Tables
# --------------------------------------------------------------------------- #
class Problem(SQLModel, table=True):
    """A competition math problem (official or synthetic)."""

    id: str = Field(default_factory=new_id, primary_key=True)

    source: ProblemSource = Field(index=True)
    statement: str
    # AIME-style short answer (e.g. "042"); ``None`` for proof problems.
    answer: Optional[str] = Field(default=None)

    # Source-provided numeric difficulty (e.g. Omni-MATH's 1-10 rating).
    difficulty: Optional[float] = Field(default=None, index=True)
    # Which section this problem belongs to (easy vs hard); see ProblemTier.
    tier: Optional[ProblemTier] = Field(default=None, index=True)
    # Primary subject/topic (e.g. "Algebra", "Number Theory").
    topic: Optional[str] = Field(default=None, index=True)

    # --- train/eval split (upstream protection) -------------------------- #
    # Famous-contest problems solvers may recognize/regurgitate rather than
    # reason through. The difficulty judge discounts solver success when set.
    possibly_memorized: bool = Field(default=False, index=True)

    # Distillation: was the answer verified by the independent solver loop, and
    # where is it in human review? (Meaningful mainly for SYNTHETIC problems.)
    verified: Optional[bool] = Field(default=None, index=True)
    review_status: Optional[ReviewStatus] = Field(default=None, index=True)

    # TRAIN rows feed ingest/annotate/generate; EVAL rows are held out.
    split: DataSplit = Field(default=DataSplit.TRAIN, index=True)
    # Once frozen, a problem is a locked member of the eval set and must not be
    # mutated or used upstream.
    frozen: bool = Field(default=False, index=True)
    frozen_at: Optional[datetime] = Field(default=None)

    # Free-form origin metadata. For official problems: year/round/number. For
    # synthetic problems: generating model, seed insight id, prompt hash, etc.
    provenance: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))

    # --- dedup fields ---------------------------------------------------- #
    # sha256 of the normalized statement (exact-duplicate key).
    statement_hash: Optional[str] = Field(default=None, index=True)
    # Canonicalized statement text, handy for exact and fuzzy matching.
    normalized_statement: Optional[str] = Field(default=None)
    # Cluster id assigned by a near-duplicate pass (many rows share one id).
    dedup_group_id: Optional[str] = Field(default=None, index=True)

    created_at: datetime = Field(default_factory=utcnow)

    solutions: list["Solution"] = Relationship(back_populates="problem")
    evaluations: list["Evaluation"] = Relationship(back_populates="problem")

    def refresh_dedup_fields(self) -> "Problem":
        """(Re)compute ``statement_hash`` and ``normalized_statement``."""
        self.normalized_statement = normalize_statement(self.statement)
        self.statement_hash = statement_hash(self.statement)
        return self


class Solution(SQLModel, table=True):
    """A worked solution to a :class:`Problem`.

    ``crux_count`` and ``routine_step_count`` are the signal we care about: an
    *elegant* problem has a small number of genuine insight leaps (cruxes)
    relative to routine bookkeeping steps.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    problem_id: str = Field(foreign_key="problem.id", index=True)

    text: str
    techniques: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    # The single key idea that unlocks the problem.
    crux_insight: str = ""
    # Number of genuine insight leaps required.
    crux_count: int = 0
    # Number of routine/mechanical steps (algebra, casework bookkeeping, ...).
    routine_step_count: int = 0

    # --- teacher-extracted difficulty features --------------------------- #
    # Prerequisite knowledge level required, 1 (elementary) .. 5 (olympiad-deep).
    prerequisite_level: Optional[int] = Field(default=None)
    # Does a standard/textbook method solve it (vs. needing a creative leap)?
    standard_method_solves: Optional[bool] = Field(default=None)
    # Teacher model that produced these features (e.g. "gpt-4o", "heuristic").
    extractor_model: Optional[str] = Field(default=None, index=True)
    extracted_at: Optional[datetime] = Field(default=None)
    # Extra structured teacher outputs (prerequisite_topics, confidence,
    # difficulty_estimate, parse_error, ...).
    features: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))

    source: SolutionSource = Field(default=SolutionSource.MODEL, index=True)
    created_at: datetime = Field(default_factory=utcnow)

    problem: Optional[Problem] = Relationship(back_populates="solutions")


class Evaluation(SQLModel, table=True):
    """A difficulty/elegance judgment of a :class:`Problem`."""

    id: Optional[int] = Field(default=None, primary_key=True)
    problem_id: str = Field(foreign_key="problem.id", index=True)

    # Both axes are optional so a source can supply only one (e.g. Omni-MATH
    # ships human difficulty ratings but no elegance score).
    difficulty_score: Optional[float] = Field(default=None)
    elegance_score: Optional[float] = Field(default=None)
    # One of: "human", "solver_panel", or "judge_v<N>".
    evaluator: str = Field(index=True)
    rationale: str = ""

    created_at: datetime = Field(default_factory=utcnow)

    problem: Optional[Problem] = Relationship(back_populates="evaluations")


class Insight(SQLModel, table=True):
    """An elegant, reusable idea mined from strong problems.

    These are the *seeds*: generation starts from an interesting pattern/insight
    and grows a full problem around it.
    """

    id: str = Field(default_factory=new_id, primary_key=True)
    text: str

    concept_tags: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    difficulty_band: DifficultyBand = Field(default=DifficultyBand.AIME_HARD, index=True)
    source_problem_ids: list[str] = Field(
        default_factory=list, sa_column=Column(JSON)
    )
    # Optional dense vector for semantic dedup/retrieval of ideas.
    embedding: Optional[list[float]] = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )

    created_at: datetime = Field(default_factory=utcnow)


class CombinationJob(SQLModel, table=True):
    """Checkpoint for one bridge-first technique-combination attempt.

    Full parsed artifacts live here so a stopped run can resume without placing
    incomplete placeholder rows in :class:`Problem` or relying on truncated
    :class:`LLMCall` previews.
    """

    __table_args__ = (
        UniqueConstraint("run_id", "ordinal", name="uq_combination_job_run_ordinal"),
    )

    id: str = Field(default_factory=new_id, primary_key=True)
    run_id: str = Field(index=True)
    ordinal: int = Field(index=True)
    seed: int = 0

    pair_key: str = Field(index=True)
    technique_ids: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    technique_snapshot: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSON)
    )
    taxonomy_sha256: str = ""
    sampler_metadata: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    config: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))

    stage: str = Field(default="pair_selected", index=True)
    status: CombinationJobStatus = Field(default=CombinationJobStatus.PENDING, index=True)
    bridge_candidates: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    bridge_judgment: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    selected_bridge: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    # V2 shell proposals, blind audits, and draft lineage. Kept separate from
    # ``preflight`` so existing exporters can continue consuming its v1 shape.
    design_artifacts: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    draft: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    preflight: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))

    attempts: dict[str, int] = Field(default_factory=dict, sa_column=Column(JSON))
    call_ids: dict[str, list[int]] = Field(default_factory=dict, sa_column=Column(JSON))
    failures: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    rejection_reason: Optional[str] = None
    lease_started_at: Optional[datetime] = None
    lease_owner: Optional[str] = Field(default=None, index=True)
    problem_id: Optional[str] = Field(default=None, index=True)

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class CombinationStatementClaim(SQLModel, table=True):
    """Durable uniqueness claim for a combination draft's canonical statement.

    ``Problem`` predates canonical hashes, so it cannot enforce this constraint
    directly without a destructive migration.  Combination workers reserve the
    hash here before inserting a candidate.  The primary key makes that reserve
    atomic across processes, including concurrent SQLite workers.
    """

    __table_args__ = (
        UniqueConstraint("job_id", name="uq_combination_statement_claim_job"),
    )

    canonical_hash: str = Field(primary_key=True)
    statement_hash: str = Field(index=True)
    job_id: str = Field(foreign_key="combinationjob.id", index=True)
    problem_id: Optional[str] = Field(default=None, index=True)
    claimed_at: datetime = Field(default_factory=utcnow)


class CombinationStorageLock(SQLModel, table=True):
    """Singleton row used to serialize final duplicate checks and insertion."""

    id: int = Field(default=1, primary_key=True)
    owner_job_id: Optional[str] = Field(default=None, index=True)
    updated_at: datetime = Field(default_factory=utcnow)


class LLMCall(SQLModel, table=True):
    """Audit record for a single LLM call: model, tokens, and cost."""

    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=utcnow, index=True)

    provider: Optional[str] = Field(default=None)
    model: str = Field(index=True)
    # Coarse pipeline stage: "ingest" | "annotate" | "generate" | "evaluate" ...
    purpose: Optional[str] = Field(default=None, index=True)

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: Optional[float] = None

    # Truncated previews for debugging (never rely on these for full payloads).
    request_preview: Optional[str] = None
    response_preview: Optional[str] = None

    # Optional link to the row this call helped produce (problem/insight id...).
    related_id: Optional[str] = Field(default=None, index=True)
    meta: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))


class SolverAttempt(SQLModel, table=True):
    """One independent solver attempt on a problem (the cached API unit).

    The unique constraint on (problem_id, model, prompt_version, attempt_index)
    is what makes the panel *cacheable*: a given attempt is never solved twice,
    which is the dominant API cost of the project.
    """

    __table_args__ = (
        UniqueConstraint(
            "problem_id",
            "model",
            "prompt_version",
            "attempt_index",
            name="uq_solver_attempt",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    problem_id: str = Field(foreign_key="problem.id", index=True)

    role: SolverRole = Field(index=True)
    model: str = Field(index=True)
    prompt_version: str = Field(index=True)
    attempt_index: int = 0

    final_answer: Optional[str] = None
    correct: bool = False
    confidence: Optional[str] = None
    ambiguity_flag: bool = False
    recognized_as_existing: bool = False

    llm_call_id: Optional[int] = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow)


class SolverPanel(SQLModel, table=True):
    """Aggregate behavioral signal for a problem: weak + strong solve rates.

    The pair of rates locates a problem (see :class:`SolverClassification`):
    weak succeeds often -> exercise; weak fails but strong succeeds -> target
    (hard-but-well-posed); both fail -> probably broken.
    """

    __table_args__ = (
        UniqueConstraint("problem_id", "prompt_version", name="uq_solver_panel"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    problem_id: str = Field(foreign_key="problem.id", index=True)
    prompt_version: str = Field(index=True)

    weak_model: Optional[str] = None
    weak_attempts: int = 0
    weak_successes: int = 0
    weak_solve_rate: float = 0.0

    strong_model: Optional[str] = None
    strong_attempts: int = 0
    strong_successes: int = 0
    strong_solve_rate: float = 0.0

    # Effective memorization flag (contest fame OR solver recognition); the
    # difficulty judge discounts solver success when this is set.
    possibly_memorized: bool = Field(default=False, index=True)
    any_recognized: bool = False
    ambiguity_count: int = 0

    classification: SolverClassification = Field(
        default=SolverClassification.INCONCLUSIVE, index=True
    )
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
