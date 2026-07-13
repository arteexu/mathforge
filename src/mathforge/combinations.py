"""Durable bridge-and-shell generation from competition-math technique pairs.

The module separates deterministic pair planning and strict output validation
from model orchestration.  Every attempt is checkpointed in ``CombinationJob``;
only a complete, quality-gated draft becomes a ``Problem``. V2 adds four-shell
diversification, a statement-only blind audit, a corpus-neighbor novelty audit,
and one durable structural repair.
Independent answer verification and human acceptance remain downstream gates.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from itertools import combinations
from pathlib import Path
from typing import Any, Callable, Optional

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from mathforge import db
from mathforge.distill import (
    is_banned_template,
    is_garbled,
    is_near_duplicate,
    token_set,
)
from mathforge.integrity import (
    canonical_statement_hash,
    canonicalize_statement,
    deduplicated_training_problems,
    is_export_eligible,
    normalize_aime_answer,
    preferred_solution,
)
from mathforge.llm import LLMClient, LLMResponse
from mathforge.prompts import load_prompt, render_prompt
from mathforge.schema import (
    CombinationJob,
    CombinationJobStatus,
    CombinationStatementClaim,
    CombinationStorageLock,
    DataSplit,
    Problem,
    ProblemSource,
    ReviewStatus,
    Solution,
    SolutionSource,
    statement_hash,
    utcnow,
)

__all__ = [
    "ALIAS_VERSION",
    "SAMPLER_VERSION",
    "MIN_LEASE_SECONDS",
    "PIPELINE_V1",
    "PIPELINE_V2",
    "V1_GENERATOR_MAX_OUTPUT_TOKENS",
    "V2_GENERATOR_MAX_OUTPUT_TOKENS",
    "DEFAULT_JUDGE_MAX_OUTPUT_TOKENS",
    "LEGACY_EFFORT_POLICY",
    "STAGE_EFFORT_POLICY",
    "CORPUS_NOVELTY_PROMPT",
    "CORPUS_NOVELTY_GATE_V1",
    "V1_PROMPT_VERSIONS",
    "V2_PROMPT_VERSIONS",
    "TechniqueCatalog",
    "PairEvidence",
    "PairCandidate",
    "ComboRunReport",
    "ContractError",
    "load_technique_catalog",
    "build_pair_evidence",
    "build_pair_candidates",
    "plan_pairs",
    "strict_json_object",
    "parse_bridge_proposals",
    "parse_bridge_judgment",
    "parse_shell_proposals",
    "parse_shell_judgment",
    "parse_combo_draft",
    "parse_combo_draft_v2",
    "parse_blind_audit",
    "parse_faithfulness",
    "parse_corpus_novelty",
    "preview_pair_plan",
    "create_combination_jobs",
    "process_combination_run",
    "retry_combination_jobs",
    "combination_run_status",
]


ALIAS_VERSION = "exact-name-nfkc-v1"
SAMPLER_VERSION = "grounded-65-25-10-v1"
BRIDGE_PROMPT = "combo_bridge_generation_v1"
BRIDGE_JUDGE_PROMPT = "combo_bridge_judge_v1"
PROBLEM_PROMPT = "combo_problem_generation_v1"
FAITHFULNESS_PROMPT = "combo_faithfulness_v1"
SHELL_PROMPT = "combo_shell_generation_v1"
SHELL_JUDGE_PROMPT = "combo_shell_judge_v1"
PROBLEM_PROMPT_V2 = "combo_problem_generation_v2"
BLIND_AUDIT_PROMPT = "combo_blind_audit_v1"
FAITHFULNESS_PROMPT_V2 = "combo_faithfulness_v2"
CREATIVITY_REPAIR_PROMPT = "combo_creativity_repair_v1"
CORPUS_NOVELTY_PROMPT = "combo_corpus_novelty_v1"
CORPUS_NOVELTY_GATE_DISABLED = "disabled"
CORPUS_NOVELTY_GATE_V1 = "corpus-neighbor-judge-v1"
SUPPORTED_NOVELTY_GATES = {
    CORPUS_NOVELTY_GATE_DISABLED,
    CORPUS_NOVELTY_GATE_V1,
}
PIPELINE_V1 = "v1"
PIPELINE_V2 = "v2"
V1_GENERATOR_MAX_OUTPUT_TOKENS = 32000
V2_GENERATOR_MAX_OUTPUT_TOKENS = 48000
DEFAULT_JUDGE_MAX_OUTPUT_TOKENS = 12000
LEGACY_EFFORT_POLICY = "combo-role-effort-legacy-v1"
STAGE_EFFORT_POLICY = "combo-stage-effort-v1"
SUPPORTED_EFFORT_POLICIES = {LEGACY_EFFORT_POLICY, STAGE_EFFORT_POLICY}
MIN_LEASE_SECONDS = 900
ALLOWED_TOPICS = {
    "Algebra",
    "Combinatorics",
    "Geometry",
    "Number Theory",
    "Precalculus",
    "Probability",
}
INTERACTION_TYPES = {
    "feeds",
    "transforms_into",
    "dual_representation",
    "certifies",
    "forces_structure",
    "counts_same_object",
}
BRIDGE_DESCRIPTIVE_FIELDS = {
    "bridge_id",
    "shared_object",
    "interaction_type",
    "crux",
    "technique_roles",
    "proof_sketch",
    "problem_shape",
    "integer_answer_route",
}
SHELL_DIVERSITY_AXES = {
    "mathematical_object",
    "target_quantity",
    "quantifier",
    "constraint_interaction",
    "direction_of_inference",
    "representation",
}
BLIND_BYPASS_TYPES = {
    "none",
    "direct_enumeration",
    "standard_formula",
    "one_technique",
    "coordinate_bash",
    "symbolic_bash",
    "symmetry",
    "other",
}
BLIND_DIFFICULTY_BANDS = {
    "below_aime",
    "easy_aime",
    "mid_aime",
    "late_aime",
    "olympiad",
}
TERMINAL_STATUSES = {
    CombinationJobStatus.STORED,
    CombinationJobStatus.REJECTED,
    CombinationJobStatus.EXHAUSTED,
}
V1_PROMPT_VERSIONS = {
    "bridge": BRIDGE_PROMPT,
    "bridge_judge": BRIDGE_JUDGE_PROMPT,
    "problem": PROBLEM_PROMPT,
    "preflight": FAITHFULNESS_PROMPT,
}
V2_PROMPT_VERSIONS = {
    "bridge": BRIDGE_PROMPT,
    "bridge_judge": BRIDGE_JUDGE_PROMPT,
    "shell": SHELL_PROMPT,
    "shell_judge": SHELL_JUDGE_PROMPT,
    "problem": PROBLEM_PROMPT_V2,
    "blind_audit": BLIND_AUDIT_PROMPT,
    "preflight": FAITHFULNESS_PROMPT_V2,
    "repair": CREATIVITY_REPAIR_PROMPT,
}
SUPPORTED_PROMPT_VERSIONS = {
    PIPELINE_V1: V1_PROMPT_VERSIONS,
    PIPELINE_V2: V2_PROMPT_VERSIONS,
}
JSON_ONLY_SYSTEM = (
    "You are a strict JSON API. Perform all mathematical analysis in private "
    "thinking. Your visible response must be exactly one valid JSON object: "
    "the first character must be { and the last character must be }. Never "
    "include prose, Markdown, or code fences outside that object."
)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _name_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    normalized = normalized.replace("&", " and ")
    return "".join(character for character in normalized if character.isalnum())


def _phrase_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    return " ".join(re.findall(r"[a-z0-9]+", normalized))


def _pair_key(first: str, second: str) -> str:
    return "+".join(sorted((first, second)))


def _pair_tuple(first: str, second: str) -> tuple[str, str]:
    return tuple(sorted((first, second)))  # type: ignore[return-value]


def _json_hash(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validated_difficulty_band(
    value: Any, *, label: str = "target_difficulty"
) -> tuple[float, float]:
    """Return a finite, ordered competition difficulty band in ``[1, 10]``."""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{label} must contain exactly two numeric values")
    if any(isinstance(item, bool) for item in value):
        raise ValueError(f"{label} must contain exactly two numeric values")
    try:
        low, high = float(value[0]), float(value[1])
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must contain exactly two numeric values") from exc
    if not math.isfinite(low) or not math.isfinite(high):
        raise ValueError(f"{label} values must be finite")
    if not 1.0 <= low <= high <= 10.0:
        raise ValueError(f"{label} must satisfy 1 <= low <= high <= 10")
    return low, high


def _validated_lease_seconds(config: dict[str, Any]) -> int:
    raw = config.get("lease_seconds", 1200)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError("lease_seconds must be an integer")
    value = raw
    if value < MIN_LEASE_SECONDS:
        raise ValueError(
            f"lease_seconds must be at least {MIN_LEASE_SECONDS} so a live "
            "provider call cannot be stolen before its configured timeout"
        )
    return value


@dataclass(frozen=True)
class TechniqueContext:
    """One raw taxonomy row retained as a possible context for a canonical node."""

    id: str
    name: str
    area: str
    family: str
    one_liner: str
    trigger: str
    objects: tuple[str, ...]
    mechanism: str
    difficulty_band: tuple[float, float]
    example_crux: str
    avoid_with: tuple[str, ...]

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> "TechniqueContext":
        band = raw["difficulty_band"] if "difficulty_band" in raw else [1, 10]
        validated_band = _validated_difficulty_band(
            band, label=f"difficulty_band for technique {raw.get('id') or '<unknown>'}"
        )
        combinability = raw.get("combinability") or {}
        return cls(
            id=str(raw.get("id") or "").strip(),
            name=str(raw.get("name") or "").strip(),
            area=str(raw.get("area") or "Unknown").strip(),
            family=str(raw.get("family") or "").strip(),
            one_liner=str(raw.get("one_liner") or "").strip(),
            trigger=str(raw.get("trigger") or "").strip(),
            objects=tuple(sorted({str(item) for item in raw.get("objects") or []})),
            mechanism=str(raw.get("mechanism") or "").strip(),
            difficulty_band=validated_band,
            example_crux=str(raw.get("example_crux") or "").strip(),
            avoid_with=tuple(sorted({str(item) for item in combinability.get("avoid_with") or []})),
        )


@dataclass(frozen=True)
class CanonicalTechnique:
    id: str
    name: str
    aliases: tuple[str, ...]
    contexts: tuple[TechniqueContext, ...]


@dataclass(frozen=True)
class TechniqueCatalog:
    techniques: dict[str, CanonicalTechnique]
    alias_map: dict[str, str]
    taxonomy_sha256: str
    alias_version: str = ALIAS_VERSION
    object_df: dict[str, int] = field(default_factory=dict)

    def canonical_id(self, raw_or_canonical_id: str) -> Optional[str]:
        if raw_or_canonical_id in self.techniques:
            return raw_or_canonical_id
        return self.alias_map.get(raw_or_canonical_id)


@dataclass
class PairEvidence:
    support: Counter[str] = field(default_factory=Counter)
    pair_support: Counter[tuple[str, str]] = field(default_factory=Counter)
    trusted_pair_support: Counter[tuple[str, str]] = field(default_factory=Counter)
    evidence_ids: dict[tuple[str, str], list[str]] = field(default_factory=dict)
    topic_counts: dict[tuple[str, str], Counter[str]] = field(default_factory=dict)
    snapshot_hash: str = ""


@dataclass(frozen=True)
class PairCandidate:
    pair_key: str
    technique_ids: tuple[str, str]
    contexts: tuple[TechniqueContext, TechniqueContext]
    tranche: str
    support_a: int
    support_b: int
    pair_support: int
    trusted_pair_support: int
    shared_objects: tuple[str, ...]
    area_pair: tuple[str, str]
    mechanism_pair: tuple[str, str]
    difficulty_overlap: tuple[float, float]
    evidence_ids: tuple[str, ...]
    topic_counts: dict[str, int]
    weight: float
    weight_components: dict[str, float]

    def snapshots(self, catalog: TechniqueCatalog) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        supports = (self.support_a, self.support_b)
        for canonical_id, context, support in zip(
            self.technique_ids, self.contexts, supports
        ):
            canonical = catalog.techniques[canonical_id]
            result.append(
                {
                    "id": canonical_id,
                    "context_id": context.id,
                    "name": context.name,
                    "aliases": list(canonical.aliases),
                    "area": context.area,
                    "family": context.family,
                    "one_liner": context.one_liner,
                    "trigger": context.trigger,
                    "objects": list(context.objects),
                    "mechanism": context.mechanism,
                    "difficulty_band": list(context.difficulty_band),
                    "example_crux": context.example_crux,
                    "support": support,
                }
            )
        return result


@dataclass(frozen=True)
class PlannedPair:
    candidate: PairCandidate
    draw_index: int
    requested_tranche: str
    relaxation_level: int
    priority: float


@dataclass(frozen=True)
class PairHistoryEntry:
    pair_key: str
    technique_ids: tuple[str, str]
    area_pair: tuple[str, str]
    failed: bool = False


@dataclass
class ComboRunReport:
    run_id: str
    total: int = 0
    stored: int = 0
    rejected: int = 0
    exhausted: int = 0
    pending: int = 0
    records: list[dict[str, Any]] = field(default_factory=list)


class ContractError(ValueError):
    """A model response violated an exact stage contract."""


class LeaseLostError(RuntimeError):
    """A stale worker tried to checkpoint after another worker took its lease."""


def load_technique_catalog(path: Path | str = Path("data/techniques.json")) -> TechniqueCatalog:
    """Load and exact-name-canonicalize the raw technique taxonomy.

    Canonical IDs are the lexicographically first raw ID in each frozen
    NFKC/casefold name group.  Every job also stores the taxonomy hash and full
    selected contexts, so future taxonomy edits cannot mutate a resumed job.
    """
    path = Path(path)
    raw_bytes = path.read_bytes()
    rows = json.loads(raw_bytes)
    if not isinstance(rows, list):
        raise ValueError("technique taxonomy must be a JSON array")

    grouped: dict[str, list[TechniqueContext]] = defaultdict(list)
    seen_ids: set[str] = set()
    for raw in rows:
        if not isinstance(raw, dict):
            raise ValueError("every technique taxonomy row must be an object")
        context = TechniqueContext.from_raw(raw)
        if not context.id or not context.name:
            raise ValueError("every technique requires nonempty id and name")
        if context.id in seen_ids:
            raise ValueError(f"duplicate raw technique id: {context.id}")
        seen_ids.add(context.id)
        grouped[_name_key(context.name)].append(context)

    techniques: dict[str, CanonicalTechnique] = {}
    alias_map: dict[str, str] = {}
    for contexts in grouped.values():
        contexts = sorted(contexts, key=lambda item: item.id)
        canonical_id = contexts[0].id
        aliases = tuple(context.id for context in contexts)
        technique = CanonicalTechnique(
            id=canonical_id,
            name=contexts[0].name,
            aliases=aliases,
            contexts=tuple(contexts),
        )
        techniques[canonical_id] = technique
        alias_map.update({alias: canonical_id for alias in aliases})

    object_df: Counter[str] = Counter()
    for technique in techniques.values():
        objects = {obj for context in technique.contexts for obj in context.objects}
        object_df.update(objects)
    return TechniqueCatalog(
        techniques=techniques,
        alias_map=alias_map,
        taxonomy_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        object_df=dict(object_df),
    )


def _problem_techniques(problem: Problem, catalog: TechniqueCatalog) -> set[str]:
    provenance = problem.provenance or {}
    raw = (
        provenance.get("required_techniques")
        or provenance.get("inferred_techniques")
        or provenance.get("techniques")
        or []
    )
    result: set[str] = set()
    for value in raw if isinstance(raw, list) else []:
        canonical = catalog.canonical_id(str(value))
        if canonical:
            result.add(canonical)
    return result


def build_pair_evidence(
    catalog: TechniqueCatalog,
    db_url: Optional[str] = None,
) -> PairEvidence:
    """Recompute technique and pair support from distinct train-only groups."""
    db.init_db(db_url)
    with db.session_scope(db_url) as session:
        rows = [
            problem
            for problem in deduplicated_training_problems(session)
            if is_export_eligible(problem)
        ]

    evidence = PairEvidence()
    evidence_ids: dict[tuple[str, str], list[str]] = defaultdict(list)
    topics: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for problem in rows:
        tags = _problem_techniques(problem, catalog)
        if not tags:
            continue
        tags = sorted(tags)
        evidence.support.update(tags)
        for first, second in combinations(tags, 2):
            pair = _pair_tuple(first, second)
            evidence.pair_support[pair] += 1
            # Every retained row is either an official source or a verified and
            # human-accepted synthetic positive.
            evidence.trusted_pair_support[pair] += 1
            evidence_ids[pair].append(problem.id)
            if problem.topic:
                topics[pair][problem.topic] += 1

    evidence.evidence_ids = {
        pair: list(dict.fromkeys(problem_ids))[:3]
        for pair, problem_ids in evidence_ids.items()
    }
    evidence.topic_counts = dict(topics)
    evidence.snapshot_hash = _json_hash(
        {
            "support": dict(sorted(evidence.support.items())),
            "pair_support": {
                "+".join(pair): value
                for pair, value in sorted(evidence.pair_support.items())
            },
            "trusted_pair_support": {
                "+".join(pair): value
                for pair, value in sorted(evidence.trusted_pair_support.items())
            },
        }
    )
    return evidence


def _difficulty_overlap(
    first: TechniqueContext, second: TechniqueContext, target: tuple[float, float]
) -> tuple[float, float]:
    low = max(first.difficulty_band[0], second.difficulty_band[0], target[0])
    high = min(first.difficulty_band[1], second.difficulty_band[1], target[1])
    return (low, high)


def _context_pair(
    catalog: TechniqueCatalog,
    first: CanonicalTechnique,
    second: CanonicalTechnique,
    target: tuple[float, float],
) -> tuple[TechniqueContext, TechniqueContext, dict[str, Any]]:
    total = max(1, len(catalog.techniques))
    ranked: list[
        tuple[
            int,
            float,
            str,
            str,
            TechniqueContext,
            TechniqueContext,
            dict[str, Any],
        ]
    ] = []
    for left in first.contexts:
        for right in second.contexts:
            shared = tuple(sorted(set(left.objects) & set(right.objects)))
            overlap = _difficulty_overlap(left, right, target)
            idf_values = [
                math.log((total + 1) / (catalog.object_df.get(obj, total) + 1))
                for obj in shared
            ]
            object_score = sum(idf_values)
            overlap_width = max(0.0, overlap[1] - overlap[0])
            score = object_score + 0.25 * len(shared) + min(2.0, overlap_width / 2)
            score += 0.75 if left.mechanism != right.mechanism else 0.0
            score += 0.25 if left.area == right.area else 0.0
            ranked.append(
                (
                    0 if overlap[0] <= overlap[1] else 1,
                    -score,
                    left.id,
                    right.id,
                    left,
                    right,
                    {
                        "shared_objects": shared,
                        "difficulty_overlap": overlap,
                        "object_specificity": min(
                            2.0,
                            1.0
                            + (max(idf_values, default=0.0) / 4.0)
                            + 0.1 * max(0, len(shared) - 1),
                        ),
                    },
                )
            )
    ranked.sort(key=lambda item: (item[0], item[1], item[2], item[3]))
    _, _, _, _, left, right, metadata = ranked[0]
    return left, right, metadata


def _avoids(
    catalog: TechniqueCatalog,
    first: CanonicalTechnique,
    second: CanonicalTechnique,
) -> bool:
    for context in first.contexts:
        if any(catalog.canonical_id(value) == second.id for value in context.avoid_with):
            return True
    for context in second.contexts:
        if any(catalog.canonical_id(value) == first.id for value in context.avoid_with):
            return True
    return False


def _rarity(support: int) -> float:
    return min(2.0, math.sqrt(9.0 / (min(max(support, 0), 8) + 1)))


def build_pair_candidates(
    catalog: TechniqueCatalog,
    evidence: PairEvidence,
    *,
    target_difficulty: tuple[float, float] = (4.0, 8.0),
    prior_attempt_counts: Optional[Counter[str]] = None,
) -> list[PairCandidate]:
    """Create observed, structured-novel, and bounded-exploration pools."""
    target_difficulty = _validated_difficulty_band(target_difficulty)
    prior_attempt_counts = prior_attempt_counts or Counter()
    observed_contexts: dict[tuple[str, str], tuple[TechniqueContext, TechniqueContext, dict[str, Any]]] = {}
    area_prior: Counter[tuple[str, str]] = Counter()
    mechanism_prior: Counter[tuple[str, str]] = Counter()
    for pair, count in evidence.pair_support.items():
        if pair[0] not in catalog.techniques or pair[1] not in catalog.techniques:
            continue
        context = _context_pair(
            catalog,
            catalog.techniques[pair[0]],
            catalog.techniques[pair[1]],
            target_difficulty,
        )
        observed_contexts[pair] = context
        left, right, _ = context
        area_prior[_pair_tuple(left.area, right.area)] += count
        mechanism_prior[_pair_tuple(left.mechanism, right.mechanism)] += count

    candidates: list[PairCandidate] = []
    canonical_ids = sorted(catalog.techniques)
    for first_id, second_id in combinations(canonical_ids, 2):
        first = catalog.techniques[first_id]
        second = catalog.techniques[second_id]
        if _avoids(catalog, first, second):
            continue
        pair = _pair_tuple(first_id, second_id)
        left, right, context_meta = observed_contexts.get(pair) or _context_pair(
            catalog, first, second, target_difficulty
        )
        shared = tuple(context_meta["shared_objects"])
        overlap = tuple(context_meta["difficulty_overlap"])
        mechanisms_differ = bool(left.mechanism and right.mechanism and left.mechanism != right.mechanism)
        difficulty_ok = overlap[0] <= overlap[1]
        support_a = evidence.support[first_id]
        support_b = evidence.support[second_id]
        observed = evidence.pair_support[pair]
        area_pair = _pair_tuple(left.area, right.area)
        mechanism_pair = _pair_tuple(left.mechanism, right.mechanism)

        tranche: Optional[str] = None
        if observed and difficulty_ok:
            tranche = "observed"
        elif shared and mechanisms_differ and difficulty_ok:
            structured_context = (
                left.area == right.area or area_prior[area_pair] >= 2
            ) and mechanism_prior[mechanism_pair] >= 2
            if support_a >= 3 and support_b >= 3 and structured_context:
                tranche = "structured"
            elif structured_context and (
                (support_a >= 5 and 1 <= support_b <= 2)
                or (support_b >= 5 and 1 <= support_a <= 2)
            ):
                tranche = "explore_rare"
            elif structured_context and (
                (support_a >= 10 and support_b == 0)
                or (support_b >= 10 and support_a == 0)
            ):
                tranche = "explore_gap"
        if tranche is None:
            continue

        rarity = math.sqrt(_rarity(support_a) * _rarity(support_b))
        evidence_factor = (
            1.0 + min(2.0, math.log2(observed + 1)) if observed else 1.0
        )
        trusted_bonus = 1.15 if evidence.trusted_pair_support[pair] else 1.0
        object_specificity = float(context_meta["object_specificity"])
        attempt_penalty = 1.0 / math.sqrt(1 + prior_attempt_counts[_pair_key(*pair)])
        weight = rarity * evidence_factor * trusted_bonus * object_specificity * attempt_penalty
        candidates.append(
            PairCandidate(
                pair_key=_pair_key(*pair),
                technique_ids=pair,
                contexts=(left, right),
                tranche=tranche,
                support_a=support_a,
                support_b=support_b,
                pair_support=observed,
                trusted_pair_support=evidence.trusted_pair_support[pair],
                shared_objects=shared,
                area_pair=area_pair,
                mechanism_pair=mechanism_pair,
                difficulty_overlap=(float(overlap[0]), float(overlap[1])),
                evidence_ids=tuple(evidence.evidence_ids.get(pair, [])),
                topic_counts=dict(evidence.topic_counts.get(pair, {})),
                weight=max(weight, 1e-9),
                weight_components={
                    "rarity": rarity,
                    "evidence": evidence_factor,
                    "trusted_bonus": trusted_bonus,
                    "object_specificity": object_specificity,
                    "attempt_penalty": attempt_penalty,
                },
            )
        )
    return candidates


def _quota_labels(count: int) -> list[str]:
    # Allocate the 10% exploration tranche first, then alternate its two bounded
    # forms.  This preserves the overall 65/25/10 mix for small pilots while
    # converging to an exact 5% rare / 5% gap split for even exploration quotas.
    proportions = {"observed": 0.65, "structured": 0.25, "explore": 0.10}
    raw = {name: count * value for name, value in proportions.items()}
    quotas = {name: int(math.floor(value)) for name, value in raw.items()}
    remaining = count - sum(quotas.values())
    order = {name: index for index, name in enumerate(proportions)}
    for name in sorted(
        proportions, key=lambda item: (-(raw[item] - quotas[item]), order[item])
    )[:remaining]:
        quotas[name] += 1

    labels: list[str] = []
    used = Counter()
    for index in range(count):
        eligible = [name for name in proportions if used[name] < quotas[name]]
        chosen = max(
            eligible,
            key=lambda name: (
                proportions[name] * (index + 1) - used[name],
                -order[name],
            ),
        )
        used[chosen] += 1
        labels.append(chosen)
    explore_index = 0
    split_labels: list[str] = []
    for label in labels:
        if label == "explore":
            split_labels.append(
                "explore_gap" if explore_index % 2 == 0 else "explore_rare"
            )
            explore_index += 1
        else:
            split_labels.append(label)
    return split_labels


def _hash_priority(
    seed: int, snapshot_hash: str, draw_index: int, pair_key: str, weight: float
) -> float:
    digest = hashlib.sha256(
        f"{seed}|{snapshot_hash}|{draw_index}|{pair_key}".encode("utf-8")
    ).digest()
    integer = int.from_bytes(digest, "big")
    uniform = (integer + 1) / (2 ** (8 * len(digest)) + 1)
    return -math.log(uniform) / max(weight, 1e-12)


def _history_allows(
    candidate: PairCandidate,
    history: list[PairHistoryEntry],
    relaxation: int,
) -> bool:
    pair_window = 100 if relaxation < 4 else 50
    if any(item.pair_key == candidate.pair_key for item in history[-pair_window:]):
        return False
    if relaxation < 3:
        recent_techniques = {
            technique for item in history[-3:] for technique in item.technique_ids
        }
        if recent_techniques & set(candidate.technique_ids):
            return False
    if relaxation < 2:
        counts = Counter(
            technique for item in history[-20:] for technique in item.technique_ids
        )
        if any(counts[technique] >= 2 for technique in candidate.technique_ids):
            return False
    if relaxation < 1:
        area_counts = Counter(item.area_pair for item in history[-20:])
        if area_counts[candidate.area_pair] >= 4:
            return False
    return True


def plan_pairs(
    candidates: list[PairCandidate],
    *,
    count: int,
    seed: int,
    snapshot_hash: str,
    history: Optional[list[PairHistoryEntry]] = None,
    failed_counts: Optional[Counter[str]] = None,
) -> list[PlannedPair]:
    """Plan a whole deterministic batch before any model calls are launched."""
    if count < 1:
        return []
    history = list(history or [])
    failed_counts = failed_counts or Counter()
    selected: list[PlannedPair] = []
    selected_keys: set[str] = set()

    for draw_index, requested in enumerate(_quota_labels(count)):
        def matches(candidate: PairCandidate, label: str) -> bool:
            return candidate.tranche == label

        chosen: Optional[tuple[PairCandidate, int, float]] = None
        for allow_fallback in (False, True):
            for relaxation in range(5):
                pool = [
                    candidate
                    for candidate in candidates
                    if candidate.pair_key not in selected_keys
                    and failed_counts[candidate.pair_key] < 3
                    and (matches(candidate, requested) or allow_fallback)
                    and _history_allows(candidate, history, relaxation)
                ]
                if not pool:
                    continue
                ranked = [
                    (
                        _hash_priority(
                            seed,
                            snapshot_hash,
                            draw_index,
                            candidate.pair_key,
                            candidate.weight,
                        ),
                        candidate.pair_key,
                        candidate,
                    )
                    for candidate in pool
                ]
                priority, _, candidate = min(ranked, key=lambda item: (item[0], item[1]))
                chosen = (candidate, relaxation, priority)
                break
            if chosen:
                break
        if chosen is None:
            raise ValueError(f"pair sampler exhausted at draw {draw_index}")
        candidate, relaxation, priority = chosen
        planned = PlannedPair(
            candidate=candidate,
            draw_index=draw_index,
            requested_tranche=requested,
            relaxation_level=relaxation,
            priority=priority,
        )
        selected.append(planned)
        selected_keys.add(candidate.pair_key)
        history.append(
            PairHistoryEntry(
                pair_key=candidate.pair_key,
                technique_ids=candidate.technique_ids,
                area_pair=candidate.area_pair,
            )
        )
    return selected


def _reject_constant(value: str) -> None:
    raise ContractError(f"non-finite JSON constant is forbidden: {value}")


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def strict_json_object(text: str) -> dict[str, Any]:
    """Parse one strict JSON object, rejecting prose, fences, duplicates and NaN."""
    source = (text or "").strip()
    if not source.startswith("{") or not source.endswith("}"):
        raise ContractError("response must contain exactly one bare JSON object")
    try:
        value = json.loads(
            source,
            object_pairs_hook=_no_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except ContractError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ContractError(f"invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError("top-level JSON value must be an object")
    return value


def _exact_keys(value: dict[str, Any], expected: set[str], path: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ContractError(f"{path} keys mismatch; missing={missing}, extra={extra}")


def _text(value: Any, path: str, minimum: int = 1) -> str:
    if not isinstance(value, str) or len(value.strip()) < minimum:
        raise ContractError(f"{path} must be a nonempty string")
    return value.strip()


def _score(value: Any, path: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ContractError(f"{path} must be an integer in [{low}, {high}]")
    return value


def parse_bridge_proposals(
    text: str, technique_ids: tuple[str, str], bridge_count: int = 3
) -> dict[str, Any]:
    data = strict_json_object(text)
    _exact_keys(data, {"schema_version", "technique_ids", "candidates"}, "root")
    if data["schema_version"] != BRIDGE_PROMPT:
        raise ContractError("wrong bridge schema_version")
    if data["technique_ids"] != list(technique_ids):
        raise ContractError("bridge technique_ids must match the exact ordered pair")
    candidates = data["candidates"]
    if not isinstance(candidates, list) or len(candidates) != bridge_count:
        raise ContractError(f"candidates must contain exactly {bridge_count} objects")
    expected_ids = {f"b{index}" for index in range(1, bridge_count + 1)}
    seen: set[str] = set()
    seen_cruxes: set[str] = set()
    fields = {
        "bridge_id", "shared_object", "interaction_type", "crux",
        "technique_roles", "proof_sketch", "problem_shape",
        "integer_answer_route", "naturalness", "surprise", "feasibility",
        "stapling_risk", "memorization_risk",
    }
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            raise ContractError(f"candidates[{index}] must be an object")
        _exact_keys(candidate, fields, f"candidates[{index}]")
        bridge_id = _text(candidate["bridge_id"], f"candidates[{index}].bridge_id")
        seen.add(bridge_id)
        _text(candidate["shared_object"], f"candidates[{index}].shared_object", minimum=3)
        interaction_type = _text(
            candidate["interaction_type"], f"candidates[{index}].interaction_type"
        )
        if interaction_type not in INTERACTION_TYPES:
            raise ContractError(f"unsupported interaction_type: {interaction_type}")
        for name in ("crux", "proof_sketch", "problem_shape", "integer_answer_route"):
            _text(candidate[name], f"candidates[{index}].{name}", minimum=8)
        crux_key = _phrase_key(candidate["crux"])
        if crux_key in seen_cruxes:
            raise ContractError("bridge candidates must have distinct cruxes")
        seen_cruxes.add(crux_key)
        roles = candidate["technique_roles"]
        if not isinstance(roles, dict):
            raise ContractError(f"candidates[{index}].technique_roles must be an object")
        _exact_keys(roles, set(technique_ids), f"candidates[{index}].technique_roles")
        for technique_id in technique_ids:
            _text(roles[technique_id], f"roles.{technique_id}", minimum=8)
        for name in ("naturalness", "surprise", "feasibility"):
            _score(candidate[name], f"candidates[{index}].{name}", 1, 5)
        for name in ("stapling_risk", "memorization_risk"):
            _score(candidate[name], f"candidates[{index}].{name}", 0, 5)
    if seen != expected_ids:
        raise ContractError(f"bridge IDs must be exactly {sorted(expected_ids)}")
    return data


def _bridge_score(evaluation: dict[str, Any]) -> int:
    return (
        2 * evaluation["interaction"]
        + 2 * evaluation["essentiality"]
        + evaluation["soundness"]
        + evaluation["naturalness"]
        + evaluation["surprise"]
        + evaluation["generativity"]
        + evaluation["contest_fit"]
        - 2 * evaluation["stapling_risk"]
        - evaluation["known_problem_risk"]
    )


def parse_bridge_judgment(
    text: str, bridge_ids: tuple[str, ...]
) -> dict[str, Any]:
    data = strict_json_object(text)
    _exact_keys(
        data,
        {"schema_version", "evaluations", "selected_bridge_id", "reject_all"},
        "root",
    )
    if data["schema_version"] != BRIDGE_JUDGE_PROMPT:
        raise ContractError("wrong bridge-judge schema_version")
    if not isinstance(data["reject_all"], bool):
        raise ContractError("reject_all must be boolean")
    evaluations = data["evaluations"]
    if not isinstance(evaluations, list) or len(evaluations) != len(bridge_ids):
        raise ContractError("judge must evaluate every bridge exactly once")
    fields = {
        "bridge_id", "soundness", "interaction", "naturalness", "essentiality",
        "surprise", "generativity", "contest_fit", "stapling_risk",
        "known_problem_risk", "fatal_issue", "verdict", "reason",
    }
    by_id: dict[str, dict[str, Any]] = {}
    eligible: list[dict[str, Any]] = []
    for index, evaluation in enumerate(evaluations):
        if not isinstance(evaluation, dict):
            raise ContractError(f"evaluations[{index}] must be an object")
        _exact_keys(evaluation, fields, f"evaluations[{index}]")
        bridge_id = _text(evaluation["bridge_id"], f"evaluations[{index}].bridge_id")
        if bridge_id in by_id:
            raise ContractError(f"duplicate bridge evaluation: {bridge_id}")
        for name in (
            "soundness", "interaction", "naturalness", "essentiality", "surprise",
            "generativity", "contest_fit", "stapling_risk", "known_problem_risk",
        ):
            _score(evaluation[name], f"evaluations[{index}].{name}", 0, 5)
        if evaluation["fatal_issue"] is not None:
            _text(evaluation["fatal_issue"], f"evaluations[{index}].fatal_issue")
        if evaluation["verdict"] not in {"keep", "reject"}:
            raise ContractError("bridge verdict must be keep or reject")
        _text(evaluation["reason"], f"evaluations[{index}].reason")
        evaluation["computed_score"] = _bridge_score(evaluation)
        by_id[bridge_id] = evaluation
        component_gate_pass = (
            evaluation["fatal_issue"] is None
            and evaluation["soundness"] >= 4
            and evaluation["interaction"] >= 4
            and evaluation["essentiality"] >= 4
            and evaluation["naturalness"] >= 3
            and evaluation["surprise"] >= 3
            and evaluation["generativity"] >= 3
            and evaluation["contest_fit"] >= 3
            and evaluation["stapling_risk"] <= 1
            and evaluation["known_problem_risk"] <= 3
        )
        evaluation["reported_verdict"] = evaluation["verdict"]
        evaluation["reported_verdict_consistent"] = not (
            evaluation["verdict"] == "keep" and not component_gate_pass
        )
        evaluation["computed_eligible"] = bool(
            evaluation["verdict"] == "keep" and component_gate_pass
        )
        if evaluation["computed_eligible"]:
            eligible.append(evaluation)
    if set(by_id) != set(bridge_ids):
        raise ContractError("evaluated bridge IDs do not match proposals")
    winner = (
        sorted(eligible, key=lambda item: (-item["computed_score"], item["bridge_id"]))[0]["bridge_id"]
        if eligible
        else None
    )
    eligible_ids = {evaluation["bridge_id"] for evaluation in eligible}
    selected_bridge_id = data["selected_bridge_id"]
    if selected_bridge_id is not None:
        _text(selected_bridge_id, "selected_bridge_id")
        if selected_bridge_id not in set(bridge_ids):
            raise ContractError("selected_bridge_id must name an evaluated bridge")
    selected_consistent = (
        selected_bridge_id is None
        if winner is None
        else selected_bridge_id in eligible_ids
    )
    reject_all_consistent = data["reject_all"] == (winner is None)
    data["reported_selected_bridge_id"] = data["selected_bridge_id"]
    data["reported_selected_bridge_id_consistent"] = selected_consistent
    data["reported_reject_all"] = data["reject_all"]
    data["reported_reject_all_consistent"] = reject_all_consistent
    data["reported_decision_consistent"] = (
        selected_consistent and reject_all_consistent
    )
    data["computed_selected_bridge_id"] = winner
    return data


def parse_shell_proposals(
    text: str,
    selected_bridge_id: str,
    technique_ids: tuple[str, str],
    difficulty_band: tuple[float, float],
    shell_count: int = 4,
) -> dict[str, Any]:
    """Parse four structurally distinct shells for one accepted bridge."""
    data = strict_json_object(text)
    _exact_keys(
        data,
        {
            "schema_version",
            "bridge_id",
            "technique_ids",
            "canonical_shape_to_avoid",
            "shells",
        },
        "root",
    )
    if data["schema_version"] != SHELL_PROMPT:
        raise ContractError("wrong shell-generation schema_version")
    if data["bridge_id"] != selected_bridge_id:
        raise ContractError("shell bridge_id does not match the selected bridge")
    if data["technique_ids"] != list(technique_ids):
        raise ContractError("shell technique_ids must match the exact ordered pair")
    _text(data["canonical_shape_to_avoid"], "canonical_shape_to_avoid", 12)
    shells = data["shells"]
    if not isinstance(shells, list) or len(shells) != shell_count:
        raise ContractError(f"shells must contain exactly {shell_count} objects")
    expected_ids = {f"s{index}" for index in range(1, shell_count + 1)}
    fields = {
        "shell_id",
        "diversity_axis",
        "premise",
        "target",
        "structural_twist",
        "shared_object",
        "fused_crux",
        "novelty_delta",
        "anti_copy_check",
        "technique_necessity",
        "shortest_expected_route",
        "routine_bypass_tested",
        "integer_answer_route",
        "existence_uniqueness_plan",
        "estimated_difficulty",
        "naturalness",
        "surprise",
        "feasibility",
        "known_problem_risk",
        "routine_bypass_risk",
    }
    low, high = _validated_difficulty_band(difficulty_band)
    seen_ids: set[str] = set()
    seen_axes: set[str] = set()
    seen_cruxes: set[str] = set()
    for index, shell in enumerate(shells):
        if not isinstance(shell, dict):
            raise ContractError(f"shells[{index}] must be an object")
        _exact_keys(shell, fields, f"shells[{index}]")
        shell_id = _text(shell["shell_id"], f"shells[{index}].shell_id")
        seen_ids.add(shell_id)
        axis = _text(shell["diversity_axis"], f"shells[{index}].diversity_axis")
        if axis not in SHELL_DIVERSITY_AXES:
            raise ContractError(f"unsupported shell diversity_axis: {axis}")
        if axis in seen_axes:
            raise ContractError("shell diversity_axis values must be distinct")
        seen_axes.add(axis)
        for name in (
            "premise",
            "target",
            "structural_twist",
            "shared_object",
            "fused_crux",
            "novelty_delta",
            "anti_copy_check",
            "shortest_expected_route",
            "routine_bypass_tested",
            "integer_answer_route",
            "existence_uniqueness_plan",
        ):
            _text(shell[name], f"shells[{index}].{name}", 8)
        crux_key = _phrase_key(shell["fused_crux"])
        if crux_key in seen_cruxes:
            raise ContractError("shell fused_crux values must be distinct")
        seen_cruxes.add(crux_key)
        necessity = shell["technique_necessity"]
        if not isinstance(necessity, dict):
            raise ContractError("technique_necessity must be an object")
        _exact_keys(necessity, set(technique_ids), "technique_necessity")
        for technique_id in technique_ids:
            role = necessity[technique_id]
            if not isinstance(role, dict):
                raise ContractError(
                    f"technique_necessity.{technique_id} must be an object"
                )
            _exact_keys(
                role,
                {"load_bearing_role", "counterfactual_without"},
                f"technique_necessity.{technique_id}",
            )
            _text(
                role["load_bearing_role"],
                f"technique_necessity.{technique_id}.load_bearing_role",
                8,
            )
            _text(
                role["counterfactual_without"],
                f"technique_necessity.{technique_id}.counterfactual_without",
                8,
            )
        raw_difficulty = shell["estimated_difficulty"]
        if isinstance(raw_difficulty, bool):
            raise ContractError("estimated_difficulty must be a finite number")
        try:
            estimated_difficulty = float(raw_difficulty)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ContractError("estimated_difficulty must be a finite number") from exc
        if (
            not math.isfinite(estimated_difficulty)
            or not 1 <= estimated_difficulty <= 10
            or not low <= estimated_difficulty <= high
        ):
            raise ContractError(
                f"estimated_difficulty must be inside target band [{low:g}, {high:g}]"
            )
        for name in (
            "naturalness",
            "surprise",
            "feasibility",
            "known_problem_risk",
            "routine_bypass_risk",
        ):
            _score(shell[name], f"shells[{index}].{name}", 0, 5)
    if seen_ids != expected_ids:
        raise ContractError(f"shell IDs must be exactly {sorted(expected_ids)}")
    return data


def parse_shell_judgment(
    text: str,
    shell_ids: tuple[str, ...],
    technique_ids: tuple[str, str],
    *,
    creativity_floor: int = 4,
) -> dict[str, Any]:
    """Parse validity-first shell judgments and compute the deterministic winner."""
    if (
        isinstance(creativity_floor, bool)
        or not isinstance(creativity_floor, int)
        or not 0 <= creativity_floor <= 5
    ):
        raise ContractError("creativity_floor must be an integer in [0, 5]")
    data = strict_json_object(text)
    _exact_keys(
        data,
        {
            "schema_version",
            "evaluations",
            "selected_shell_id",
            "reject_all",
            "selection_reason",
        },
        "root",
    )
    if data["schema_version"] != SHELL_JUDGE_PROMPT:
        raise ContractError("wrong shell-judge schema_version")
    if not isinstance(data["reject_all"], bool):
        raise ContractError("shell reject_all must be boolean")
    _text(data["selection_reason"], "selection_reason", 5)
    evaluations = data["evaluations"]
    if not isinstance(evaluations, list) or len(evaluations) != len(shell_ids):
        raise ContractError("shell judge must evaluate every shell exactly once")
    fields = {
        "shell_id",
        "bridge_sound",
        "integer_answer_feasible",
        "existence_supported",
        "uniqueness_supported",
        "fatal_issue",
        "copies_canonical_shape",
        "routine_bypass",
        "soundness",
        "interaction",
        "essentiality",
        "novelty_delta",
        "surprise",
        "naturalness",
        "contest_fit",
        "known_problem_risk",
        "routine_bypass_risk",
        "technique_checks",
        "verdict",
        "reason",
    }
    by_id: dict[str, dict[str, Any]] = {}
    eligible: list[dict[str, Any]] = []
    for index, evaluation in enumerate(evaluations):
        if not isinstance(evaluation, dict):
            raise ContractError(f"evaluations[{index}] must be an object")
        _exact_keys(evaluation, fields, f"evaluations[{index}]")
        shell_id = _text(evaluation["shell_id"], f"evaluations[{index}].shell_id")
        if shell_id in by_id:
            raise ContractError(f"duplicate shell evaluation: {shell_id}")
        for name in (
            "bridge_sound",
            "integer_answer_feasible",
            "existence_supported",
            "uniqueness_supported",
            "copies_canonical_shape",
            "routine_bypass",
        ):
            if not isinstance(evaluation[name], bool):
                raise ContractError(f"{name} must be boolean")
        if evaluation["fatal_issue"] is not None:
            _text(evaluation["fatal_issue"], f"evaluations[{index}].fatal_issue")
        for name in (
            "soundness",
            "interaction",
            "essentiality",
            "novelty_delta",
            "surprise",
            "naturalness",
            "contest_fit",
            "known_problem_risk",
            "routine_bypass_risk",
        ):
            _score(evaluation[name], f"evaluations[{index}].{name}", 0, 5)
        checks = evaluation["technique_checks"]
        if not isinstance(checks, dict):
            raise ContractError("shell technique_checks must be an object")
        _exact_keys(checks, set(technique_ids), "technique_checks")
        for technique_id in technique_ids:
            check = checks[technique_id]
            if not isinstance(check, dict):
                raise ContractError(
                    f"technique_checks.{technique_id} must be an object"
                )
            _exact_keys(
                check,
                {"used", "load_bearing", "evidence"},
                f"technique_checks.{technique_id}",
            )
            if not isinstance(check["used"], bool) or not isinstance(
                check["load_bearing"], bool
            ):
                raise ContractError("shell technique check booleans are invalid")
            _text(check["evidence"], f"technique_checks.{technique_id}.evidence", 5)
        if evaluation["verdict"] not in {"keep", "reject"}:
            raise ContractError("shell verdict must be keep or reject")
        _text(evaluation["reason"], f"evaluations[{index}].reason", 3)
        by_id[shell_id] = evaluation
        valid = (
            evaluation["bridge_sound"]
            and evaluation["integer_answer_feasible"]
            and evaluation["existence_supported"]
            and evaluation["uniqueness_supported"]
            and evaluation["fatal_issue"] is None
        )
        creative = (
            not evaluation["copies_canonical_shape"]
            and not evaluation["routine_bypass"]
            and evaluation["soundness"] >= 4
            and evaluation["interaction"] >= 4
            and evaluation["essentiality"] >= 4
            and evaluation["novelty_delta"] >= creativity_floor
            and evaluation["surprise"] >= creativity_floor
            and evaluation["naturalness"] >= 3
            and evaluation["contest_fit"] >= 3
            and evaluation["known_problem_risk"] <= 2
            and evaluation["routine_bypass_risk"] <= 2
            and all(
                checks[technique_id]["used"]
                and checks[technique_id]["load_bearing"]
                for technique_id in technique_ids
            )
        )
        should_keep = valid and creative
        evaluation["reported_verdict"] = evaluation["verdict"]
        evaluation["reported_verdict_consistent"] = not (
            evaluation["verdict"] == "keep" and not should_keep
        )
        evaluation["computed_eligible"] = bool(
            evaluation["verdict"] == "keep" and should_keep
        )
        if evaluation["computed_eligible"]:
            eligible.append(evaluation)
    if set(by_id) != set(shell_ids):
        raise ContractError("evaluated shell IDs do not match proposals")
    winner = (
        sorted(
            eligible,
            key=lambda item: (
                -item["novelty_delta"],
                -item["surprise"],
                item["known_problem_risk"],
                item["routine_bypass_risk"],
                -item["essentiality"],
                -item["interaction"],
                item["shell_id"],
            ),
        )[0]["shell_id"]
        if eligible
        else None
    )
    selected_shell_id = data["selected_shell_id"]
    if selected_shell_id is not None:
        _text(selected_shell_id, "selected_shell_id")
        if selected_shell_id not in set(shell_ids):
            raise ContractError("selected_shell_id must name an evaluated shell")
    selected_consistent = selected_shell_id == winner
    reject_all_consistent = data["reject_all"] == (winner is None)
    data["reported_selected_shell_id"] = data["selected_shell_id"]
    data["reported_selected_shell_id_consistent"] = selected_consistent
    data["reported_reject_all"] = data["reject_all"]
    data["reported_reject_all_consistent"] = reject_all_consistent
    data["reported_decision_consistent"] = (
        selected_consistent and reject_all_consistent
    )
    data["computed_selected_shell_id"] = winner
    return data


_DRAFT_TAGS = (
    "bridge_id", "statement", "answer", "topic", "difficulty", "crux",
    "solution", "technique_usage_json", "bypass_check",
)
_DRAFT_BLOCK_RE = re.compile(
    rf"<({'|'.join(_DRAFT_TAGS)})>\s*(.*?)\s*</\1>", re.DOTALL | re.IGNORECASE
)


def parse_combo_draft(
    text: str,
    selected_bridge_id: str,
    technique_ids: tuple[str, str],
    difficulty_band: Optional[tuple[float, float]] = None,
) -> dict[str, Any]:
    source = text or ""
    matches = list(_DRAFT_BLOCK_RE.finditer(source))
    tags = [match.group(1).lower() for match in matches]
    if len(matches) != len(_DRAFT_TAGS) or set(tags) != set(_DRAFT_TAGS):
        raise ContractError("draft must contain every required tag exactly once")
    cursor = 0
    for match in matches:
        if source[cursor:match.start()].strip():
            raise ContractError("draft contains prose outside required tags")
        cursor = match.end()
    if source[cursor:].strip():
        raise ContractError("draft contains trailing prose outside required tags")
    values = {match.group(1).lower(): match.group(2).strip() for match in matches}
    if values["bridge_id"] != selected_bridge_id:
        raise ContractError("draft bridge_id does not match the selected bridge")
    statement = _text(values["statement"], "statement", minimum=40)
    solution = _text(values["solution"], "solution", minimum=80)
    answer = normalize_aime_answer(values["answer"])
    if answer is None:
        raise ContractError("answer must be exactly one integer in [0, 999]")
    topic = values["topic"]
    if topic not in ALLOWED_TOPICS:
        raise ContractError(f"topic must be one of {sorted(ALLOWED_TOPICS)}")
    try:
        difficulty = float(values["difficulty"])
    except ValueError as exc:
        raise ContractError("difficulty must be a finite number") from exc
    if not math.isfinite(difficulty) or not 1 <= difficulty <= 10:
        raise ContractError("difficulty must be in [1, 10]")
    if difficulty_band is not None:
        try:
            low, high = _validated_difficulty_band(
                difficulty_band, label="difficulty_band"
            )
        except ValueError as exc:
            raise ContractError(str(exc)) from exc
        if difficulty < low - 0.5 or difficulty > high + 0.5:
            raise ContractError(
                f"difficulty {difficulty} is outside target band [{low}, {high}]"
            )
    crux = _text(values["crux"], "crux", minimum=12)
    bypass = _text(values["bypass_check"], "bypass_check", minimum=12)
    usage = strict_json_object(values["technique_usage_json"])
    _exact_keys(usage, set(technique_ids), "technique_usage_json")
    for technique_id in technique_ids:
        item = usage[technique_id]
        if not isinstance(item, dict):
            raise ContractError(f"usage for {technique_id} must be an object")
        _exact_keys(item, {"load_bearing_step", "failure_without"}, f"usage.{technique_id}")
        _text(item["load_bearing_step"], f"usage.{technique_id}.load_bearing_step", 8)
        _text(item["failure_without"], f"usage.{technique_id}.failure_without", 8)
    return {
        "bridge_id": selected_bridge_id,
        "statement": statement,
        "answer": answer,
        "topic": topic,
        "difficulty": difficulty,
        "crux": crux,
        "solution": solution,
        "technique_usage": usage,
        "bypass_check": bypass,
    }


def _tagged_values(text: str, tags: tuple[str, ...]) -> dict[str, str]:
    pattern = re.compile(
        rf"<({'|'.join(map(re.escape, tags))})>\s*(.*?)\s*</\1>",
        re.DOTALL | re.IGNORECASE,
    )
    source = text or ""
    matches = list(pattern.finditer(source))
    observed = tuple(match.group(1).lower() for match in matches)
    if len(matches) != len(tags) or observed != tags:
        raise ContractError("tagged artifact must contain every required tag once in order")
    cursor = 0
    for match in matches:
        if source[cursor:match.start()].strip():
            raise ContractError("tagged artifact contains prose outside required tags")
        cursor = match.end()
    if source[cursor:].strip():
        raise ContractError("tagged artifact contains trailing prose outside required tags")
    return {match.group(1).lower(): match.group(2).strip() for match in matches}


def parse_combo_draft_v2(
    text: str,
    selected_bridge_id: str,
    selected_shell_id: str,
    technique_ids: tuple[str, str],
    difficulty_band: tuple[float, float],
    *,
    repair: bool = False,
) -> dict[str, Any]:
    """Parse a novelty-shell composition or its one allowed structural repair."""
    tags = (
        "schema_version",
        "bridge_id",
        "shell_id",
        "statement",
        "answer",
        "topic",
        "difficulty",
        "crux",
        "novelty_delta",
        "solution",
        "technique_usage_json",
        *(("repair_summary_json",) if repair else ()),
        "bypass_attempts_json",
        "verification_json",
    )
    values = _tagged_values(text, tags)
    expected_schema = CREATIVITY_REPAIR_PROMPT if repair else PROBLEM_PROMPT_V2
    if values["schema_version"] != expected_schema:
        raise ContractError(f"wrong {'repair' if repair else 'v2 draft'} schema_version")
    if values["bridge_id"] != selected_bridge_id:
        raise ContractError("v2 draft bridge_id does not match the selected bridge")
    if values["shell_id"] != selected_shell_id:
        raise ContractError("v2 draft shell_id does not match the selected shell")
    statement = _text(values["statement"], "statement", 40)
    solution = _text(values["solution"], "solution", 100)
    answer = normalize_aime_answer(values["answer"])
    if answer is None:
        raise ContractError("answer must be exactly one integer in [0, 999]")
    topic = values["topic"]
    if topic not in ALLOWED_TOPICS:
        raise ContractError(f"topic must be one of {sorted(ALLOWED_TOPICS)}")
    try:
        difficulty = float(values["difficulty"])
    except (TypeError, ValueError, OverflowError) as exc:
        raise ContractError("difficulty must be a finite number") from exc
    low, high = _validated_difficulty_band(difficulty_band)
    if not math.isfinite(difficulty) or not 1 <= difficulty <= 10:
        raise ContractError("difficulty must be in [1, 10]")
    if not low <= difficulty <= high:
        raise ContractError(f"difficulty {difficulty} is outside target band [{low}, {high}]")
    crux = _text(values["crux"], "crux", 12)
    novelty_delta = _text(values["novelty_delta"], "novelty_delta", 12)

    usage = strict_json_object(values["technique_usage_json"])
    _exact_keys(usage, set(technique_ids), "technique_usage_json")
    for technique_id in technique_ids:
        item = usage[technique_id]
        if not isinstance(item, dict):
            raise ContractError(f"usage for {technique_id} must be an object")
        _exact_keys(
            item,
            {"load_bearing_step", "failure_without"},
            f"usage.{technique_id}",
        )
        _text(item["load_bearing_step"], f"usage.{technique_id}.load_bearing_step", 8)
        _text(item["failure_without"], f"usage.{technique_id}.failure_without", 8)

    bypass = strict_json_object(values["bypass_attempts_json"])
    _exact_keys(
        bypass,
        {"attempts", "shortest_valid_route", "shortest_route_uses"},
        "bypass_attempts_json",
    )
    expected_routes = (
        [
            "prior_audit_shortest_route",
            "standard_formula_or_one_technique",
            "direct_enumeration_or_bash",
        ]
        if repair
        else [
            "direct_enumeration",
            "standard_formula_or_one_technique",
            "bash_or_alternate_representation",
        ]
    )
    attempts = bypass["attempts"]
    if not isinstance(attempts, list) or len(attempts) != 3:
        raise ContractError("bypass attempts must contain exactly three objects")
    for index, (attempt, expected_route) in enumerate(zip(attempts, expected_routes)):
        if not isinstance(attempt, dict):
            raise ContractError(f"bypass attempts[{index}] must be an object")
        _exact_keys(attempt, {"route", "works", "reason"}, f"attempts[{index}]")
        if attempt["route"] != expected_route:
            raise ContractError("bypass attempt routes must match the required order")
        if attempt["works"] is not False:
            raise ContractError("every claimed bypass must be blocked before output")
        _text(attempt["reason"], f"attempts[{index}].reason", 8)
    _text(bypass["shortest_valid_route"], "shortest_valid_route", 8)
    shortest_route_uses = bypass["shortest_route_uses"]
    if (
        not isinstance(shortest_route_uses, list)
        or len(shortest_route_uses) != len(technique_ids)
        or any(not isinstance(item, str) for item in shortest_route_uses)
        or Counter(shortest_route_uses) != Counter(technique_ids)
    ):
        raise ContractError(
            "shortest_route_uses must contain each technique ID exactly once"
        )
    bypass["shortest_route_uses"] = list(technique_ids)

    verification = strict_json_object(values["verification_json"])
    _exact_keys(
        verification,
        {
            "existence",
            "uniqueness",
            "domain_and_boundaries",
            "independent_arithmetic_check",
            "answer_in_range",
        },
        "verification_json",
    )
    for name in (
        "existence",
        "uniqueness",
        "domain_and_boundaries",
        "independent_arithmetic_check",
    ):
        _text(verification[name], f"verification.{name}", 5)
    if verification["answer_in_range"] is not True:
        raise ContractError("verification.answer_in_range must be true")

    repair_summary: Optional[dict[str, Any]] = None
    if repair:
        repair_summary = strict_json_object(values["repair_summary_json"])
        _exact_keys(
            repair_summary,
            {
                "feedback_failures",
                "structural_changes",
                "blocked_bypass",
                "preserved_bridge",
                "cosmetic_only",
            },
            "repair_summary_json",
        )
        failures = repair_summary["feedback_failures"]
        changes = repair_summary["structural_changes"]
        if not isinstance(failures, list) or not failures:
            raise ContractError("repair feedback_failures must be a nonempty list")
        if not isinstance(changes, list) or len(changes) < 2:
            raise ContractError("repair structural_changes must contain at least two items")
        for index, item in enumerate(failures):
            _text(item, f"feedback_failures[{index}]", 3)
        for index, item in enumerate(changes):
            _text(item, f"structural_changes[{index}]", 3)
        _text(repair_summary["blocked_bypass"], "blocked_bypass", 8)
        _text(repair_summary["preserved_bridge"], "preserved_bridge", 8)
        if repair_summary["cosmetic_only"] is not False:
            raise ContractError("repair_summary.cosmetic_only must be false")

    return {
        "schema_version": expected_schema,
        "bridge_id": selected_bridge_id,
        "shell_id": selected_shell_id,
        "statement": statement,
        "answer": answer,
        "topic": topic,
        "difficulty": difficulty,
        "crux": crux,
        "novelty_delta": novelty_delta,
        "solution": solution,
        "technique_usage": usage,
        "bypass_attempts": bypass,
        "verification": verification,
        "repair_summary": repair_summary,
    }


def parse_blind_audit(
    text: str,
    expected_answer: str,
    target_difficulty: tuple[float, float],
    *,
    creativity_floor: int = 4,
    difficulty_floor: float = 4.5,
) -> dict[str, Any]:
    """Parse a statement-only solve and compute the non-self-reported v2 action."""
    if (
        isinstance(creativity_floor, bool)
        or not isinstance(creativity_floor, int)
        or not 0 <= creativity_floor <= 5
    ):
        raise ContractError("creativity_floor must be an integer in [0, 5]")
    if isinstance(difficulty_floor, bool):
        raise ContractError("difficulty_floor must be a finite number in [1, 10]")
    try:
        difficulty_floor = float(difficulty_floor)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ContractError(
            "difficulty_floor must be a finite number in [1, 10]"
        ) from exc
    if not math.isfinite(difficulty_floor) or not 1 <= difficulty_floor <= 10:
        raise ContractError("difficulty_floor must be a finite number in [1, 10]")
    low, high = _validated_difficulty_band(target_difficulty)
    if difficulty_floor > high:
        raise ContractError("difficulty_floor cannot exceed target_difficulty high")

    data = strict_json_object(text)
    _exact_keys(
        data,
        {
            "schema_version",
            "well_posed",
            "solved",
            "unique_answer",
            "answer",
            "shortest_solution",
            "shortest_route_steps",
            "actual_techniques",
            "bypass",
            "difficulty",
            "novelty",
            "verdict",
            "reason",
        },
        "root",
    )
    if data["schema_version"] != BLIND_AUDIT_PROMPT:
        raise ContractError("wrong blind-audit schema_version")
    for name in ("well_posed", "solved", "unique_answer"):
        if not isinstance(data[name], bool):
            raise ContractError(f"{name} must be boolean")
    answer = None if data["answer"] is None else normalize_aime_answer(data["answer"])
    if data["answer"] is not None and answer is None:
        raise ContractError("blind answer must be null or one integer in [0, 999]")
    if data["solved"] and answer is None:
        raise ContractError("a solved blind audit must provide an integer answer")
    _text(data["shortest_solution"], "shortest_solution", 12)
    steps = data["shortest_route_steps"]
    if not isinstance(steps, list) or not 1 <= len(steps) <= 8:
        raise ContractError("shortest_route_steps must contain one to eight items")
    for index, item in enumerate(steps):
        _text(item, f"shortest_route_steps[{index}]", 3)
    techniques = data["actual_techniques"]
    if not isinstance(techniques, list) or not 1 <= len(techniques) <= 6:
        raise ContractError("actual_techniques must contain one to six objects")
    for index, item in enumerate(techniques):
        if not isinstance(item, dict):
            raise ContractError(f"actual_techniques[{index}] must be an object")
        _exact_keys(item, {"name", "load_bearing", "evidence"}, f"actual_techniques[{index}]")
        _text(item["name"], f"actual_techniques[{index}].name", 3)
        if not isinstance(item["load_bearing"], bool):
            raise ContractError("actual technique load_bearing must be boolean")
        _text(item["evidence"], f"actual_techniques[{index}].evidence", 5)

    bypass = data["bypass"]
    if not isinstance(bypass, dict):
        raise ContractError("bypass must be an object")
    _exact_keys(
        bypass,
        {"exists", "type", "route", "estimated_cases_or_steps", "reason"},
        "bypass",
    )
    if not isinstance(bypass["exists"], bool):
        raise ContractError("bypass.exists must be boolean")
    if bypass["type"] not in BLIND_BYPASS_TYPES:
        raise ContractError("unsupported bypass.type")
    if (bypass["type"] == "none") != (not bypass["exists"]):
        raise ContractError("bypass.type none must agree with bypass.exists")
    _text(bypass["route"], "bypass.route", 3)
    if (
        isinstance(bypass["estimated_cases_or_steps"], bool)
        or not isinstance(bypass["estimated_cases_or_steps"], int)
        or bypass["estimated_cases_or_steps"] < 0
    ):
        raise ContractError("estimated_cases_or_steps must be a nonnegative integer")
    _text(bypass["reason"], "bypass.reason", 5)

    difficulty = data["difficulty"]
    if not isinstance(difficulty, dict):
        raise ContractError("difficulty must be an object")
    _exact_keys(
        difficulty,
        {
            "score",
            "band",
            "primary_barrier",
            "inside_target_band",
            "structural_inflation",
        },
        "difficulty",
    )
    if isinstance(difficulty["score"], bool):
        raise ContractError("difficulty.score must be a finite number")
    try:
        difficulty_score = float(difficulty["score"])
    except (TypeError, ValueError, OverflowError) as exc:
        raise ContractError("difficulty.score must be a finite number") from exc
    if not math.isfinite(difficulty_score) or not 1 <= difficulty_score <= 10:
        raise ContractError("difficulty.score must be in [1, 10]")
    if difficulty["band"] not in BLIND_DIFFICULTY_BANDS:
        raise ContractError("unsupported difficulty.band")
    _text(difficulty["primary_barrier"], "difficulty.primary_barrier", 5)
    if not isinstance(difficulty["inside_target_band"], bool) or not isinstance(
        difficulty["structural_inflation"], bool
    ):
        raise ContractError("difficulty audit booleans are invalid")

    novelty = data["novelty"]
    if not isinstance(novelty, dict):
        raise ContractError("novelty must be an object")
    _exact_keys(
        novelty,
        {
            "known_problem_pattern",
            "closest_pattern",
            "surprise_compression",
            "resistance",
            "statement_naturalness",
            "reason",
        },
        "novelty",
    )
    if not isinstance(novelty["known_problem_pattern"], bool):
        raise ContractError("known_problem_pattern must be boolean")
    if novelty["closest_pattern"] is not None:
        _text(novelty["closest_pattern"], "closest_pattern", 3)
    for name in ("surprise_compression", "resistance", "statement_naturalness"):
        _score(novelty[name], f"novelty.{name}", 0, 5)
    _text(novelty["reason"], "novelty.reason", 5)
    if data["verdict"] not in {"accept", "reject", "inconclusive"}:
        raise ContractError("blind verdict must be accept, reject, or inconclusive")
    _text(data["reason"], "reason", 3)

    reported_inside = low <= difficulty_score <= high
    if difficulty["inside_target_band"] != reported_inside:
        raise ContractError(
            "difficulty.inside_target_band contradicts the reported score"
        )
    policy_failures: list[str] = []
    if not data["well_posed"]:
        policy_failures.append("well_posed")
    if not data["solved"]:
        policy_failures.append("solved")
    if not data["unique_answer"]:
        policy_failures.append("unique_answer")
    if answer is None:
        policy_failures.append("integer_answer")
    if bypass["exists"]:
        policy_failures.append("routine_bypass")
    if not difficulty["inside_target_band"]:
        policy_failures.append("target_difficulty")
    if difficulty_score < difficulty_floor:
        policy_failures.append("difficulty_floor")
    if difficulty["structural_inflation"]:
        policy_failures.append("structural_inflation")
    if novelty["known_problem_pattern"]:
        policy_failures.append("known_problem_pattern")
    if novelty["surprise_compression"] < creativity_floor:
        policy_failures.append("surprise_compression")
    if novelty["resistance"] < creativity_floor:
        policy_failures.append("resistance")
    if novelty["statement_naturalness"] < 3:
        policy_failures.append("statement_naturalness")
    base_accept = not policy_failures
    answer_matches = bool(answer is not None and answer == normalize_aime_answer(expected_answer))
    strict_quality = (
        base_accept
        and data["verdict"] == "accept"
        and answer_matches
    )
    correctness = (
        data["well_posed"]
        and data["solved"]
        and data["unique_answer"]
        and answer_matches
    )
    if strict_quality:
        action = "accept"
    elif correctness and data["verdict"] != "inconclusive":
        action = "repair"
    else:
        action = "reject"
    data["normalized_answer"] = answer
    data["answer_matches"] = answer_matches
    data["policy_failures"] = policy_failures
    data["reported_verdict"] = data["verdict"]
    data["reported_verdict_consistent"] = not (
        data["verdict"] == "accept" and bool(policy_failures)
    )
    data["computed_action"] = action
    return data


def parse_faithfulness(
    text: str,
    technique_ids: tuple[str, str],
    *,
    schema_version: str = FAITHFULNESS_PROMPT,
    creativity_floor: Optional[int] = None,
) -> dict[str, Any]:
    data = strict_json_object(text)
    fields = {
        "schema_version", "well_posed", "answer_consistent", "bridge_faithful",
        "both_load_bearing", "sequential_stacking", "routine_bypass",
        "interaction_creativity", "problem_creativity", "naturalness",
        "creativity_reason", "technique_checks", "verdict", "reason",
    }
    _exact_keys(data, fields, "root")
    if data["schema_version"] != schema_version:
        raise ContractError("wrong faithfulness schema_version")
    if schema_version not in {FAITHFULNESS_PROMPT, FAITHFULNESS_PROMPT_V2}:
        raise ContractError("unsupported faithfulness schema_version")
    floor = creativity_floor
    if floor is None:
        floor = 4 if schema_version == FAITHFULNESS_PROMPT_V2 else 3
    if isinstance(floor, bool) or not isinstance(floor, int) or not 0 <= floor <= 5:
        raise ContractError("creativity_floor must be an integer in [0, 5]")
    for name in (
        "well_posed", "answer_consistent", "bridge_faithful", "both_load_bearing",
        "sequential_stacking", "routine_bypass",
    ):
        if not isinstance(data[name], bool):
            raise ContractError(f"{name} must be boolean")
    for name in ("interaction_creativity", "problem_creativity", "naturalness"):
        _score(data[name], name, 0, 5)
    _text(data["creativity_reason"], "creativity_reason", 8)
    checks = data["technique_checks"]
    if not isinstance(checks, dict):
        raise ContractError("technique_checks must be an object")
    _exact_keys(checks, set(technique_ids), "technique_checks")
    for technique_id in technique_ids:
        check = checks[technique_id]
        if not isinstance(check, dict):
            raise ContractError(f"technique_checks.{technique_id} must be an object")
        _exact_keys(check, {"used", "load_bearing", "evidence"}, f"technique_checks.{technique_id}")
        if not isinstance(check["used"], bool) or not isinstance(check["load_bearing"], bool):
            raise ContractError("technique check booleans are invalid")
        _text(check["evidence"], f"technique_checks.{technique_id}.evidence", 5)
    if data["verdict"] not in {"accept", "reject"}:
        raise ContractError("faithfulness verdict must be accept or reject")
    _text(data["reason"], "reason")
    should_accept = (
        data["well_posed"]
        and data["answer_consistent"]
        and data["bridge_faithful"]
        and data["both_load_bearing"]
        and not data["sequential_stacking"]
        and not data["routine_bypass"]
        and data["interaction_creativity"] >= floor
        and data["problem_creativity"] >= floor
        and data["naturalness"] >= floor
        and all(checks[technique_id]["used"] and checks[technique_id]["load_bearing"] for technique_id in technique_ids)
    )
    if (
        schema_version != FAITHFULNESS_PROMPT_V2
        and data["verdict"] == "accept"
        and not should_accept
    ):
        raise ContractError("an accept verdict contradicts its component fields")
    data["reported_verdict"] = data["verdict"]
    data["reported_verdict_consistent"] = not (
        data["verdict"] == "accept" and not should_accept
    )
    data["computed_quality_pass"] = should_accept and data["verdict"] == "accept"
    return data


def parse_corpus_novelty(
    text: str,
    neighbor_ids: tuple[str, ...],
    *,
    distance_floor: int = 3,
) -> dict[str, Any]:
    """Parse neighbor comparisons and compute the non-self-reported hard gate."""
    if not neighbor_ids or len(set(neighbor_ids)) != len(neighbor_ids):
        raise ContractError("neighbor_ids must be a nonempty unique tuple")
    if (
        isinstance(distance_floor, bool)
        or not isinstance(distance_floor, int)
        or not 1 <= distance_floor <= 5
    ):
        raise ContractError("distance_floor must be an integer in [1, 5]")
    data = strict_json_object(text)
    _exact_keys(
        data,
        {
            "schema_version",
            "comparisons",
            "closest_neighbor_id",
            "verdict",
            "reason",
        },
        "root",
    )
    if data["schema_version"] != CORPUS_NOVELTY_PROMPT:
        raise ContractError("wrong corpus-novelty schema_version")
    comparisons = data["comparisons"]
    if not isinstance(comparisons, list) or len(comparisons) != len(neighbor_ids):
        raise ContractError("novelty audit must compare every supplied neighbor once")
    fields = {
        "neighbor_id",
        "same_core_object",
        "same_target_quantity",
        "same_key_invariant",
        "same_proof_kernel",
        "surface_change_only",
        "new_load_bearing_mechanism",
        "structural_distance",
        "reason",
    }
    by_id: dict[str, dict[str, Any]] = {}
    policy_failures: list[str] = []
    for index, comparison in enumerate(comparisons):
        if not isinstance(comparison, dict):
            raise ContractError(f"comparisons[{index}] must be an object")
        _exact_keys(comparison, fields, f"comparisons[{index}]")
        neighbor_id = _text(
            comparison["neighbor_id"], f"comparisons[{index}].neighbor_id"
        )
        if neighbor_id in by_id:
            raise ContractError(f"duplicate novelty comparison: {neighbor_id}")
        for name in (
            "same_core_object",
            "same_target_quantity",
            "same_key_invariant",
            "same_proof_kernel",
            "surface_change_only",
            "new_load_bearing_mechanism",
        ):
            if not isinstance(comparison[name], bool):
                raise ContractError(f"comparisons[{index}].{name} must be boolean")
        distance = comparison["structural_distance"]
        if (
            isinstance(distance, bool)
            or not isinstance(distance, int)
            or not 0 <= distance <= 5
        ):
            raise ContractError("structural_distance must be an integer in [0, 5]")
        _text(comparison["reason"], f"comparisons[{index}].reason", 8)

        blockers: list[str] = []
        if comparison["surface_change_only"]:
            blockers.append("surface_change_only")
        if (
            comparison["same_core_object"]
            and comparison["same_key_invariant"]
            and comparison["same_proof_kernel"]
        ):
            blockers.append("same_mathematical_kernel")
        if (
            comparison["same_target_quantity"]
            and comparison["same_proof_kernel"]
            and not comparison["new_load_bearing_mechanism"]
        ):
            blockers.append("same_target_and_route")
        if distance < distance_floor:
            blockers.append("structural_distance")
        comparison["policy_failures"] = list(dict.fromkeys(blockers))
        comparison["computed_blocking"] = bool(blockers)
        policy_failures.extend(
            f"{neighbor_id}:{failure}" for failure in comparison["policy_failures"]
        )
        by_id[neighbor_id] = comparison
    if set(by_id) != set(neighbor_ids):
        raise ContractError("novelty comparison IDs do not match supplied neighbors")

    reported_closest = data["closest_neighbor_id"]
    if reported_closest is not None:
        _text(reported_closest, "closest_neighbor_id")
        if reported_closest not in by_id:
            raise ContractError("closest_neighbor_id must name a supplied neighbor")
    computed_closest = (
        min(
            comparisons,
            key=lambda item: (item["structural_distance"], item["neighbor_id"]),
        )["neighbor_id"]
        if comparisons
        else None
    )
    if data["verdict"] not in {"accept", "reject"}:
        raise ContractError("corpus-novelty verdict must be accept or reject")
    _text(data["reason"], "reason", 5)
    unique_failures = list(dict.fromkeys(policy_failures))
    component_pass = not unique_failures
    data["reported_closest_neighbor_id"] = reported_closest
    data["reported_closest_neighbor_consistent"] = (
        reported_closest == computed_closest
    )
    data["computed_closest_neighbor_id"] = computed_closest
    data["reported_verdict"] = data["verdict"]
    data["reported_verdict_consistent"] = not (
        data["verdict"] == "accept" and not component_pass
    )
    data["policy_failures"] = unique_failures
    data["computed_novelty_pass"] = component_pass and data["verdict"] == "accept"
    return data


def _load_pair_history(
    catalog: TechniqueCatalog, db_url: Optional[str]
) -> tuple[list[PairHistoryEntry], Counter[str], Counter[str]]:
    """Load attempted pairs, including failures and pre-ComboJob legacy rows."""
    db.init_db(db_url)
    with db.session_scope(db_url) as session:
        jobs = session.exec(select(CombinationJob).order_by(CombinationJob.created_at)).all()
        linked_problem_ids = [job.problem_id for job in jobs if job.problem_id]
        linked_problems = {
            problem.id: problem
            for problem in (
                session.exec(
                    select(Problem).where(Problem.id.in_(linked_problem_ids))
                ).all()
                if linked_problem_ids
                else []
            )
        }
        legacy = [
            problem
            for problem in session.exec(db.training_problems_select()).all()
            if str((problem.provenance or {}).get("pipeline") or "").startswith("distill-combo")
            and not (problem.provenance or {}).get("combo_job_id")
        ]
    history: list[PairHistoryEntry] = []
    failure_counts: Counter[str] = Counter()
    attempt_counts: Counter[str] = Counter()
    for job in jobs:
        raw_ids = tuple(job.technique_ids)
        if len(raw_ids) != 2:
            continue
        canonical_ids = tuple(
            catalog.canonical_id(str(value)) or str(value) for value in raw_ids
        )
        ids = _pair_tuple(str(canonical_ids[0]), str(canonical_ids[1]))
        canonical_pair_key = _pair_key(*ids)
        area = tuple((job.sampler_metadata or {}).get("area_pair") or ("Unknown", "Unknown"))
        linked = linked_problems.get(job.problem_id or "")
        downstream_failed = bool(
            linked
            and (
                linked.verified is False
                or linked.review_status is ReviewStatus.REJECTED
            )
        )
        content_rejected = bool(
            job.status is CombinationJobStatus.REJECTED
            and str(job.rejection_reason or "").startswith(
                (
                    "bridge_rejected",
                    "shell_rejected",
                    "draft_filter",
                    "blind_audit_rejected",
                    "preflight_rejected",
                )
            )
        )
        entry = PairHistoryEntry(
            pair_key=canonical_pair_key,
            technique_ids=ids,
            area_pair=_pair_tuple(str(area[0]), str(area[1])),
            failed=content_rejected or downstream_failed,
        )
        history.append(entry)
        attempt_counts[canonical_pair_key] += 1
        if entry.failed:
            failure_counts[canonical_pair_key] += 1
    for problem in sorted(legacy, key=lambda item: item.created_at):
        ids = sorted(_problem_techniques(problem, catalog))
        if len(ids) != 2:
            continue
        first = catalog.techniques[ids[0]].contexts[0]
        second = catalog.techniques[ids[1]].contexts[0]
        key = _pair_key(ids[0], ids[1])
        history.append(
            PairHistoryEntry(
                pair_key=key,
                technique_ids=(ids[0], ids[1]),
                area_pair=_pair_tuple(first.area, second.area),
                failed=problem.verified is False,
            )
        )
        attempt_counts[key] += 1
        if problem.verified is False:
            failure_counts[key] += 1
    return history, failure_counts, attempt_counts


def _explicit_candidate(
    raw_ids: tuple[str, str],
    catalog: TechniqueCatalog,
    evidence: PairEvidence,
    target_difficulty: tuple[float, float],
    prior_attempt_counts: Counter[str],
) -> PairCandidate:
    target_difficulty = _validated_difficulty_band(target_difficulty)
    canonical = tuple(catalog.canonical_id(value) for value in raw_ids)
    if any(value is None for value in canonical):
        unknown = [raw for raw, value in zip(raw_ids, canonical) if value is None]
        raise ValueError(f"unknown technique IDs: {', '.join(unknown)}")
    first_id, second_id = _pair_tuple(str(canonical[0]), str(canonical[1]))
    if first_id == second_id:
        raise ValueError("an explicit pair cannot contain aliases of the same technique")
    first = catalog.techniques[first_id]
    second = catalog.techniques[second_id]
    if _avoids(catalog, first, second):
        raise ValueError("the explicit pair is listed as incompatible")
    support_a, support_b = evidence.support[first_id], evidence.support[second_id]
    if support_a == 0 and support_b == 0:
        raise ValueError("zero-support + zero-support pairs are forbidden")
    left, right, metadata = _context_pair(catalog, first, second, target_difficulty)
    overlap = tuple(metadata["difficulty_overlap"])
    if overlap[0] > overlap[1]:
        raise ValueError(
            "the explicit pair has no technique-context overlap within target_difficulty"
        )
    pair = (first_id, second_id)
    key = _pair_key(*pair)
    rarity = math.sqrt(_rarity(support_a) * _rarity(support_b))
    attempt_penalty = 1.0 / math.sqrt(1 + prior_attempt_counts[key])
    return PairCandidate(
        pair_key=key,
        technique_ids=pair,
        contexts=(left, right),
        tranche="explicit",
        support_a=support_a,
        support_b=support_b,
        pair_support=evidence.pair_support[pair],
        trusted_pair_support=evidence.trusted_pair_support[pair],
        shared_objects=tuple(metadata["shared_objects"]),
        area_pair=_pair_tuple(left.area, right.area),
        mechanism_pair=_pair_tuple(left.mechanism, right.mechanism),
        difficulty_overlap=(float(overlap[0]), float(overlap[1])),
        evidence_ids=tuple(evidence.evidence_ids.get(pair, [])),
        topic_counts=dict(evidence.topic_counts.get(pair, {})),
        weight=rarity * attempt_penalty,
        weight_components={"rarity": rarity, "attempt_penalty": attempt_penalty},
    )


def create_combination_jobs(
    *,
    run_id: str,
    count: int,
    seed: int,
    catalog: TechniqueCatalog,
    evidence: PairEvidence,
    config: dict[str, Any],
    db_url: Optional[str] = None,
    explicit_pair: Optional[tuple[str, str]] = None,
) -> list[CombinationJob]:
    """Pre-plan and persist an entire reproducible run before model calls."""
    if not run_id.strip():
        raise ValueError("run_id cannot be empty")
    if count < 1:
        raise ValueError("count must be positive")
    if explicit_pair and count != 1:
        raise ValueError("an explicit pair requires count=1")
    config = _freeze_combination_config(config)
    db.init_db(db_url)
    with db.session_scope(db_url) as session:
        existing = session.exec(
            select(CombinationJob).where(CombinationJob.run_id == run_id)
        ).all()
    if existing:
        raise ValueError(f"run {run_id!r} already exists; use resume")

    planned = preview_pair_plan(
        count=count,
        seed=seed,
        catalog=catalog,
        evidence=evidence,
        config=config,
        db_url=db_url,
        explicit_pair=explicit_pair,
    )

    jobs: list[CombinationJob] = []
    with db.session_scope(db_url) as session:
        for ordinal, item in enumerate(planned, 1):
            candidate = item.candidate
            stable_id = hashlib.sha256(
                f"{run_id}|{ordinal}|{candidate.pair_key}".encode("utf-8")
            ).hexdigest()[:32]
            sampler_metadata = {
                "sampler_version": SAMPLER_VERSION,
                "alias_version": catalog.alias_version,
                "alias_map_hash": _json_hash(catalog.alias_map),
                "support_snapshot_hash": evidence.snapshot_hash,
                "draw_index": item.draw_index,
                "requested_tranche": item.requested_tranche,
                "actual_tranche": candidate.tranche,
                "relaxation_level": item.relaxation_level,
                "priority": item.priority,
                "support_a": candidate.support_a,
                "support_b": candidate.support_b,
                "pair_support": candidate.pair_support,
                "trusted_pair_support": candidate.trusted_pair_support,
                "evidence_ids": list(candidate.evidence_ids),
                "topic_counts": candidate.topic_counts,
                "shared_objects": list(candidate.shared_objects),
                "area_pair": list(candidate.area_pair),
                "mechanism_pair": list(candidate.mechanism_pair),
                "difficulty_overlap": list(candidate.difficulty_overlap),
                "weight": candidate.weight,
                "weight_components": candidate.weight_components,
            }
            job = CombinationJob(
                id=stable_id,
                run_id=run_id,
                ordinal=ordinal,
                seed=seed,
                pair_key=candidate.pair_key,
                technique_ids=list(candidate.technique_ids),
                technique_snapshot=candidate.snapshots(catalog),
                taxonomy_sha256=catalog.taxonomy_sha256,
                sampler_metadata=sampler_metadata,
                config=dict(config),
                stage="pair_selected",
                status=CombinationJobStatus.PENDING,
            )
            session.add(job)
            jobs.append(job)
    return jobs


def preview_pair_plan(
    *,
    count: int,
    seed: int,
    catalog: TechniqueCatalog,
    evidence: PairEvidence,
    config: dict[str, Any],
    db_url: Optional[str] = None,
    explicit_pair: Optional[tuple[str, str]] = None,
) -> list[PlannedPair]:
    """Return the exact plan a start command would persist, without mutation."""
    history, failed_counts, attempt_counts = _load_pair_history(catalog, db_url)
    validated_config = _validate_combination_config(config)
    target = validated_config["target_difficulty"]
    if explicit_pair:
        candidate = _explicit_candidate(
            explicit_pair,
            catalog,
            evidence,
            target,
            attempt_counts,
        )
        return [
            PlannedPair(
                candidate=candidate,
                draw_index=0,
                requested_tranche="explicit",
                relaxation_level=0,
                priority=0.0,
            )
        ]
    else:
        candidates = build_pair_candidates(
            catalog,
            evidence,
            target_difficulty=target,
            prior_attempt_counts=attempt_counts,
        )
        snapshot_hash = _json_hash(
            {
                "taxonomy": catalog.taxonomy_sha256,
                "alias_version": catalog.alias_version,
                "support": evidence.snapshot_hash,
                "sampler": SAMPLER_VERSION,
            }
        )
        return plan_pairs(
            candidates,
            count=count,
            seed=seed,
            snapshot_hash=snapshot_hash,
            history=history,
            failed_counts=failed_counts,
        )


@dataclass
class _DedupIndex:
    hashes: set[str]
    canonical_hashes: set[str]
    statement_signatures: list[frozenset[str]]
    crux_signatures: list[frozenset[str]]


@dataclass(frozen=True)
class _NoveltyDocument:
    problem_id: str
    source: str
    topic: Optional[str]
    statement: str
    crux: str
    solution_excerpt: str
    technique_ids: tuple[str, ...]
    statement_terms: frozenset[str]
    crux_terms: frozenset[str]
    terms: frozenset[str]
    statement_hash: str


@dataclass(frozen=True)
class _NoveltyIndex:
    documents: tuple[_NoveltyDocument, ...]
    by_id: dict[str, _NoveltyDocument]
    idf: dict[str, float]
    snapshot_hash: str


@dataclass(frozen=True)
class _NoveltyScore:
    document: _NoveltyDocument
    statement_similarity: float
    cross_field_similarity: float
    crux_similarity: float
    technique_overlap: float
    structural_anchor_overlap: int

    @property
    def retrieval_similarity(self) -> float:
        return max(
            self.statement_similarity,
            self.cross_field_similarity,
            self.crux_similarity,
        )


_NOVELTY_WORD_RE = re.compile(r"[a-z]+")
_NOVELTY_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "compute", "determine",
    "each", "find", "for", "from", "given", "if", "in", "integer", "is",
    "let", "of", "on", "or", "over", "show", "such", "that", "the", "then",
    "to", "value", "what", "where", "which", "with", "big", "dfrac", "frac",
    "left", "mathbb", "operatorname", "right", "text",
}
_NOVELTY_NORMAL_FORMS = {
    "expected": "expectation",
    "expects": "expectation",
    "expectations": "expectation",
    "maximum": "maximize",
    "maximal": "maximize",
    "minimize": "minimum",
    "minimal": "minimum",
    "numbers": "number",
    "roots": "root",
    "subsets": "subset",
    "sums": "sum",
}
_NOVELTY_PHRASES = {
    "phrase:root_of_unity": re.compile(r"roots?\s+of\s+unity|root\s+of\s+unity"),
    "phrase:random_subset": re.compile(
        r"random\s+(?:size\s+\w+\s+)?subset|subset.+(?:uniform|random)"
    ),
    "phrase:complex_sum": re.compile(r"complex.+sum|sum.+complex"),
    "phrase:expected_norm_square": re.compile(
        r"expect(?:ed|ation).{0,80}(?:magnitude\s+squared|norm\s+squared|squared\s+magnitude)"
    ),
    "phrase:fixed_cardinality": re.compile(
        r"size\s+\w+\s+(?:activation\s+)?set|exactly\s+\w+.+(?:chosen|selected)"
    ),
}


def _novelty_terms(text: str) -> frozenset[str]:
    """Deterministic semantic-ish terms for local corpus retrieval.

    The final originality decision is made by the strict judge. Retrieval only
    needs high recall, so it combines normalized words, adjacent content-word
    pairs, and a small set of mathematical-object phrases.
    """
    normalized = unicodedata.normalize("NFKC", text or "").casefold()
    normalized = normalized.replace("\\mathbb{e}", " expectation ")
    normalized = normalized.replace("\\operatorname{e}", " expectation ")
    normalized = re.sub(
        r"\|s\|\s*\^\s*\{?2\}?", " expected norm squared ", normalized
    )
    words: list[str] = []
    content = canonicalize_statement(normalized)
    for raw in _NOVELTY_WORD_RE.findall(content):
        word = _NOVELTY_NORMAL_FORMS.get(raw, raw)
        if len(word) > 4 and word.endswith("ies"):
            word = word[:-3] + "y"
        elif len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        if len(word) > 1 and word not in _NOVELTY_STOPWORDS:
            words.append(word)
    terms = set(words)
    terms.update(
        f"pair:{left}_{right}" for left, right in zip(words, words[1:])
    )
    for label, pattern in _NOVELTY_PHRASES.items():
        if pattern.search(normalized):
            terms.add(label)
    return frozenset(terms)


def _tfidf_cosine(
    left: frozenset[str], right: frozenset[str], idf: dict[str, float]
) -> float:
    if not left or not right:
        return 0.0
    numerator = math.fsum(
        idf.get(term, 1.0) ** 2 for term in sorted(left & right)
    )
    left_norm = math.sqrt(
        math.fsum(idf.get(term, 1.0) ** 2 for term in sorted(left))
    )
    right_norm = math.sqrt(
        math.fsum(idf.get(term, 1.0) ** 2 for term in sorted(right))
    )
    return numerator / (left_norm * right_norm) if left_norm and right_norm else 0.0


def _raw_technique_ids(problem: Problem) -> tuple[str, ...]:
    provenance = problem.provenance or {}
    raw = (
        provenance.get("required_techniques")
        or provenance.get("inferred_techniques")
        or provenance.get("techniques")
        or []
    )
    if not isinstance(raw, list):
        return ()
    return tuple(dict.fromkeys(str(value) for value in raw if str(value).strip()))


def _build_novelty_index(db_url: Optional[str]) -> _NoveltyIndex:
    """Snapshot trusted train/eval problems for deterministic neighbor retrieval."""
    with db.session_scope(db_url) as session:
        problems = session.exec(select(Problem).order_by(Problem.id)).all()
        solutions_by: dict[str, list[Solution]] = defaultdict(list)
        for solution in session.exec(select(Solution).order_by(Solution.id)).all():
            solutions_by[solution.problem_id].append(solution)

    documents: list[_NoveltyDocument] = []
    for problem in problems:
        solution = preferred_solution(problem, solutions_by.get(problem.id, []))
        provenance = problem.provenance or {}
        crux = str(
            provenance.get("crux")
            or (solution.crux_insight if solution is not None else "")
            or ""
        ).strip()
        solution_excerpt = " ".join(
            str(solution.text if solution is not None else "").split()
        )[:1800]
        retrieval_text = "\n".join(part for part in (problem.statement, crux) if part)
        documents.append(
            _NoveltyDocument(
                problem_id=problem.id,
                source=problem.source.value,
                topic=problem.topic,
                statement=problem.statement,
                crux=crux,
                solution_excerpt=solution_excerpt,
                technique_ids=_raw_technique_ids(problem),
                statement_terms=_novelty_terms(problem.statement),
                crux_terms=_novelty_terms(crux),
                terms=_novelty_terms(retrieval_text),
                statement_hash=(
                    problem.statement_hash or statement_hash(problem.statement)
                ),
            )
        )

    document_frequency: Counter[str] = Counter()
    for document in documents:
        document_frequency.update(document.terms)
    total = max(1, len(documents))
    idf = {
        term: math.log((total + 1) / (frequency + 1)) + 1.0
        for term, frequency in document_frequency.items()
    }
    snapshot_hash = _json_hash(
        [
            {
                "id": document.problem_id,
                "statement_hash": document.statement_hash,
                "crux_hash": hashlib.sha256(document.crux.encode("utf-8")).hexdigest(),
                "solution_excerpt_hash": hashlib.sha256(
                    document.solution_excerpt.encode("utf-8")
                ).hexdigest(),
                "technique_ids": list(document.technique_ids),
            }
            for document in documents
        ]
    )
    return _NoveltyIndex(
        documents=tuple(documents),
        by_id={document.problem_id: document for document in documents},
        idf=idf,
        snapshot_hash=snapshot_hash,
    )


def _novelty_neighbor_payload(
    *,
    job: CombinationJob,
    draft: dict[str, Any],
    index: _NoveltyIndex,
    neighbor_count: int,
) -> dict[str, Any]:
    """Select evidence sources first, then highest-scoring corpus neighbors."""
    query_statement_terms = _novelty_terms(str(draft.get("statement") or ""))
    query_crux_terms = _novelty_terms(str(draft.get("crux") or ""))
    query_terms = query_statement_terms | query_crux_terms
    query_techniques = set(str(value) for value in (job.technique_ids or []))
    evidence_ids = list(
        dict.fromkeys((job.sampler_metadata or {}).get("evidence_ids") or [])
    )
    evidence_set = set(evidence_ids)
    query_anchors = {term for term in query_terms if term.startswith("phrase:")}
    scored: list[_NoveltyScore] = []
    for document in index.documents:
        if document.problem_id == job.problem_id:
            continue
        statement_similarity = _tfidf_cosine(
            query_statement_terms, document.statement_terms, index.idf
        )
        crux_similarity = _tfidf_cosine(
            query_crux_terms, document.crux_terms, index.idf
        )
        cross_field_similarity = _tfidf_cosine(query_terms, document.terms, index.idf)
        document_techniques = set(document.technique_ids)
        technique_overlap = (
            len(query_techniques & document_techniques)
            / max(1, len(query_techniques | document_techniques))
            if query_techniques and document_techniques
            else 0.0
        )
        scored.append(
            _NoveltyScore(
                document=document,
                statement_similarity=statement_similarity,
                cross_field_similarity=cross_field_similarity,
                crux_similarity=crux_similarity,
                technique_overlap=technique_overlap,
                structural_anchor_overlap=len(
                    query_anchors
                    & {term for term in document.terms if term.startswith("phrase:")}
                ),
            )
        )
    # Lexical structure is the high-recall channel. Technique overlap is only a
    # tie-breaker; otherwise heavily tagged rows crowd out untagged official
    # neighbors such as Omni/HMMT source material.
    scored.sort(
        key=lambda item: (
            -item.structural_anchor_overlap,
            -item.retrieval_similarity,
            -item.technique_overlap,
            item.document.problem_id,
        )
    )
    by_id = {item.document.problem_id: item for item in scored}
    lexical_rank = {
        item.document.problem_id: rank for rank, item in enumerate(scored, 1)
    }
    chosen_ids = [problem_id for problem_id in evidence_ids if problem_id in by_id]
    lexical_selected_ids = {
        problem_id
        for problem_id in chosen_ids
        if lexical_rank[problem_id] <= neighbor_count
    }
    # Evidence sources are forced in addition to (not instead of) the lexical
    # shortlist. This preserves recall when all three evidence slots are used.
    lexical_added = 0
    seen_statement_hashes = {
        by_id[problem_id].document.statement_hash for problem_id in chosen_ids
    }
    for item in scored:
        problem_id = item.document.problem_id
        if problem_id in chosen_ids:
            continue
        document = item.document
        if document.statement_hash in seen_statement_hashes:
            continue
        chosen_ids.append(problem_id)
        lexical_selected_ids.add(problem_id)
        seen_statement_hashes.add(document.statement_hash)
        lexical_added += 1
        if lexical_added >= neighbor_count:
            break

    neighbors: list[dict[str, Any]] = []
    for problem_id in chosen_ids:
        score = by_id[problem_id]
        document = score.document
        inclusion_reasons = []
        if problem_id in evidence_set:
            inclusion_reasons.append("pair_evidence")
        if problem_id in lexical_selected_ids:
            inclusion_reasons.append("lexical_top_k")
        neighbors.append(
            {
                "neighbor_id": document.problem_id,
                "source": document.source,
                "topic": document.topic,
                "statement": document.statement,
                "crux": document.crux or None,
                "solution_excerpt": document.solution_excerpt or None,
                "technique_ids": list(document.technique_ids),
                "statement_hash": document.statement_hash,
                "statement_similarity": round(score.statement_similarity, 6),
                "cross_field_similarity": round(score.cross_field_similarity, 6),
                "crux_similarity": round(score.crux_similarity, 6),
                "structural_anchor_overlap": score.structural_anchor_overlap,
                "lexical_rank": lexical_rank[problem_id],
                "technique_overlap": round(score.technique_overlap, 6),
                "pair_evidence_source": document.problem_id in evidence_set,
                "shared_terms": sorted(
                    query_terms & document.terms,
                    key=lambda term: (-index.idf.get(term, 1.0), term),
                )[:20],
                "inclusion_reasons": inclusion_reasons,
            }
        )
    payload = {
        "schema_version": "combo_novelty_neighbors_v1",
        "statement_hash": statement_hash(str(draft.get("statement") or "")),
        "corpus_snapshot_hash": index.snapshot_hash,
        "corpus_count": len(index.documents),
        "requested_neighbor_count": neighbor_count,
        "evidence_ids": evidence_ids,
        "missing_evidence_ids": [
            problem_id for problem_id in evidence_ids if problem_id not in index.by_id
        ],
        "neighbors": neighbors,
    }
    payload["retrieval_hash"] = _json_hash(payload)
    return payload


def _build_dedup_index(db_url: Optional[str]) -> _DedupIndex:
    with db.session_scope(db_url) as session:
        train_rows = deduplicated_training_problems(session)
        eval_rows = session.exec(
            select(Problem).where(
                (Problem.split == DataSplit.EVAL) | (Problem.frozen == True)  # noqa: E712
            )
        ).all()
    hashes = {
        problem.statement_hash or statement_hash(problem.statement)
        for problem in train_rows
        if problem.statement
    }
    hashes.update(
        problem.statement_hash or statement_hash(problem.statement)
        for problem in eval_rows
        if problem.statement
    )
    canonical_hashes = {
        canonical_statement_hash(problem.statement)
        for problem in [*train_rows, *eval_rows]
        if problem.statement
    }
    # Frozen eval statements participate in fuzzy filtering too.  Exact and
    # canonical hashes alone miss reordered or lightly paraphrased holdout text.
    statement_signatures = [
        token_set(problem.statement)
        for problem in [*train_rows, *eval_rows]
        if problem.statement
    ]
    crux_signatures = [
        token_set(crux)
        for problem in train_rows
        if (crux := str((problem.provenance or {}).get("crux") or "").strip())
    ]
    return _DedupIndex(hashes, canonical_hashes, statement_signatures, crux_signatures)


def _static_draft_issues(
    draft: dict[str, Any],
    bridge: dict[str, Any],
    snapshots: list[dict[str, Any]],
    dedup_index: _DedupIndex,
) -> list[str]:
    statement = draft["statement"]
    issues: list[str] = []
    if is_banned_template(statement):
        issues.append("banned_template")
    if is_garbled(statement):
        issues.append("garbled_statement")
    if statement_hash(statement) in dedup_index.hashes:
        issues.append("exact_duplicate")
    if canonical_statement_hash(statement) in dedup_index.canonical_hashes:
        issues.append("canonical_duplicate")
    signature = token_set(statement)
    if is_near_duplicate(signature, dedup_index.statement_signatures):
        issues.append("near_duplicate_statement")
    bridge_signature = token_set(str(bridge.get("crux") or ""))
    if bridge_signature and is_near_duplicate(
        bridge_signature, dedup_index.crux_signatures, threshold=0.55
    ):
        issues.append("near_duplicate_crux")
    normalized_statement = f" {_phrase_key(statement)} "
    leaked: list[str] = []
    for snapshot in snapshots:
        labels = [snapshot.get("name"), snapshot.get("id")]
        labels.extend(snapshot.get("aliases") or [])
        for raw_label in labels:
            label = _phrase_key(str(raw_label or ""))
            if label and f" {label} " in normalized_statement:
                leaked.append(str(raw_label))
    if leaked:
        issues.append("technique_name_leak:" + ",".join(dict.fromkeys(leaked)))
    return issues


def _update_job(
    db_url: Optional[str],
    job_id: str,
    *,
    expected_stage: Optional[str] = None,
    expected_status: Optional[CombinationJobStatus] = CombinationJobStatus.PENDING,
    **values: Any,
) -> CombinationJob:
    """Apply a local checkpoint transition with compare-and-swap semantics."""
    with db.session_scope(db_url) as session:
        conditions = [CombinationJob.id == job_id]
        if expected_stage is not None:
            conditions.append(CombinationJob.stage == expected_stage)
        if expected_status is not None:
            conditions.append(CombinationJob.status == expected_status)
        result = session.exec(
            update(CombinationJob)
            .where(*conditions)
            .values(**values, updated_at=utcnow())
        )
        session.expire_all()
        job = session.get(CombinationJob, job_id)
        if job is None:
            raise KeyError(f"combination job not found: {job_id}")
        # A zero-row CAS is an idempotent lost race; callers re-read on their
        # next loop and must not rewind the newer checkpoint.
        _ = getattr(result, "rowcount", 0)
        return job


def _append_failure(
    db_url: Optional[str],
    job_id: str,
    *,
    stage: str,
    kind: str,
    message: str,
    terminal: bool = False,
    worker_id: Optional[str] = None,
    expected_status: Optional[CombinationJobStatus] = None,
    expected_job_stage: Optional[str] = None,
) -> bool:
    with db.session_scope(db_url) as session:
        job = session.get(CombinationJob, job_id)
        if job is None:
            raise KeyError(job_id)
        # A stale exception handler must never reopen a terminal row or clear a
        # lease acquired after its earlier read.
        if job.status in TERMINAL_STATUSES:
            return False
        if expected_status is not None and job.status is not expected_status:
            return False
        if expected_job_stage is not None and job.stage != expected_job_stage:
            return False
        if worker_id and (
            job.status is not CombinationJobStatus.INFLIGHT
            or job.lease_owner != worker_id
        ):
            return False
        if worker_id is None and job.status is CombinationJobStatus.INFLIGHT:
            return False
        failures = list(job.failures or [])
        failures.append(
            {
                "at": _utc_iso(),
                "stage": stage,
                "kind": kind,
                "message": message[:1000],
            }
        )
        next_status = (
            CombinationJobStatus.EXHAUSTED if terminal else CombinationJobStatus.PENDING
        )
        conditions = [
            CombinationJob.id == job_id,
            CombinationJob.status == job.status,
            CombinationJob.stage == job.stage,
            CombinationJob.updated_at == job.updated_at,
        ]
        conditions.append(
            CombinationJob.lease_owner == job.lease_owner
            if job.lease_owner is not None
            else CombinationJob.lease_owner.is_(None)
        )
        result = session.exec(
            update(CombinationJob)
            .where(*conditions)
            .values(
                failures=failures,
                status=next_status,
                rejection_reason=(
                    f"{kind}: {message}"[:1000] if terminal else None
                ),
                lease_started_at=None,
                lease_owner=None,
                updated_at=utcnow(),
            )
        )
        return getattr(result, "rowcount", 0) == 1


def _record_call(
    db_url: Optional[str],
    job_id: str,
    stage: str,
    response: LLMResponse,
    worker_id: Optional[str] = None,
) -> bool:
    with db.session_scope(db_url) as session:
        job = session.get(CombinationJob, job_id)
        if job is None:
            raise KeyError(job_id)
        if worker_id and job.lease_owner != worker_id:
            return False
        call_ids = {key: list(value) for key, value in (job.call_ids or {}).items()}
        if response.call_id is not None:
            call_ids.setdefault(stage, []).append(response.call_id)
        job.call_ids = call_ids
        job.updated_at = utcnow()
        session.add(job)
        return True


def _finish_stage_success(
    *,
    db_url: Optional[str],
    job_id: str,
    stage: str,
    expected_job_stage: str,
    response: LLMResponse,
    worker_id: str,
    values: dict[str, Any],
) -> None:
    """Atomically checkpoint the parsed artifact, call ID, and next stage."""
    with db.session_scope(db_url) as session:
        job = session.get(CombinationJob, job_id)
        if job is None:
            raise KeyError(job_id)
        if (
            job.status is not CombinationJobStatus.INFLIGHT
            or job.lease_owner != worker_id
            or job.stage != expected_job_stage
        ):
            raise LeaseLostError(f"lease lost before checkpointing {stage}")
        call_ids = {key: list(value) for key, value in (job.call_ids or {}).items()}
        if response.call_id is not None:
            call_ids.setdefault(stage, []).append(response.call_id)
        checkpoint = dict(values)
        checkpoint.update(
            {
                "call_ids": call_ids,
                "status": CombinationJobStatus.PENDING,
                "rejection_reason": None,
                "lease_started_at": None,
                "lease_owner": None,
                "updated_at": utcnow(),
            }
        )
        result = session.exec(
            update(CombinationJob)
            .where(
                CombinationJob.id == job_id,
                CombinationJob.status == CombinationJobStatus.INFLIGHT,
                CombinationJob.lease_owner == worker_id,
                CombinationJob.stage == expected_job_stage,
                CombinationJob.updated_at == job.updated_at,
            )
            .values(**checkpoint)
        )
        if getattr(result, "rowcount", 0) != 1:
            raise LeaseLostError(f"lease lost before checkpointing {stage}")


def _claim_stage_attempt(
    *,
    db_url: Optional[str],
    job_id: str,
    stage: str,
    expected_job_stage: str,
    prompt_version: str,
    worker_id: str,
    max_attempts: int,
    lease_seconds: int,
) -> Optional[tuple[int, dict[str, Any]]]:
    """Atomically claim a pending/stale job and allocate its stage attempt."""
    now = utcnow()
    cutoff = now - timedelta(seconds=max(1, lease_seconds))
    with db.session_scope(db_url) as session:
        prior = session.get(CombinationJob, job_id)
        if prior is None:
            raise KeyError(job_id)
        if prior.stage != expected_job_stage:
            return None
        was_stale = bool(
            prior.status is CombinationJobStatus.INFLIGHT
            and (
                prior.lease_started_at is None
                or (
                    (prior.lease_started_at.replace(tzinfo=timezone.utc)
                     if prior.lease_started_at.tzinfo is None
                     else prior.lease_started_at)
                    < cutoff
                )
            )
        )
        if prior.status not in {
            CombinationJobStatus.PENDING,
            CombinationJobStatus.INFLIGHT,
        } or (prior.status is CombinationJobStatus.INFLIGHT and not was_stale):
            return None
        claim_conditions = [
            CombinationJob.id == job_id,
            CombinationJob.status == prior.status,
            CombinationJob.stage == expected_job_stage,
        ]
        if prior.status is CombinationJobStatus.INFLIGHT:
            claim_conditions.append(
                CombinationJob.lease_owner == prior.lease_owner
                if prior.lease_owner is not None
                else CombinationJob.lease_owner.is_(None)
            )
            claim_conditions.append(
                CombinationJob.lease_started_at == prior.lease_started_at
                if prior.lease_started_at is not None
                else CombinationJob.lease_started_at.is_(None)
            )
        claim = session.exec(
            update(CombinationJob)
            .where(*claim_conditions)
            .values(
                status=CombinationJobStatus.INFLIGHT,
                lease_started_at=now,
                lease_owner=worker_id,
                updated_at=now,
            )
        )
        if getattr(claim, "rowcount", 0) != 1:
            return None
        session.expire_all()
        job = session.get(CombinationJob, job_id)
        attempts = dict(job.attempts or {})
        used = attempts.get(stage, 0)
        retry_epoch = sum(
            1
            for failure in (job.failures or [])
            if failure.get("stage") == stage
            and failure.get("kind") == "manual_retry_reset"
        )
        already_recovered = any(
            failure.get("stage") == stage
            and failure.get("kind") == "stale_lease_recovered"
            and failure.get("attempt") == used
            and failure.get("retry_epoch", 0) == retry_epoch
            for failure in (job.failures or [])
        )
        if was_stale and used and not already_recovered:
            # The process may have died before LLMClient returned or before the
            # parsed artifact was checkpointed. Reuse that ordinal once rather
            # than exhausting a paid stage with no recoverable artifact.
            used -= 1
            attempts[stage] = used
            failures = list(job.failures or [])
            failures.append(
                {
                    "at": _utc_iso(),
                    "stage": stage,
                    "kind": "stale_lease_recovered",
                    "message": "reclaimed an uncheckpointed inflight attempt",
                    "attempt": used + 1,
                    "retry_epoch": retry_epoch,
                }
            )
            job.failures = failures
        if used >= max_attempts:
            failures = list(job.failures or [])
            failures.append(
                {
                    "at": _utc_iso(),
                    "stage": stage,
                    "kind": "attempts_exhausted",
                    "message": f"stage reached {max_attempts} attempts",
                }
            )
            job.failures = failures
            job.status = CombinationJobStatus.EXHAUSTED
            job.rejection_reason = f"attempts_exhausted: stage reached {max_attempts} attempts"
            job.lease_started_at = None
            job.lease_owner = None
            job.updated_at = utcnow()
            session.add(job)
            return None
        attempt = used + 1
        attempts[stage] = attempt
        job.attempts = attempts
        session.add(job)
        metadata = {
            "run_id": job.run_id,
            "combo_job_id": job.id,
            "pair_key": job.pair_key,
            "stage": stage,
            "attempt": attempt,
            "prompt_version": prompt_version,
        }
        return attempt, metadata


def _stop_reason(response: LLMResponse) -> Optional[str]:
    raw = response.raw if isinstance(response.raw, dict) else {}
    value = raw.get("stop_reason") or raw.get("finish_reason")
    if value is None:
        return None
    normalized = str(value).strip().lower()
    return normalized or None


def _stage_effort(
    *,
    policy_version: str,
    stage: str,
    generator_stage: bool,
    attempt: int,
) -> str:
    """Return the frozen adaptive-thinking effort for one durable attempt."""
    if (
        policy_version == STAGE_EFFORT_POLICY
        and generator_stage
        and stage != "bridge_proposal"
    ):
        first, retry = "medium", "low"
    elif generator_stage:
        first, retry = "high", "medium"
    else:
        first, retry = "medium", "low"
    return first if attempt == 1 else retry


def _stage_call(
    *,
    db_url: Optional[str],
    job_id: str,
    stage: str,
    expected_job_stage: str,
    prompt_version: str,
    prompt: str,
    client: LLMClient,
    parser: Callable[[str], dict[str, Any]],
    purpose: str,
    generator_stage: bool,
    json_contract: bool,
    worker_id: str,
    success_values: Callable[[dict[str, Any]], dict[str, Any]],
) -> Optional[dict[str, Any]]:
    """Call and strictly parse one stage, with a single schema-aware retry."""
    with db.session_scope(db_url) as session:
        job = session.get(CombinationJob, job_id)
        if job is None:
            raise KeyError(job_id)
        config = _validate_combination_config(job.config or {})
        max_attempts = int(config["stage_attempts"])
        lease_seconds = int(config["lease_seconds"])
        effort_policy_version = str(config["effort_policy_version"])
        configured_max_output_tokens = (
            int(config["generator_max_output_tokens"])
            if generator_stage
            else DEFAULT_JUDGE_MAX_OUTPUT_TOKENS
        )
    retry_prompt = prompt
    while True:
        claimed = _claim_stage_attempt(
            db_url=db_url,
            job_id=job_id,
            stage=stage,
            expected_job_stage=expected_job_stage,
            prompt_version=prompt_version,
            worker_id=worker_id,
            max_attempts=max_attempts,
            lease_seconds=lease_seconds,
        )
        if claimed is None:
            return None
        attempt, metadata = claimed
        temperature = 0.9 if generator_stage else 0.0
        effort = _stage_effort(
            policy_version=effort_policy_version,
            stage=stage,
            generator_stage=generator_stage,
            attempt=attempt,
        )
        metadata.update(
            {
                "requested_temperature": temperature,
                "requested_effort": effort,
                "effort_policy_version": effort_policy_version,
                "configured_max_output_tokens": configured_max_output_tokens,
                "effective_temperature": (
                    None
                    if client.provider == "anthropic" and effort is not None
                    else temperature
                ),
            }
        )
        try:
            response = client.complete(
                retry_prompt,
                system=JSON_ONLY_SYSTEM if json_contract else None,
                purpose=purpose,
                related_id=job_id,
                meta=metadata,
                temperature=temperature,
                effort=effort,
            )
        except Exception as exc:  # noqa: BLE001 - persist and keep the run alive
            message = f"{type(exc).__name__}: {exc}"
            applied = _append_failure(
                db_url,
                job_id,
                stage=stage,
                kind="transport",
                message=message,
                terminal=attempt >= max_attempts,
                worker_id=worker_id,
                expected_status=CombinationJobStatus.INFLIGHT,
                expected_job_stage=expected_job_stage,
            )
            if not applied:
                return None
            if attempt >= max_attempts:
                return None
            continue

        reason = _stop_reason(response)
        exhausted = reason in {"max_tokens", "length", "max_output_tokens"}
        if not response.text.strip():
            if not _record_call(db_url, job_id, stage, response, worker_id):
                return None
            message = (
                f"empty/exhausted output (stop_reason={reason!r}, "
                f"completion_tokens={response.completion_tokens})"
            )
            applied = _append_failure(
                db_url,
                job_id,
                stage=stage,
                kind="output_exhausted",
                message=message,
                terminal=attempt >= max_attempts,
                worker_id=worker_id,
                expected_status=CombinationJobStatus.INFLIGHT,
                expected_job_stage=expected_job_stage,
            )
            if not applied:
                return None
            if attempt >= max_attempts:
                return None
            retry_prompt = (
                prompt
                + "\n\nThe prior response exhausted its output budget. Do not repeat "
                "hidden analysis. Return only the required compact artifact, with "
                "concise proof and reason fields."
            )
            continue
        try:
            parsed = parser(response.text)
        except ContractError as exc:
            if not _record_call(db_url, job_id, stage, response, worker_id):
                return None
            kind = "output_exhausted" if exhausted else "parse"
            message = (
                f"output exhausted before a valid artifact "
                f"(stop_reason={reason!r}, output_chars={len(response.text)}, "
                f"completion_tokens={response.completion_tokens}, parser={exc})"
                if exhausted
                else str(exc)
            )
            applied = _append_failure(
                db_url,
                job_id,
                stage=stage,
                kind=kind,
                message=message,
                terminal=attempt >= max_attempts,
                worker_id=worker_id,
                expected_status=CombinationJobStatus.INFLIGHT,
                expected_job_stage=expected_job_stage,
            )
            if not applied:
                return None
            if attempt >= max_attempts:
                return None
            if exhausted:
                retry_prompt = (
                    prompt
                    + "\n\nThe prior response exhausted its output budget before a valid "
                    "artifact. Do not repeat hidden analysis. Return only the required "
                    "compact artifact, with concise proof and reason fields."
                )
            else:
                retry_prompt = (
                    prompt
                    + f"\n\nThe prior response failed schema validation: {exc}. "
                    "Return a fresh artifact only."
                )
            continue
        _finish_stage_success(
            db_url=db_url,
            job_id=job_id,
            stage=stage,
            expected_job_stage=expected_job_stage,
            response=response,
            worker_id=worker_id,
            values=success_values(parsed),
        )
        return parsed


def _reject_job(
    db_url: Optional[str],
    job_id: str,
    reason: str,
    *,
    expected_stage: Optional[str] = None,
    extra_values: Optional[dict[str, Any]] = None,
) -> None:
    values = dict(extra_values or {})
    values.update(
        {
            "status": CombinationJobStatus.REJECTED,
            "rejection_reason": reason[:1000],
            "lease_started_at": None,
            "lease_owner": None,
        }
    )
    _update_job(
        db_url,
        job_id,
        expected_stage=expected_stage,
        **values,
    )


def _prompt_snapshots(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove alias/context IDs that can confuse exact-ID model contracts."""
    allowed = {
        "id", "name", "area", "family", "one_liner", "trigger", "objects",
        "mechanism", "difficulty_band", "example_crux",
    }
    return [
        {key: value for key, value in snapshot.items() if key in allowed}
        for snapshot in snapshots
    ]


def _prompt_bridge(bridge: dict[str, Any]) -> dict[str, Any]:
    """Strip proposer self-scores so downstream models judge descriptions blind."""
    return {
        key: value for key, value in bridge.items() if key in BRIDGE_DESCRIPTIVE_FIELDS
    }


def _prompt_bridge_proposals(proposals: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": proposals.get("schema_version"),
        "technique_ids": list(proposals.get("technique_ids") or []),
        "candidates": [
            _prompt_bridge(candidate)
            for candidate in list(proposals.get("candidates") or [])
        ],
    }


def _prompt_shell(shell: dict[str, Any]) -> dict[str, Any]:
    """Hide proposer self-scores while retaining the mathematical shell design."""
    hidden = {
        "naturalness",
        "surprise",
        "feasibility",
        "known_problem_risk",
        "routine_bypass_risk",
    }
    return {key: value for key, value in shell.items() if key not in hidden}


def _prompt_shell_proposals(proposals: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": proposals.get("schema_version"),
        "bridge_id": proposals.get("bridge_id"),
        "technique_ids": list(proposals.get("technique_ids") or []),
        "canonical_shape_to_avoid": proposals.get("canonical_shape_to_avoid"),
        "shells": [
            _prompt_shell(shell) for shell in list(proposals.get("shells") or [])
        ],
    }


def _pipeline_version(config: dict[str, Any]) -> str:
    value = config.get("pipeline_version", PIPELINE_V1)
    if value not in SUPPORTED_PROMPT_VERSIONS:
        raise ValueError(
            f"pipeline_version must be one of {sorted(SUPPORTED_PROMPT_VERSIONS)}"
        )
    return str(value)


def _effort_policy_version(config: dict[str, Any]) -> str:
    """Resolve runtime effort policy; absence denotes historical behavior."""
    value = config.get("effort_policy_version", LEGACY_EFFORT_POLICY)
    if value not in SUPPORTED_EFFORT_POLICIES:
        raise ValueError(
            "effort_policy_version must be one of "
            f"{sorted(SUPPORTED_EFFORT_POLICIES)}"
        )
    return str(value)


def _novelty_gate_version(config: dict[str, Any]) -> str:
    """Resolve the optional corpus gate; absence keeps historical V2 resumable."""
    value = config.get("novelty_gate_version", CORPUS_NOVELTY_GATE_DISABLED)
    if value not in SUPPORTED_NOVELTY_GATES:
        raise ValueError(
            "novelty_gate_version must be one of "
            f"{sorted(SUPPORTED_NOVELTY_GATES)}"
        )
    return str(value)


def _validate_prompt_versions(config: dict[str, Any]) -> dict[str, str]:
    """Resolve prompt versions and reject contracts this parser cannot read."""
    pipeline_version = _pipeline_version(config)
    supported_versions = SUPPORTED_PROMPT_VERSIONS[pipeline_version]
    raw = config["prompt_versions"] if "prompt_versions" in config else {}
    if not isinstance(raw, dict):
        raise ValueError("prompt_versions must be an object")
    unknown = set(raw) - set(supported_versions)
    if unknown:
        raise ValueError(
            f"unsupported prompt-version keys: {sorted(map(str, unknown))}"
        )
    resolved: dict[str, str] = {}
    for key, supported in supported_versions.items():
        version = raw[key] if key in raw else supported
        if not isinstance(version, str) or version != supported:
            raise ValueError(
                f"unsupported {key} prompt version {version!r}; "
                f"this build supports only {supported!r}"
            )
        resolved[key] = version

    if "prompt_hashes" in config:
        hashes = config["prompt_hashes"]
        if not isinstance(hashes, dict):
            raise ValueError("prompt_hashes must be an object")
        if set(hashes) != set(supported_versions):
            raise ValueError(
                "prompt_hashes must contain exactly the supported stage keys for "
                f"pipeline {pipeline_version}"
            )
        for key, digest in hashes.items():
            if not isinstance(digest, str) or not re.fullmatch(
                r"[0-9a-f]{64}", digest
            ):
                raise ValueError(f"prompt_hashes.{key} must be a SHA-256 hex digest")
    return resolved


def _validate_combination_config(config: dict[str, Any]) -> dict[str, Any]:
    """Validate all controls whose corruption could change a resumed run."""
    if not isinstance(config, dict):
        raise ValueError("combination config must be an object")
    pipeline_version = _pipeline_version(config)
    bridge_count = config.get("bridges_per_pair", 3)
    stage_attempts = config.get("stage_attempts", 2)
    # Missing means the historical 32k runtime. New runs freeze their current
    # pipeline-specific cap in _freeze_combination_config before persistence.
    generator_token_default = V1_GENERATOR_MAX_OUTPUT_TOKENS
    output_token_values = {
        "generator_max_output_tokens": config.get(
            "generator_max_output_tokens", generator_token_default
        ),
    }
    for key, value in output_token_values.items():
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 1024 <= value <= V2_GENERATOR_MAX_OUTPUT_TOKENS
        ):
            raise ValueError(
                f"{key} must be an integer in "
                f"[1024, {V2_GENERATOR_MAX_OUTPUT_TOKENS}]"
            )
    if (
        isinstance(bridge_count, bool)
        or not isinstance(bridge_count, int)
        or bridge_count != 3
    ):
        raise ValueError("bridges_per_pair must be exactly 3")
    if (
        isinstance(stage_attempts, bool)
        or not isinstance(stage_attempts, int)
        or not 1 <= stage_attempts <= 3
    ):
        raise ValueError("stage_attempts must be an integer in [1, 3]")
    for role in ("generator", "judge"):
        backend_key = f"{role}_backend"
        model_key = f"{role}_model"
        if backend_key in config and config[backend_key] not in {
            "anthropic",
            "openai",
        }:
            raise ValueError(
                f"{backend_key} must be either 'anthropic' or 'openai'"
            )
        if model_key in config and (
            not isinstance(config[model_key], str)
            or not config[model_key].strip()
        ):
            raise ValueError(f"{model_key} must be a nonempty string")
    prompt_versions = _validate_prompt_versions(config)
    prompt_hashes = config.get("prompt_hashes")
    if prompt_hashes is not None:
        for key, version in prompt_versions.items():
            actual = hashlib.sha256(load_prompt(version).encode("utf-8")).hexdigest()
            if actual != prompt_hashes[key]:
                raise ValueError(
                    f"prompt {version} changed since run creation; expected "
                    f"{prompt_hashes[key][:12]}, got {actual[:12]}"
                )
    result = {
        "pipeline_version": pipeline_version,
        "effort_policy_version": _effort_policy_version(config),
        "novelty_gate_version": _novelty_gate_version(config),
        "prompt_versions": prompt_versions,
        "target_difficulty": _validated_difficulty_band(
            config["target_difficulty"]
            if "target_difficulty" in config
            else (4.0, 8.0)
        ),
        "lease_seconds": _validated_lease_seconds(config),
        "bridges_per_pair": bridge_count,
        "stage_attempts": stage_attempts,
        **output_token_values,
    }
    if pipeline_version == PIPELINE_V2:
        shell_count = config.get("shells_per_bridge", 4)
        creativity_floor = config.get("creativity_floor", 4)
        raw_difficulty_floor = config.get("blind_difficulty_floor", 4.5)
        repair_limit = config.get("max_creativity_repairs", 1)
        if (
            isinstance(shell_count, bool)
            or not isinstance(shell_count, int)
            or shell_count != 4
        ):
            raise ValueError("shells_per_bridge must be exactly 4 for the v2 contract")
        if (
            isinstance(creativity_floor, bool)
            or not isinstance(creativity_floor, int)
            or not 4 <= creativity_floor <= 5
        ):
            raise ValueError("creativity_floor must be an integer in [4, 5]")
        if isinstance(raw_difficulty_floor, bool):
            raise ValueError("blind_difficulty_floor must be a finite number in [1, 10]")
        try:
            difficulty_floor = float(raw_difficulty_floor)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(
                "blind_difficulty_floor must be a finite number in [1, 10]"
            ) from exc
        if not math.isfinite(difficulty_floor) or not 1 <= difficulty_floor <= 10:
            raise ValueError("blind_difficulty_floor must be a finite number in [1, 10]")
        if difficulty_floor > result["target_difficulty"][1]:
            raise ValueError(
                "blind_difficulty_floor cannot exceed target_difficulty high"
            )
        if (
            isinstance(repair_limit, bool)
            or not isinstance(repair_limit, int)
            or repair_limit not in {0, 1}
        ):
            raise ValueError("max_creativity_repairs must be 0 or 1")
        result.update(
            {
                "shells_per_bridge": shell_count,
                "creativity_floor": creativity_floor,
                "blind_difficulty_floor": difficulty_floor,
                "max_creativity_repairs": repair_limit,
            }
        )
        novelty_gate = result["novelty_gate_version"]
        neighbor_count = config.get("novelty_neighbor_count", 8)
        distance_floor = config.get("novelty_distance_floor", 3)
        if (
            isinstance(neighbor_count, bool)
            or not isinstance(neighbor_count, int)
            or not 1 <= neighbor_count <= 8
        ):
            raise ValueError("novelty_neighbor_count must be an integer in [1, 8]")
        if (
            isinstance(distance_floor, bool)
            or not isinstance(distance_floor, int)
            or not 1 <= distance_floor <= 5
        ):
            raise ValueError("novelty_distance_floor must be an integer in [1, 5]")
        novelty_prompt_version = config.get(
            "novelty_prompt_version", CORPUS_NOVELTY_PROMPT
        )
        if novelty_prompt_version != CORPUS_NOVELTY_PROMPT:
            raise ValueError(
                f"unsupported novelty prompt version {novelty_prompt_version!r}"
            )
        novelty_prompt_sha256 = config.get("novelty_prompt_sha256")
        if novelty_gate == CORPUS_NOVELTY_GATE_V1:
            if not isinstance(novelty_prompt_sha256, str) or not re.fullmatch(
                r"[0-9a-f]{64}", novelty_prompt_sha256
            ):
                raise ValueError(
                    "enabled novelty gate requires novelty_prompt_sha256"
                )
            actual = hashlib.sha256(
                load_prompt(CORPUS_NOVELTY_PROMPT).encode("utf-8")
            ).hexdigest()
            if novelty_prompt_sha256 != actual:
                raise ValueError(
                    f"prompt {CORPUS_NOVELTY_PROMPT} changed since run creation; "
                    f"expected {novelty_prompt_sha256[:12]}, got {actual[:12]}"
                )
        result.update(
            {
                "novelty_neighbor_count": neighbor_count,
                "novelty_distance_floor": distance_floor,
                "novelty_prompt_version": str(novelty_prompt_version),
                "novelty_prompt_sha256": novelty_prompt_sha256,
            }
        )
    elif result["novelty_gate_version"] != CORPUS_NOVELTY_GATE_DISABLED:
        raise ValueError("corpus novelty gate is supported only for pipeline v2")
    return result


def _freeze_combination_config(config: dict[str, Any]) -> dict[str, Any]:
    """Fill durable defaults and hashes before any CombinationJob is inserted."""
    candidate = dict(config)
    pipeline_version = _pipeline_version(candidate)
    candidate.setdefault(
        "generator_max_output_tokens",
        V2_GENERATOR_MAX_OUTPUT_TOKENS
        if pipeline_version == PIPELINE_V2
        else V1_GENERATOR_MAX_OUTPUT_TOKENS,
    )
    candidate.setdefault(
        "effort_policy_version",
        STAGE_EFFORT_POLICY
        if pipeline_version == PIPELINE_V2
        else LEGACY_EFFORT_POLICY,
    )
    candidate.setdefault(
        "novelty_gate_version",
        CORPUS_NOVELTY_GATE_V1
        if pipeline_version == PIPELINE_V2
        else CORPUS_NOVELTY_GATE_DISABLED,
    )
    if candidate["novelty_gate_version"] == CORPUS_NOVELTY_GATE_V1:
        candidate.setdefault("novelty_neighbor_count", 8)
        candidate.setdefault("novelty_distance_floor", 3)
        candidate.setdefault("novelty_prompt_version", CORPUS_NOVELTY_PROMPT)
        candidate.setdefault(
            "novelty_prompt_sha256",
            hashlib.sha256(
                load_prompt(CORPUS_NOVELTY_PROMPT).encode("utf-8")
            ).hexdigest(),
        )
    validated = _validate_combination_config(candidate)
    frozen = dict(candidate)
    frozen["pipeline_version"] = validated["pipeline_version"]
    frozen["effort_policy_version"] = validated["effort_policy_version"]
    frozen["novelty_gate_version"] = validated["novelty_gate_version"]
    frozen["prompt_versions"] = dict(validated["prompt_versions"])
    frozen["prompt_hashes"] = {
        key: hashlib.sha256(load_prompt(version).encode("utf-8")).hexdigest()
        for key, version in validated["prompt_versions"].items()
    }
    frozen["target_difficulty"] = list(validated["target_difficulty"])
    frozen["lease_seconds"] = validated["lease_seconds"]
    frozen["bridges_per_pair"] = validated["bridges_per_pair"]
    frozen["stage_attempts"] = validated["stage_attempts"]
    frozen["generator_max_output_tokens"] = validated[
        "generator_max_output_tokens"
    ]
    if validated["pipeline_version"] == PIPELINE_V2:
        frozen["shells_per_bridge"] = validated["shells_per_bridge"]
        frozen["creativity_floor"] = validated["creativity_floor"]
        frozen["blind_difficulty_floor"] = validated["blind_difficulty_floor"]
        frozen["max_creativity_repairs"] = validated["max_creativity_repairs"]
        frozen["novelty_neighbor_count"] = validated["novelty_neighbor_count"]
        frozen["novelty_distance_floor"] = validated["novelty_distance_floor"]
        frozen["novelty_prompt_version"] = validated["novelty_prompt_version"]
        frozen["novelty_prompt_sha256"] = validated["novelty_prompt_sha256"]
    return frozen


def _prompt_version(job: CombinationJob, key: str, default: str) -> str:
    versions = _validate_prompt_versions(job.config or {})
    version = versions.get(key, default)
    expected_hash = ((job.config or {}).get("prompt_hashes") or {}).get(key)
    if expected_hash:
        actual_hash = hashlib.sha256(load_prompt(version).encode("utf-8")).hexdigest()
        if actual_hash != expected_hash:
            raise ValueError(
                f"prompt {version} changed since run creation; expected {expected_hash[:12]}, "
                f"got {actual_hash[:12]}"
            )
    return version


def _claim_storage_lease(
    *,
    db_url: Optional[str],
    job_id: str,
    worker_id: str,
    lease_seconds: int,
    expected_stage: str = "preflight_passed",
) -> bool:
    """Atomically reserve the non-LLM storage stage for one worker."""
    now = utcnow()
    cutoff = now - timedelta(seconds=max(1, lease_seconds))
    with db.session_scope(db_url) as session:
        prior = session.get(CombinationJob, job_id)
        if prior is None:
            raise KeyError(job_id)
        if prior.stage != expected_stage:
            return False
        stale = bool(
            prior.status is CombinationJobStatus.INFLIGHT
            and (
                prior.lease_started_at is None
                or (
                    prior.lease_started_at.replace(tzinfo=timezone.utc)
                    if prior.lease_started_at.tzinfo is None
                    else prior.lease_started_at
                )
                < cutoff
            )
        )
        if prior.status not in {
            CombinationJobStatus.PENDING,
            CombinationJobStatus.INFLIGHT,
        } or (prior.status is CombinationJobStatus.INFLIGHT and not stale):
            return False
        conditions = [
            CombinationJob.id == job_id,
            CombinationJob.stage == expected_stage,
            CombinationJob.status == prior.status,
        ]
        if prior.status is CombinationJobStatus.INFLIGHT:
            conditions.extend(
                [
                    CombinationJob.lease_owner == prior.lease_owner
                    if prior.lease_owner is not None
                    else CombinationJob.lease_owner.is_(None),
                    CombinationJob.lease_started_at == prior.lease_started_at
                    if prior.lease_started_at is not None
                    else CombinationJob.lease_started_at.is_(None),
                ]
            )
        result = session.exec(
            update(CombinationJob)
            .where(*conditions)
            .values(
                status=CombinationJobStatus.INFLIGHT,
                lease_started_at=now,
                lease_owner=worker_id,
                updated_at=now,
            )
        )
        return getattr(result, "rowcount", 0) == 1


def _ensure_storage_lock(db_url: Optional[str]) -> None:
    """Create the singleton lock row once, tolerating a concurrent creator."""
    try:
        with db.session_scope(db_url) as session:
            if session.get(CombinationStorageLock, 1) is None:
                session.add(CombinationStorageLock(id=1))
                session.flush()
    except IntegrityError:
        # Another process inserted the same singleton between our read/write.
        pass


def _store_job_problem(
    db_url: Optional[str],
    job_id: str,
    dedup_index: _DedupIndex,
    *,
    worker_id: str,
    expected_stage: str = "preflight_passed",
) -> str:
    problem_id = f"distill-combo-{hashlib.sha256(job_id.encode()).hexdigest()[:12]}"
    _ensure_storage_lock(db_url)
    with db.session_scope(db_url) as session:
        # This UPDATE is intentionally the transaction's first statement.  It
        # obtains a row lock on server databases and a writer lock on SQLite;
        # every subsequent duplicate read therefore observes prior stores.
        lock_result = session.exec(
            update(CombinationStorageLock)
            .where(CombinationStorageLock.id == 1)
            .values(owner_job_id=job_id, updated_at=utcnow())
        )
        if getattr(lock_result, "rowcount", 0) != 1:
            raise RuntimeError("combination storage lock is unavailable")
        job = session.get(CombinationJob, job_id)
        if job is None:
            raise KeyError(job_id)
        if (
            job.status is not CombinationJobStatus.INFLIGHT
            or job.stage != expected_stage
            or job.lease_owner != worker_id
        ):
            return ""
        draft = dict(job.draft)
        bridge = dict(job.selected_bridge)
        ids = list(job.technique_ids)
        prompt_versions = _validate_prompt_versions(job.config or {})
        pipeline_version = _pipeline_version(job.config or {})
        is_v2 = pipeline_version == PIPELINE_V2
        design = dict(job.design_artifacts or {})
        validated_config = _validate_combination_config(job.config or {})
        if (
            is_v2
            and validated_config["novelty_gate_version"]
            == CORPUS_NOVELTY_GATE_V1
        ):
            bound_novelty_audit = _current_v2_novelty_audit(job)
            if bound_novelty_audit.get("computed_novelty_pass") is not True:
                raise ValueError(
                    f"v2 job {job.id} cannot store without a passing novelty audit"
                )
        repair_count = int(design.get("regeneration_count") or 0)
        final_prompt_version = (
            prompt_versions.get("repair", CREATIVITY_REPAIR_PROMPT)
            if is_v2 and repair_count
            else prompt_versions["problem"]
        )
        blind_audits = dict(design.get("blind_audits") or {})
        blind_round = "revised" if repair_count else "initial"
        final_blind_audit = dict(blind_audits.get(blind_round) or {})
        novelty_neighbors = dict(design.get("novelty_neighbors") or {})
        novelty_audits = dict(design.get("novelty_audits") or {})
        final_novelty_neighbors = dict(novelty_neighbors.get(blind_round) or {})
        final_novelty_audit = dict(novelty_audits.get(blind_round) or {})
        final_difficulty = draft["difficulty"]
        if is_v2:
            blind_score = (final_blind_audit.get("difficulty") or {}).get("score")
            if isinstance(blind_score, (int, float)) and not isinstance(
                blind_score, bool
            ):
                final_difficulty = float(blind_score)
        existing = session.get(Problem, problem_id)
        if existing is not None:
            if (existing.provenance or {}).get("combo_job_id") != job_id:
                raise ValueError(f"deterministic problem ID collision: {problem_id}")
            if (
                existing.statement != draft.get("statement")
                or normalize_aime_answer(existing.answer) != draft.get("answer")
                or (existing.provenance or {}).get("required_techniques") != ids
            ):
                raise ValueError(f"stored problem does not reconcile with job {job_id}")
            stored_solutions = session.exec(
                select(Solution).where(Solution.problem_id == problem_id)
            ).all()
            matching_solution = any(
                solution.text == draft.get("solution")
                and list(solution.techniques or []) == ids
                for solution in stored_solutions
            )
            if stored_solutions and not matching_solution:
                raise ValueError(f"stored solution does not reconcile with job {job_id}")
            if not stored_solutions:
                session.add(
                    Solution(
                        problem_id=problem_id,
                        text=draft["solution"],
                        techniques=ids,
                        crux_insight=str(
                            draft.get("crux") or bridge.get("crux") or ""
                        ),
                        source=SolutionSource.MODEL,
                        extractor_model=(job.config or {}).get("generator_model"),
                        features={
                            "combo_job_id": job.id,
                            "prompt_version": final_prompt_version,
                            "technique_usage": draft.get("technique_usage") or {},
                            "bypass_check": draft.get("bypass_check"),
                            "bypass_attempts": draft.get("bypass_attempts"),
                            "verification": draft.get("verification"),
                            "novelty_delta": draft.get("novelty_delta"),
                            "repair_summary": draft.get("repair_summary"),
                        },
                    )
                )
            job.problem_id = problem_id
            job.stage = "stored"
            job.status = CombinationJobStatus.STORED
            job.lease_started_at = None
            job.lease_owner = None
            job.updated_at = utcnow()
            session.add(job)
            return problem_id

        digest = statement_hash(draft["statement"])
        canonical_digest = canonical_statement_hash(draft["statement"])

        # The claim is inserted in the same transaction as the Problem.  A
        # savepoint lets a losing worker handle the uniqueness error without
        # poisoning its outer transaction, while the primary key serializes
        # identical canonical statements across jobs/processes.
        claim = session.get(CombinationStatementClaim, canonical_digest)
        if claim is None:
            try:
                with session.begin_nested():
                    session.add(
                        CombinationStatementClaim(
                            canonical_hash=canonical_digest,
                            statement_hash=digest,
                            job_id=job_id,
                            problem_id=problem_id,
                        )
                    )
                    session.flush()
            except IntegrityError:
                session.expire_all()
            claim = session.get(CombinationStatementClaim, canonical_digest)
        if claim is None:
            raise RuntimeError("canonical statement claim was not persisted")
        if claim.job_id != job_id:
            job.status = CombinationJobStatus.REJECTED
            job.rejection_reason = f"duplicate_claim: {claim.job_id}"
            job.lease_started_at = None
            job.lease_owner = None
            job.updated_at = utcnow()
            session.add(job)
            return ""

        all_problems = session.exec(select(Problem)).all()
        draft_signature = token_set(draft["statement"])
        duplicate = next(
            (
                problem
                for problem in all_problems
                if (problem.statement_hash or statement_hash(problem.statement))
                == digest
                or canonical_statement_hash(problem.statement) == canonical_digest
                or is_near_duplicate(
                    draft_signature, [token_set(problem.statement)]
                )
            ),
            None,
        )
        if duplicate is not None:
            job.status = CombinationJobStatus.REJECTED
            job.rejection_reason = f"duplicate_at_store: {duplicate.id}"
            job.lease_started_at = None
            job.lease_owner = None
            job.updated_at = utcnow()
            session.add(job)
            return ""

        provenance = {
            "pipeline": (
                "distill-combo-bridge-shell-v2"
                if is_v2
                else "distill-combo-bridge-v1"
            ),
            "run_id": job.run_id,
            "combo_job_id": job.id,
            "generator_model": (job.config or {}).get("generator_model"),
            "bridge_judge_model": (job.config or {}).get("judge_model"),
            "repaired": bool(is_v2 and repair_count),
            "techniques": ids,
            "required_techniques": ids,
            "technique_snapshot": job.technique_snapshot,
            "taxonomy_sha256": job.taxonomy_sha256,
            "sampler": job.sampler_metadata,
            # The top-level crux describes the final generated problem. Keep
            # the more general bridge crux in provenance["bridge"]["selected"].
            "crux": draft.get("crux") or bridge.get("crux"),
            "draft_crux": draft.get("crux"),
            "bridge": {
                "prompt_version": prompt_versions.get("bridge", BRIDGE_PROMPT),
                "judge_prompt_version": prompt_versions.get(
                    "bridge_judge", BRIDGE_JUDGE_PROMPT
                ),
                "selected": bridge,
                "candidates": (job.bridge_candidates or {}).get("candidates", []),
                "judgment": job.bridge_judgment,
            },
            "generation": {
                "prompt_version": final_prompt_version,
                "initial_prompt_version": prompt_versions.get(
                    "problem", PROBLEM_PROMPT
                ),
                "call_ids": (job.call_ids or {}).get("compose", []),
                "compose_call_ids": (job.call_ids or {}).get("compose", []),
                "repair_call_ids": (job.call_ids or {}).get(
                    "creativity_repair", []
                ),
                "declared_difficulty": draft.get("difficulty"),
            },
            "preflight": job.preflight,
            "call_ids": job.call_ids,
            "execution": {
                "seed": job.seed,
                "attempts": job.attempts,
                "failures": job.failures,
                "generator_backend": (job.config or {}).get("generator_backend"),
                "judge_backend": (job.config or {}).get("judge_backend"),
                "prompt_versions": prompt_versions,
                "prompt_hashes": (job.config or {}).get("prompt_hashes") or {},
                "pipeline_version": pipeline_version,
                "novelty_gate_version": (job.config or {}).get(
                    "novelty_gate_version", CORPUS_NOVELTY_GATE_DISABLED
                ),
            },
        }
        if is_v2:
            provenance.update(
                {
                    "design": design,
                    "shell": dict(design.get("shells") or {}),
                    "blind_audit": final_blind_audit,
                    "regeneration_count": repair_count,
                    "automated_creativity_gate_passed": True,
                    # The final setter proof is the only stored solution audited
                    # for both required techniques. Independent solver attempts
                    # remain in provenance/DB for correctness evidence.
                    "prefer_generator_solution": True,
                }
            )
            if (
                (job.config or {}).get("novelty_gate_version")
                == CORPUS_NOVELTY_GATE_V1
            ):
                provenance.update(
                    {
                        "corpus_novelty_gate_passed": bool(
                            final_novelty_audit.get("computed_novelty_pass")
                        ),
                        "corpus_novelty": {
                            "gate_version": CORPUS_NOVELTY_GATE_V1,
                            "prompt_version": (job.config or {}).get(
                                "novelty_prompt_version"
                            ),
                            "retrieval": final_novelty_neighbors,
                            "audit": final_novelty_audit,
                        },
                    }
                )
        problem = Problem(
            id=problem_id,
            source=ProblemSource.SYNTHETIC,
            statement=draft["statement"],
            answer=draft["answer"],
            difficulty=final_difficulty,
            topic=draft["topic"],
            split=DataSplit.TRAIN,
            frozen=False,
            verified=None,
            review_status=ReviewStatus.PENDING,
            possibly_memorized=False,
            provenance=provenance,
        ).refresh_dedup_fields()
        session.add(problem)
        claim.problem_id = problem_id
        session.add(claim)
        session.add(
            Solution(
                problem_id=problem_id,
                text=draft["solution"],
                techniques=ids,
                crux_insight=str(
                    draft.get("crux") or bridge.get("crux") or ""
                ),
                source=SolutionSource.MODEL,
                extractor_model=(job.config or {}).get("generator_model"),
                features={
                    "combo_job_id": job.id,
                    "prompt_version": final_prompt_version,
                    "technique_usage": draft.get("technique_usage") or {},
                    "bypass_check": draft.get("bypass_check"),
                    "bypass_attempts": draft.get("bypass_attempts"),
                    "verification": draft.get("verification"),
                    "novelty_delta": draft.get("novelty_delta"),
                    "repair_summary": draft.get("repair_summary"),
                },
            )
        )
        job.problem_id = problem_id
        job.stage = "stored"
        job.status = CombinationJobStatus.STORED
        job.lease_started_at = None
        job.lease_owner = None
        job.updated_at = utcnow()
        session.add(job)

    dedup_index.hashes.add(statement_hash(draft["statement"]))
    dedup_index.canonical_hashes.add(canonical_statement_hash(draft["statement"]))
    dedup_index.statement_signatures.append(token_set(draft["statement"]))
    if bridge.get("crux"):
        dedup_index.crux_signatures.append(token_set(str(bridge["crux"])))
    return problem_id


def _v2_design(job: CombinationJob) -> dict[str, Any]:
    design = dict(job.design_artifacts or {})
    design.setdefault("schema_version", "combo_design_artifacts_v2")
    design.setdefault("shells", {})
    design.setdefault("drafts", {})
    design.setdefault("blind_audits", {})
    design.setdefault("preflights", {})
    design.setdefault("novelty_neighbors", {})
    design.setdefault("novelty_audits", {})
    design.setdefault("repair_history", [])
    design.setdefault("regeneration_count", 0)
    return design


def _v2_design_put(
    job: CombinationJob, section: str, key: str, value: Any
) -> dict[str, Any]:
    design = _v2_design(job)
    nested = dict(design.get(section) or {})
    nested[key] = value
    design[section] = nested
    return design


def _v2_round(job: CombinationJob) -> str:
    return "revised" if int(_v2_design(job).get("regeneration_count") or 0) else "initial"


def _v2_selected_shell(job: CombinationJob) -> dict[str, Any]:
    shell = dict((_v2_design(job).get("shells") or {}).get("selected") or {})
    if not shell:
        raise ValueError(f"v2 job {job.id} has no selected shell")
    return shell


def _request_v2_repair(
    *,
    job: CombinationJob,
    db_url: Optional[str],
    source: str,
    feedback: Any,
) -> bool:
    config = _validate_combination_config(job.config or {})
    design = _v2_design(job)
    count = int(design.get("regeneration_count") or 0)
    if count >= int(config.get("max_creativity_repairs", 0)):
        return False
    history = list(design.get("repair_history") or [])
    history.append(
        {
            "round": count + 1,
            "requested_at": _utc_iso(),
            "source": source,
            "statement_hash": statement_hash(str((job.draft or {}).get("statement") or "")),
            "feedback": feedback,
        }
    )
    design["repair_history"] = history
    design["regeneration_count"] = count + 1
    design["repair_request"] = history[-1]
    _update_job(
        db_url,
        job.id,
        expected_stage=job.stage,
        design_artifacts=design,
        stage="repair_pending",
    )
    return True


def _current_v2_blind_audit(job: CombinationJob) -> dict[str, Any]:
    round_name = _v2_round(job)
    audit = dict((_v2_design(job).get("blind_audits") or {}).get(round_name) or {})
    if not audit:
        raise ValueError(f"v2 job {job.id} has no {round_name} blind audit")
    current_hash = statement_hash(str((job.draft or {}).get("statement") or ""))
    if audit.get("statement_hash") != current_hash:
        raise ValueError(f"v2 job {job.id} blind audit is bound to a stale statement")
    return audit


def _current_v2_novelty_neighbors(job: CombinationJob) -> dict[str, Any]:
    round_name = _v2_round(job)
    retrieval = dict(
        (_v2_design(job).get("novelty_neighbors") or {}).get(round_name) or {}
    )
    if not retrieval:
        raise ValueError(f"v2 job {job.id} has no {round_name} novelty retrieval")
    if retrieval.get("round") != round_name:
        raise ValueError(f"v2 job {job.id} novelty retrieval has the wrong round")
    current_hash = statement_hash(str((job.draft or {}).get("statement") or ""))
    if retrieval.get("statement_hash") != current_hash:
        raise ValueError(
            f"v2 job {job.id} novelty retrieval is bound to a stale statement"
        )
    if not list(retrieval.get("neighbors") or []):
        raise ValueError(f"v2 job {job.id} novelty retrieval has no neighbors")
    if retrieval.get("missing_evidence_ids"):
        raise ValueError(
            f"v2 job {job.id} novelty retrieval is missing pair evidence"
        )
    expected_hash = _json_hash(
        {key: value for key, value in retrieval.items() if key != "retrieval_hash"}
    )
    if retrieval.get("retrieval_hash") != expected_hash:
        raise ValueError(f"v2 job {job.id} novelty retrieval hash is invalid")
    return retrieval


def _current_v2_novelty_audit(job: CombinationJob) -> dict[str, Any]:
    round_name = _v2_round(job)
    audit = dict(
        (_v2_design(job).get("novelty_audits") or {}).get(round_name) or {}
    )
    if not audit:
        raise ValueError(f"v2 job {job.id} has no {round_name} novelty audit")
    if audit.get("round") != round_name:
        raise ValueError(f"v2 job {job.id} novelty audit has the wrong round")
    current_hash = statement_hash(str((job.draft or {}).get("statement") or ""))
    if audit.get("statement_hash") != current_hash:
        raise ValueError(f"v2 job {job.id} novelty audit is bound to a stale statement")
    retrieval = _current_v2_novelty_neighbors(job)
    if audit.get("retrieval_hash") != retrieval.get("retrieval_hash"):
        raise ValueError(f"v2 job {job.id} novelty audit used a stale retrieval")
    return audit


def _process_job(
    *,
    job_id: str,
    generator: LLMClient,
    judge: LLMClient,
    db_url: Optional[str],
    dedup_index: _DedupIndex,
    worker_id: str,
) -> None:
    while True:
        with db.session_scope(db_url) as session:
            job = session.get(CombinationJob, job_id)
            if job is None:
                raise KeyError(job_id)
        if job.status in TERMINAL_STATUSES:
            return
        technique_ids = tuple(job.technique_ids)
        if len(technique_ids) != 2:
            _reject_job(
                db_url,
                job_id,
                "invalid checkpoint: expected exactly two techniques",
                expected_stage=job.stage,
            )
            return
        pair = (str(technique_ids[0]), str(technique_ids[1]))
        config = _validate_combination_config(job.config or {})
        is_v2 = config["pipeline_version"] == PIPELINE_V2
        snapshots_json = json.dumps(
            _prompt_snapshots(job.technique_snapshot), ensure_ascii=False, indent=2
        )
        target_band = config["target_difficulty"]
        target_text = f"{target_band[0]:g}-{target_band[1]:g}"
        overlap_values = (
            (job.sampler_metadata or {}).get("difficulty_overlap") or target_band
        )
        overlap_band = _validated_difficulty_band(
            overlap_values, label="sampler difficulty_overlap"
        )
        overlap_text = f"{overlap_band[0]:g}-{overlap_band[1]:g}"

        if job.stage == "pair_selected":
            bridge_count = int((job.config or {}).get("bridges_per_pair", 3))
            prompt_version = _prompt_version(job, "bridge", BRIDGE_PROMPT)
            prompt = render_prompt(
                prompt_version,
                bridge_count=bridge_count,
                techniques_json=snapshots_json,
                target_difficulty=target_text,
                difficulty_overlap=overlap_text,
            )
            payload = _stage_call(
                db_url=db_url,
                job_id=job_id,
                stage="bridge_proposal",
                expected_job_stage="pair_selected",
                prompt_version=prompt_version,
                prompt=prompt,
                client=generator,
                parser=lambda text: parse_bridge_proposals(text, pair, bridge_count),
                purpose="combo-bridge-propose",
                generator_stage=True,
                json_contract=True,
                worker_id=worker_id,
                success_values=lambda value: {
                    "bridge_candidates": value,
                    "stage": "bridges_proposed",
                },
            )
            if payload is None:
                return
            continue

        if job.stage == "bridges_proposed":
            candidates = list((job.bridge_candidates or {}).get("candidates") or [])
            bridge_ids = tuple(str(candidate.get("bridge_id")) for candidate in candidates)
            prompt_version = _prompt_version(job, "bridge_judge", BRIDGE_JUDGE_PROMPT)
            prompt = render_prompt(
                prompt_version,
                techniques_json=snapshots_json,
                bridges_json=json.dumps(
                    _prompt_bridge_proposals(job.bridge_candidates),
                    ensure_ascii=False,
                    indent=2,
                ),
            )
            payload = _stage_call(
                db_url=db_url,
                job_id=job_id,
                stage="bridge_judgment",
                expected_job_stage="bridges_proposed",
                prompt_version=prompt_version,
                prompt=prompt,
                client=judge,
                parser=lambda text: parse_bridge_judgment(text, bridge_ids),
                purpose="combo-bridge-judge",
                generator_stage=False,
                json_contract=True,
                worker_id=worker_id,
                success_values=lambda value: {
                    "bridge_judgment": value,
                    "stage": "bridges_judged",
                },
            )
            if payload is None:
                return
            continue

        if job.stage == "bridges_judged":
            candidates = list((job.bridge_candidates or {}).get("candidates") or [])
            winner = (job.bridge_judgment or {}).get("computed_selected_bridge_id")
            if winner is None:
                _reject_job(
                    db_url,
                    job_id,
                    "bridge_rejected: no proposal passed hard gates",
                    expected_stage="bridges_judged",
                )
                return
            selected = next(
                candidate for candidate in candidates if candidate["bridge_id"] == winner
            )
            _update_job(
                db_url,
                job_id,
                expected_stage="bridges_judged",
                selected_bridge=selected,
                stage="bridge_selected",
            )
            continue

        if job.stage == "bridge_selected" and is_v2:
            shell_count = int(config["shells_per_bridge"])
            prompt_version = _prompt_version(job, "shell", SHELL_PROMPT)
            prompt = render_prompt(
                prompt_version,
                techniques_json=snapshots_json,
                bridge_json=json.dumps(
                    _prompt_bridge(job.selected_bridge), ensure_ascii=False, indent=2
                ),
                target_difficulty=target_text,
                creativity_floor=int(config["creativity_floor"]),
            )
            payload = _stage_call(
                db_url=db_url,
                job_id=job_id,
                stage="shell_proposal",
                expected_job_stage="bridge_selected",
                prompt_version=prompt_version,
                prompt=prompt,
                client=generator,
                parser=lambda text: parse_shell_proposals(
                    text,
                    str(job.selected_bridge.get("bridge_id")),
                    pair,
                    target_band,
                    shell_count,
                ),
                purpose="combo-shell-propose",
                generator_stage=True,
                json_contract=True,
                worker_id=worker_id,
                success_values=lambda value: {
                    "design_artifacts": _v2_design_put(
                        job, "shells", "generation", value
                    ),
                    "stage": "shells_proposed",
                },
            )
            if payload is None:
                return
            continue

        if job.stage == "shells_proposed" and is_v2:
            generation = dict((_v2_design(job).get("shells") or {}).get("generation") or {})
            shells = list(generation.get("shells") or [])
            shell_ids = tuple(str(shell.get("shell_id")) for shell in shells)
            prompt_version = _prompt_version(job, "shell_judge", SHELL_JUDGE_PROMPT)
            prompt = render_prompt(
                prompt_version,
                techniques_json=snapshots_json,
                bridge_json=json.dumps(
                    _prompt_bridge(job.selected_bridge), ensure_ascii=False, indent=2
                ),
                shells_json=json.dumps(
                    _prompt_shell_proposals(generation), ensure_ascii=False, indent=2
                ),
                creativity_floor=int(config["creativity_floor"]),
            )
            payload = _stage_call(
                db_url=db_url,
                job_id=job_id,
                stage="shell_judgment",
                expected_job_stage="shells_proposed",
                prompt_version=prompt_version,
                prompt=prompt,
                client=judge,
                parser=lambda text: parse_shell_judgment(
                    text,
                    shell_ids,
                    pair,
                    creativity_floor=int(config["creativity_floor"]),
                ),
                purpose="combo-shell-judge",
                generator_stage=False,
                json_contract=True,
                worker_id=worker_id,
                success_values=lambda value: {
                    "design_artifacts": _v2_design_put(
                        job, "shells", "judgment", value
                    ),
                    "stage": "shells_judged",
                },
            )
            if payload is None:
                return
            continue

        if job.stage == "shells_judged" and is_v2:
            design = _v2_design(job)
            shells_section = dict(design.get("shells") or {})
            judgment = dict(shells_section.get("judgment") or {})
            winner = judgment.get("computed_selected_shell_id")
            if winner is None:
                _reject_job(
                    db_url,
                    job_id,
                    "shell_rejected: no shell passed validity and novelty gates",
                    expected_stage="shells_judged",
                )
                return
            generation = dict(shells_section.get("generation") or {})
            selected = next(
                shell for shell in generation.get("shells", []) if shell["shell_id"] == winner
            )
            shells_section["selected"] = selected
            design["shells"] = shells_section
            _update_job(
                db_url,
                job_id,
                expected_stage="shells_judged",
                design_artifacts=design,
                stage="shell_selected",
            )
            continue

        if job.stage == "bridge_selected" and not is_v2:
            prompt_version = _prompt_version(job, "problem", PROBLEM_PROMPT)
            prompt = render_prompt(
                prompt_version,
                techniques_json=snapshots_json,
                bridge_json=json.dumps(
                    _prompt_bridge(job.selected_bridge), ensure_ascii=False, indent=2
                ),
                target_difficulty=target_text,
            )
            bridge_id = str(job.selected_bridge.get("bridge_id"))
            payload = _stage_call(
                db_url=db_url,
                job_id=job_id,
                stage="compose",
                expected_job_stage="bridge_selected",
                prompt_version=prompt_version,
                prompt=prompt,
                client=generator,
                parser=lambda text: parse_combo_draft(text, bridge_id, pair, target_band),
                purpose="combo-compose",
                generator_stage=True,
                json_contract=False,
                worker_id=worker_id,
                success_values=lambda value: {
                    "draft": value,
                    "stage": "draft_generated",
                },
            )
            if payload is None:
                return
            continue

        if job.stage == "shell_selected" and is_v2:
            shell = _v2_selected_shell(job)
            prompt_version = _prompt_version(job, "problem", PROBLEM_PROMPT_V2)
            prompt = render_prompt(
                prompt_version,
                techniques_json=snapshots_json,
                bridge_json=json.dumps(
                    _prompt_bridge(job.selected_bridge), ensure_ascii=False, indent=2
                ),
                shell_json=json.dumps(_prompt_shell(shell), ensure_ascii=False, indent=2),
                target_difficulty=target_text,
                creativity_floor=int(config["creativity_floor"]),
                blind_difficulty_floor=f"{float(config['blind_difficulty_floor']):g}",
            )
            bridge_id = str(job.selected_bridge.get("bridge_id"))
            payload = _stage_call(
                db_url=db_url,
                job_id=job_id,
                stage="compose",
                expected_job_stage="shell_selected",
                prompt_version=prompt_version,
                prompt=prompt,
                client=generator,
                parser=lambda text: parse_combo_draft_v2(
                    text,
                    bridge_id,
                    str(shell.get("shell_id")),
                    pair,
                    target_band,
                ),
                purpose="combo-compose-v2",
                generator_stage=True,
                json_contract=False,
                worker_id=worker_id,
                success_values=lambda value: {
                    "draft": value,
                    "design_artifacts": _v2_design_put(job, "drafts", "initial", value),
                    "stage": "draft_generated",
                },
            )
            if payload is None:
                return
            continue

        if job.stage in {"draft_generated", "draft_repaired"}:
            static_issues = _static_draft_issues(
                job.draft, job.selected_bridge, job.technique_snapshot, dedup_index
            )
            if static_issues:
                if is_v2 and _request_v2_repair(
                    job=job,
                    db_url=db_url,
                    source="static_filter",
                    feedback={"static_issues": static_issues},
                ):
                    continue
                _reject_job(
                    db_url,
                    job_id,
                    "draft_filter: " + ", ".join(static_issues),
                    expected_stage=job.stage,
                    extra_values={"preflight": {"static_issues": static_issues}},
                )
                return

            if not is_v2:
                prompt_version = _prompt_version(job, "preflight", FAITHFULNESS_PROMPT)
                untrusted_claims_removed = {
                    key: job.draft[key] for key in ("statement", "answer", "solution")
                }
                prompt = render_prompt(
                    prompt_version,
                    techniques_json=snapshots_json,
                    bridge_json=json.dumps(
                        _prompt_bridge(job.selected_bridge), ensure_ascii=False, indent=2
                    ),
                    draft_json=json.dumps(
                        untrusted_claims_removed, ensure_ascii=False, indent=2
                    ),
                )
                payload = _stage_call(
                    db_url=db_url,
                    job_id=job_id,
                    stage="preflight",
                    expected_job_stage="draft_generated",
                    prompt_version=prompt_version,
                    prompt=prompt,
                    client=judge,
                    parser=lambda text: parse_faithfulness(text, pair),
                    purpose="combo-preflight",
                    generator_stage=False,
                    json_contract=True,
                    worker_id=worker_id,
                    success_values=lambda value: {
                        "preflight": {"static_issues": [], "faithfulness": value},
                        "stage": "preflight_judged",
                    },
                )
                if payload is None:
                    return
                continue

            round_name = _v2_round(job)
            blind_stage = "blind_audit_r1" if round_name == "revised" else "blind_audit_r0"
            judged_stage = (
                "blind_revised_judged" if round_name == "revised" else "blind_initial_judged"
            )
            prompt_version = _prompt_version(job, "blind_audit", BLIND_AUDIT_PROMPT)
            prompt = render_prompt(
                prompt_version,
                statement=job.draft["statement"],
                target_difficulty=target_text,
                creativity_floor=int(config["creativity_floor"]),
                blind_difficulty_floor=f"{float(config['blind_difficulty_floor']):g}",
            )

            def blind_checkpoint(value: dict[str, Any]) -> dict[str, Any]:
                artifact = dict(value)
                artifact["statement_hash"] = statement_hash(job.draft["statement"])
                artifact["round"] = round_name
                return {
                    "design_artifacts": _v2_design_put(
                        job, "blind_audits", round_name, artifact
                    ),
                    "stage": judged_stage,
                }

            payload = _stage_call(
                db_url=db_url,
                job_id=job_id,
                stage=blind_stage,
                expected_job_stage=job.stage,
                prompt_version=prompt_version,
                prompt=prompt,
                client=judge,
                parser=lambda text: parse_blind_audit(
                    text,
                    str(job.draft["answer"]),
                    target_band,
                    creativity_floor=int(config["creativity_floor"]),
                    difficulty_floor=float(config["blind_difficulty_floor"]),
                ),
                purpose="combo-blind-audit",
                generator_stage=False,
                json_contract=True,
                worker_id=worker_id,
                success_values=blind_checkpoint,
            )
            if payload is None:
                return
            continue

        if job.stage in {"blind_initial_judged", "blind_revised_judged"} and is_v2:
            try:
                audit = _current_v2_blind_audit(job)
            except ValueError as exc:
                _reject_job(
                    db_url,
                    job_id,
                    f"invalid checkpoint: {exc}",
                    expected_stage=job.stage,
                )
                return
            action = audit.get("computed_action")
            if action == "accept":
                _update_job(
                    db_url,
                    job_id,
                    expected_stage=job.stage,
                    stage="blind_audit_passed",
                )
                continue
            if action == "repair" and _request_v2_repair(
                job=job,
                db_url=db_url,
                source="blind_audit",
                feedback=audit,
            ):
                continue
            _reject_job(
                db_url,
                job_id,
                "blind_audit_rejected: "
                + (
                    "policy failures=" + ",".join(audit.get("policy_failures") or [])
                    if audit.get("policy_failures")
                    else str(audit.get("reason") or action or "rejected")
                ),
                expected_stage=job.stage,
            )
            return

        if job.stage == "blind_audit_passed" and is_v2:
            try:
                blind_audit = _current_v2_blind_audit(job)
            except ValueError as exc:
                _reject_job(
                    db_url,
                    job_id,
                    f"invalid checkpoint: {exc}",
                    expected_stage="blind_audit_passed",
                )
                return
            shell = _v2_selected_shell(job)
            prompt_version = _prompt_version(job, "preflight", FAITHFULNESS_PROMPT_V2)
            prompt = render_prompt(
                prompt_version,
                techniques_json=snapshots_json,
                bridge_json=json.dumps(
                    _prompt_bridge(job.selected_bridge), ensure_ascii=False, indent=2
                ),
                shell_json=json.dumps(_prompt_shell(shell), ensure_ascii=False, indent=2),
                draft_json=json.dumps(job.draft, ensure_ascii=False, indent=2),
                blind_audit_json=json.dumps(blind_audit, ensure_ascii=False, indent=2),
                creativity_floor=int(config["creativity_floor"]),
            )
            round_name = _v2_round(job)
            stage_name = "preflight_repair" if round_name == "revised" else "preflight"

            def preflight_checkpoint(value: dict[str, Any]) -> dict[str, Any]:
                return {
                    "preflight": {"static_issues": [], "faithfulness": value},
                    "design_artifacts": _v2_design_put(
                        job, "preflights", round_name, value
                    ),
                    "stage": "preflight_judged",
                }

            payload = _stage_call(
                db_url=db_url,
                job_id=job_id,
                stage=stage_name,
                expected_job_stage="blind_audit_passed",
                prompt_version=prompt_version,
                prompt=prompt,
                client=judge,
                parser=lambda text: parse_faithfulness(
                    text,
                    pair,
                    schema_version=FAITHFULNESS_PROMPT_V2,
                    creativity_floor=int(config["creativity_floor"]),
                ),
                purpose="combo-preflight-v2",
                generator_stage=False,
                json_contract=True,
                worker_id=worker_id,
                success_values=preflight_checkpoint,
            )
            if payload is None:
                return
            continue

        if job.stage == "preflight_judged":
            faithfulness = (job.preflight or {}).get("faithfulness") or {}
            passed = bool(
                faithfulness.get("verdict") == "accept"
                and faithfulness.get("computed_quality_pass", True)
            )
            if passed:
                if (
                    is_v2
                    and config["novelty_gate_version"]
                    == CORPUS_NOVELTY_GATE_V1
                ):
                    # Rebuild here, not once per run: sequential jobs must see
                    # candidates stored by earlier jobs in the same batch.
                    novelty_index = _build_novelty_index(db_url)
                    retrieval = _novelty_neighbor_payload(
                        job=job,
                        draft=dict(job.draft or {}),
                        index=novelty_index,
                        neighbor_count=int(config["novelty_neighbor_count"]),
                    )
                    if not retrieval["neighbors"]:
                        _reject_job(
                            db_url,
                            job_id,
                            "novelty_retrieval_invalid: corpus returned no neighbors",
                            expected_stage="preflight_judged",
                        )
                        return
                    if retrieval["missing_evidence_ids"]:
                        _reject_job(
                            db_url,
                            job_id,
                            "novelty_retrieval_invalid: missing pair evidence "
                            + ",".join(retrieval["missing_evidence_ids"]),
                            expected_stage="preflight_judged",
                        )
                        return
                    round_name = _v2_round(job)
                    retrieval["round"] = round_name
                    retrieval["retrieval_hash"] = _json_hash(
                        {
                            key: value
                            for key, value in retrieval.items()
                            if key != "retrieval_hash"
                        }
                    )
                    _update_job(
                        db_url,
                        job_id,
                        expected_stage="preflight_judged",
                        design_artifacts=_v2_design_put(
                            job, "novelty_neighbors", round_name, retrieval
                        ),
                        stage="novelty_retrieved",
                    )
                    continue
                _update_job(
                    db_url,
                    job_id,
                    expected_stage="preflight_judged",
                    stage="quality_passed" if is_v2 else "preflight_passed",
                )
                continue
            if (
                is_v2
                and faithfulness.get("well_posed") is True
                and faithfulness.get("answer_consistent") is True
                and _request_v2_repair(
                    job=job,
                    db_url=db_url,
                    source="faithfulness",
                    feedback=faithfulness,
                )
            ):
                continue
            _reject_job(
                db_url,
                job_id,
                "preflight_rejected: "
                + str(faithfulness.get("reason") or "rejected"),
                expected_stage="preflight_judged",
            )
            return

        if job.stage == "novelty_retrieved" and is_v2:
            if config["novelty_gate_version"] != CORPUS_NOVELTY_GATE_V1:
                _reject_job(
                    db_url,
                    job_id,
                    "invalid checkpoint: novelty stage without enabled gate",
                    expected_stage="novelty_retrieved",
                )
                return
            try:
                retrieval = _current_v2_novelty_neighbors(job)
            except ValueError as exc:
                _reject_job(
                    db_url,
                    job_id,
                    f"invalid checkpoint: {exc}",
                    expected_stage="novelty_retrieved",
                )
                return
            round_name = _v2_round(job)
            neighbors = list(retrieval["neighbors"])
            neighbor_ids = tuple(
                str(neighbor["neighbor_id"]) for neighbor in neighbors
            )
            prompt_version = str(config["novelty_prompt_version"])
            prompt = render_prompt(
                prompt_version,
                candidate_json=json.dumps(
                    {
                        "statement": job.draft.get("statement"),
                        "crux": job.draft.get("crux"),
                        "solution": job.draft.get("solution"),
                        "technique_usage": job.draft.get("technique_usage") or {},
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                neighbors_json=json.dumps(neighbors, ensure_ascii=False, indent=2),
                distance_floor=int(config["novelty_distance_floor"]),
            )
            stage_name = (
                "novelty_audit_r1" if round_name == "revised" else "novelty_audit_r0"
            )

            def novelty_checkpoint(value: dict[str, Any]) -> dict[str, Any]:
                artifact = dict(value)
                artifact.update(
                    {
                        "round": round_name,
                        "statement_hash": statement_hash(job.draft["statement"]),
                        "retrieval_hash": retrieval["retrieval_hash"],
                    }
                )
                return {
                    "design_artifacts": _v2_design_put(
                        job, "novelty_audits", round_name, artifact
                    ),
                    "stage": "novelty_judged",
                }

            payload = _stage_call(
                db_url=db_url,
                job_id=job_id,
                stage=stage_name,
                expected_job_stage="novelty_retrieved",
                prompt_version=prompt_version,
                prompt=prompt,
                client=judge,
                parser=lambda text: parse_corpus_novelty(
                    text,
                    neighbor_ids,
                    distance_floor=int(config["novelty_distance_floor"]),
                ),
                purpose="combo-corpus-novelty",
                generator_stage=False,
                json_contract=True,
                worker_id=worker_id,
                success_values=novelty_checkpoint,
            )
            if payload is None:
                return
            continue

        if job.stage == "novelty_judged" and is_v2:
            try:
                audit = _current_v2_novelty_audit(job)
                retrieval = _current_v2_novelty_neighbors(job)
            except ValueError as exc:
                _reject_job(
                    db_url,
                    job_id,
                    f"invalid checkpoint: {exc}",
                    expected_stage="novelty_judged",
                )
                return
            if audit.get("computed_novelty_pass") is True:
                _update_job(
                    db_url,
                    job_id,
                    expected_stage="novelty_judged",
                    stage="novelty_passed",
                )
                continue
            closest_id = audit.get("computed_closest_neighbor_id")
            closest = next(
                (
                    neighbor
                    for neighbor in retrieval["neighbors"]
                    if neighbor.get("neighbor_id") == closest_id
                ),
                None,
            )
            if _request_v2_repair(
                job=job,
                db_url=db_url,
                source="corpus_novelty",
                feedback={
                    "policy_failures": audit.get("policy_failures") or [],
                    "reason": audit.get("reason"),
                    "closest_neighbor": closest,
                },
            ):
                continue
            _reject_job(
                db_url,
                job_id,
                "corpus_novelty_rejected: "
                + (
                    ",".join(audit.get("policy_failures") or [])
                    or str(audit.get("reason") or "rejected")
                ),
                expected_stage="novelty_judged",
            )
            return

        if job.stage == "repair_pending" and is_v2:
            design = _v2_design(job)
            request = dict(design.get("repair_request") or {})
            if int(design.get("regeneration_count") or 0) != 1 or not request:
                _reject_job(
                    db_url,
                    job_id,
                    "invalid checkpoint: repair request is missing or exceeds limit",
                    expected_stage="repair_pending",
                )
                return
            shell = _v2_selected_shell(job)
            prompt_version = _prompt_version(job, "repair", CREATIVITY_REPAIR_PROMPT)
            prompt = render_prompt(
                prompt_version,
                techniques_json=snapshots_json,
                bridge_json=json.dumps(
                    _prompt_bridge(job.selected_bridge), ensure_ascii=False, indent=2
                ),
                shell_json=json.dumps(_prompt_shell(shell), ensure_ascii=False, indent=2),
                draft_json=json.dumps(job.draft, ensure_ascii=False, indent=2),
                audit_json=json.dumps(request, ensure_ascii=False, indent=2),
                target_difficulty=target_text,
                creativity_floor=int(config["creativity_floor"]),
                blind_difficulty_floor=f"{float(config['blind_difficulty_floor']):g}",
            )

            def repair_checkpoint(value: dict[str, Any]) -> dict[str, Any]:
                updated = _v2_design_put(job, "drafts", "revised", value)
                updated["repair_completed_at"] = _utc_iso()
                return {
                    "draft": value,
                    "design_artifacts": updated,
                    "stage": "draft_repaired",
                }

            payload = _stage_call(
                db_url=db_url,
                job_id=job_id,
                stage="creativity_repair",
                expected_job_stage="repair_pending",
                prompt_version=prompt_version,
                prompt=prompt,
                client=generator,
                parser=lambda text: parse_combo_draft_v2(
                    text,
                    str(job.selected_bridge.get("bridge_id")),
                    str(shell.get("shell_id")),
                    pair,
                    target_band,
                    repair=True,
                ),
                purpose="combo-creativity-repair",
                generator_stage=True,
                json_contract=False,
                worker_id=worker_id,
                success_values=repair_checkpoint,
            )
            if payload is None:
                return
            continue

        novelty_enabled = (
            is_v2
            and config["novelty_gate_version"] == CORPUS_NOVELTY_GATE_V1
        )
        final_stage = (
            "novelty_passed"
            if novelty_enabled
            else ("quality_passed" if is_v2 else "preflight_passed")
        )
        if job.stage == final_stage:
            if novelty_enabled:
                try:
                    audit = _current_v2_novelty_audit(job)
                except ValueError as exc:
                    _reject_job(
                        db_url,
                        job_id,
                        f"invalid checkpoint: {exc}",
                        expected_stage=final_stage,
                    )
                    return
                if audit.get("computed_novelty_pass") is not True:
                    _reject_job(
                        db_url,
                        job_id,
                        "invalid checkpoint: novelty gate did not pass",
                        expected_stage=final_stage,
                    )
                    return
            lease_seconds = _validated_lease_seconds(job.config or {})
            if not _claim_storage_lease(
                db_url=db_url,
                job_id=job_id,
                worker_id=worker_id,
                lease_seconds=lease_seconds,
                expected_stage=final_stage,
            ):
                return
            _store_job_problem(
                db_url,
                job_id,
                dedup_index,
                worker_id=worker_id,
                expected_stage=final_stage,
            )
            return

        _reject_job(
            db_url,
            job_id,
            f"invalid checkpoint stage: {job.stage}",
            expected_stage=job.stage,
        )
        return


def combination_run_status(
    run_id: str, db_url: Optional[str] = None
) -> ComboRunReport:
    db.init_db(db_url)
    with db.session_scope(db_url) as session:
        jobs = session.exec(
            select(CombinationJob)
            .where(CombinationJob.run_id == run_id)
            .order_by(CombinationJob.ordinal)
        ).all()
    report = ComboRunReport(run_id=run_id, total=len(jobs))
    for job in jobs:
        if job.status is CombinationJobStatus.STORED:
            report.stored += 1
        elif job.status is CombinationJobStatus.REJECTED:
            report.rejected += 1
        elif job.status is CombinationJobStatus.EXHAUSTED:
            report.exhausted += 1
        else:
            report.pending += 1
        report.records.append(
            {
                "id": job.id,
                "ordinal": job.ordinal,
                "pair_key": job.pair_key,
                "tranche": (job.sampler_metadata or {}).get("actual_tranche"),
                "stage": job.stage,
                "status": job.status.value,
                "problem_id": job.problem_id,
                "rejection_reason": job.rejection_reason,
                "attempts": job.attempts,
                "pipeline_version": _pipeline_version(job.config or {}),
                "regeneration_count": int(
                    (job.design_artifacts or {}).get("regeneration_count") or 0
                ),
            }
        )
    return report


def retry_combination_jobs(
    run_id: str,
    *,
    failure_kinds: set[str],
    ordinals: Optional[set[int]] = None,
    db_url: Optional[str] = None,
) -> int:
    """Reset exhausted infrastructure/output jobs while preserving audit history."""
    if not failure_kinds:
        return 0
    db.init_db(db_url)
    reset = 0
    with db.session_scope(db_url) as session:
        jobs = session.exec(
            select(CombinationJob).where(
                CombinationJob.run_id == run_id,
                CombinationJob.status == CombinationJobStatus.EXHAUSTED,
            )
        ).all()
        for job in jobs:
            if ordinals is not None and job.ordinal not in ordinals:
                continue
            # Retry only the cause that actually made the job terminal.  An old
            # transport error must not reopen a job later exhausted by a parse
            # or content failure at another stage.
            failures = list(job.failures or [])
            terminal_failure = failures[-1] if failures else None
            if (
                terminal_failure is None
                or terminal_failure.get("kind") not in failure_kinds
            ):
                continue
            stage = str(terminal_failure.get("stage") or job.stage)
            attempts = dict(job.attempts or {})
            attempts[stage] = 0
            failures.append(
                {
                    "at": _utc_iso(),
                    "stage": stage,
                    "kind": "manual_retry_reset",
                    "message": "reset after: "
                    + str(terminal_failure.get("kind")),
                }
            )
            result = session.exec(
                update(CombinationJob)
                .where(
                    CombinationJob.id == job.id,
                    CombinationJob.status == CombinationJobStatus.EXHAUSTED,
                    CombinationJob.stage == job.stage,
                    CombinationJob.updated_at == job.updated_at,
                )
                .values(
                    attempts=attempts,
                    failures=failures,
                    status=CombinationJobStatus.PENDING,
                    rejection_reason=None,
                    lease_started_at=None,
                    lease_owner=None,
                    updated_at=utcnow(),
                )
            )
            if getattr(result, "rowcount", 0) == 1:
                reset += 1
    return reset


def process_combination_run(
    *,
    run_id: str,
    generator: LLMClient,
    judge: LLMClient,
    db_url: Optional[str] = None,
) -> ComboRunReport:
    """Resume every nonterminal job in a run; one failure never kills the batch."""
    status = combination_run_status(run_id, db_url)
    if status.total == 0:
        raise ValueError(f"combination run not found: {run_id}")
    with db.session_scope(db_url) as session:
        jobs = session.exec(
            select(CombinationJob)
            .where(CombinationJob.run_id == run_id)
            .order_by(CombinationJob.ordinal)
        ).all()
    first = jobs[0]
    _validate_combination_config(first.config or {})
    config_fingerprint = _json_hash(first.config or {})
    for job in jobs:
        if _json_hash(job.config or {}) != config_fingerprint:
            raise ValueError(f"run {run_id} contains inconsistent job configurations")
        if job.taxonomy_sha256 != first.taxonomy_sha256:
            raise ValueError(f"run {run_id} contains inconsistent taxonomy snapshots")
        for key in ("sampler_version", "alias_map_hash", "support_snapshot_hash"):
            if (job.sampler_metadata or {}).get(key) != (
                first.sampler_metadata or {}
            ).get(key):
                raise ValueError(f"run {run_id} contains inconsistent sampler metadata: {key}")
    expected_generator = (first.config or {}).get("generator_model")
    expected_judge = (first.config or {}).get("judge_model")
    if expected_generator and expected_generator != generator.model:
        raise ValueError(
            f"generator model mismatch: run expects {expected_generator}, got {generator.model}"
        )
    if expected_judge and expected_judge != judge.model:
        raise ValueError(f"judge model mismatch: run expects {expected_judge}, got {judge.model}")
    dedup_index = _build_dedup_index(db_url)
    worker_id = uuid.uuid4().hex
    for record in status.records:
        if record["status"] in {
            CombinationJobStatus.STORED.value,
            CombinationJobStatus.REJECTED.value,
            CombinationJobStatus.EXHAUSTED.value,
        }:
            continue
        try:
            _process_job(
                job_id=record["id"],
                generator=generator,
                judge=judge,
                db_url=db_url,
                dedup_index=dedup_index,
                worker_id=worker_id,
            )
        except LeaseLostError:
            # Another resumer owns the newer checkpoint; stale completion is
            # intentionally discarded without adding a misleading failure.
            continue
        except Exception as exc:  # noqa: BLE001 - leave an auditable terminal row
            with db.session_scope(db_url) as session:
                current = session.get(CombinationJob, record["id"])
            if current is None or current.status in TERMINAL_STATUSES:
                continue
            if (
                current.status is CombinationJobStatus.INFLIGHT
                and current.lease_owner != worker_id
            ):
                continue
            _append_failure(
                db_url,
                record["id"],
                stage="orchestrator",
                kind="internal",
                message=f"{type(exc).__name__}: {exc}",
                terminal=False,
                worker_id=(
                    worker_id
                    if current.status is CombinationJobStatus.INFLIGHT
                    else None
                ),
                expected_status=current.status,
                expected_job_stage=current.stage,
            )
    return combination_run_status(run_id, db_url)
