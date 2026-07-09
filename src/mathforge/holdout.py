"""Freeze and protect the held-out evaluation split.

The eval set is frozen **once** and recorded in an immutable manifest
(``eval/frozen_eval_v1.json`` by default). It consists of:

* the 90 problems of the 2024-2026 AIME I & II, and
* 150 Omni-MATH problems selected to span distinct difficulty bands and topics.

Everything in the eval split is marked ``split=eval`` and ``frozen=True`` so the
upstream pipeline (which must query via :func:`mathforge.db.training_problems_select`)
can never train or generate on it. The manifest stores full content plus an
integrity hash, so the exact eval set can always be verified/rehydrated.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from sqlmodel import select

from mathforge import db
from mathforge.datasets import load_aime_eval, load_omni_math, omni_row_to_records
from mathforge.schema import (
    DataSplit,
    Problem,
    ProblemSource,
    Solution,
    SolutionSource,
    difficulty_band,
    statement_hash,
    utcnow,
)

__all__ = [
    "MANIFEST_VERSION",
    "default_manifest_path",
    "FreezeReport",
    "freeze_eval",
    "load_manifest",
    "verify_manifest",
    "select_omni_eval_ids",
]

MANIFEST_VERSION = 1
_EXCLUDED_TOPICS = {"Unknown", "Other"}


def default_manifest_path() -> Path:
    return Path("eval") / f"frozen_eval_v{MANIFEST_VERSION}.json"


@dataclass
class FreezeReport:
    aime: int = 0
    omni: int = 0
    manifest_path: str = ""
    integrity_sha256: str = ""
    per_topic: dict[str, int] = field(default_factory=dict)
    per_band: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return self.aime + self.omni


# --------------------------------------------------------------------------- #
# Deterministic Omni-MATH eval selection (stratified by topic x difficulty band)
# --------------------------------------------------------------------------- #
def select_omni_eval_ids(session, n: int = 150) -> list[str]:
    """Pick ``n`` TRAIN Omni-MATH problem ids spread over topics and bands.

    Deterministic: strata are visited in sorted order and, within a stratum,
    problems are taken in sorted-id order. No randomness -> reproducible freeze.
    """
    rows = session.exec(
        select(Problem.id, Problem.topic, Problem.difficulty).where(
            Problem.split == DataSplit.TRAIN,
            Problem.frozen == False,  # noqa: E712
            Problem.source == ProblemSource.OTHER_COMPETITION,
        )
    ).all()

    strata: dict[tuple[str, str], list[str]] = defaultdict(list)
    for pid, topic, diff in rows:
        band = difficulty_band(diff)
        if topic in _EXCLUDED_TOPICS or topic is None or band is None:
            continue
        # only Omni rows carry the "omni-math-" id prefix
        if not pid.startswith("omni-math-"):
            continue
        strata[(topic, band)].append(pid)

    for key in strata:
        strata[key].sort(key=_omni_sort_key)

    ordered_keys = sorted(strata.keys())
    selected: list[str] = []
    cursors = {k: 0 for k in ordered_keys}
    # Round-robin across strata until we have n (or exhaust everything).
    progress = True
    while len(selected) < n and progress:
        progress = False
        for key in ordered_keys:
            if len(selected) >= n:
                break
            c = cursors[key]
            if c < len(strata[key]):
                selected.append(strata[key][c])
                cursors[key] = c + 1
                progress = True
    return selected


def _omni_sort_key(pid: str):
    # "omni-math-123" -> 123 for stable numeric ordering
    try:
        return int(pid.rsplit("-", 1)[1])
    except (ValueError, IndexError):
        return pid


# --------------------------------------------------------------------------- #
# AIME eval ingestion
# --------------------------------------------------------------------------- #
def _ingest_aime_eval(session, now: datetime) -> int:
    existing = set(session.exec(select(Problem.id)).all())
    added = 0
    for rec in load_aime_eval():
        pid = f"aime-{rec['year']}-{rec['round']}-{rec['number']}"
        if pid in existing:
            continue
        problem = Problem(
            id=pid,
            source=ProblemSource.AIME,
            statement=rec["statement"],
            answer=rec["answer"],
            topic=None,
            split=DataSplit.EVAL,
            frozen=True,
            frozen_at=now,
            provenance={
                "dataset": rec["dataset"],
                "competition": f"{rec['year']} AIME {rec['round']}",
                "year": rec["year"],
                "round": rec["round"],
                "number": rec["number"],
            },
        ).refresh_dedup_fields()
        session.add(problem)
        existing.add(pid)
        added += 1
    return added


# --------------------------------------------------------------------------- #
# Freeze
# --------------------------------------------------------------------------- #
def freeze_eval(
    n_omni: int = 150,
    db_url: Optional[str] = None,
    manifest_path: Optional[Path] = None,
    force: bool = False,
) -> FreezeReport:
    """Freeze the eval split and write the immutable manifest.

    Raises if the manifest already exists (unless ``force=True``) to protect the
    freeze from being silently overwritten.
    """
    path = Path(manifest_path) if manifest_path else default_manifest_path()
    if path.exists() and not force:
        raise FileExistsError(
            f"eval manifest already frozen at {path}; refuse to overwrite "
            "(pass force=True to re-freeze intentionally)"
        )

    db.init_db(db_url)
    now = utcnow()
    report = FreezeReport(manifest_path=str(path))

    with db.session_scope(db_url) as session:
        # 1) AIME eval (90).
        report.aime = _ingest_aime_eval(session, now)

        # 2) 150 stratified Omni-MATH problems -> eval + frozen.
        omni_ids = select_omni_eval_ids(session, n=n_omni)
        if len(omni_ids) < n_omni:
            raise RuntimeError(
                f"only {len(omni_ids)} Omni-MATH TRAIN problems available for eval "
                f"selection (need {n_omni}); run `ingest omni-math` first."
            )
        for pid in omni_ids:
            problem = session.get(Problem, pid)
            problem.split = DataSplit.EVAL
            problem.frozen = True
            problem.frozen_at = now
            session.add(problem)
        report.omni = len(omni_ids)

        session.commit()

        # 3) Build manifest from every eval problem now in the DB.
        eval_problems = session.exec(
            select(Problem).where(Problem.split == DataSplit.EVAL)
        ).all()
        entries = [_manifest_entry(p) for p in eval_problems]

    entries.sort(key=lambda e: e["id"])
    for e in entries:
        if e["source"] == ProblemSource.AIME.value:
            continue
        report.per_topic[e["topic"] or "Unknown"] = (
            report.per_topic.get(e["topic"] or "Unknown", 0) + 1
        )
        band = e["difficulty_band"] or "?"
        report.per_band[band] = report.per_band.get(band, 0) + 1

    integrity = _integrity_hash(entries)
    report.integrity_sha256 = integrity

    manifest = {
        "version": MANIFEST_VERSION,
        "frozen_at": now.isoformat(),
        "counts": {"aime": report.aime, "omni": report.omni, "total": len(entries)},
        "integrity_sha256": integrity,
        "sources": {
            "aime": ["2024/2025/2026 AIME I & II"],
            "omni": "KbsdJames/Omni-MATH (stratified by topic x difficulty band)",
        },
        "problems": entries,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def _manifest_entry(p: Problem) -> dict[str, Any]:
    return {
        "id": p.id,
        "source": p.source.value,
        "split": p.split.value,
        "statement": p.statement,
        "answer": p.answer,
        "difficulty": p.difficulty,
        "difficulty_band": difficulty_band(p.difficulty),
        "topic": p.topic,
        "statement_hash": p.statement_hash,
        "provenance": p.provenance,
    }


def _integrity_hash(entries: list[dict[str, Any]]) -> str:
    """Stable hash over (id, statement_hash, answer) of the sorted eval set."""
    core = [
        [e["id"], e["statement_hash"], e["answer"]]
        for e in sorted(entries, key=lambda e: e["id"])
    ]
    blob = json.dumps(core, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# Verification
# --------------------------------------------------------------------------- #
def load_manifest(manifest_path: Optional[Path] = None) -> dict[str, Any]:
    path = Path(manifest_path) if manifest_path else default_manifest_path()
    return json.loads(path.read_text(encoding="utf-8"))


def verify_manifest(
    db_url: Optional[str] = None, manifest_path: Optional[Path] = None
) -> dict[str, Any]:
    """Check the DB eval split matches the frozen manifest. Returns a report."""
    manifest = load_manifest(manifest_path)
    entries = manifest["problems"]

    recomputed = _integrity_hash(entries)
    problems_issues: list[str] = []

    db.init_db(db_url)
    with db.session_scope(db_url) as session:
        for e in entries:
            p = session.get(Problem, e["id"])
            if p is None:
                problems_issues.append(f"missing in DB: {e['id']}")
                continue
            if p.split != DataSplit.EVAL or not p.frozen:
                problems_issues.append(f"not frozen-eval in DB: {e['id']}")
            if statement_hash(p.statement) != e["statement_hash"]:
                problems_issues.append(f"statement changed: {e['id']}")

    return {
        "ok": recomputed == manifest["integrity_sha256"] and not problems_issues,
        "integrity_matches": recomputed == manifest["integrity_sha256"],
        "manifest_integrity": manifest["integrity_sha256"],
        "recomputed_integrity": recomputed,
        "count": len(entries),
        "issues": problems_issues,
    }
