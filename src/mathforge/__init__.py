"""MathForge: a pipeline for generating elegant competition math problems."""

from mathforge.schema import (
    DataSplit,
    DifficultyBand,
    Evaluation,
    EvaluatorKind,
    Insight,
    LLMCall,
    Problem,
    ProblemSource,
    ProblemTier,
    Solution,
    SolutionSource,
    difficulty_band,
    tier_for_difficulty,
)

__version__ = "0.1.0"

__all__ = [
    "Problem",
    "Solution",
    "Evaluation",
    "Insight",
    "LLMCall",
    "ProblemSource",
    "SolutionSource",
    "DifficultyBand",
    "EvaluatorKind",
    "ProblemTier",
    "DataSplit",
    "tier_for_difficulty",
    "difficulty_band",
    "__version__",
]
