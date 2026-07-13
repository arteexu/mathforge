from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from sqlmodel import Session

from mathforge import db
from mathforge.combo_efficiency import (
    EfficiencyThresholds,
    combination_efficiency_report,
)
from mathforge.combinations import CORPUS_NOVELTY_GATE_V1
from mathforge.schema import (
    CombinationJob,
    CombinationJobStatus,
    LLMCall,
    statement_hash,
)


BASE_TIME = datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc)


def _url(tmp_path, name: str) -> str:
    return f"sqlite:///{tmp_path / (name + '.db')}"


def _add_job(
    session: Session,
    *,
    run_id: str,
    ordinal: int,
    status: CombinationJobStatus,
    stage: str,
    config: dict | None = None,
    failures: list[dict] | None = None,
    design_artifacts: dict | None = None,
) -> CombinationJob:
    job = CombinationJob(
        id=f"{run_id}-job-{ordinal}",
        run_id=run_id,
        ordinal=ordinal,
        seed=ordinal,
        pair_key=f"technique-{ordinal}-a+technique-{ordinal}-b",
        technique_ids=[f"technique-{ordinal}-a", f"technique-{ordinal}-b"],
        config=dict(config or {}),
        stage=stage,
        status=status,
        failures=list(failures or []),
        design_artifacts=dict(design_artifacts or {}),
        created_at=BASE_TIME + timedelta(minutes=ordinal),
        updated_at=BASE_TIME + timedelta(minutes=ordinal, seconds=30),
    )
    session.add(job)
    session.flush()
    return job


def _add_call(
    session: Session,
    job: CombinationJob,
    stage: str,
    *,
    total_tokens: int = 1_000,
    created_at: datetime | None = None,
    meta: dict | None = None,
    attach: bool = True,
    purpose: str = "combo-test",
) -> LLMCall:
    prompt_tokens = total_tokens // 4
    call_meta = {"stage": stage, "stop_reason": "end_turn"}
    if meta is not None:
        call_meta = dict(meta)
    call = LLMCall(
        created_at=created_at or BASE_TIME,
        model="fake",
        purpose=purpose,
        prompt_tokens=prompt_tokens,
        completion_tokens=total_tokens - prompt_tokens,
        total_tokens=total_tokens,
        latency_ms=60_000,
        related_id=job.id,
        meta=call_meta,
    )
    session.add(call)
    session.flush()
    assert call.id is not None
    if attach:
        call_ids = {
            key: list(values) for key, values in dict(job.call_ids or {}).items()
        }
        call_ids.setdefault(stage, []).append(call.id)
        job.call_ids = call_ids
        session.add(job)
        session.flush()
    return call


def _custom_thresholds(expected_jobs: int, **overrides) -> EfficiencyThresholds:
    values = {
        "expected_jobs": expected_jobs,
        "max_max_token_stops": 99,
        "max_parse_failures": 99,
        "max_output_exhausted_failures": 99,
        "max_transport_failures": 99,
        "max_failed_call_token_share": 1.0,
        "max_total_tokens": 10_000_000,
        "min_compose_jobs": 0,
        "min_blind_audit_jobs": 0,
        "require_novelty_gate": False,
        "min_novelty_coverage": 0.0,
    }
    values.update(overrides)
    return EfficiencyThresholds(**values)


def _passing_novelty_design() -> dict:
    draft = {
        "statement": "Determine the unique integer encoded by this test problem.",
        "crux": "A reversible encoding makes the requested integer unique.",
    }
    bound_statement_hash = statement_hash(draft["statement"])
    retrieval = {
        "schema_version": "combo_novelty_neighbors_v1",
        "round": "initial",
        "statement_hash": bound_statement_hash,
        "corpus_hash": "c" * 64,
        "missing_evidence_ids": [],
        "neighbors": [
            {
                "neighbor_id": "source-problem",
                "statement": "A distinct source problem for comparison.",
            }
        ],
    }
    retrieval["retrieval_hash"] = hashlib.sha256(
        json.dumps(
            retrieval,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    return {
        "regeneration_count": 0,
        "drafts": {"initial": draft},
        "preflights": {
            "initial": {"verdict": "accept", "computed_quality_pass": True}
        },
        "novelty_neighbors": {"initial": retrieval},
        "novelty_audits": {
            "initial": {
                "round": "initial",
                "statement_hash": bound_statement_hash,
                "retrieval_hash": retrieval["retrieval_hash"],
                "computed_novelty_pass": True,
            }
        },
    }


def test_confirmation_three_profile_passes_a_completed_efficient_run(tmp_path):
    run_id = "confirmation-three"
    db_url = _url(tmp_path, run_id)
    db.init_db(db_url)
    with db.session_scope(db_url) as session:
        stored = _add_job(
            session,
            run_id=run_id,
            ordinal=1,
            status=CombinationJobStatus.STORED,
            stage="stored",
            config={"pipeline_version": "v2"},
        )
        rejected_a = _add_job(
            session,
            run_id=run_id,
            ordinal=2,
            status=CombinationJobStatus.REJECTED,
            stage="bridges_judged",
        )
        rejected_b = _add_job(
            session,
            run_id=run_id,
            ordinal=3,
            status=CombinationJobStatus.REJECTED,
            stage="bridges_judged",
        )
        _add_call(session, stored, "compose", total_tokens=40_000)
        _add_call(session, stored, "blind_audit_r0", total_tokens=20_000)
        _add_call(session, rejected_a, "bridge_proposal", total_tokens=10_000)
        _add_call(session, rejected_b, "bridge_proposal", total_tokens=10_000)

    report = combination_efficiency_report(
        run_id, db_url=db_url, profile="confirmation-3"
    )

    assert report["overall_pass"] is True
    assert report["auditability"]["mode"] == "legacy_or_nonpilot"
    assert report["failed_gates"] == []
    assert report["totals"] == {
        **report["totals"],
        "jobs": 3,
        "stored": 1,
        "rejected": 2,
        "exhausted": 0,
        "pending": 0,
        "calls": 4,
        "total_tokens": 80_000,
        "compose_jobs": 1,
        "blind_audit_jobs": 1,
    }
    assert all(gate["passed"] for gate in report["gates"])


def test_failed_token_share_attributes_only_the_failed_retry_call(tmp_path):
    run_id = "failed-token-attribution"
    db_url = _url(tmp_path, run_id)
    db.init_db(db_url)
    failure_at = BASE_TIME + timedelta(seconds=2)
    with db.session_scope(db_url) as session:
        job = _add_job(
            session,
            run_id=run_id,
            ordinal=1,
            status=CombinationJobStatus.STORED,
            stage="stored",
            failures=[
                {
                    "at": failure_at.isoformat(),
                    "stage": "compose",
                    "kind": "parse",
                    "message": "malformed first artifact",
                }
            ],
        )
        first = _add_call(
            session,
            job,
            "compose",
            total_tokens=100,
            created_at=BASE_TIME + timedelta(seconds=1),
        )
        second = _add_call(
            session,
            job,
            "compose",
            total_tokens=300,
            created_at=BASE_TIME + timedelta(seconds=3),
            # A complete, schema-valid artifact may legitimately be usable even
            # when the provider reports a token-limit stop.
            meta={"stage": "compose", "stop_reason": "max_tokens"},
        )

    report = combination_efficiency_report(
        run_id,
        db_url=db_url,
        profile="custom",
        thresholds=_custom_thresholds(1),
    )

    assert first.id != second.id
    assert report["totals"]["calls"] == 2
    assert report["totals"]["retry_calls"] == 1
    assert report["totals"]["parse_failures"] == 1
    assert report["totals"]["max_token_stops"] == 1
    assert report["totals"]["failed_calls"] == 1
    assert report["totals"]["failed_call_tokens"] == 100
    assert report["totals"]["failed_call_token_share"] == 0.25
    compose = next(row for row in report["stages"] if row["stage"] == "compose")
    assert compose["failed_calls"] == 1
    assert compose["failed_call_tokens"] == 100


def test_pilot_five_profile_reports_all_material_failure_gates(tmp_path):
    run_id = "failing-pilot-five"
    db_url = _url(tmp_path, run_id)
    db.init_db(db_url)
    enabled = {
        "pipeline_version": "v2",
        "novelty_gate_version": CORPUS_NOVELTY_GATE_V1,
    }
    with db.session_scope(db_url) as session:
        stored = _add_job(
            session,
            run_id=run_id,
            ordinal=1,
            status=CombinationJobStatus.STORED,
            stage="stored",
            config=enabled,
            design_artifacts={
                "preflights": {
                    "initial": {
                        "verdict": "accept",
                        "computed_quality_pass": True,
                    }
                }
            },
        )
        failures = [
            *[
                {
                    "at": (BASE_TIME + timedelta(seconds=index)).isoformat(),
                    "stage": "bridge_proposal",
                    "kind": "parse",
                    "message": "invalid JSON",
                }
                for index in range(1, 4)
            ],
            *[
                {
                    "at": (BASE_TIME + timedelta(seconds=index)).isoformat(),
                    "stage": "bridge_proposal",
                    "kind": "output_exhausted",
                    "message": "truncated output",
                }
                for index in range(4, 6)
            ],
            {
                "at": (BASE_TIME + timedelta(seconds=6)).isoformat(),
                "stage": "bridge_proposal",
                "kind": "transport",
                "message": "timeout",
            },
            {
                "at": (BASE_TIME + timedelta(seconds=7)).isoformat(),
                "stage": "bridge_proposal",
                "kind": "transport",
                "message": "gateway unavailable",
            },
            {
                "at": (BASE_TIME + timedelta(seconds=8)).isoformat(),
                "stage": "bridge_proposal",
                "kind": "manual_retry_reset",
                "message": "manual reset",
            },
        ]
        exhausted = _add_job(
            session,
            run_id=run_id,
            ordinal=2,
            status=CombinationJobStatus.EXHAUSTED,
            stage="pair_selected",
            config=enabled,
            failures=failures,
        )
        _add_job(
            session,
            run_id=run_id,
            ordinal=3,
            status=CombinationJobStatus.PENDING,
            stage="pair_selected",
        )
        _add_job(
            session,
            run_id=run_id,
            ordinal=4,
            status=CombinationJobStatus.REJECTED,
            stage="bridges_judged",
        )
        _add_job(
            session,
            run_id=run_id,
            ordinal=5,
            status=CombinationJobStatus.REJECTED,
            stage="bridges_judged",
            config=enabled,
        )

        _add_call(session, stored, "compose", total_tokens=400_000)
        _add_call(session, stored, "blind_audit_r0", total_tokens=10_000)
        for index in range(5):
            _add_call(
                session,
                exhausted,
                "bridge_proposal",
                total_tokens=100_000,
                created_at=BASE_TIME + timedelta(seconds=index, milliseconds=500),
                meta={
                    "stage": "bridge_proposal",
                    "stop_reason": "max_tokens" if index < 2 else "end_turn",
                },
            )

    report = combination_efficiency_report(run_id, db_url=db_url, profile="pilot-5")

    assert report["overall_pass"] is False
    assert report["totals"]["jobs"] == 5
    assert report["totals"]["exhausted"] == 1
    assert report["totals"]["pending"] == 1
    assert report["totals"]["parse_failures"] == 3
    assert report["totals"]["output_exhausted_failures"] == 2
    assert report["totals"]["transport_failures"] == 2
    assert report["totals"]["manual_retry_resets"] == 1
    assert report["totals"]["max_token_stops"] == 2
    assert report["totals"]["total_tokens"] == 910_000
    expected_failures = {
        "exhausted_jobs",
        "pending_jobs",
        "manual_retry_resets",
        "max_token_stops",
        "parse_failures",
        "output_exhausted_failures",
        "transport_failures",
        "failed_call_token_share",
        "total_tokens",
        "compose_jobs",
        "blind_audit_jobs",
        "pilot_v2_config_for_all_jobs",
        "novelty_gate_enabled_for_all_jobs",
        "novelty_audit_coverage",
        "novelty_storage_bypasses",
    }
    assert expected_failures <= set(report["failed_gates"])


def test_novelty_coverage_detects_a_stored_gate_bypass(tmp_path):
    run_id = "novelty-bypass"
    db_url = _url(tmp_path, run_id)
    db.init_db(db_url)
    config = {
        "pipeline_version": "v2",
        "novelty_gate_version": CORPUS_NOVELTY_GATE_V1,
    }
    with db.session_scope(db_url) as session:
        audited = _add_job(
            session,
            run_id=run_id,
            ordinal=1,
            status=CombinationJobStatus.STORED,
            stage="stored",
            config=config,
            design_artifacts=_passing_novelty_design(),
        )
        bypass = _add_job(
            session,
            run_id=run_id,
            ordinal=2,
            status=CombinationJobStatus.STORED,
            stage="stored",
            config=config,
            design_artifacts={
                "regeneration_count": 0,
                "preflights": {
                    "initial": {
                        "verdict": "accept",
                        "computed_quality_pass": True,
                    }
                },
            },
        )
        for job in (audited, bypass):
            _add_call(session, job, "compose")
            _add_call(session, job, "blind_audit_r0")
        _add_call(session, audited, "novelty_audit_r0")

    policy = _custom_thresholds(
        2,
        min_compose_jobs=2,
        min_blind_audit_jobs=2,
        require_novelty_gate=True,
        min_novelty_coverage=1.0,
        max_novelty_storage_bypasses=0,
    )
    report = combination_efficiency_report(
        run_id, db_url=db_url, profile="custom", thresholds=policy
    )

    novelty = report["novelty"]
    assert novelty["enabled_jobs"] == 2
    assert novelty["required_jobs"] == 2
    assert novelty["audited_jobs"] == 1
    assert novelty["passing_jobs"] == 1
    assert novelty["required_rounds"] == 2
    assert novelty["retrieved_rounds"] == 1
    assert novelty["audited_rounds"] == 1
    assert novelty["passing_rounds"] == 1
    assert novelty["retrieval_coverage"] == 0.5
    assert novelty["coverage"] == 0.5
    assert novelty["storage_bypass_job_ids"] == [bypass.id]
    audited_round, bypass_round = novelty["rounds"]
    assert audited_round == {
        "job_id": audited.id,
        "ordinal": 1,
        "round": "initial",
        "retrieval_present": True,
        "retrieved": True,
        "audit_present": True,
        "audit_call_present": True,
        "audited": True,
        "passed": True,
        "issues": [],
    }
    assert bypass_round["job_id"] == bypass.id
    assert bypass_round["round"] == "initial"
    assert bypass_round["retrieved"] is False
    assert bypass_round["audited"] is False
    assert bypass_round["passed"] is False
    assert {
        "missing_round_draft",
        "missing_retrieval",
        "missing_audit",
        "missing_audit_call",
    } <= set(bypass_round["issues"])
    assert report["overall_pass"] is False
    assert "novelty_retrieval_coverage" in report["failed_gates"]
    assert "novelty_audit_coverage" in report["failed_gates"]
    assert "novelty_storage_bypasses" in report["failed_gates"]
    assert report["jobs"][0]["novelty_passed"] is True
    assert report["jobs"][1]["novelty_audited"] is False


def test_novelty_artifact_requires_a_persisted_call_and_current_binding(tmp_path):
    run_id = "novelty-artifact-binding"
    db_url = _url(tmp_path, run_id)
    db.init_db(db_url)
    config = {
        "pipeline_version": "v2",
        "novelty_gate_version": CORPUS_NOVELTY_GATE_V1,
    }
    missing_call_design = _passing_novelty_design()
    stale_binding_design = json.loads(json.dumps(_passing_novelty_design()))
    stale_binding_design["novelty_audits"]["initial"]["retrieval_hash"] = (
        "stale-retrieval-binding"
    )

    with db.session_scope(db_url) as session:
        missing_call = _add_job(
            session,
            run_id=run_id,
            ordinal=1,
            status=CombinationJobStatus.REJECTED,
            stage="novelty_judged",
            config=config,
            design_artifacts=missing_call_design,
        )
        stale_binding = _add_job(
            session,
            run_id=run_id,
            ordinal=2,
            status=CombinationJobStatus.REJECTED,
            stage="novelty_judged",
            config=config,
            design_artifacts=stale_binding_design,
        )
        for job in (missing_call, stale_binding):
            _add_call(session, job, "compose")
            _add_call(session, job, "blind_audit_r0")
        # The first job has a plausible persisted artifact but no paid audit
        # call. The second has a paid call, but its artifact is bound to a stale
        # retrieval hash. Neither is coverage.
        _add_call(session, stale_binding, "novelty_audit_r0")

    policy = _custom_thresholds(
        2,
        min_compose_jobs=2,
        min_blind_audit_jobs=2,
        require_novelty_gate=True,
        min_novelty_coverage=1.0,
    )
    report = combination_efficiency_report(
        run_id, db_url=db_url, profile="custom", thresholds=policy
    )

    novelty = report["novelty"]
    assert novelty["required_rounds"] == 2
    assert novelty["retrieved_rounds"] == 2
    assert novelty["audited_rounds"] == 0
    assert novelty["passing_rounds"] == 0
    assert novelty["retrieval_coverage"] == 1.0
    assert novelty["coverage"] == 0.0
    assert report["totals"]["novelty_audit_jobs"] == 1
    by_job = {record["job_id"]: record for record in novelty["rounds"]}
    assert by_job[missing_call.id]["audit_present"] is True
    assert by_job[missing_call.id]["audit_call_present"] is False
    assert "missing_audit_call" in by_job[missing_call.id]["issues"]
    assert by_job[stale_binding.id]["audit_call_present"] is True
    assert "audit_retrieval_mismatch" in by_job[stale_binding.id]["issues"]
    assert "novelty_retrieval_coverage" not in report["failed_gates"]
    assert "novelty_audit_coverage" in report["failed_gates"]


def test_missing_call_lineage_and_unmatched_failures_are_explicit(tmp_path):
    run_id = "missing-lineage"
    db_url = _url(tmp_path, run_id)
    db.init_db(db_url)
    with db.session_scope(db_url) as session:
        job = _add_job(
            session,
            run_id=run_id,
            ordinal=1,
            status=CombinationJobStatus.REJECTED,
            stage="draft_generated",
            failures=[
                {
                    "at": (BASE_TIME + timedelta(seconds=2)).isoformat(),
                    "stage": "compose",
                    "kind": "parse",
                    "message": "first failure has a call",
                },
                {
                    "at": (BASE_TIME + timedelta(seconds=4)).isoformat(),
                    "stage": "compose",
                    "kind": "parse",
                    "message": "second failure has no persisted call",
                },
            ],
        )
        # The call has no stage metadata, so the durable call_ids map must be
        # used as the legacy fallback.
        call = _add_call(
            session,
            job,
            "compose",
            total_tokens=200,
            created_at=BASE_TIME + timedelta(seconds=1),
            meta={},
        )
        missing_id = 999_999
        call_ids = dict(job.call_ids)
        call_ids["compose"] = [call.id, missing_id]
        job.call_ids = call_ids
        session.add(job)
        # Paid calls linked by related_id remain part of cost accounting even
        # if a crash prevented them from entering the job's call_ids lineage.
        orphan_call = _add_call(
            session,
            job,
            "orphan_stage",
            total_tokens=300,
            attach=False,
        )

    report = combination_efficiency_report(
        run_id,
        db_url=db_url,
        profile="custom",
        thresholds=_custom_thresholds(1),
    )

    assert report["totals"]["calls"] == 2
    assert report["totals"]["total_tokens"] == 500
    assert report["totals"]["failed_calls"] == 1
    assert report["totals"]["failed_call_tokens"] == 200
    assert report["totals"]["unattributed_failure_events"] == 1
    assert report["lineage"] == {
        "missing_call_ids": [missing_id],
        "unlinked_call_ids": [orphan_call.id],
        "mismatches": [],
        "unattributed_failure_events": 1,
    }
    assert report["totals"]["unlinked_calls"] == 1
    assert report["totals"]["unlinked_call_tokens"] == 300
    assert report["totals"]["failed_call_token_attribution_complete"] is False
    assert {
        "missing_call_ids",
        "unlinked_calls",
        "unattributed_failure_events",
    } <= set(report["failed_gates"])
    compose = next(row for row in report["stages"] if row["stage"] == "compose")
    assert compose["calls"] == 1
    assert compose["failed_calls"] == 1
    orphan = next(
        row for row in report["stages"] if row["stage"] == "orphan_stage"
    )
    assert orphan["unlinked_calls"] == 1
    assert orphan["unlinked_call_tokens"] == 300


def test_stop_reasons_are_normalized_across_provider_metadata(tmp_path):
    run_id = "normalized-stop-reasons"
    db_url = _url(tmp_path, run_id)
    db.init_db(db_url)
    with db.session_scope(db_url) as session:
        job = _add_job(
            session,
            run_id=run_id,
            ordinal=1,
            status=CombinationJobStatus.REJECTED,
            stage="bridges_judged",
        )
        _add_call(
            session,
            job,
            "stage-a",
            meta={"stage": "stage-a", "stop_reason": "  MAX_TOKENS  "},
        )
        _add_call(
            session,
            job,
            "stage-b",
            meta={"stage": "stage-b", "finish_reason": " Length "},
        )
        _add_call(
            session,
            job,
            "stage-c",
            meta={"stage": "stage-c", "stop_reason": " MAX_OUTPUT_TOKENS "},
        )
        _add_call(
            session,
            job,
            "stage-d",
            meta={"stage": "stage-d", "stop_reason": "end_turn"},
        )

    report = combination_efficiency_report(
        run_id,
        db_url=db_url,
        profile="custom",
        thresholds=_custom_thresholds(1),
    )

    assert report["totals"]["max_token_stops"] == 3
    by_stage = {row["stage"]: row for row in report["stages"]}
    assert [by_stage[f"stage-{suffix}"]["max_token_stops"] for suffix in "abcd"] == [
        1,
        1,
        1,
        0,
    ]


def test_legacy_v2_compose_call_uses_durable_stage_name(tmp_path):
    run_id = "legacy-v2-compose"
    db_url = _url(tmp_path, run_id)
    db.init_db(db_url)
    with db.session_scope(db_url) as session:
        job = _add_job(
            session,
            run_id=run_id,
            ordinal=1,
            status=CombinationJobStatus.STORED,
            stage="stored",
            # Historical V2 rows predate novelty/effort metadata.
            config={"pipeline_version": "v2"},
        )
        _add_call(
            session,
            job,
            "compose",
            meta={},
            purpose="combo-compose-v2",
        )

    report = combination_efficiency_report(
        run_id,
        db_url=db_url,
        profile="custom",
        thresholds=_custom_thresholds(1),
    )

    assert report["totals"]["compose_jobs"] == 1
    assert [row["stage"] for row in report["stages"]] == ["compose"]
    assert report["stages"][0]["efforts"] == {"unknown": 1}
    assert report["novelty"]["enabled_jobs"] == 0
