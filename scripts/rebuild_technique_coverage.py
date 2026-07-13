"""Rebuild technique coverage from stored TRAIN-only tags without new LLM calls.

Use this after split/integrity changes.  Frozen evaluation annotations are ignored,
so they cannot influence novelty sampling or published coverage statistics.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from mathforge import db

TECH_PATH = Path("data/techniques.json")
OUT_PATH = Path("data/technique_coverage.json")


def main() -> None:
    db.init_db()
    techniques = json.loads(TECH_PATH.read_text(encoding="utf-8"))
    valid_ids = {technique["id"] for technique in techniques}

    counts: Counter[str] = Counter()
    total_cruxes = tagged_cruxes = 0
    with db.session_scope() as session:
        for problem in session.exec(db.training_problems_select()).all():
            provenance = problem.provenance or {}
            if not provenance.get("crux"):
                continue
            total_cruxes += 1
            raw_tags = (
                provenance.get("inferred_techniques")
                or provenance.get("required_techniques")
                or provenance.get("techniques")
                or []
            )
            if isinstance(raw_tags, str):
                raw_tags = [raw_tags]
            tags = list(dict.fromkeys(tag for tag in raw_tags if tag in valid_ids))
            if tags:
                tagged_cruxes += 1
                counts.update(tags)

    for technique in techniques:
        technique["source_count"] = counts.get(technique["id"], 0)
    TECH_PATH.write_text(
        json.dumps(techniques, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    area = {technique["id"]: technique["area"] for technique in techniques}
    mechanism = {technique["id"]: technique.get("mechanism") for technique in techniques}
    covered = [technique["id"] for technique in techniques if counts[technique["id"]] > 0]
    gaps = [technique["id"] for technique in techniques if counts[technique["id"]] == 0]
    by_area = Counter()
    by_mechanism = Counter()
    for technique_id, count in counts.items():
        by_area[area[technique_id]] += count
        by_mechanism[mechanism[technique_id]] += count

    report = {
        "scope": "train_only_nonfrozen",
        "total_cruxes": total_cruxes,
        "tagged_cruxes": tagged_cruxes,
        "counts": dict(counts),
        "covered": covered,
        "gaps": gaps,
        "by_area": dict(by_area),
        "by_mechanism": dict(by_mechanism),
    }
    OUT_PATH.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"rebuilt TRAIN-only coverage: {len(covered)}/{len(techniques)} techniques; "
        f"{tagged_cruxes}/{total_cruxes} cruxes tagged -> {OUT_PATH}"
    )


if __name__ == "__main__":
    main()
