"""Dataset reporting: counts by source / difficulty band / topic (+ split).

``build_report`` returns a plain-dict snapshot (JSON-serializable) used by both
the ``mathforge report`` CLI command and the one-page data-report canvas.
"""

from __future__ import annotations

from typing import Optional

from sqlmodel import select

from mathforge import db
from mathforge.schema import (
    DataSplit,
    Evaluation,
    Problem,
    Solution,
    difficulty_band,
    utcnow,
)

__all__ = ["build_report"]


def _band_sort_key(band: str) -> tuple[int, float]:
    # "d7" -> (0, 7); "unrated" -> (1, inf)
    if band.startswith("d") and band[1:].isdigit():
        return (0, float(band[1:]))
    return (1, float("inf"))


def build_report(db_url: Optional[str] = None) -> dict:
    """Compute dataset counts grouped by source, difficulty band, and topic."""
    db.init_db(db_url)
    with db.session_scope(db_url) as session:
        problems = session.exec(select(Problem)).all()
        n_solutions = len(session.exec(select(Solution.id)).all())
        n_evaluations = len(session.exec(select(Evaluation.id)).all())

    def bucket() -> dict[str, int]:
        return {"total": 0, "train": 0, "eval": 0}

    by_source: dict[str, dict[str, int]] = {}
    by_band: dict[str, dict[str, int]] = {}
    by_topic: dict[str, dict[str, int]] = {}
    by_tier: dict[str, int] = {}
    totals = {"problems": 0, "train": 0, "eval": 0, "frozen": 0}

    aime_by_comp: dict[str, int] = {}
    omni_eval_by_topic: dict[str, int] = {}
    omni_eval_by_band: dict[str, int] = {}

    for p in problems:
        split = p.split.value if hasattr(p.split, "value") else str(p.split)
        totals["problems"] += 1
        totals[split] = totals.get(split, 0) + 1
        if p.frozen:
            totals["frozen"] += 1

        src = p.source.value if hasattr(p.source, "value") else str(p.source)
        band = difficulty_band(p.difficulty) or "unrated"
        topic = p.topic or "untagged"
        tier = p.tier.value if p.tier is not None else "unrated"

        for group, key in ((by_source, src), (by_band, band), (by_topic, topic)):
            b = group.setdefault(key, bucket())
            b["total"] += 1
            b[split] = b.get(split, 0) + 1
        by_tier[tier] = by_tier.get(tier, 0) + 1

        if split == DataSplit.EVAL.value:
            if src == "aime":
                comp = f"{p.provenance.get('year')} AIME {p.provenance.get('round')}"
                aime_by_comp[comp] = aime_by_comp.get(comp, 0) + 1
            else:
                omni_eval_by_topic[topic] = omni_eval_by_topic.get(topic, 0) + 1
                omni_eval_by_band[band] = omni_eval_by_band.get(band, 0) + 1

    def rows(group: dict[str, dict[str, int]], sort_key=None) -> list[dict]:
        keys = sorted(group, key=sort_key) if sort_key else sorted(
            group, key=lambda k: -group[k]["total"]
        )
        return [
            {"key": k, **group[k]} for k in keys
        ]

    return {
        "generated_at": utcnow().isoformat(),
        "totals": {
            **totals,
            "solutions": n_solutions,
            "evaluations": n_evaluations,
        },
        "by_source": rows(by_source),
        "by_band": rows(by_band, sort_key=_band_sort_key),
        "by_topic": rows(by_topic),
        "by_tier": [
            {"key": k, "count": by_tier[k]}
            for k in sorted(by_tier, key=lambda k: -by_tier[k])
        ],
        "eval": {
            "aime_by_competition": [
                {"key": k, "count": aime_by_comp[k]} for k in sorted(aime_by_comp)
            ],
            "omni_by_topic": [
                {"key": k, "count": omni_eval_by_topic[k]}
                for k in sorted(omni_eval_by_topic, key=lambda k: -omni_eval_by_topic[k])
            ],
            "omni_by_band": [
                {"key": k, "count": omni_eval_by_band[k]}
                for k in sorted(omni_eval_by_band, key=_band_sort_key)
            ],
        },
    }
