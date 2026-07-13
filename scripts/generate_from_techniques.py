"""Durable bridge, shell, blind-audit, and corpus-novelty generator (V2).

Examples (after loading ``.env.local``):

  # Preview the deterministic pair plan without creating jobs/candidates or API calls.
  PYTHONPATH=src python scripts/generate_from_techniques.py start \
      --jobs 10 --seed 13 --dry-run

  # Create and process a durable run.
  PYTHONPATH=src python scripts/generate_from_techniques.py start \
      --jobs 10 --seed 15 --run-id combo-creativity-canary-v3

  # Debug one exact pair, resume, or inspect.
  PYTHONPATH=src python scripts/generate_from_techniques.py start \
      --pair prob.indicator,geo.isoperimetric --run-id combo-debug
  PYTHONPATH=src python scripts/generate_from_techniques.py resume --run-id combo-debug
  PYTHONPATH=src python scripts/generate_from_techniques.py status --run-id combo-debug

New problems are stored as ``verified=None`` and ``review_status=PENDING``.
Run the independent frontier verifier and human review before export.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlmodel import select

from mathforge import db
from mathforge.combinations import (
    DEFAULT_JUDGE_MAX_OUTPUT_TOKENS,
    CORPUS_NOVELTY_GATE_V1,
    CORPUS_NOVELTY_PROMPT,
    MIN_LEASE_SECONDS,
    PIPELINE_V1,
    PIPELINE_V2,
    LEGACY_EFFORT_POLICY,
    STAGE_EFFORT_POLICY,
    V1_GENERATOR_MAX_OUTPUT_TOKENS,
    V1_PROMPT_VERSIONS,
    V2_GENERATOR_MAX_OUTPUT_TOKENS,
    V2_PROMPT_VERSIONS,
    build_pair_evidence,
    combination_run_status,
    create_combination_jobs,
    load_technique_catalog,
    preview_pair_plan,
    process_combination_run,
    retry_combination_jobs,
)
from mathforge.llm import LLMClient, make_anthropic_backend, make_openai_backend
from mathforge.prompts import load_prompt
from mathforge.schema import CombinationJob

DEFAULT_MODEL = "claude-opus-4-8"


def _default_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"combo-{stamp}-{uuid.uuid4().hex[:6]}"


def _pair(value: Optional[str]) -> Optional[tuple[str, str]]:
    if not value:
        return None
    parts = tuple(part.strip() for part in value.split(",") if part.strip())
    if len(parts) != 2:
        raise ValueError("--pair must be exactly two comma-separated technique IDs")
    return parts  # type: ignore[return-value]


def _client(
    *,
    model: str,
    backend_name: str,
    generation: bool,
    max_output_tokens: int,
    db_url: Optional[str],
) -> LLMClient:
    # Judge calls use adaptive thinking so their visible answer can remain a
    # strict JSON object; the budget includes both thinking and final output.
    if backend_name == "anthropic":
        backend = make_anthropic_backend(
            model,
            effort="high" if generation else None,
            max_output_tokens=max_output_tokens,
            timeout=840.0 if generation else 360.0,
        )
    else:
        backend = make_openai_backend(model, max_output_tokens=max_output_tokens)
    return LLMClient(
        model=model,
        provider=backend_name,
        backend=backend,
        db_url=db_url,
        purpose="combo-generator" if generation else "combo-judge",
    )


def _print_plan(plan) -> None:
    for index, item in enumerate(plan, 1):
        candidate = item.candidate
        names = " + ".join(context.name for context in candidate.contexts)
        print(
            f"{index:3d}. {candidate.pair_key} [{candidate.tranche}] "
            f"support={candidate.support_a}/{candidate.support_b} "
            f"pair={candidate.pair_support} :: {names}"
        )


def _print_status(report) -> None:
    print(
        json.dumps(
            {
                "run_id": report.run_id,
                "total": report.total,
                "stored_unverified": report.stored,
                "rejected": report.rejected,
                "exhausted": report.exhausted,
                "pending": report.pending,
            },
            indent=2,
        )
    )
    for record in report.records:
        tail = record.get("problem_id") or record.get("rejection_reason") or ""
        if record.get("regeneration_count"):
            tail = (tail + " " if tail else "") + "repair=1"
        print(
            f"[{record['ordinal']:03d}] {record['status']:9s} "
            f"{record['stage']:19s} {record['pair_key']} {tail}"
        )


def _run_config(args: argparse.Namespace) -> dict:
    prompt_versions = dict(
        V2_PROMPT_VERSIONS
        if args.pipeline_version == PIPELINE_V2
        else V1_PROMPT_VERSIONS
    )
    config = {
        "pipeline_version": args.pipeline_version,
        "effort_policy_version": (
            STAGE_EFFORT_POLICY
            if args.pipeline_version == PIPELINE_V2
            else LEGACY_EFFORT_POLICY
        ),
        "generator_model": args.generator_model,
        "generator_backend": args.generator_backend,
        "judge_model": args.judge_model,
        "judge_backend": args.judge_backend,
        "bridges_per_pair": 3,
        "stage_attempts": args.stage_attempts,
        "generator_max_output_tokens": (
            args.generator_max_output_tokens
            if args.generator_max_output_tokens is not None
            else (
                V2_GENERATOR_MAX_OUTPUT_TOKENS
                if args.pipeline_version == PIPELINE_V2
                else V1_GENERATOR_MAX_OUTPUT_TOKENS
            )
        ),
        "lease_seconds": args.lease_seconds,
        "target_difficulty": [args.difficulty_low, args.difficulty_high],
        "prompt_versions": prompt_versions,
        "prompt_hashes": {
            key: hashlib.sha256(load_prompt(version).encode("utf-8")).hexdigest()
            for key, version in prompt_versions.items()
        },
    }
    if args.pipeline_version == PIPELINE_V2:
        config.update(
            {
                "shells_per_bridge": args.shells_per_bridge,
                "creativity_floor": args.creativity_floor,
                "blind_difficulty_floor": args.blind_difficulty_floor,
                "max_creativity_repairs": args.max_creativity_repairs,
                "novelty_gate_version": CORPUS_NOVELTY_GATE_V1,
                "novelty_neighbor_count": 8,
                "novelty_distance_floor": 3,
                "novelty_prompt_version": CORPUS_NOVELTY_PROMPT,
                "novelty_prompt_sha256": hashlib.sha256(
                    load_prompt(CORPUS_NOVELTY_PROMPT).encode("utf-8")
                ).hexdigest(),
            }
        )
    return config


def _config_for_resume(run_id: str, db_url: Optional[str]) -> dict:
    db.init_db(db_url)
    with db.session_scope(db_url) as session:
        jobs = session.exec(
            select(CombinationJob)
            .where(CombinationJob.run_id == run_id)
            .order_by(CombinationJob.ordinal)
        ).all()
        if not jobs:
            raise ValueError(f"combination run not found: {run_id}")
        resolved = dict(jobs[0].config or {})
    # Do not rewrite historical provenance. Missing caps retain the runtime that
    # predates the explicit V2 48k field; every new run stores its cap directly.
    resolved.setdefault(
        "generator_max_output_tokens", V1_GENERATOR_MAX_OUTPUT_TOKENS
    )
    return resolved


def _model_family(model: object, backend: object) -> str:
    """Infer the underlying model family, independent of transport protocol."""
    name = str(model or "").strip().lower()
    transport = str(backend or "").strip().lower()
    if "claude" in name or "anthropic" in name or transport == "anthropic":
        return "anthropic"
    if (
        "openai" in name
        or name.startswith(("gpt-", "chatgpt-", "o1", "o3", "o4"))
    ):
        return "openai"
    # Exact unknown model names still represent the same preliminary judge.
    return name or f"backend:{transport}"


def _same_model_family(config: dict) -> bool:
    return _model_family(
        config.get("generator_model"), config.get("generator_backend")
    ) == _model_family(config.get("judge_model"), config.get("judge_backend"))


def _process(run_id: str, config: dict, db_url: Optional[str]) -> None:
    if _same_model_family(config):
        print(
            "warning: generator and preliminary judge use the same model family; "
            "independent frontier verification remains mandatory"
        )
    generator = _client(
        model=config.get("generator_model") or DEFAULT_MODEL,
        backend_name=config.get("generator_backend") or "anthropic",
        generation=True,
        max_output_tokens=int(
            config.get("generator_max_output_tokens")
            or V1_GENERATOR_MAX_OUTPUT_TOKENS
        ),
        db_url=db_url,
    )
    judge = _client(
        model=config.get("judge_model") or DEFAULT_MODEL,
        backend_name=config.get("judge_backend") or "anthropic",
        generation=False,
        max_output_tokens=DEFAULT_JUDGE_MAX_OUTPUT_TOKENS,
        db_url=db_url,
    )
    report = process_combination_run(
        run_id=run_id,
        generator=generator,
        judge=judge,
        db_url=db_url,
    )
    _print_status(report)


def start(args: argparse.Namespace) -> None:
    if args.jobs < 1:
        raise ValueError("--jobs must be positive")
    if args.lease_seconds < MIN_LEASE_SECONDS:
        raise ValueError(
            f"--lease-seconds must be at least {MIN_LEASE_SECONDS}"
        )
    if args.difficulty_low > args.difficulty_high:
        raise ValueError("--difficulty-low cannot exceed --difficulty-high")
    explicit_pair = _pair(args.pair)
    jobs = 1 if explicit_pair else args.jobs
    run_id = args.run_id or _default_run_id()
    catalog = load_technique_catalog(args.taxonomy)
    evidence = build_pair_evidence(catalog, args.db_url)
    config = _run_config(args)
    plan = preview_pair_plan(
        count=jobs,
        seed=args.seed,
        catalog=catalog,
        evidence=evidence,
        config=config,
        db_url=args.db_url,
        explicit_pair=explicit_pair,
    )
    print(
        f"taxonomy: {len(catalog.techniques)} canonical techniques; "
        f"support snapshot={evidence.snapshot_hash[:12]}"
    )
    settings = (
        f"pipeline={config['pipeline_version']} "
        f"target={args.difficulty_low:g}-{args.difficulty_high:g}"
    )
    if config["pipeline_version"] == PIPELINE_V2:
        settings += (
            f" shells={config['shells_per_bridge']}"
            f" creativity>={config['creativity_floor']}"
            f" blind_difficulty>={config['blind_difficulty_floor']:g}"
            f" repairs<={config['max_creativity_repairs']}"
            f" generator_tokens={config['generator_max_output_tokens']}"
            f" effort_policy={config['effort_policy_version']}"
            f" novelty_gate={config['novelty_gate_version']}"
        )
    print(settings)
    _print_plan(plan)
    if args.dry_run:
        print("dry-run: no jobs created and no model calls made")
        return
    create_combination_jobs(
        run_id=run_id,
        count=jobs,
        seed=args.seed,
        catalog=catalog,
        evidence=evidence,
        config=config,
        db_url=args.db_url,
        explicit_pair=explicit_pair,
    )
    print(f"created run {run_id!r} with {jobs} durable jobs")
    _process(run_id, config, args.db_url)


def resume(args: argparse.Namespace) -> None:
    config = _config_for_resume(args.run_id, args.db_url)
    _process(args.run_id, config, args.db_url)


def status(args: argparse.Namespace) -> None:
    _print_status(combination_run_status(args.run_id, args.db_url))


def retry(args: argparse.Namespace) -> None:
    kinds = {value.strip() for value in args.kinds.split(",") if value.strip()}
    ordinals = None
    if args.ordinals.strip():
        try:
            ordinals = {
                int(value.strip())
                for value in args.ordinals.split(",")
                if value.strip()
            }
        except ValueError as exc:
            raise ValueError("--ordinals must be comma-separated integers") from exc
        if not ordinals or any(value < 1 for value in ordinals):
            raise ValueError("--ordinals must contain positive integers")
    reset = retry_combination_jobs(
        args.run_id,
        failure_kinds=kinds,
        ordinals=ordinals,
        db_url=args.db_url,
    )
    print(f"reset {reset} exhausted jobs for retry")
    if reset:
        _process(args.run_id, _config_for_resume(args.run_id, args.db_url), args.db_url)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    start_parser = subparsers.add_parser("start", help="plan, persist, and process a new run")
    start_parser.add_argument("--jobs", type=int, default=4, help="number of technique pairs")
    start_parser.add_argument("--pair", default="", help="one exact pair: id1,id2")
    start_parser.add_argument("--seed", type=int, default=0)
    start_parser.add_argument("--run-id", default="")
    start_parser.add_argument("--dry-run", action="store_true")
    start_parser.add_argument("--taxonomy", type=Path, default=Path("data/techniques.json"))
    start_parser.add_argument("--difficulty-low", type=float, default=4.0)
    start_parser.add_argument("--difficulty-high", type=float, default=8.0)
    start_parser.add_argument(
        "--pipeline-version",
        choices=(PIPELINE_V1, PIPELINE_V2),
        default=PIPELINE_V2,
        help=(
            "v2 adds shell diversification, blind and corpus-novelty audits, "
            "and one bounded repair"
        ),
    )
    start_parser.add_argument("--shells-per-bridge", type=int, default=4)
    start_parser.add_argument(
        "--creativity-floor", type=int, choices=(4, 5), default=4
    )
    start_parser.add_argument("--blind-difficulty-floor", type=float, default=4.5)
    start_parser.add_argument(
        "--max-creativity-repairs", type=int, choices=(0, 1), default=1
    )
    start_parser.add_argument("--stage-attempts", type=int, default=2, choices=(1, 2, 3))
    start_parser.add_argument(
        "--generator-max-output-tokens",
        type=int,
        default=None,
        help="generation budget (default: 48000 for v2, 32000 for v1)",
    )
    start_parser.add_argument("--lease-seconds", type=int, default=1200)
    start_parser.add_argument("--generator-model", default=DEFAULT_MODEL)
    start_parser.add_argument("--generator-backend", choices=("anthropic", "openai"), default="anthropic")
    start_parser.add_argument("--judge-model", default=DEFAULT_MODEL)
    start_parser.add_argument("--judge-backend", choices=("anthropic", "openai"), default="anthropic")
    start_parser.add_argument("--db-url", default=None)
    start_parser.set_defaults(func=start)

    resume_parser = subparsers.add_parser("resume", help="resume all nonterminal jobs")
    resume_parser.add_argument("--run-id", required=True)
    resume_parser.add_argument("--db-url", default=None)
    resume_parser.set_defaults(func=resume)

    status_parser = subparsers.add_parser("status", help="show durable run state")
    status_parser.add_argument("--run-id", required=True)
    status_parser.add_argument("--db-url", default=None)
    status_parser.set_defaults(func=status)

    retry_parser = subparsers.add_parser(
        "retry", help="reset selected exhausted failures and resume"
    )
    retry_parser.add_argument("--run-id", required=True)
    retry_parser.add_argument(
        "--kinds", default="transport,output_exhausted", help="comma-separated failure kinds"
    )
    retry_parser.add_argument(
        "--ordinals",
        default="",
        help="optional comma-separated job ordinals to reset (for example 9,10)",
    )
    retry_parser.add_argument("--db-url", default=None)
    retry_parser.set_defaults(func=retry)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except (ValueError, FileNotFoundError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
