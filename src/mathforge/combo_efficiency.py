"""Operational efficiency audit for durable technique-combination runs."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import or_
from sqlmodel import select

from mathforge import db
from mathforge.combinations import (
    CORPUS_NOVELTY_GATE_V1,
    PIPELINE_V2,
    STAGE_EFFORT_POLICY,
    V2_GENERATOR_MAX_OUTPUT_TOKENS,
)
from mathforge.schema import (
    CombinationJob,
    CombinationJobStatus,
    LLMCall,
    statement_hash,
)

__all__ = [
    "EfficiencyThresholds",
    "EFFICIENCY_PROFILES",
    "combination_efficiency_report",
]


MODEL_FAILURE_KINDS = {"parse", "output_exhausted"}
MAX_TOKEN_REASONS = {"max_tokens", "length", "max_output_tokens"}
TERMINAL_STATUSES = {
    CombinationJobStatus.STORED,
    CombinationJobStatus.REJECTED,
    CombinationJobStatus.EXHAUSTED,
}


@dataclass(frozen=True)
class EfficiencyThresholds:
    expected_jobs: int
    max_exhausted: int = 0
    max_pending: int = 0
    max_manual_retry_resets: int = 0
    max_stale_lease_recoveries: int = 0
    max_max_token_stops: int = 1
    max_parse_failures: int = 2
    max_output_exhausted_failures: int = 1
    max_transport_failures: int = 0
    max_internal_failures: int = 0
    max_failed_call_token_share: float = 0.15
    max_total_tokens: int = 650_000
    min_compose_jobs: int = 2
    min_blind_audit_jobs: int = 2
    max_missing_call_ids: int = 0
    max_unlinked_calls: int = 0
    max_lineage_mismatches: int = 0
    max_unattributed_failure_events: int = 0
    require_pilot_v2_config: bool = False
    require_novelty_gate: bool = True
    min_novelty_required_rounds: int = 1
    min_novelty_coverage: float = 1.0
    max_novelty_storage_bypasses: int = 0


EFFICIENCY_PROFILES: dict[str, EfficiencyThresholds] = {
    "pilot-5": EfficiencyThresholds(
        expected_jobs=5,
        require_pilot_v2_config=True,
    ),
    "confirmation-3": EfficiencyThresholds(
        expected_jobs=3,
        max_parse_failures=1,
        max_transport_failures=0,
        max_total_tokens=400_000,
        min_compose_jobs=1,
        min_blind_audit_jobs=1,
        min_novelty_required_rounds=0,
        require_novelty_gate=False,
        min_novelty_coverage=0.0,
    ),
}


def _iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _stop_reason(call: LLMCall) -> Optional[str]:
    meta = call.meta if isinstance(call.meta, dict) else {}
    raw = meta.get("stop_reason") or meta.get("finish_reason")
    if raw is None:
        return None
    normalized = str(raw).strip().lower()
    return normalized or None


def _call_stage(call: LLMCall, reverse_call_stage: dict[int, str]) -> str:
    meta = call.meta if isinstance(call.meta, dict) else {}
    stage = str(meta.get("stage") or "").strip()
    return stage or reverse_call_stage.get(int(call.id or 0), "unattributed")


def _quality_passed(verdict: Any) -> bool:
    if not isinstance(verdict, dict):
        return False
    if verdict.get("computed_quality_pass") is True:
        return True
    return bool(
        verdict.get("verdict") == "accept"
        and verdict.get("computed_quality_pass", True) is True
    )


def _json_hash(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _novelty_round_records(
    job: CombinationJob, successful_call_ids: set[int]
) -> list[dict[str, Any]]:
    """Return every round that crossed the quality gate and required novelty."""
    design = dict(job.design_artifacts or {})
    preflights = dict(design.get("preflights") or {})
    drafts = dict(design.get("drafts") or {})
    retrievals = dict(design.get("novelty_neighbors") or {})
    audits = dict(design.get("novelty_audits") or {})
    records: list[dict[str, Any]] = []
    for round_name in ("initial", "revised"):
        preflight = preflights.get(round_name)
        if not _quality_passed(preflight):
            continue
        issues: list[str] = []
        draft = drafts.get(round_name)
        draft_statement = (
            str(draft.get("statement") or "") if isinstance(draft, dict) else ""
        )
        if not draft_statement:
            issues.append("missing_round_draft")
        expected_statement_hash = (
            statement_hash(draft_statement) if draft_statement else None
        )

        retrieval = retrievals.get(round_name)
        retrieval_present = isinstance(retrieval, dict) and bool(retrieval)
        retrieval_valid = retrieval_present
        if not retrieval_present:
            issues.append("missing_retrieval")
        else:
            if retrieval.get("round") != round_name:
                retrieval_valid = False
                issues.append("retrieval_round_mismatch")
            if not list(retrieval.get("neighbors") or []):
                retrieval_valid = False
                issues.append("retrieval_has_no_neighbors")
            if retrieval.get("missing_evidence_ids"):
                retrieval_valid = False
                issues.append("retrieval_missing_pair_evidence")
            if (
                expected_statement_hash is None
                or retrieval.get("statement_hash") != expected_statement_hash
            ):
                retrieval_valid = False
                issues.append("retrieval_statement_mismatch")
            expected_retrieval_hash = _json_hash(
                {
                    key: value
                    for key, value in retrieval.items()
                    if key != "retrieval_hash"
                }
            )
            if retrieval.get("retrieval_hash") != expected_retrieval_hash:
                retrieval_valid = False
                issues.append("retrieval_hash_mismatch")

        audit = audits.get(round_name)
        audit_present = isinstance(audit, dict) and bool(audit)
        audit_stage = "novelty_audit_r1" if round_name == "revised" else "novelty_audit_r0"
        audit_call_present = any(
            int(call_id) in successful_call_ids
            for call_id in ((job.call_ids or {}).get(audit_stage) or [])
        )
        audit_valid = audit_present and audit_call_present and retrieval_valid
        if not audit_present:
            issues.append("missing_audit")
        if not audit_call_present:
            issues.append("missing_audit_call")
        if audit_present:
            if audit.get("round") != round_name:
                audit_valid = False
                issues.append("audit_round_mismatch")
            if (
                expected_statement_hash is None
                or audit.get("statement_hash") != expected_statement_hash
            ):
                audit_valid = False
                issues.append("audit_statement_mismatch")
            retrieval_hash = (
                retrieval.get("retrieval_hash")
                if isinstance(retrieval, dict)
                else None
            )
            if not retrieval_hash or audit.get("retrieval_hash") != retrieval_hash:
                audit_valid = False
                issues.append("audit_retrieval_mismatch")
        records.append(
            {
                "job_id": job.id,
                "ordinal": job.ordinal,
                "round": round_name,
                "retrieval_present": retrieval_present,
                "retrieved": retrieval_valid,
                "audit_present": audit_present,
                "audit_call_present": audit_call_present,
                "audited": audit_valid,
                "passed": bool(
                    audit_valid
                    and audit.get("computed_novelty_pass") is True
                ),
                "issues": issues,
            }
        )
    return records


def _gate(
    *,
    name: str,
    category: str,
    value: Any,
    operator: str,
    threshold: Any,
    passed: bool,
) -> dict[str, Any]:
    return {
        "name": name,
        "category": category,
        "value": value,
        "operator": operator,
        "threshold": threshold,
        "passed": bool(passed),
    }


def combination_efficiency_report(
    run_id: str,
    *,
    db_url: Optional[str] = None,
    profile: str = "pilot-5",
    thresholds: Optional[EfficiencyThresholds] = None,
) -> dict[str, Any]:
    """Build a reproducible efficiency report without mutating run state."""
    if profile not in EFFICIENCY_PROFILES and thresholds is None:
        raise ValueError(
            f"unknown efficiency profile {profile!r}; choose from "
            f"{sorted(EFFICIENCY_PROFILES)}"
        )
    policy = thresholds or EFFICIENCY_PROFILES[profile]
    db.init_db(db_url)
    with db.session_scope(db_url) as session:
        jobs = session.exec(
            select(CombinationJob)
            .where(CombinationJob.run_id == run_id)
            .order_by(CombinationJob.ordinal)
        ).all()
        if not jobs:
            raise ValueError(f"combination run not found: {run_id}")
        job_ids = [job.id for job in jobs]
        call_references: dict[int, list[tuple[str, str]]] = defaultdict(list)
        for job in jobs:
            for stage, raw_ids in (job.call_ids or {}).items():
                for raw_id in raw_ids or []:
                    call_references[int(raw_id)].append((job.id, str(stage)))
        declared_call_ids = list(call_references)
        call_filter = LLMCall.related_id.in_(job_ids)
        if declared_call_ids:
            call_filter = or_(call_filter, LLMCall.id.in_(declared_call_ids))
        calls = session.exec(
            select(LLMCall).where(call_filter).order_by(LLMCall.id)
        ).all()

    calls_by_id = {int(call.id): call for call in calls if call.id is not None}
    calls_by_job: dict[str, list[LLMCall]] = defaultdict(list)
    reverse_call_stage: dict[int, str] = {}
    missing_call_ids = sorted(set(call_references) - set(calls_by_id))
    lineage_mismatches: list[dict[str, Any]] = []
    for call_id, references in call_references.items():
        reverse_call_stage[call_id] = references[0][1]
        if len(references) > 1:
            lineage_mismatches.append(
                {
                    "call_id": call_id,
                    "kind": "duplicate_reference",
                    "references": [
                        {"job_id": job_id, "stage": stage}
                        for job_id, stage in references
                    ],
                }
            )
        call = calls_by_id.get(call_id)
        if call is None:
            continue
        meta = call.meta if isinstance(call.meta, dict) else {}
        for job_id, stage in references:
            if call.related_id != job_id:
                lineage_mismatches.append(
                    {
                        "call_id": call_id,
                        "kind": "related_id_mismatch",
                        "expected": job_id,
                        "actual": call.related_id,
                    }
                )
            meta_job_id = meta.get("combo_job_id")
            if meta_job_id is not None and str(meta_job_id) != job_id:
                lineage_mismatches.append(
                    {
                        "call_id": call_id,
                        "kind": "metadata_job_mismatch",
                        "expected": job_id,
                        "actual": str(meta_job_id),
                    }
                )
            meta_stage = str(meta.get("stage") or "").strip()
            if meta_stage and meta_stage != stage:
                lineage_mismatches.append(
                    {
                        "call_id": call_id,
                        "kind": "metadata_stage_mismatch",
                        "expected": stage,
                        "actual": meta_stage,
                    }
                )

    job_id_set = set(job_ids)
    unlinked_call_ids = sorted(
        int(call.id)
        for call in calls
        if call.id is not None
        and call.related_id in job_id_set
        and int(call.id) not in call_references
    )
    for call in calls:
        related_id = str(call.related_id or "")
        if related_id in job_id_set:
            calls_by_job[related_id].append(call)
        elif call.id is not None and int(call.id) in call_references:
            calls_by_job[call_references[int(call.id)][0][0]].append(call)

    failed_call_ids: set[int] = set()
    unattributed_failure_events = 0
    failure_kind_counts: Counter[str] = Counter()
    for job in jobs:
        failures_by_stage: Counter[str] = Counter()
        for failure in job.failures or []:
            kind = str(failure.get("kind") or "unknown")
            stage = str(failure.get("stage") or "unattributed")
            failure_kind_counts[kind] += 1
            if kind in MODEL_FAILURE_KINDS:
                failures_by_stage[stage] += 1
        for stage, failure_count in failures_by_stage.items():
            stage_ids = [
                int(value) for value in ((job.call_ids or {}).get(stage) or [])
            ]
            for index in range(failure_count):
                if index >= len(stage_ids):
                    unattributed_failure_events += 1
                    continue
                call_id = stage_ids[index]
                if call_id not in calls_by_id:
                    unattributed_failure_events += 1
                    continue
                failed_call_ids.add(call_id)

    unlinked_call_id_set = set(unlinked_call_ids)
    stage_rows: dict[str, dict[str, Any]] = {}
    for call in calls:
        stage = _call_stage(call, reverse_call_stage)
        row = stage_rows.setdefault(
            stage,
            {
                "stage": stage,
                "calls": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "model_minutes": 0.0,
                "cost_usd": 0.0,
                "max_token_stops": 0,
                "failed_calls": 0,
                "failed_call_tokens": 0,
                "unlinked_calls": 0,
                "unlinked_call_tokens": 0,
                "efforts": Counter(),
                "first_call_id": int(call.id or 0),
            },
        )
        row["calls"] += 1
        row["prompt_tokens"] += int(call.prompt_tokens or 0)
        row["completion_tokens"] += int(call.completion_tokens or 0)
        row["total_tokens"] += int(call.total_tokens or 0)
        row["model_minutes"] += float(call.latency_ms or 0.0) / 60_000.0
        row["cost_usd"] += float(call.cost_usd or 0.0)
        if _stop_reason(call) in MAX_TOKEN_REASONS:
            row["max_token_stops"] += 1
        if int(call.id or 0) in failed_call_ids:
            row["failed_calls"] += 1
            row["failed_call_tokens"] += int(call.total_tokens or 0)
        if int(call.id or 0) in unlinked_call_id_set:
            row["unlinked_calls"] += 1
            row["unlinked_call_tokens"] += int(call.total_tokens or 0)
        meta = call.meta if isinstance(call.meta, dict) else {}
        effort = str(meta.get("requested_effort") or "unknown")
        row["efforts"][effort] += 1

    stages = []
    for row in sorted(stage_rows.values(), key=lambda item: item["first_call_id"]):
        row = dict(row)
        row["model_minutes"] = round(row["model_minutes"], 3)
        row["cost_usd"] = round(row["cost_usd"], 6)
        row["efforts"] = dict(sorted(row["efforts"].items()))
        row.pop("first_call_id", None)
        stages.append(row)

    total_tokens = sum(int(call.total_tokens or 0) for call in calls)
    failed_call_tokens = sum(
        int(calls_by_id[call_id].total_tokens or 0)
        for call_id in failed_call_ids
        if call_id in calls_by_id
    )
    failed_share = failed_call_tokens / total_tokens if total_tokens else 0.0
    unlinked_call_tokens = sum(
        int(calls_by_id[call_id].total_tokens or 0)
        for call_id in unlinked_call_ids
        if call_id in calls_by_id
    )
    max_token_stops = sum(
        _stop_reason(call) in MAX_TOKEN_REASONS for call in calls
    )
    retry_calls = sum(
        max(0, len(raw_ids or []) - 1)
        for job in jobs
        for raw_ids in (job.call_ids or {}).values()
    )

    status_counts = Counter(job.status.value.lower() for job in jobs)
    pending = sum(job.status not in TERMINAL_STATUSES for job in jobs)
    compose_jobs = sum(
        any(
            stage == "compose" or stage.startswith("compose_")
            for stage in (job.call_ids or {})
        )
        for job in jobs
    )
    blind_jobs = sum(
        any(stage.startswith("blind_audit_r") for stage in (job.call_ids or {}))
        for job in jobs
    )
    novelty_jobs = sum(
        any(stage.startswith("novelty_audit_r") for stage in (job.call_ids or {}))
        for job in jobs
    )

    def config_counts(key: str) -> dict[str, int]:
        values = Counter(
            str((job.config or {}).get(key) or "<missing>") for job in jobs
        )
        return dict(sorted(values.items()))

    config_issues: list[dict[str, Any]] = []
    pilot_compatible_job_ids: set[str] = set()
    for job in jobs:
        config = dict(job.config or {})
        issues: list[str] = []
        if config.get("pipeline_version") != PIPELINE_V2:
            issues.append("pipeline_version")
        if config.get("effort_policy_version") != STAGE_EFFORT_POLICY:
            issues.append("effort_policy_version")
        if config.get("novelty_gate_version") != CORPUS_NOVELTY_GATE_V1:
            issues.append("novelty_gate_version")
        if (
            config.get("generator_max_output_tokens")
            != V2_GENERATOR_MAX_OUTPUT_TOKENS
        ):
            issues.append("generator_max_output_tokens")
        if issues:
            config_issues.append(
                {"job_id": job.id, "ordinal": job.ordinal, "fields": issues}
            )
        else:
            pilot_compatible_job_ids.add(job.id)
    auditability = {
        "mode": (
            "pilot_compatible"
            if len(pilot_compatible_job_ids) == len(jobs)
            else "legacy_or_nonpilot"
        ),
        "pilot_compatible_jobs": len(pilot_compatible_job_ids),
        "pipeline_versions": config_counts("pipeline_version"),
        "effort_policy_versions": config_counts("effort_policy_version"),
        "novelty_gate_versions": config_counts("novelty_gate_version"),
        "generator_max_output_tokens": config_counts(
            "generator_max_output_tokens"
        ),
        "issues": config_issues,
    }

    novelty_enabled_jobs = [
        job
        for job in jobs
        if (job.config or {}).get("novelty_gate_version")
        == CORPUS_NOVELTY_GATE_V1
    ]
    novelty_enabled_ids = {job.id for job in novelty_enabled_jobs}
    successful_call_id_set = set(calls_by_id) - failed_call_ids
    novelty_rounds_by_job = {
        job.id: (
            _novelty_round_records(job, successful_call_id_set)
            if job.id in novelty_enabled_ids
            else []
        )
        for job in jobs
    }
    novelty_rounds = [
        record
        for job in jobs
        for record in novelty_rounds_by_job[job.id]
    ]
    required_job_ids = {record["job_id"] for record in novelty_rounds}
    audited_job_ids = {
        record["job_id"] for record in novelty_rounds if record["audited"]
    }
    passing_job_ids = {
        record["job_id"] for record in novelty_rounds if record["passed"]
    }
    final_novelty_records: dict[str, Optional[dict[str, Any]]] = {}
    for job in novelty_enabled_jobs:
        final_round = (
            "revised"
            if int((job.design_artifacts or {}).get("regeneration_count") or 0)
            else "initial"
        )
        final_novelty_records[job.id] = next(
            (
                record
                for record in novelty_rounds_by_job[job.id]
                if record["round"] == final_round
            ),
            None,
        )
    audited_rounds = sum(bool(record["audited"]) for record in novelty_rounds)
    retrieved_rounds = sum(bool(record["retrieved"]) for record in novelty_rounds)
    passing_rounds = sum(bool(record["passed"]) for record in novelty_rounds)
    novelty_bypasses = [
        job.id
        for job in novelty_enabled_jobs
        if job.status is CombinationJobStatus.STORED
        and not bool(
            final_novelty_records.get(job.id)
            and final_novelty_records[job.id].get("passed") is True
        )
    ]
    novelty_coverage = (
        audited_rounds / len(novelty_rounds) if novelty_rounds else None
    )
    retrieval_coverage = (
        retrieved_rounds / len(novelty_rounds) if novelty_rounds else None
    )

    job_records = []
    for job in jobs:
        job_calls = calls_by_job.get(job.id, [])
        job_novelty_rounds = novelty_rounds_by_job[job.id]
        final_novelty_record = final_novelty_records.get(job.id)
        failures = Counter(
            str(item.get("kind") or "unknown") for item in (job.failures or [])
        )
        job_records.append(
            {
                "id": job.id,
                "ordinal": job.ordinal,
                "pair_key": job.pair_key,
                "status": job.status.value.lower(),
                "stage": job.stage,
                "problem_id": job.problem_id,
                "rejection_reason": job.rejection_reason,
                "calls": len(job_calls),
                "total_tokens": sum(int(call.total_tokens or 0) for call in job_calls),
                "retry_calls": sum(
                    max(0, len(raw_ids or []) - 1)
                    for raw_ids in (job.call_ids or {}).values()
                ),
                "failure_kinds": dict(sorted(failures.items())),
                "novelty_gate_enabled": job.id in novelty_enabled_ids,
                "novelty_required_rounds": [
                    record["round"] for record in job_novelty_rounds
                ],
                "novelty_audited_rounds": [
                    record["round"]
                    for record in job_novelty_rounds
                    if record["audited"]
                ],
                "novelty_audited": any(
                    record["audited"] for record in job_novelty_rounds
                ),
                "novelty_passed": bool(
                    final_novelty_record
                    and final_novelty_record.get("passed") is True
                ),
            }
        )

    failed_token_attribution_complete = not (
        failure_kind_counts["transport"]
        or failure_kind_counts["internal"]
        or failure_kind_counts["stale_lease_recovered"]
        or missing_call_ids
        or unlinked_call_ids
        or lineage_mismatches
        or unattributed_failure_events
    )
    totals = {
        "jobs": len(jobs),
        "stored": status_counts["stored"],
        "rejected": status_counts["rejected"],
        "exhausted": status_counts["exhausted"],
        "pending": pending,
        "calls": len(calls),
        "retry_calls": retry_calls,
        "prompt_tokens": sum(int(call.prompt_tokens or 0) for call in calls),
        "completion_tokens": sum(int(call.completion_tokens or 0) for call in calls),
        "total_tokens": total_tokens,
        "model_minutes": round(
            sum(float(call.latency_ms or 0.0) for call in calls) / 60_000.0, 3
        ),
        "cost_usd": round(sum(float(call.cost_usd or 0.0) for call in calls), 6),
        "max_token_stops": int(max_token_stops),
        "failed_calls": len(failed_call_ids),
        "failed_call_tokens": failed_call_tokens,
        "failed_call_token_share": round(failed_share, 6),
        "failed_call_token_attribution_complete": (
            failed_token_attribution_complete
        ),
        "unlinked_calls": len(unlinked_call_ids),
        "unlinked_call_tokens": unlinked_call_tokens,
        "parse_failures": failure_kind_counts["parse"],
        "output_exhausted_failures": failure_kind_counts["output_exhausted"],
        "transport_failures": failure_kind_counts["transport"],
        "internal_failures": failure_kind_counts["internal"],
        "manual_retry_resets": failure_kind_counts["manual_retry_reset"],
        "stale_lease_recoveries": failure_kind_counts["stale_lease_recovered"],
        "unattributed_failure_events": unattributed_failure_events,
        "compose_jobs": compose_jobs,
        "blind_audit_jobs": blind_jobs,
        "novelty_audit_jobs": novelty_jobs,
    }
    novelty = {
        "enabled_jobs": len(novelty_enabled_jobs),
        "required_jobs": len(required_job_ids),
        "audited_jobs": len(audited_job_ids),
        "passing_jobs": len(passing_job_ids),
        "required_rounds": len(novelty_rounds),
        "retrieved_rounds": retrieved_rounds,
        "audited_rounds": audited_rounds,
        "passing_rounds": passing_rounds,
        "retrieval_coverage": (
            round(retrieval_coverage, 6)
            if retrieval_coverage is not None
            else None
        ),
        "coverage": (
            round(novelty_coverage, 6) if novelty_coverage is not None else None
        ),
        "storage_bypass_job_ids": novelty_bypasses,
        "rounds": novelty_rounds,
    }

    gates = [
        _gate(
            name="expected_job_count",
            category="completion",
            value=len(jobs),
            operator="==",
            threshold=policy.expected_jobs,
            passed=len(jobs) == policy.expected_jobs,
        ),
        _gate(
            name="exhausted_jobs",
            category="completion",
            value=totals["exhausted"],
            operator="<=",
            threshold=policy.max_exhausted,
            passed=totals["exhausted"] <= policy.max_exhausted,
        ),
        _gate(
            name="pending_jobs",
            category="completion",
            value=pending,
            operator="<=",
            threshold=policy.max_pending,
            passed=pending <= policy.max_pending,
        ),
        _gate(
            name="manual_retry_resets",
            category="reliability",
            value=totals["manual_retry_resets"],
            operator="<=",
            threshold=policy.max_manual_retry_resets,
            passed=totals["manual_retry_resets"] <= policy.max_manual_retry_resets,
        ),
        _gate(
            name="stale_lease_recoveries",
            category="reliability",
            value=totals["stale_lease_recoveries"],
            operator="<=",
            threshold=policy.max_stale_lease_recoveries,
            passed=(
                totals["stale_lease_recoveries"]
                <= policy.max_stale_lease_recoveries
            ),
        ),
        _gate(
            name="max_token_stops",
            category="reliability",
            value=totals["max_token_stops"],
            operator="<=",
            threshold=policy.max_max_token_stops,
            passed=totals["max_token_stops"] <= policy.max_max_token_stops,
        ),
        _gate(
            name="parse_failures",
            category="reliability",
            value=totals["parse_failures"],
            operator="<=",
            threshold=policy.max_parse_failures,
            passed=totals["parse_failures"] <= policy.max_parse_failures,
        ),
        _gate(
            name="output_exhausted_failures",
            category="reliability",
            value=totals["output_exhausted_failures"],
            operator="<=",
            threshold=policy.max_output_exhausted_failures,
            passed=(
                totals["output_exhausted_failures"]
                <= policy.max_output_exhausted_failures
            ),
        ),
        _gate(
            name="transport_failures",
            category="reliability",
            value=totals["transport_failures"],
            operator="<=",
            threshold=policy.max_transport_failures,
            passed=totals["transport_failures"] <= policy.max_transport_failures,
        ),
        _gate(
            name="internal_failures",
            category="reliability",
            value=totals["internal_failures"],
            operator="<=",
            threshold=policy.max_internal_failures,
            passed=totals["internal_failures"] <= policy.max_internal_failures,
        ),
        _gate(
            name="failed_call_token_share",
            category="efficiency",
            value=totals["failed_call_token_share"],
            operator="<=",
            threshold=policy.max_failed_call_token_share,
            passed=failed_share <= policy.max_failed_call_token_share,
        ),
        _gate(
            name="total_tokens",
            category="efficiency",
            value=total_tokens,
            operator="<=",
            threshold=policy.max_total_tokens,
            passed=total_tokens <= policy.max_total_tokens,
        ),
        _gate(
            name="compose_jobs",
            category="coverage",
            value=compose_jobs,
            operator=">=",
            threshold=policy.min_compose_jobs,
            passed=compose_jobs >= policy.min_compose_jobs,
        ),
        _gate(
            name="blind_audit_jobs",
            category="coverage",
            value=blind_jobs,
            operator=">=",
            threshold=policy.min_blind_audit_jobs,
            passed=blind_jobs >= policy.min_blind_audit_jobs,
        ),
        _gate(
            name="missing_call_ids",
            category="lineage",
            value=len(missing_call_ids),
            operator="<=",
            threshold=policy.max_missing_call_ids,
            passed=len(missing_call_ids) <= policy.max_missing_call_ids,
        ),
        _gate(
            name="unlinked_calls",
            category="lineage",
            value=len(unlinked_call_ids),
            operator="<=",
            threshold=policy.max_unlinked_calls,
            passed=len(unlinked_call_ids) <= policy.max_unlinked_calls,
        ),
        _gate(
            name="lineage_mismatches",
            category="lineage",
            value=len(lineage_mismatches),
            operator="<=",
            threshold=policy.max_lineage_mismatches,
            passed=len(lineage_mismatches) <= policy.max_lineage_mismatches,
        ),
        _gate(
            name="unattributed_failure_events",
            category="lineage",
            value=unattributed_failure_events,
            operator="<=",
            threshold=policy.max_unattributed_failure_events,
            passed=(
                unattributed_failure_events
                <= policy.max_unattributed_failure_events
            ),
        ),
    ]
    if policy.require_pilot_v2_config:
        gates.append(
            _gate(
                name="pilot_v2_config_for_all_jobs",
                category="configuration",
                value=len(pilot_compatible_job_ids),
                operator="==",
                threshold=len(jobs),
                passed=len(pilot_compatible_job_ids) == len(jobs),
            )
        )
    if policy.require_novelty_gate:
        gates.extend(
            [
                _gate(
                    name="novelty_gate_enabled_for_all_jobs",
                    category="novelty",
                    value=len(novelty_enabled_jobs),
                    operator="==",
                    threshold=len(jobs),
                    passed=len(novelty_enabled_jobs) == len(jobs),
                ),
                _gate(
                    name="novelty_required_rounds",
                    category="novelty",
                    value=len(novelty_rounds),
                    operator=">=",
                    threshold=policy.min_novelty_required_rounds,
                    passed=(
                        len(novelty_rounds)
                        >= policy.min_novelty_required_rounds
                    ),
                ),
                _gate(
                    name="novelty_retrieval_coverage",
                    category="novelty",
                    value=novelty["retrieval_coverage"],
                    operator=">=",
                    threshold=policy.min_novelty_coverage,
                    passed=bool(
                        retrieval_coverage is not None
                        and retrieval_coverage >= policy.min_novelty_coverage
                    ),
                ),
                _gate(
                    name="novelty_audit_coverage",
                    category="novelty",
                    value=novelty["coverage"],
                    operator=">=",
                    threshold=policy.min_novelty_coverage,
                    passed=bool(
                        novelty_coverage is not None
                        and novelty_coverage >= policy.min_novelty_coverage
                    ),
                ),
                _gate(
                    name="novelty_storage_bypasses",
                    category="novelty",
                    value=len(novelty_bypasses),
                    operator="<=",
                    threshold=policy.max_novelty_storage_bypasses,
                    passed=len(novelty_bypasses)
                    <= policy.max_novelty_storage_bypasses,
                ),
            ]
        )

    failed_gates = [gate["name"] for gate in gates if not gate["passed"]]
    generated_at = datetime.now(timezone.utc).isoformat()
    return {
        "report_type": "combination_efficiency",
        "generated_at": generated_at,
        "run_id": run_id,
        "profile": profile,
        "thresholds": asdict(policy),
        "overall_pass": not failed_gates,
        "failed_gates": failed_gates,
        "run_window": {
            "created_at": _iso(min((job.created_at for job in jobs), default=None)),
            "updated_at": _iso(max((job.updated_at for job in jobs), default=None)),
        },
        "totals": totals,
        "failure_kinds": dict(sorted(failure_kind_counts.items())),
        "auditability": auditability,
        "novelty": novelty,
        "lineage": {
            "missing_call_ids": missing_call_ids,
            "unlinked_call_ids": unlinked_call_ids,
            "mismatches": lineage_mismatches,
            "unattributed_failure_events": unattributed_failure_events,
        },
        "gates": gates,
        "stages": stages,
        "jobs": job_records,
    }
