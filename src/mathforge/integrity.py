"""Shared data-integrity helpers for training exports and upstream curation.

The frozen evaluation split is a hard boundary.  Exporters and annotation stages
must query through :func:`mathforge.db.training_problems_select`, and exports must
also defend against duplicate statements and statement-level overlap with eval.
"""

from __future__ import annotations

import ast
import re
import hashlib
import json
import os
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Optional

from sqlmodel import select

from mathforge import db
from mathforge.schema import (
    DataSplit,
    Problem,
    ProblemSource,
    ReviewStatus,
    Solution,
    SolutionSource,
    statement_hash,
)

__all__ = [
    "answer_type",
    "audit_export_records",
    "canonical_statement_hash",
    "canonicalize_statement",
    "deduplicated_training_problems",
    "is_export_eligible",
    "normalize_aime_answer",
    "normalize_solution_text",
    "preferred_solution",
    "techniques_for",
]


_PLAIN_INT_RE = re.compile(r"^[+-]?\d+$")
_BOXED_INT_RE = re.compile(r"\\(?:boxed|fbox)\s*\{\s*([+-]?\d+)\s*\}")
_MATH_WRAPPERS = (("$", "$"), (r"\(", r"\)"), (r"\[", r"\]"))
_ASY_BLOCK_RE = re.compile(
    r"(?:\[asy\].*?\[/asy\]|\\begin\{asy\}.*?\\end\{asy\})",
    re.IGNORECASE | re.DOTALL,
)
_CANON_TOKEN_RE = re.compile(r"[a-z]+|\d+|<=|>=|!=|[=+\-*/^<>]")
_CANON_REPLACEMENTS = {
    "≤": "<=", "≥": ">=", "≠": "!=", "−": "-", "–": "-", "—": "-",
    r"\leqslant": "<=", r"\leq": "<=", r"\le": "<=",
    r"\geqslant": ">=", r"\geq": ">=", r"\ge": ">=",
    r"\neq": "!=", r"\ne": "!=", r"\cdot": "*", r"\times": "*",
    r"\dfrac": " frac ", r"\tfrac": " frac ", r"\frac": " frac ",
}


def canonicalize_statement(statement: str) -> str:
    """Conservative content canonicalization for cross-source format duplicates.

    This removes presentation-only LaTeX differences and embedded Asymptote code
    while preserving words, numbers, and mathematical operators.  It intentionally
    does not attempt semantic/fuzzy deduplication; parameter variants remain distinct.
    """

    text = unicodedata.normalize("NFKC", statement or "").casefold()
    text = _ASY_BLOCK_RE.sub(" ", text)
    for old, new in _CANON_REPLACEMENTS.items():
        text = text.replace(old, new)
    for command in (r"\left", r"\right", r"\,", r"\;", r"\!", r"\quad", r"\qquad"):
        text = text.replace(command, " ")
    # Keep command names (sqrt, binom, angle, ...) as semantic tokens while
    # discarding TeX escaping/grouping/punctuation differences.
    text = text.replace("\\", " ")
    return " ".join(_CANON_TOKEN_RE.findall(text))


def canonical_statement_hash(statement: str) -> str:
    return hashlib.sha256(canonicalize_statement(statement).encode("utf-8")).hexdigest()


def _manual_dedup_rules() -> tuple[
    set[str], dict[str, str], set[str], dict[str, str]
]:
    """Load reviewed duplicate clusters that formatting hashes cannot safely infer."""

    path = Path(os.environ.get("MATHFORGE_DEDUP_MANIFEST", "eval/dedup_quarantine_v1.json"))
    if not path.exists():
        return set(), {}, set(), {}
    data = json.loads(path.read_text(encoding="utf-8"))
    cross_split_ids = [
        pid
        for group in data.get("cross_split", [])
        for pid in group.get("train_ids", [])
    ]
    if len(cross_split_ids) != len(set(cross_split_ids)):
        raise ValueError("dedup manifest repeats a cross-split train id")
    excluded_for_eval = set(cross_split_ids)
    group_by_id: dict[str, str] = {}
    quarantine_all: set[str] = set()
    keeper_by_group: dict[str, str] = {}
    seen_group_ids: set[str] = set()
    for index, group in enumerate(data.get("train_groups", [])):
        group_id = group.get("id") or f"manual-{index}"
        if group_id in seen_group_ids:
            raise ValueError(f"dedup manifest repeats train group id {group_id!r}")
        seen_group_ids.add(group_id)
        members = group.get("members", [])
        if not isinstance(members, list) or len(members) < 2:
            raise ValueError(f"dedup group {group_id!r} must contain at least two members")
        if len(members) != len(set(members)):
            raise ValueError(f"dedup group {group_id!r} repeats a member")
        overlap = sorted(set(members) & excluded_for_eval)
        if overlap:
            raise ValueError(
                f"dedup group {group_id!r} overlaps cross-split exclusions: {overlap}"
            )
        keeper_id = group.get("keeper_id")
        crux_source_id = group.get("keeper_crux_from_id")
        if keeper_id is not None:
            if keeper_id not in members:
                raise ValueError(
                    f"dedup group {group_id!r} keeper_id {keeper_id!r} is not a member"
                )
            if group.get("quarantine_all"):
                raise ValueError(
                    f"dedup group {group_id!r} cannot set keeper_id and quarantine_all"
                )
            keeper_by_group[group_id] = keeper_id
        if crux_source_id is not None and (
            keeper_id is None or crux_source_id not in members
        ):
            raise ValueError(
                f"dedup group {group_id!r} has invalid keeper_crux_from_id"
            )
        for pid in members:
            if pid in group_by_id:
                raise ValueError(
                    f"dedup member {pid!r} appears in both {group_by_id[pid]!r} "
                    f"and {group_id!r}"
                )
            group_by_id[pid] = group_id
        if group.get("quarantine_all"):
            quarantine_all.update(members)
    return excluded_for_eval, group_by_id, quarantine_all, keeper_by_group


def normalize_aime_answer(value: Any) -> Optional[str]:
    """Return a canonical integer in ``[0, 999]`` or ``None``.

    Parsing is deliberately conservative: plain integers and common LaTeX math /
    box wrappers are accepted, but arbitrary symbolic answers containing a number
    are not guessed to be AIME answers.
    """

    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None

    boxed = _BOXED_INT_RE.fullmatch(raw)
    if boxed:
        raw = boxed.group(1)
    else:
        changed = True
        while changed:
            changed = False
            raw = raw.strip()
            for left, right in _MATH_WRAPPERS:
                if raw.startswith(left) and raw.endswith(right):
                    raw = raw[len(left): len(raw) - len(right)].strip()
                    changed = True
            boxed = _BOXED_INT_RE.fullmatch(raw)
            if boxed:
                raw = boxed.group(1)
                changed = True

    raw = raw.strip().rstrip(".").strip()
    if not _PLAIN_INT_RE.fullmatch(raw):
        return None
    number = int(raw)
    return str(number) if 0 <= number <= 999 else None


def answer_type(value: Any) -> str:
    """Classify a stored answer without treating symbolic expressions as integers."""

    if value is None or not str(value).strip():
        return "none"
    if normalize_aime_answer(value) is not None:
        return "integer"
    raw = str(value).strip().replace(",", "")
    if _PLAIN_INT_RE.fullmatch(raw):
        return "integer_other"
    return "symbolic"


def normalize_solution_text(value: Any) -> str:
    """Unwrap a conservatively recognized serialized list of solution strings.

    Some OlympiadBench solutions were imported as literal text such as
    ``['proof one', 'proof two']`` instead of a proof.  When the entire value is a
    Python/JSON list of strings, the first nonempty proof is used deterministically;
    ordinary mathematical text is preserved verbatim.
    """

    text = str(value or "").strip()
    if not (text.startswith("[") and text.endswith("]")):
        return text
    try:
        parsed = ast.literal_eval(text)
    except (SyntaxError, ValueError):
        return text
    if isinstance(parsed, list) and parsed and all(isinstance(item, str) for item in parsed):
        proofs = [item.strip() for item in parsed if item.strip()]
        if proofs:
            return proofs[0]
    return text


def is_export_eligible(problem: Problem) -> bool:
    """Whether a problem may be used as an SFT positive.

    Official/human competition rows are trusted source material.  Synthetic rows
    must have passed both independent verification and human acceptance.
    """

    if problem.source != ProblemSource.SYNTHETIC:
        return True
    return (
        problem.verified is True
        and problem.review_status == ReviewStatus.ACCEPTED
    )


def deduplicated_training_problems(session) -> list[Problem]:
    """Return deterministic, train-only problems with no eval overlap or duplicates.

    Exact duplicates use the normalized statement hash.  When a future fuzzy pass
    assigns ``dedup_group_id``, only one row from that group is retained as well.
    """

    eval_rows = session.exec(
        select(Problem).where(
            (Problem.split == DataSplit.EVAL) | (Problem.frozen == True)  # noqa: E712
        )
    ).all()
    eval_hashes = {
        p.statement_hash or statement_hash(p.statement)
        for p in eval_rows
        if p.statement
    }
    eval_canonical_hashes = {
        canonical_statement_hash(p.statement) for p in eval_rows if p.statement
    }

    candidates = session.exec(db.training_problems_select()).all()
    (
        excluded_for_eval,
        manual_group_by_id,
        quarantine_all,
        manual_keeper_by_group,
    ) = _manual_dedup_rules()
    # Prefer official/human rows if malformed future data introduces duplicates.
    candidates.sort(
        key=lambda p: (
            p.source == ProblemSource.SYNTHETIC,
            not bool((p.provenance or {}).get("quality")),
            not bool((p.provenance or {}).get("crux")),
            p.id,
        )
    )

    kept: list[Problem] = []
    seen_hashes: set[str] = set()
    seen_canonical_hashes: set[str] = set()
    seen_groups: set[str] = set()
    seen_manual_groups: set[str] = set()
    for problem in candidates:
        if problem.id in excluded_for_eval or problem.id in quarantine_all:
            continue
        manual_group = manual_group_by_id.get(problem.id)
        explicit_keeper = manual_keeper_by_group.get(manual_group or "")
        if explicit_keeper is not None and problem.id != explicit_keeper:
            continue
        if manual_group and manual_group in seen_manual_groups:
            continue
        digest = problem.statement_hash or statement_hash(problem.statement)
        canonical_digest = canonical_statement_hash(problem.statement)
        if (
            digest in eval_hashes
            or digest in seen_hashes
            or canonical_digest in eval_canonical_hashes
            or canonical_digest in seen_canonical_hashes
        ):
            continue
        if problem.dedup_group_id and problem.dedup_group_id in seen_groups:
            continue
        kept.append(problem)
        seen_hashes.add(digest)
        seen_canonical_hashes.add(canonical_digest)
        if problem.dedup_group_id:
            seen_groups.add(problem.dedup_group_id)
        if manual_group:
            seen_manual_groups.add(manual_group)
    return kept


def preferred_solution(problem: Problem, solutions: Iterable[Solution]) -> Optional[Solution]:
    """Choose the strongest complete solution deterministically.

    Official and human solutions dominate.  For corrected synthetic problems, the
    explicitly backfilled model solution is preferred over short solver stubs. For
    V2 combinations, only the generator proof tied to the originating combo job gets
    that preference. Otherwise an independent solver-panel solution precedes model
    solutions.
    """

    rows = [s for s in solutions if s.problem_id == problem.id and (s.text or "").strip()]
    if not rows:
        return None

    provenance = problem.provenance or {}
    prefer_backfilled = bool(provenance.get("solution_backfilled"))
    combo_job_id = (
        str(provenance.get("combo_job_id") or "")
        if provenance.get("prefer_generator_solution")
        else ""
    )

    def priority(solution: Solution) -> int:
        if solution.source is SolutionSource.OFFICIAL:
            return 0
        if solution.source is SolutionSource.HUMAN:
            return 1
        if solution.source is SolutionSource.MODEL and (
            prefer_backfilled
            or (
                combo_job_id
                and str((solution.features or {}).get("combo_job_id") or "")
                == combo_job_id
            )
        ):
            return 2
        return {
            SolutionSource.SOLVER_PANEL: 3,
            SolutionSource.MODEL: 4,
            SolutionSource.TEACHER: 5,
        }.get(solution.source, 99)

    return min(
        rows,
        key=lambda s: (priority(s), -len(s.text or ""), s.id or 0),
    )


def techniques_for(problem: Problem, solution: Optional[Solution]) -> list[str]:
    """Return stable, de-duplicated technique identifiers for a training seed."""

    provenance = problem.provenance or {}
    # Generator-required techniques are immutable task conditioning.  Later
    # taxonomy audits write ``inferred_techniques`` and must not overwrite them.
    raw = (
        provenance.get("required_techniques")
        or provenance.get("inferred_techniques")
        or provenance.get("techniques")
        or []
    )
    if not raw and solution is not None:
        raw = solution.techniques or []
    if isinstance(raw, str):
        raw = [raw]
    return list(dict.fromkeys(str(x).strip() for x in raw if str(x).strip()))


def audit_export_records(session, records: list[dict]) -> dict[str, Any]:
    """Audit JSONL chat records against the database's split and validity state."""

    ids = [str((row.get("meta") or {}).get("id") or "") for row in records]
    duplicate_ids = sorted(pid for pid, n in Counter(ids).items() if pid and n > 1)
    problems = {p.id: p for p in session.exec(select(Problem)).all()}

    missing_ids: list[str] = []
    non_train_ids: list[str] = []
    frozen_ids: list[str] = []
    invalid_answer_ids: list[str] = []
    unverified_synthetic_ids: list[str] = []
    (
        excluded_for_eval,
        manual_group_by_id,
        quarantine_all,
        manual_keeper_by_group,
    ) = _manual_dedup_rules()
    manual_counts: Counter[str] = Counter()
    quarantined_ids: list[str] = []
    statement_counts: Counter[str] = Counter()
    canonical_statement_counts: Counter[str] = Counter()
    for pid in ids:
        problem = problems.get(pid)
        if problem is None:
            missing_ids.append(pid)
            continue
        statement_counts[problem.statement_hash or statement_hash(problem.statement)] += 1
        canonical_statement_counts[canonical_statement_hash(problem.statement)] += 1
        if problem.split != DataSplit.TRAIN:
            non_train_ids.append(pid)
        if problem.frozen:
            frozen_ids.append(pid)
        if normalize_aime_answer(problem.answer) is None:
            invalid_answer_ids.append(pid)
        if problem.source == ProblemSource.SYNTHETIC and not is_export_eligible(problem):
            unverified_synthetic_ids.append(pid)
        manual_group = manual_group_by_id.get(pid)
        if manual_group:
            manual_counts[manual_group] += 1
        explicit_keeper = manual_keeper_by_group.get(manual_group or "")
        if (
            pid in excluded_for_eval
            or pid in quarantine_all
            or (explicit_keeper is not None and pid != explicit_keeper)
        ):
            quarantined_ids.append(pid)

    duplicate_statement_hashes = sorted(
        digest for digest, n in statement_counts.items() if n > 1
    )
    duplicate_canonical_hashes = sorted(
        digest for digest, n in canonical_statement_counts.items() if n > 1
    )
    report = {
        "rows": len(records),
        "unique_ids": len(set(ids)),
        "duplicate_ids": sorted(set(duplicate_ids)),
        "duplicate_statement_hashes": duplicate_statement_hashes,
        "duplicate_canonical_hashes": duplicate_canonical_hashes,
        "missing_ids": sorted(set(missing_ids)),
        "non_train_ids": sorted(set(non_train_ids)),
        "frozen_ids": sorted(set(frozen_ids)),
        "invalid_aime_answer_ids": sorted(set(invalid_answer_ids)),
        "unverified_synthetic_ids": sorted(set(unverified_synthetic_ids)),
        "manual_duplicate_groups": sorted(
            group for group, count in manual_counts.items() if count > 1
        ),
        "quarantined_ids": sorted(set(quarantined_ids)),
    }
    report["ok"] = not any(
        report[key]
        for key in (
            "duplicate_ids",
            "duplicate_statement_hashes",
            "duplicate_canonical_hashes",
            "missing_ids",
            "non_train_ids",
            "frozen_ids",
            "invalid_aime_answer_ids",
            "unverified_synthetic_ids",
            "manual_duplicate_groups",
            "quarantined_ids",
        )
    )
    return report
