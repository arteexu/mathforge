"""HuggingFace dataset loaders + mappers into MathForge's schema.

Two source datasets:

* **Omni-MATH** (``KbsdJames/Omni-MATH``) — 4,428 olympiad problems with
  official solutions, human *difficulty* ratings, and subject *domains*.
* **NuminaMath-1.5** (``AI-MO/NuminaMath-1.5``) — ~896k competition problems
  with solutions/answers and rich source/type metadata.

Datasets are cached in the standard HuggingFace cache (``~/.cache/huggingface``
by default, overridable via ``MATHFORGE_HF_CACHE`` or ``HF_HOME``) so large
downloads never land in an iCloud-synced project folder.
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, Any, Optional

from mathforge.schema import (
    DEFAULT_TIER_THRESHOLD,
    Evaluation,
    Problem,
    ProblemSource,
    Solution,
    SolutionSource,
    tier_for_difficulty,
)

if TYPE_CHECKING:  # avoid importing heavy deps at module import time
    from datasets import Dataset

__all__ = [
    "OMNI_MATH_REPO",
    "NUMINA_MATH_REPO",
    "cache_dir",
    "load_omni_math",
    "load_numina_math",
    "infer_source",
    "omni_topic",
    "omni_row_to_records",
    "numina_row_to_records",
    "load_aime_eval",
]

OMNI_MATH_REPO = "KbsdJames/Omni-MATH"
NUMINA_MATH_REPO = "AI-MO/NuminaMath-1.5"


def cache_dir() -> Optional[str]:
    """Resolve the HF cache dir (``MATHFORGE_HF_CACHE`` wins, else HF default)."""
    return os.environ.get("MATHFORGE_HF_CACHE") or None


def load_omni_math(split: str = "test", cache: Optional[str] = None) -> "Dataset":
    """Load (downloading+caching on first call) the Omni-MATH dataset."""
    from datasets import load_dataset

    return load_dataset(OMNI_MATH_REPO, split=split, cache_dir=cache or cache_dir())


def load_numina_math(split: str = "train", cache: Optional[str] = None) -> "Dataset":
    """Load (downloading+caching on first call) the NuminaMath-1.5 dataset."""
    from datasets import load_dataset

    return load_dataset(NUMINA_MATH_REPO, split=split, cache_dir=cache or cache_dir())


# --------------------------------------------------------------------------- #
# Mapping into the MathForge schema
# --------------------------------------------------------------------------- #
_SOURCE_KEYWORDS: list[tuple[str, ProblemSource]] = [
    ("usajmo", ProblemSource.USAJMO),
    ("usamo", ProblemSource.USAMO),
    ("aime", ProblemSource.AIME),
    ("amc", ProblemSource.AMC),
    ("imo", ProblemSource.IMO),
    ("putnam", ProblemSource.PUTNAM),
]


def omni_topic(domains: Optional[list[str]]) -> str:
    """Extract the primary subject from an Omni-MATH ``domain`` list.

    e.g. ``"Mathematics -> Number Theory -> Congruences"`` -> ``"Number Theory"``.
    """
    if not domains:
        return "Unknown"
    parts = [p.strip() for p in domains[0].split("->")]
    return parts[1] if len(parts) > 1 else parts[0]


def infer_source(raw: Optional[str], synthetic: bool = False) -> ProblemSource:
    """Best-effort map a free-text source string to a :class:`ProblemSource`."""
    if synthetic:
        return ProblemSource.SYNTHETIC
    text = (raw or "").lower()
    for keyword, source in _SOURCE_KEYWORDS:
        if keyword in text:
            return source
    return ProblemSource.OTHER_COMPETITION


def omni_row_to_records(
    row: dict[str, Any],
    idx: int,
    threshold: float = DEFAULT_TIER_THRESHOLD,
) -> tuple[Problem, Optional[Solution], Optional[Evaluation]]:
    """Convert one Omni-MATH row into (Problem, Solution?, Evaluation?).

    ``threshold`` sets the easy/hard section cutoff on the difficulty rating
    (default 4.0: ``< 4`` -> easy, ``>= 4`` -> hard).
    """
    pid = f"omni-math-{idx}"
    domains = row.get("domain") or []
    raw_source = row.get("source")
    difficulty = row.get("difficulty")

    problem = Problem(
        id=pid,
        source=infer_source(raw_source),
        statement=row["problem"],
        answer=(row.get("answer") or None),
        difficulty=difficulty,
        tier=tier_for_difficulty(difficulty, threshold),
        topic=omni_topic(domains),
        provenance={
            "dataset": OMNI_MATH_REPO,
            "row_index": idx,
            "raw_source": raw_source,
            "domain": domains,
            "difficulty": difficulty,
            "tier_threshold": threshold,
        },
    ).refresh_dedup_fields()

    solution_text = row.get("solution")
    solution = (
        Solution(
            problem_id=pid,
            text=solution_text,
            techniques=list(domains),
            source=SolutionSource.OFFICIAL,
        )
        if solution_text
        else None
    )

    evaluation = (
        Evaluation(
            problem_id=pid,
            difficulty_score=float(difficulty),
            elegance_score=None,
            evaluator="dataset",
            rationale="Omni-MATH official difficulty rating.",
        )
        if difficulty is not None
        else None
    )

    return problem, solution, evaluation


def numina_row_to_records(
    row: dict[str, Any], idx: int
) -> tuple[Problem, Optional[Solution]]:
    """Convert one NuminaMath-1.5 row into (Problem, Solution?)."""
    pid = f"numina-1.5-{idx}"
    raw_source = row.get("source")
    synthetic = bool(row.get("synthetic"))

    problem = Problem(
        id=pid,
        source=infer_source(raw_source, synthetic=synthetic),
        statement=row["problem"],
        answer=(row.get("answer") or None),
        provenance={
            "dataset": NUMINA_MATH_REPO,
            "row_index": idx,
            "raw_source": raw_source,
            "problem_type": row.get("problem_type"),
            "question_type": row.get("question_type"),
            "synthetic": synthetic,
            "problem_is_valid": row.get("problem_is_valid"),
            "solution_is_valid": row.get("solution_is_valid"),
        },
    ).refresh_dedup_fields()

    solution_text = row.get("solution")
    solution = (
        Solution(
            problem_id=pid,
            text=solution_text,
            source=SolutionSource.OFFICIAL,
        )
        if solution_text
        else None
    )

    return problem, solution


# --------------------------------------------------------------------------- #
# AIME eval sources (2024-2026, rounds I & II)
# --------------------------------------------------------------------------- #
# Authoritative, round-labeled sources chosen after verifying each against the
# AoPS wiki statements:
#   2024 I/II -> Maxwell-Jia/AIME_2024   (ID encodes "2024-<round>-<n>")
#   2025 I/II -> opencompass/AIME2025    (separate I / II jsonl files)
#   2026 I/II -> MathArena/aime_2026     (idx 1-15 = I, 16-30 = II)
AIME_2024_REPO = "Maxwell-Jia/AIME_2024"
AIME_2025_REPO = "opencompass/AIME2025"
AIME_2026_REPO = "MathArena/aime_2026"


_INT_RE = re.compile(r"-?\d+")


def _clean_aime_answer(answer: Any) -> str:
    """AIME answers are integers 0-999; strip stray LaTeX (e.g. ``336^\\circ``)."""
    raw = str(answer).strip()
    if raw.isdigit():
        return str(int(raw))
    match = _INT_RE.search(raw)
    return str(int(match.group())) if match else raw


def _aime_record(
    year: int, rnd: str, number: int, statement: str, answer: str, dataset: str
) -> dict[str, Any]:
    return {
        "year": year,
        "round": rnd,
        "number": number,
        "statement": statement.strip(),
        "answer": _clean_aime_answer(answer),
        "dataset": dataset,
    }


def load_aime_eval(cache: Optional[str] = None) -> list[dict[str, Any]]:
    """Load all 90 problems of 2024-2026 AIME I & II as normalized records.

    Each record has: ``year``, ``round`` ("I"/"II"), ``number`` (1-15),
    ``statement``, ``answer`` (integer string), and source ``dataset``.
    """
    from datasets import load_dataset

    cd = cache or cache_dir()
    records: list[dict[str, Any]] = []

    # --- 2024 (Maxwell-Jia): ID like "2024-II-4" -----------------------------
    ds24 = load_dataset(AIME_2024_REPO, split="train", cache_dir=cd)
    for row in ds24:
        year_s, rnd, num_s = row["ID"].split("-")
        records.append(
            _aime_record(
                int(year_s), rnd, int(num_s), row["Problem"], row["Answer"], AIME_2024_REPO
            )
        )

    # --- 2025 (opencompass): explicit I / II jsonl ---------------------------
    for rnd, fname in (("I", "aime2025-I.jsonl"), ("II", "aime2025-II.jsonl")):
        ds = load_dataset(AIME_2025_REPO, data_files=fname, split="train", cache_dir=cd)
        for i, row in enumerate(ds, start=1):
            records.append(
                _aime_record(2025, rnd, i, row["question"], row["answer"], AIME_2025_REPO)
            )

    # --- 2026 (MathArena combined): idx 1-15 = I, 16-30 = II -----------------
    ds26 = load_dataset(AIME_2026_REPO, split="train", cache_dir=cd)
    for row in ds26:
        idx = int(row["problem_idx"])
        rnd = "I" if idx <= 15 else "II"
        number = idx if idx <= 15 else idx - 15
        records.append(
            _aime_record(2026, rnd, number, row["problem"], row["answer"], AIME_2026_REPO)
        )

    return records
