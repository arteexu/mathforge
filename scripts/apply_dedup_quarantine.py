"""Apply reviewed duplicate-group metadata to TRAIN rows without deleting data.

Frozen eval rows are never mutated.  The DB remains a provenance archive while
exporters use these groups plus the versioned manifest to emit one safe master.
"""

from __future__ import annotations

import json
from pathlib import Path

from mathforge import db
from mathforge.schema import DataSplit, Problem

MANIFEST = Path("eval/dedup_quarantine_v1.json")


def main() -> None:
    rules = json.loads(MANIFEST.read_text(encoding="utf-8"))
    updated = missing = 0
    with db.session_scope() as session:
        for group in rules.get("cross_split", []):
            eval_id = group["eval_id"]
            group_id = f"eval-duplicate:{eval_id}"
            for problem_id in group.get("train_ids", []):
                problem = session.get(Problem, problem_id)
                if problem is None:
                    missing += 1
                    continue
                if problem.split != DataSplit.TRAIN or problem.frozen:
                    raise ValueError(
                        f"refusing to apply train duplicate metadata to non-TRAIN/frozen row {problem_id}"
                    )
                provenance = dict(problem.provenance or {})
                integrity = dict(provenance.get("integrity") or {})
                integrity.update({"duplicate_of_eval": eval_id, "reviewed_manifest": rules["version"]})
                provenance["integrity"] = integrity
                problem.provenance = provenance
                problem.dedup_group_id = group_id
                session.add(problem)
                updated += 1

        for group in rules.get("train_groups", []):
            group_id = f"train-duplicate:{group['id']}"
            members = group.get("members", [])
            keeper_id = group.get("keeper_id")
            crux_source_id = group.get("keeper_crux_from_id")
            if keeper_id is not None and keeper_id not in members:
                raise ValueError(
                    f"group {group['id']!r} keeper_id {keeper_id!r} is not a member"
                )
            if crux_source_id is not None:
                if keeper_id is None:
                    raise ValueError(
                        f"group {group['id']!r} has keeper_crux_from_id without keeper_id"
                    )
                if crux_source_id not in members:
                    raise ValueError(
                        f"group {group['id']!r} keeper_crux_from_id "
                        f"{crux_source_id!r} is not a member"
                    )
                crux_source = session.get(Problem, crux_source_id)
                if crux_source is None:
                    missing += 1
                    source_crux = None
                else:
                    source_crux = (crux_source.provenance or {}).get("crux")
                    if not str(source_crux or "").strip():
                        raise ValueError(
                            f"group {group['id']!r} crux source {crux_source_id!r} "
                            "has no crux"
                        )
            else:
                source_crux = None
            for problem_id in members:
                problem = session.get(Problem, problem_id)
                if problem is None:
                    missing += 1
                    continue
                if problem.split != DataSplit.TRAIN or problem.frozen:
                    raise ValueError(
                        f"refusing to apply train duplicate metadata to non-TRAIN/frozen row {problem_id}"
                    )
                provenance = dict(problem.provenance or {})
                integrity = dict(provenance.get("integrity") or {})
                integrity.update({
                    "reviewed_duplicate_group": group["id"],
                    "quarantine_all": bool(group.get("quarantine_all")),
                    "reviewed_manifest": rules["version"],
                })
                if keeper_id is not None:
                    integrity.update(
                        {
                            "duplicate_keeper": keeper_id,
                            "quarantined_duplicate": problem_id != keeper_id,
                        }
                    )
                if group.get("reason"):
                    integrity["duplicate_reason"] = group["reason"]
                if problem_id == keeper_id and crux_source_id is not None:
                    if "keeper_crux_override" not in integrity:
                        integrity["keeper_crux_override"] = {
                            "from_id": crux_source_id,
                            "original_crux": provenance.get("crux"),
                        }
                    provenance["crux"] = str(source_crux).strip()
                provenance["integrity"] = integrity
                problem.provenance = provenance
                problem.dedup_group_id = group_id
                session.add(problem)
                updated += 1

        if missing:
            raise RuntimeError(
                f"dedup manifest references {missing} missing problem row(s); no changes applied"
            )

    print(f"applied reviewed dedup metadata to {updated} TRAIN rows; missing={missing}")


if __name__ == "__main__":
    main()
