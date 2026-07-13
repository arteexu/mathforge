"""Audit training JSONL files against the DB and frozen eval boundary.

The command exits non-zero on any hard violation and writes a machine-readable
report to ``data/data_integrity_report.json``.

Usage: ``PYTHONPATH=src python scripts/audit_data_integrity.py [jsonl ...]``
"""

from __future__ import annotations

import json
import hashlib
import sys
from collections import Counter
from pathlib import Path

from sqlmodel import select

from mathforge import db
from mathforge.integrity import audit_export_records, canonical_statement_hash
from mathforge.schema import Problem, statement_hash

DEFAULT_PATHS = [
    Path("data/train.jsonl"),
    Path("data/train_pt.jsonl"),
    Path("data/train_elegant.jsonl"),
    Path("data/train_creative.jsonl"),
]
REPORT_PATH = Path("data/data_integrity_report.json")


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
        # Plain prompt/completion exports use the same metadata and audit rules.
        rows.append(row)
    return rows


def main() -> None:
    paths = [Path(value) for value in sys.argv[1:]] or DEFAULT_PATHS
    db.init_db()
    report: dict = {"database": {}, "exports": {}}

    with db.session_scope() as session:
        problems = session.exec(select(Problem)).all()
        raw_hashes = [p.statement_hash or statement_hash(p.statement) for p in problems]
        canonical_hashes = [canonical_statement_hash(p.statement) for p in problems]
        canonical_counts = Counter(canonical_hashes)
        report["database"] = {
            "problems": len(problems),
            "unique_statement_hashes": len(set(raw_hashes)),
            "canonical_duplicate_groups": sum(count > 1 for count in canonical_counts.values()),
            "canonical_duplicate_extra_rows": sum(count - 1 for count in canonical_counts.values() if count > 1),
            "reviewed_dedup_rows": sum(bool(p.dedup_group_id) for p in problems),
            "reviewed_dedup_groups": len({p.dedup_group_id for p in problems if p.dedup_group_id}),
            "frozen": sum(bool(p.frozen) for p in problems),
            "eval": sum(p.split.value == "eval" for p in problems),
        }

        all_ok = True
        for path in paths:
            if not path.exists():
                report["exports"][str(path)] = {"ok": False, "error": "missing file"}
                all_ok = False
                continue
            try:
                rows = _read_jsonl(path)
                result = audit_export_records(session, rows)
                result["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            except Exception as exc:  # noqa: BLE001
                result = {"ok": False, "error": str(exc)}
            report["exports"][str(path)] = result
            all_ok = all_ok and bool(result.get("ok"))

    report["ok"] = all_ok
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    for path, result in report["exports"].items():
        status = "PASS" if result.get("ok") else "FAIL"
        print(f"{status} {path}: rows={result.get('rows', '?')} unique={result.get('unique_ids', '?')}")
        if not result.get("ok"):
            for key, value in result.items():
                if key in {"ok", "rows", "unique_ids"} or not value:
                    continue
                count = len(value) if isinstance(value, list) else value
                print(f"  {key}: {count}")
    print(f"wrote {REPORT_PATH}")
    if not all_ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
