"""Report operational efficiency for one durable combination-generator run.

Examples:
  PYTHONPATH=src python scripts/report_combination_efficiency.py \
    --run-id combo-creativity-canary-20260712-v4 --profile confirmation-3
  PYTHONPATH=src python scripts/report_combination_efficiency.py \
    --run-id combo-v2-pilot --profile pilot-5 --strict
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mathforge.combo_efficiency import (
    EFFICIENCY_PROFILES,
    combination_efficiency_report,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--profile", choices=sorted(EFFICIENCY_PROFILES), default="pilot-5"
    )
    parser.add_argument("--db-url", default=None)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="default: output/combination_efficiency/<run-id>.json",
    )
    parser.add_argument(
        "--strict", action="store_true", help="exit nonzero when any gate fails"
    )
    args = parser.parse_args()

    report = combination_efficiency_report(
        args.run_id, db_url=args.db_url, profile=args.profile
    )
    output = args.output or Path("output/combination_efficiency") / (
        args.run_id + ".json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    totals = report["totals"]
    state = "PASS" if report["overall_pass"] else "FAIL"
    failed_share_note = (
        ""
        if totals["failed_call_token_attribution_complete"]
        else " (lower bound; attribution incomplete)"
    )
    print(
        f"{state} {args.run_id} ({args.profile}): "
        f"jobs={totals['jobs']} stored={totals['stored']} "
        f"rejected={totals['rejected']} exhausted={totals['exhausted']} "
        f"pending={totals['pending']}"
    )
    print(
        f"calls={totals['calls']} retries={totals['retry_calls']} "
        f"tokens={totals['total_tokens']} failed_share="
        f"{100 * totals['failed_call_token_share']:.1f}%{failed_share_note} "
        f"max_stops={totals['max_token_stops']} "
        f"model_minutes={totals['model_minutes']:.1f}"
    )
    print(
        f"deep coverage: compose={totals['compose_jobs']} "
        f"blind={totals['blind_audit_jobs']} novelty={totals['novelty_audit_jobs']}"
    )
    novelty = report["novelty"]
    coverage = (
        "n/a"
        if novelty["coverage"] is None
        else f"{100 * novelty['coverage']:.1f}%"
    )
    print(
        f"auditability={report['auditability']['mode']} novelty_rounds="
        f"{novelty['audited_rounds']}/{novelty['required_rounds']} "
        f"coverage={coverage}"
    )
    if report["failed_gates"]:
        print("failed gates: " + ", ".join(report["failed_gates"]))
    print(f"wrote {output}")
    if args.strict and not report["overall_pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
