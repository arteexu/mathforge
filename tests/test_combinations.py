from __future__ import annotations

import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import inspect as sa_inspect
from sqlmodel import select

from mathforge import db
import mathforge.combinations as combo
from mathforge.combinations import (
    ContractError,
    PairCandidate,
    PairEvidence,
    TechniqueContext,
    build_pair_candidates,
    build_pair_evidence,
    create_combination_jobs,
    load_technique_catalog,
    parse_bridge_judgment,
    parse_bridge_proposals,
    parse_combo_draft,
    parse_faithfulness,
    plan_pairs,
    process_combination_run,
    retry_combination_jobs,
    strict_json_object,
)
from mathforge.llm import LLMClient, RawCompletion
from mathforge.integrity import is_export_eligible
from mathforge.schema import (
    CombinationJob,
    CombinationJobStatus,
    CombinationStatementClaim,
    DataSplit,
    LLMCall,
    Problem,
    ProblemSource,
    ReviewStatus,
    Solution,
    utcnow,
)
from scripts import generate_from_techniques as combo_cli
from scripts.generate_from_techniques import _config_for_resume, _same_model_family


IDS = ("co.alpha", "nt.beta")


def _bridge_candidates() -> dict:
    candidates = []
    for index in range(1, 4):
        candidates.append(
            {
                "bridge_id": f"b{index}",
                "shared_object": "a finite integer configuration",
                "interaction_type": "transforms_into",
                "crux": f"Bridge {index} converts one encoding into a forced count.",
                "technique_roles": {
                    IDS[0]: "Transforms the original configuration into integer data.",
                    IDS[1]: "Certifies the unique count from that transformed data.",
                },
                "proof_sketch": "The transformation is reversible and preserves the counted quantity.",
                "problem_shape": "A hidden finite arrangement with one requested count.",
                "integer_answer_route": "The preserved count is a unique integer below one thousand.",
                "naturalness": 4,
                "surprise": 4,
                "feasibility": 5,
                "stapling_risk": 1,
                "memorization_risk": 1,
            }
        )
    return {
        "schema_version": "combo_bridge_generation_v1",
        "technique_ids": list(IDS),
        "candidates": candidates,
    }


def _bridge_judgment() -> dict:
    evaluations = []
    for index in range(1, 4):
        keep = index == 2
        evaluations.append(
            {
                "bridge_id": f"b{index}",
                "soundness": 5 if keep else 3,
                "interaction": 5 if keep else 2,
                "naturalness": 4 if keep else 2,
                "essentiality": 5 if keep else 2,
                "surprise": 4,
                "generativity": 5 if keep else 2,
                "contest_fit": 4 if keep else 2,
                "stapling_risk": 0 if keep else 3,
                "known_problem_risk": 1,
                "fatal_issue": None,
                "verdict": "keep" if keep else "reject",
                "reason": "The two operations genuinely fuse." if keep else "The roles are separable.",
            }
        )
    return {
        "schema_version": "combo_bridge_judge_v1",
        "evaluations": evaluations,
        "selected_bridge_id": "b2",
        "reject_all": False,
    }


def _draft() -> str:
    usage = {
        IDS[0]: {
            "load_bearing_step": "Encode every admissible choice as an integer residue.",
            "failure_without": "There is no tractable representation to count.",
        },
        IDS[1]: {
            "load_bearing_step": "Force the residue count to be unique.",
            "failure_without": "The encoded possibilities cannot be distinguished.",
        },
    }
    return "\n".join(
        [
            "<bridge_id>b2</bridge_id>",
            "<statement>For each subset S of {0,1,2,3,4,5}, define c(S) as the sum of 2^j over all j in S. How many subsets have c(S) divisible by 3?</statement>",
            "<answer>22</answer>",
            "<topic>Number Theory</topic>",
            "<difficulty>6.0</difficulty>",
            "<crux>Re-encode every admissible object as a residue whose count is forced.</crux>",
            "<solution>The map S to c(S) is a bijection from the subsets to the integers 0 through 63, by binary representation. Exactly the multiples 0,3,...,63 are divisible by 3. There are 63/3+1=22 of them, so the requested answer is 22.</solution>",
            f"<technique_usage_json>{json.dumps(usage)}</technique_usage_json>",
            "<bypass_check>Direct enumeration does not expose completeness, while the reversible encoding does.</bypass_check>",
        ]
    )


def _faithfulness() -> dict:
    return {
        "schema_version": "combo_faithfulness_v1",
        "well_posed": True,
        "answer_consistent": True,
        "bridge_faithful": True,
        "both_load_bearing": True,
        "sequential_stacking": False,
        "routine_bypass": False,
        "interaction_creativity": 4,
        "problem_creativity": 4,
        "naturalness": 4,
        "creativity_reason": "The two representations collapse into one unexpected counting invariant.",
        "technique_checks": {
            IDS[0]: {
                "used": True,
                "load_bearing": True,
                "evidence": "The solution begins with the indispensable encoding.",
            },
            IDS[1]: {
                "used": True,
                "load_bearing": True,
                "evidence": "The second method forces the encoded count.",
            },
        },
        "verdict": "accept",
        "reason": "One fused bridge carries the solution and both roles are indispensable.",
    }


def _shell_proposals() -> dict:
    axes = [
        "mathematical_object",
        "target_quantity",
        "constraint_interaction",
        "direction_of_inference",
    ]
    shells = []
    for index, axis in enumerate(axes, 1):
        shells.append(
            {
                "shell_id": f"s{index}",
                "diversity_axis": axis,
                "premise": f"A finite encoded configuration with structural constraint {index}.",
                "target": f"Determine the unique residue-class count forced in case {index}.",
                "structural_twist": "The target is recovered backwards from two interacting representations.",
                "shared_object": "One finite family carrying an integer encoding and invariant.",
                "fused_crux": f"Shell {index} makes reversibility expose the invariant count.",
                "novelty_delta": "It changes both the target quantity and direction of inference.",
                "anti_copy_check": "It is not the canonical direct encoding exercise with new constants.",
                "technique_necessity": {
                    IDS[0]: {
                        "load_bearing_role": "Builds the reversible representation of every object.",
                        "counterfactual_without": "The objects cannot be organized into countable residue classes.",
                    },
                    IDS[1]: {
                        "load_bearing_role": "Forces the only compatible count from the representation.",
                        "counterfactual_without": "Several encoded counts remain possible.",
                    },
                },
                "shortest_expected_route": "Encode, apply the invariant on the same object, and invert the encoding.",
                "routine_bypass_tested": "Direct listing loses the global constraint and does not certify completeness.",
                "integer_answer_route": "The forced count is a unique integer below one thousand.",
                "existence_uniqueness_plan": "Construct one family and prove injectivity and surjectivity of the encoding.",
                "estimated_difficulty": 6.0,
                "naturalness": 4,
                "surprise": 4,
                "feasibility": 5,
                "known_problem_risk": 1,
                "routine_bypass_risk": 1,
            }
        )
    return {
        "schema_version": "combo_shell_generation_v1",
        "bridge_id": "b2",
        "technique_ids": list(IDS),
        "canonical_shape_to_avoid": "Directly encode a standard family and count residues.",
        "shells": shells,
    }


def _shell_judgment() -> dict:
    evaluations = []
    for index in range(1, 5):
        keep = index in {1, 2}
        evaluations.append(
            {
                "shell_id": f"s{index}",
                "bridge_sound": True,
                "integer_answer_feasible": True,
                "existence_supported": True,
                "uniqueness_supported": True,
                "fatal_issue": None,
                "copies_canonical_shape": False,
                "routine_bypass": False,
                "soundness": 5 if keep else 3,
                "interaction": 5 if keep else 3,
                "essentiality": 5 if keep else 3,
                "novelty_delta": 5 if index == 2 else (4 if keep else 3),
                "surprise": 4 if keep else 3,
                "naturalness": 4,
                "contest_fit": 4,
                "known_problem_risk": 1,
                "routine_bypass_risk": 1,
                "technique_checks": {
                    IDS[0]: {
                        "used": keep,
                        "load_bearing": keep,
                        "evidence": "The reversible encoding controls the same target.",
                    },
                    IDS[1]: {
                        "used": keep,
                        "load_bearing": keep,
                        "evidence": "The invariant uniquely certifies the encoded count.",
                    },
                },
                "verdict": "keep" if keep else "reject",
                "reason": "A valid noncanonical fusion." if keep else "The fusion is too weak.",
            }
        )
    return {
        "schema_version": "combo_shell_judge_v1",
        "evaluations": evaluations,
        "selected_shell_id": "s2",
        "reject_all": False,
        "selection_reason": "Shell s2 has the highest novelty delta after validity gates.",
    }


def _draft_v2(*, repair: bool = False) -> str:
    usage = {
        IDS[0]: {
            "load_bearing_step": "Encode every admissible configuration reversibly as an integer.",
            "failure_without": "There is no complete representation of the objects.",
        },
        IDS[1]: {
            "load_bearing_step": "Use the invariant to force the encoded residue count.",
            "failure_without": "The encoding alone leaves several counts possible.",
        },
    }
    routes = (
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
    bypass = {
        "attempts": [
            {
                "route": route,
                "works": False,
                "reason": "The coupled global constraint prevents this route from certifying completeness.",
            }
            for route in routes
        ],
        "shortest_valid_route": "Encode the family and apply the invariant to that same representation.",
        "shortest_route_uses": list(IDS),
    }
    verification = {
        "existence": "An explicit admissible family realizes the claimed count.",
        "uniqueness": "Injectivity and the invariant exclude every other count.",
        "domain_and_boundaries": "The empty and full configurations are checked separately.",
        "independent_arithmetic_check": "A second residue count again gives twenty-two.",
        "answer_in_range": True,
    }
    statement = (
        "A revised family of binary configurations obeys two coupled endpoint constraints. "
        "Under the reversible integer encoding described by those constraints, determine "
        "the number of configurations in the forced residue class."
        if repair
        else
        "A family of binary configurations obeys two coupled endpoint constraints and has "
        "a reversible integer encoding. Determine the number of configurations in the "
        "unique residue class compatible with both constraints."
    )
    tags = [
        ("schema_version", "combo_creativity_repair_v1" if repair else "combo_problem_generation_v2"),
        ("bridge_id", "b2"),
        ("shell_id", "s2"),
        ("statement", statement),
        ("answer", "22"),
        ("topic", "Combinatorics"),
        ("difficulty", "6.0"),
        ("crux", "The reversible encoding and invariant act on one object to force the count."),
        ("novelty_delta", "The target and inference direction differ structurally from direct residue counting."),
        (
            "solution",
            "Encode each admissible configuration by its binary integer. The endpoint constraints "
            "make the encoding reversible, while the invariant partitions the images into three "
            "classes and forces exactly twenty-two images into the compatible class. Injectivity "
            "returns twenty-two configurations, and the explicit construction proves existence. "
            "Therefore the requested answer is 22.",
        ),
        ("technique_usage_json", json.dumps(usage)),
    ]
    if repair:
        tags.append(
            (
                "repair_summary_json",
                json.dumps(
                    {
                        "feedback_failures": ["The prior shell admitted a standard formula."],
                        "structural_changes": [
                            "Added coupled endpoint constraints.",
                            "Reversed the direction of inference.",
                        ],
                        "blocked_bypass": "The prior formula no longer respects both endpoint constraints.",
                        "preserved_bridge": "The same reversible encoding feeds the same invariant.",
                        "cosmetic_only": False,
                    }
                ),
            )
        )
    tags.extend(
        [
            ("bypass_attempts_json", json.dumps(bypass)),
            ("verification_json", json.dumps(verification)),
        ]
    )
    return "\n".join(f"<{name}>{value}</{name}>" for name, value in tags)


def _blind_audit(kind: str = "accept") -> dict:
    accept = kind == "accept"
    fatal = kind == "fatal"
    return {
        "schema_version": "combo_blind_audit_v1",
        "well_posed": not fatal,
        "solved": not fatal,
        "unique_answer": not fatal,
        "answer": None if fatal else "22",
        "shortest_solution": (
            "The statement is inconsistent, so no unique answer can be certified."
            if fatal
            else "Encode each configuration reversibly, apply the global invariant, and count twenty-two images."
        ),
        "shortest_route_steps": ["Build the reversible encoding.", "Apply the global invariant."],
        "actual_techniques": [
            {
                "name": "reversible encoding",
                "load_bearing": True,
                "evidence": "It represents every admissible configuration exactly once.",
            },
            {
                "name": "invariant count",
                "load_bearing": True,
                "evidence": "It forces the compatible residue-class size.",
            },
        ],
        "bypass": {
            "exists": kind == "repair",
            "type": "standard_formula" if kind == "repair" else "none",
            "route": "A standard formula solves the unrevised shell." if kind == "repair" else "No shorter route succeeds.",
            "estimated_cases_or_steps": 2 if kind == "repair" else 0,
            "reason": "This is materially easier." if kind == "repair" else "Every tested route still needs both ideas.",
        },
        "difficulty": {
            "score": 2.5 if fatal else (3.5 if kind == "repair" else 5.5),
            "band": "below_aime" if fatal else ("easy_aime" if kind == "repair" else "mid_aime"),
            "primary_barrier": "No valid configuration." if fatal else "Seeing the fused representation.",
            "inside_target_band": accept,
            "structural_inflation": False,
        },
        "novelty": {
            "known_problem_pattern": kind != "accept",
            "closest_pattern": None if accept else "A standard residue-count formula.",
            "surprise_compression": 4 if accept else 2,
            "resistance": 4 if accept else 2,
            "statement_naturalness": 4,
            "reason": "The two representations genuinely compress the solution." if accept else "The shortest route is familiar.",
        },
        "verdict": "accept" if accept else ("inconclusive" if fatal else "reject"),
        "reason": "The statement-only audit passes." if accept else ("The statement is invalid." if fatal else "A routine bypass exists."),
    }


def _faithfulness_v2() -> dict:
    value = _faithfulness()
    value["schema_version"] = "combo_faithfulness_v2"
    return value


def _novelty_audit(
    neighbor_ids: tuple[str, ...],
    *,
    blocked_id: str | None = None,
    reported_verdict: str | None = None,
) -> dict:
    comparisons = []
    for neighbor_id in neighbor_ids:
        blocked = neighbor_id == blocked_id
        comparisons.append(
            {
                "neighbor_id": neighbor_id,
                "same_core_object": blocked,
                "same_target_quantity": blocked,
                "same_key_invariant": blocked,
                "same_proof_kernel": blocked,
                "surface_change_only": False,
                "new_load_bearing_mechanism": True,
                "structural_distance": 2 if blocked else 4,
                "reason": (
                    "Both problems compute the same expected squared root-of-unity sum "
                    "through the same pair expansion and cancellation kernel."
                    if blocked
                    else "The neighbor uses a different mathematical object and proof kernel."
                ),
            }
        )
    verdict = reported_verdict or ("reject" if blocked_id else "accept")
    return {
        "schema_version": "combo_corpus_novelty_v1",
        "comparisons": comparisons,
        "closest_neighbor_id": blocked_id or min(neighbor_ids),
        "verdict": verdict,
        "reason": (
            "A retrieved neighbor reuses the mathematical kernel."
            if blocked_id
            else "Every retrieved neighbor is structurally distinct."
        ),
    }


def _write_taxonomy(path) -> None:
    path.write_text(
        json.dumps(
            [
                {
                    "id": IDS[0],
                    "name": "Alpha Encoding",
                    "family": "encoding",
                    "one_liner": "Encode configurations as integers.",
                    "trigger": "A finite configuration needs a representation.",
                    "objects": ["integers", "sets"],
                    "mechanism": "bijection",
                    "difficulty_band": [3, 8],
                    "example_crux": "A reversible encoding turns objects into residues.",
                    "area": "Combinatorics",
                    "combinability": {"pairs_well_with": [], "avoid_with": []},
                },
                {
                    "id": "co.alpha-alias",
                    "name": "alpha encoding",
                    "family": "encoding",
                    "one_liner": "The same encoding in another area.",
                    "trigger": "Represent a finite object.",
                    "objects": ["sets"],
                    "mechanism": "counting",
                    "difficulty_band": [3, 7],
                    "example_crux": "Objects become integers.",
                    "area": "Algebra",
                    "combinability": {"pairs_well_with": [], "avoid_with": []},
                },
                {
                    "id": IDS[1],
                    "name": "Beta Certification",
                    "family": "certification",
                    "one_liner": "Certify a unique integer count.",
                    "trigger": "A representation needs uniqueness.",
                    "objects": ["integers"],
                    "mechanism": "invariant",
                    "difficulty_band": [4, 9],
                    "example_crux": "An invariant forces one count.",
                    "area": "Number Theory",
                    "combinability": {"pairs_well_with": [], "avoid_with": []},
                },
            ]
        ),
        encoding="utf-8",
    )


def _create_pair_job(tmp_path, run_id: str):
    db_url = f"sqlite:///{tmp_path / (run_id + '.db')}"
    taxonomy = tmp_path / (run_id + "-techniques.json")
    _write_taxonomy(taxonomy)
    db.init_db(db_url)
    with db.session_scope(db_url) as session:
        session.add(
            Problem(
                id=f"{run_id}-source",
                source=ProblemSource.OTHER_COMPETITION,
                statement="An official source problem with a unique modular encoding.",
                provenance={"techniques": list(IDS)},
            ).refresh_dedup_fields()
        )
    catalog = load_technique_catalog(taxonomy)
    evidence = build_pair_evidence(catalog, db_url)
    create_combination_jobs(
        run_id=run_id,
        count=1,
        seed=5,
        catalog=catalog,
        evidence=evidence,
        config={
            "generator_model": "fake",
            "judge_model": "fake",
            "bridges_per_pair": 3,
            "stage_attempts": 2,
            "target_difficulty": [4, 8],
        },
        db_url=db_url,
        explicit_pair=IDS,
    )
    return db_url


def test_catalog_canonicalizes_same_name_aliases(tmp_path):
    taxonomy = tmp_path / "techniques.json"
    _write_taxonomy(taxonomy)
    catalog = load_technique_catalog(taxonomy)

    assert len(catalog.techniques) == 2
    assert catalog.canonical_id("co.alpha-alias") == IDS[0]
    assert catalog.techniques[IDS[0]].aliases == (IDS[0], "co.alpha-alias")


def test_pair_evidence_excludes_bad_synthetics_and_does_not_invent_duplicate_pairs(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'evidence.db'}"
    taxonomy = tmp_path / "evidence-techniques.json"
    _write_taxonomy(taxonomy)
    db.init_db(db_url)
    with db.session_scope(db_url) as session:
        session.add_all(
            [
                Problem(
                    id="official-a",
                    source=ProblemSource.OTHER_COMPETITION,
                    statement="A unique official alpha problem.",
                    provenance={"techniques": [IDS[0]]},
                ).refresh_dedup_fields(),
                Problem(
                    id="copy-a",
                    source=ProblemSource.OTHER_COMPETITION,
                    statement="The same copied official statement.",
                    provenance={"techniques": [IDS[0]]},
                ).refresh_dedup_fields(),
                Problem(
                    id="copy-b",
                    source=ProblemSource.OTHER_COMPETITION,
                    statement="The same copied official statement.",
                    provenance={"techniques": [IDS[1]]},
                ).refresh_dedup_fields(),
                Problem(
                    id="accepted-b",
                    source=ProblemSource.SYNTHETIC,
                    statement="A human accepted beta problem.",
                    verified=True,
                    review_status=ReviewStatus.ACCEPTED,
                    provenance={"techniques": [IDS[1]]},
                ).refresh_dedup_fields(),
                Problem(
                    id="pending-pair",
                    source=ProblemSource.SYNTHETIC,
                    statement="A pending synthetic pair must not influence sampling.",
                    verified=True,
                    review_status=ReviewStatus.PENDING,
                    provenance={"techniques": list(IDS)},
                ).refresh_dedup_fields(),
                Problem(
                    id="rejected-pair",
                    source=ProblemSource.SYNTHETIC,
                    statement="A rejected synthetic pair must not influence sampling.",
                    verified=False,
                    review_status=ReviewStatus.REJECTED,
                    provenance={"techniques": list(IDS)},
                ).refresh_dedup_fields(),
            ]
        )

    evidence = build_pair_evidence(load_technique_catalog(taxonomy), db_url)

    assert evidence.support[IDS[0]] == 2
    assert evidence.support[IDS[1]] == 1
    assert evidence.pair_support[IDS] == 0


def test_strict_json_rejects_prose_duplicates_and_nan():
    assert strict_json_object('{"ok": true}') == {"ok": True}
    with pytest.raises(ContractError):
        strict_json_object('```json\n{"ok": true}\n```')
    with pytest.raises(ContractError):
        strict_json_object('{"x": 1, "x": 2}')
    with pytest.raises(ContractError):
        strict_json_object('{"x": NaN}')


def test_bridge_contracts_and_deterministic_winner():
    proposal = parse_bridge_proposals(json.dumps(_bridge_candidates()), IDS)
    assert len(proposal["candidates"]) == 3
    judgment = parse_bridge_judgment(
        json.dumps(_bridge_judgment()), ("b1", "b2", "b3")
    )
    assert judgment["computed_selected_bridge_id"] == "b2"

    malformed = _bridge_candidates()
    malformed["extra"] = True
    with pytest.raises(ContractError):
        parse_bridge_proposals(json.dumps(malformed), IDS)


def test_bridge_judge_recommendation_is_advisory_among_eligible_bridges():
    judgment = _bridge_judgment()
    first = judgment["evaluations"][0]
    first.update(
        {
            "soundness": 4,
            "interaction": 4,
            "naturalness": 3,
            "essentiality": 4,
            "surprise": 3,
            "generativity": 3,
            "contest_fit": 3,
            "stapling_risk": 1,
            "known_problem_risk": 2,
            "verdict": "keep",
            "reason": "Eligible, but weaker than the second bridge.",
        }
    )
    judgment["selected_bridge_id"] = "b1"

    parsed = parse_bridge_judgment(
        json.dumps(judgment), ("b1", "b2", "b3")
    )

    assert parsed["selected_bridge_id"] == "b1"
    assert parsed["computed_selected_bridge_id"] == "b2"


def test_bridge_gate_requires_surprise_and_hides_proposer_self_scores():
    judgment = _bridge_judgment()
    judgment["evaluations"][1]["surprise"] = 2
    parsed = parse_bridge_judgment(json.dumps(judgment), ("b1", "b2", "b3"))
    downgraded = parsed["evaluations"][1]

    assert downgraded["reported_verdict"] == "keep"
    assert downgraded["reported_verdict_consistent"] is False
    assert downgraded["computed_eligible"] is False
    assert parsed["computed_selected_bridge_id"] is None
    assert parsed["reported_selected_bridge_id"] == "b2"
    assert parsed["reported_decision_consistent"] is False

    prompt_view = combo._prompt_bridge(_bridge_candidates()["candidates"][1])
    assert prompt_view["crux"]
    assert "surprise" not in prompt_view
    assert "naturalness" not in prompt_view
    assert "stapling_risk" not in prompt_view


def test_faithfulness_allows_a_substantive_holistic_rejection():
    verdict = _faithfulness()
    verdict["verdict"] = "reject"
    verdict["reason"] = "The construction is too close to a known contest problem."

    assert parse_faithfulness(json.dumps(verdict), IDS)["verdict"] == "reject"


def test_draft_parser_is_conservative_and_requires_exact_usage():
    parsed = parse_combo_draft(_draft(), "b2", IDS)
    assert parsed["answer"] == "22"
    assert set(parsed["technique_usage"]) == set(IDS)

    with pytest.raises(ContractError):
        parse_combo_draft(_draft().replace("<answer>22</answer>", "<answer>22 or 23</answer>"), "b2", IDS)
    with pytest.raises(ContractError):
        parse_combo_draft(_draft() + "\n<answer>22</answer>", "b2", IDS)
    with pytest.raises(ContractError):
        parse_combo_draft(_draft(), "b2", IDS, difficulty_band=(7.0, 8.0))


def _pair_candidate(index: int, tranche: str) -> PairCandidate:
    left_id, right_id = f"a{index}", f"b{index}"
    left = TechniqueContext(
        id=left_id,
        name=f"Left {index}",
        area="Algebra",
        family="",
        one_liner="left",
        trigger="left",
        objects=("integers",),
        mechanism="counting",
        difficulty_band=(4, 8),
        example_crux="left",
        avoid_with=(),
    )
    right = TechniqueContext(
        id=right_id,
        name=f"Right {index}",
        area="Number Theory",
        family="",
        one_liner="right",
        trigger="right",
        objects=("integers",),
        mechanism="invariant",
        difficulty_band=(4, 8),
        example_crux="right",
        avoid_with=(),
    )
    return PairCandidate(
        pair_key=f"{left_id}+{right_id}",
        technique_ids=(left_id, right_id),
        contexts=(left, right),
        tranche=tranche,
        support_a=10,
        support_b=4,
        pair_support=1 if tranche == "observed" else 0,
        trusted_pair_support=1 if tranche == "observed" else 0,
        shared_objects=("integers",),
        area_pair=("Algebra", "Number Theory"),
        mechanism_pair=("counting", "invariant"),
        difficulty_overlap=(4, 8),
        evidence_ids=(),
        topic_counts={},
        weight=1.0 + index / 100,
        weight_components={"test": 1.0},
    )


def test_sampler_has_exact_tranches_and_is_seed_reproducible():
    candidates = (
        [_pair_candidate(i, "observed") for i in range(12)]
        + [_pair_candidate(i + 20, "structured") for i in range(6)]
        + [_pair_candidate(i + 40, "explore_gap") for i in range(4)]
    )
    first = plan_pairs(candidates, count=10, seed=17, snapshot_hash="snapshot")
    second = plan_pairs(candidates, count=10, seed=17, snapshot_hash="snapshot")

    assert [item.candidate.pair_key for item in first] == [
        item.candidate.pair_key for item in second
    ]
    requested = Counter(item.requested_tranche for item in first)
    assert requested == {"observed": 7, "structured": 2, "explore_gap": 1}
    assert len({item.candidate.pair_key for item in first}) == 10


def test_end_to_end_bridge_run_is_resumable_and_stores_pending_candidate(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'combo.db'}"
    taxonomy = tmp_path / "techniques.json"
    _write_taxonomy(taxonomy)
    db.init_db(db_url)
    with db.session_scope(db_url) as session:
        session.add_all(
            [
                Problem(
                    id="source-a",
                    source=ProblemSource.OTHER_COMPETITION,
                    statement="An official source problem about arranging seven colored stones.",
                    provenance={"techniques": [IDS[0]]},
                ).refresh_dedup_fields(),
                Problem(
                    id="source-b",
                    source=ProblemSource.OTHER_COMPETITION,
                    statement="An official source problem about a modular uniqueness condition.",
                    provenance={"techniques": [IDS[1]]},
                ).refresh_dedup_fields(),
            ]
        )
    catalog = load_technique_catalog(taxonomy)
    evidence = build_pair_evidence(catalog, db_url)
    config = {
        "generator_model": "fake-generator",
        "judge_model": "fake-judge",
        "bridges_per_pair": 3,
        "stage_attempts": 2,
        "target_difficulty": [4, 8],
    }
    create_combination_jobs(
        run_id="test-run",
        count=1,
        seed=5,
        catalog=catalog,
        evidence=evidence,
        config=config,
        db_url=db_url,
        explicit_pair=IDS,
    )

    observed_calls = []

    def backend(prompt, system=None, **kwargs):
        observed_calls.append((prompt, system, kwargs))
        if "STAGE: COMBO_BRIDGE_GENERATION_V1" in prompt:
            text = json.dumps(_bridge_candidates())
        elif "STAGE: COMBO_BRIDGE_JUDGE_V1" in prompt:
            text = json.dumps(_bridge_judgment())
        elif "STAGE: COMBO_PROBLEM_GENERATION_V1" in prompt:
            text = _draft()
        elif "STAGE: COMBO_FAITHFULNESS_V1" in prompt:
            text = json.dumps(_faithfulness())
        else:
            raise AssertionError("unexpected prompt")
        return RawCompletion(
            text=text,
            prompt_tokens=10,
            completion_tokens=20,
            raw={"stop_reason": "end_turn"},
        )

    generator = LLMClient(model="fake-generator", backend=backend, db_url=db_url)
    judge = LLMClient(model="fake-judge", backend=backend, db_url=db_url)
    report = process_combination_run(
        run_id="test-run", generator=generator, judge=judge, db_url=db_url
    )
    assert report.stored == 1 and report.rejected == 0

    # A second resume is idempotent: no duplicate Problem or Solution.
    again = process_combination_run(
        run_id="test-run", generator=generator, judge=judge, db_url=db_url
    )
    assert again.stored == 1
    with db.session_scope(db_url) as session:
        generated = session.exec(
            select(Problem).where(Problem.source == ProblemSource.SYNTHETIC)
        ).one()
        job = session.exec(select(CombinationJob)).one()
        solutions = session.exec(
            select(Solution).where(Solution.problem_id == generated.id)
        ).all()
        calls = session.exec(select(LLMCall).order_by(LLMCall.id)).all()
        assert generated.answer == "22"
        assert generated.verified is None
        assert generated.review_status is ReviewStatus.PENDING
        assert not is_export_eligible(generated)
        assert generated.provenance["required_techniques"] == list(IDS)
        assert generated.provenance["combo_job_id"] == job.id
        assert job.status is CombinationJobStatus.STORED
        assert set(job.config["prompt_hashes"]) == {
            "bridge",
            "bridge_judge",
            "problem",
            "preflight",
        }
        assert set(job.call_ids) == {
            "bridge_proposal", "bridge_judgment", "compose", "preflight"
        }
        assert len(solutions) == 1
        assert solutions[0].techniques == list(IDS)
        assert len(calls) == 4
        assert all(call.related_id == job.id for call in calls)
        assert all(call.meta["stop_reason"] == "end_turn" for call in calls)
        json_calls = [
            call
            for call in observed_calls
            if "STAGE: COMBO_PROBLEM_GENERATION_V1" not in call[0]
        ]
        assert all("strict JSON API" in (call[1] or "") for call in json_calls)
        judge_calls = [
            call
            for call in observed_calls
            if "STAGE: COMBO_BRIDGE_JUDGE_V1" in call[0]
            or "STAGE: COMBO_FAITHFULNESS_V1" in call[0]
        ]
        assert all(call[2]["effort"] == "medium" for call in judge_calls)


def test_malformed_bridge_response_retries_once_then_completes(tmp_path):
    db_url = _create_pair_job(tmp_path, "retry-run")
    state = {"bridge": 0}

    def backend(prompt, system=None, **kwargs):
        if "STAGE: COMBO_BRIDGE_GENERATION_V1" in prompt:
            state["bridge"] += 1
            text = "```json\n{}\n```" if state["bridge"] == 1 else json.dumps(_bridge_candidates())
        elif "STAGE: COMBO_BRIDGE_JUDGE_V1" in prompt:
            text = json.dumps(_bridge_judgment())
        elif "STAGE: COMBO_PROBLEM_GENERATION_V1" in prompt:
            text = _draft()
        else:
            text = json.dumps(_faithfulness())
        return RawCompletion(text=text, raw={"stop_reason": "end_turn"})

    client = LLMClient(model="fake", backend=backend, db_url=db_url)
    report = process_combination_run(
        run_id="retry-run", generator=client, judge=client, db_url=db_url
    )

    assert report.stored == 1
    with db.session_scope(db_url) as session:
        job = session.exec(select(CombinationJob)).one()
        assert job.attempts["bridge_proposal"] == 2
        assert [failure["kind"] for failure in job.failures] == ["parse"]
        assert len(job.call_ids["bridge_proposal"]) == 2


def test_valid_artifact_with_max_token_stop_succeeds_without_retry(tmp_path):
    db_url = _create_pair_job(tmp_path, "valid-max-token-run")
    bridge_calls = 0

    def backend(prompt, system=None, **kwargs):
        nonlocal bridge_calls
        stop_reason = "end_turn"
        if "STAGE: COMBO_BRIDGE_GENERATION_V1" in prompt:
            bridge_calls += 1
            text = json.dumps(_bridge_candidates())
            stop_reason = "max_tokens"
        elif "STAGE: COMBO_BRIDGE_JUDGE_V1" in prompt:
            text = json.dumps(_bridge_judgment())
        elif "STAGE: COMBO_PROBLEM_GENERATION_V1" in prompt:
            text = _draft()
        else:
            text = json.dumps(_faithfulness())
        return RawCompletion(
            text=text,
            completion_tokens=48000 if stop_reason == "max_tokens" else None,
            raw={"stop_reason": stop_reason},
        )

    client = LLMClient(model="fake", backend=backend, db_url=db_url)
    report = process_combination_run(
        run_id="valid-max-token-run", generator=client, judge=client, db_url=db_url
    )

    assert report.stored == 1
    assert bridge_calls == 1
    with db.session_scope(db_url) as session:
        job = session.exec(select(CombinationJob)).one()
        assert job.attempts["bridge_proposal"] == 1
        assert job.failures == []
        assert len(job.call_ids["bridge_proposal"]) == 1
        call = session.get(LLMCall, job.call_ids["bridge_proposal"][0])
        assert call is not None
        assert call.meta["stop_reason"] == "max_tokens"


def test_output_exhaustion_retries_at_reduced_effort(tmp_path):
    db_url = _create_pair_job(tmp_path, "exhaustion-effort-run")
    efforts = {"generator": [], "judge": []}

    def backend(prompt, system=None, **kwargs):
        if "STAGE: COMBO_BRIDGE_GENERATION_V1" in prompt:
            efforts["generator"].append(kwargs["effort"])
            first_attempt = len(efforts["generator"]) == 1
            text = '{"schema_version":' if first_attempt else json.dumps(_bridge_candidates())
        elif "STAGE: COMBO_BRIDGE_JUDGE_V1" in prompt:
            efforts["judge"].append(kwargs["effort"])
            first_attempt = len(efforts["judge"]) == 1
            text = '{"schema_version":' if first_attempt else json.dumps(_bridge_judgment())
        elif "STAGE: COMBO_PROBLEM_GENERATION_V1" in prompt:
            first_attempt = False
            text = _draft()
        else:
            first_attempt = False
            text = json.dumps(_faithfulness())
        return RawCompletion(
            text=text,
            completion_tokens=48000 if first_attempt else None,
            raw={"stop_reason": "max_tokens" if first_attempt else "end_turn"},
        )

    client = LLMClient(model="fake", backend=backend, db_url=db_url)
    report = process_combination_run(
        run_id="exhaustion-effort-run", generator=client, judge=client, db_url=db_url
    )

    assert report.stored == 1
    assert efforts == {"generator": ["high", "medium"], "judge": ["medium", "low"]}
    with db.session_scope(db_url) as session:
        job = session.exec(select(CombinationJob)).one()
        exhausted = [
            failure
            for failure in job.failures
            if failure["kind"] == "output_exhausted"
        ]
        assert [failure["stage"] for failure in exhausted] == [
            "bridge_proposal",
            "bridge_judgment",
        ]
        assert all("stop_reason='max_tokens'" in failure["message"] for failure in exhausted)
        assert all("completion_tokens=48000" in failure["message"] for failure in exhausted)

        calls = session.exec(
            select(LLMCall)
            .where(LLMCall.related_id == job.id)
            .order_by(LLMCall.id)
        ).all()
        assert [
            call.meta["requested_effort"]
            for call in calls
            if call.meta["stage"] == "bridge_proposal"
        ] == ["high", "medium"]
        assert [
            call.meta["requested_effort"]
            for call in calls
            if call.meta["stage"] == "bridge_judgment"
        ] == ["medium", "low"]


def test_reject_all_bridge_judgment_stores_no_problem(tmp_path):
    db_url = _create_pair_job(tmp_path, "reject-run")
    rejected = _bridge_judgment()
    for evaluation in rejected["evaluations"]:
        evaluation.update(
            {
                "soundness": 3,
                "interaction": 2,
                "naturalness": 2,
                "essentiality": 2,
                "generativity": 2,
                "contest_fit": 2,
                "stapling_risk": 3,
                "verdict": "reject",
                "reason": "The operations remain separable.",
            }
        )
    rejected["selected_bridge_id"] = None
    rejected["reject_all"] = True

    def backend(prompt, system=None, **kwargs):
        if "STAGE: COMBO_BRIDGE_GENERATION_V1" in prompt:
            text = json.dumps(_bridge_candidates())
        elif "STAGE: COMBO_BRIDGE_JUDGE_V1" in prompt:
            text = json.dumps(rejected)
        else:
            raise AssertionError("composition must not run after reject-all")
        return RawCompletion(text=text, raw={"stop_reason": "end_turn"})

    client = LLMClient(model="fake", backend=backend, db_url=db_url)
    report = process_combination_run(
        run_id="reject-run", generator=client, judge=client, db_url=db_url
    )

    assert report.rejected == 1 and report.stored == 0
    with db.session_scope(db_url) as session:
        assert session.exec(
            select(Problem).where(Problem.source == ProblemSource.SYNTHETIC)
        ).all() == []
        job = session.exec(select(CombinationJob)).one()
        assert job.stage == "bridges_judged"
        assert job.rejection_reason.startswith("bridge_rejected")


def test_fresh_lease_prevents_a_second_resumer_from_calling_model(tmp_path):
    db_url = _create_pair_job(tmp_path, "leased-run")
    with db.session_scope(db_url) as session:
        job = session.exec(select(CombinationJob)).one()
        job.status = CombinationJobStatus.INFLIGHT
        job.lease_owner = "other-worker"
        job.lease_started_at = utcnow()
        session.add(job)

    def backend(prompt, system=None, **kwargs):
        raise AssertionError("a fresh lease must not be stolen")

    client = LLMClient(model="fake", backend=backend, db_url=db_url)
    report = process_combination_run(
        run_id="leased-run", generator=client, judge=client, db_url=db_url
    )

    assert report.pending == 1
    with db.session_scope(db_url) as session:
        job = session.exec(select(CombinationJob)).one()
        assert job.status is CombinationJobStatus.INFLIGHT
        assert job.lease_owner == "other-worker"


def test_stale_final_attempt_is_reclaimed_instead_of_lost(tmp_path):
    db_url = _create_pair_job(tmp_path, "stale-run")
    with db.session_scope(db_url) as session:
        job = session.exec(select(CombinationJob)).one()
        job.status = CombinationJobStatus.INFLIGHT
        job.lease_owner = "dead-worker"
        job.lease_started_at = utcnow() - timedelta(hours=1)
        job.attempts = {"bridge_proposal": 2}
        session.add(job)

    def backend(prompt, system=None, **kwargs):
        if "STAGE: COMBO_BRIDGE_GENERATION_V1" in prompt:
            text = json.dumps(_bridge_candidates())
        elif "STAGE: COMBO_BRIDGE_JUDGE_V1" in prompt:
            text = json.dumps(_bridge_judgment())
        elif "STAGE: COMBO_PROBLEM_GENERATION_V1" in prompt:
            text = _draft()
        else:
            text = json.dumps(_faithfulness())
        return RawCompletion(text=text, raw={"stop_reason": "end_turn"})

    client = LLMClient(model="fake", backend=backend, db_url=db_url)
    report = process_combination_run(
        run_id="stale-run", generator=client, judge=client, db_url=db_url
    )

    assert report.stored == 1
    with db.session_scope(db_url) as session:
        job = session.exec(select(CombinationJob)).one()
        assert job.attempts["bridge_proposal"] == 2
        assert any(
            failure["kind"] == "stale_lease_recovered" for failure in job.failures
        )


def test_same_stale_attempt_is_recovered_only_once(tmp_path):
    db_url = _create_pair_job(tmp_path, "repeated-stale-run")
    with db.session_scope(db_url) as session:
        job = session.exec(select(CombinationJob)).one()
        job.status = CombinationJobStatus.INFLIGHT
        job.lease_owner = "second-dead-worker"
        job.lease_started_at = utcnow() - timedelta(hours=1)
        job.attempts = {"bridge_proposal": 2}
        job.failures = [
            {
                "at": utcnow().isoformat(),
                "stage": "bridge_proposal",
                "kind": "stale_lease_recovered",
                "message": "already recovered this paid attempt",
                "attempt": 2,
                "retry_epoch": 0,
            }
        ]
        session.add(job)

    def no_calls(prompt, system=None, **kwargs):
        raise AssertionError("a twice-stale final attempt must not call again")

    client = LLMClient(model="fake", backend=no_calls, db_url=db_url)
    report = process_combination_run(
        run_id="repeated-stale-run", generator=client, judge=client, db_url=db_url
    )

    assert report.exhausted == 1
    with db.session_scope(db_url) as session:
        job = session.exec(select(CombinationJob)).one()
        assert job.attempts["bridge_proposal"] == 2
        assert job.failures[-1]["kind"] == "attempts_exhausted"


def test_retry_reset_only_reopens_requested_exhausted_failures(tmp_path):
    db_url = _create_pair_job(tmp_path, "reset-run")
    with db.session_scope(db_url) as session:
        job = session.exec(select(CombinationJob)).one()
        job.status = CombinationJobStatus.EXHAUSTED
        job.attempts = {"bridge_proposal": 2}
        job.failures = [
            {
                "at": utcnow().isoformat(),
                "stage": "bridge_proposal",
                "kind": "output_exhausted",
                "message": "max tokens",
            }
        ]
        session.add(job)

    reset = retry_combination_jobs(
        "reset-run", failure_kinds={"output_exhausted"}, db_url=db_url
    )

    assert reset == 1
    with db.session_scope(db_url) as session:
        job = session.exec(select(CombinationJob)).one()
        assert job.status is CombinationJobStatus.PENDING
        assert job.attempts["bridge_proposal"] == 0
        assert job.failures[-1]["kind"] == "manual_retry_reset"


def test_retry_can_select_job_ordinals(tmp_path):
    db_url = _create_pair_job(tmp_path, "ordinal-reset-run")
    with db.session_scope(db_url) as session:
        job = session.exec(select(CombinationJob)).one()
        job.status = CombinationJobStatus.EXHAUSTED
        job.attempts = {"preflight": 2}
        job.failures = [
            {
                "at": utcnow().isoformat(),
                "stage": "preflight",
                "kind": "parse",
                "message": "visible prose before JSON",
            }
        ]
        session.add(job)

    assert retry_combination_jobs(
        "ordinal-reset-run",
        failure_kinds={"parse"},
        ordinals={9, 10},
        db_url=db_url,
    ) == 0
    assert retry_combination_jobs(
        "ordinal-reset-run",
        failure_kinds={"parse"},
        ordinals={1},
        db_url=db_url,
    ) == 1


def test_retry_uses_only_the_latest_terminal_failure(tmp_path):
    db_url = _create_pair_job(tmp_path, "latest-reset-run")
    with db.session_scope(db_url) as session:
        job = session.exec(select(CombinationJob)).one()
        job.status = CombinationJobStatus.EXHAUSTED
        job.attempts = {"bridge_proposal": 2, "compose": 2}
        job.failures = [
            {
                "at": utcnow().isoformat(),
                "stage": "bridge_proposal",
                "kind": "output_exhausted",
                "message": "old failure",
            },
            {
                "at": utcnow().isoformat(),
                "stage": "compose",
                "kind": "parse",
                "message": "terminal failure",
            },
        ]
        session.add(job)

    assert retry_combination_jobs(
        "latest-reset-run", failure_kinds={"output_exhausted"}, db_url=db_url
    ) == 0
    assert retry_combination_jobs(
        "latest-reset-run", failure_kinds={"parse"}, db_url=db_url
    ) == 1
    with db.session_scope(db_url) as session:
        job = session.exec(select(CombinationJob)).one()
        assert job.attempts["bridge_proposal"] == 2
        assert job.attempts["compose"] == 0


def test_concurrent_manual_retry_has_one_compare_and_swap_winner(tmp_path):
    db_url = _create_pair_job(tmp_path, "concurrent-reset-run")
    with db.session_scope(db_url) as session:
        job = session.exec(select(CombinationJob)).one()
        job.status = CombinationJobStatus.EXHAUSTED
        job.attempts = {"bridge_proposal": 2}
        job.failures = [
            {
                "at": utcnow().isoformat(),
                "stage": "bridge_proposal",
                "kind": "output_exhausted",
                "message": "terminal failure",
            }
        ]
        session.add(job)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: retry_combination_jobs(
                    "concurrent-reset-run",
                    failure_kinds={"output_exhausted"},
                    db_url=db_url,
                ),
                range(2),
            )
        )

    assert sum(results) == 1
    with db.session_scope(db_url) as session:
        job = session.exec(select(CombinationJob)).one()
        assert job.status is CombinationJobStatus.PENDING
        assert [item["kind"] for item in job.failures].count(
            "manual_retry_reset"
        ) == 1


@pytest.mark.parametrize(
    "target",
    [
        (float("nan"), 8),
        (4, float("inf")),
        (0, 8),
        (4, 11),
        (8, 4),
    ],
)
def test_pair_builder_rejects_invalid_target_difficulty(tmp_path, target):
    taxonomy = tmp_path / "invalid-target-techniques.json"
    _write_taxonomy(taxonomy)
    with pytest.raises(ValueError, match="target_difficulty"):
        build_pair_candidates(
            load_technique_catalog(taxonomy), PairEvidence(), target_difficulty=target
        )


def test_observed_pair_with_no_difficulty_overlap_is_excluded(tmp_path):
    taxonomy = tmp_path / "disjoint-techniques.json"
    _write_taxonomy(taxonomy)
    rows = json.loads(taxonomy.read_text(encoding="utf-8"))
    for row in rows:
        row["difficulty_band"] = [1, 2] if row["id"] != IDS[1] else [8, 9]
    taxonomy.write_text(json.dumps(rows), encoding="utf-8")
    evidence = PairEvidence()
    evidence.support.update({IDS[0]: 3, IDS[1]: 3})
    evidence.pair_support[IDS] = 1
    evidence.trusted_pair_support[IDS] = 1

    candidates = build_pair_candidates(
        load_technique_catalog(taxonomy), evidence, target_difficulty=(1, 10)
    )

    assert candidates == []


def test_present_but_empty_taxonomy_difficulty_band_is_rejected(tmp_path):
    taxonomy = tmp_path / "empty-band-techniques.json"
    _write_taxonomy(taxonomy)
    rows = json.loads(taxonomy.read_text(encoding="utf-8"))
    rows[0]["difficulty_band"] = []
    taxonomy.write_text(json.dumps(rows), encoding="utf-8")

    with pytest.raises(ValueError, match="difficulty_band for technique"):
        load_technique_catalog(taxonomy)


def test_frozen_eval_token_signatures_block_reordered_paraphrase(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'eval-fuzzy.db'}"
    db.init_db(db_url)
    eval_statement = (
        "Positive integers a b and c satisfy a plus b plus c equals twenty. "
        "Determine the maximum product a b c."
    )
    reordered = (
        "Determine the maximum product a b c. Positive integers a b and c "
        "satisfy a plus b plus c equals twenty."
    )
    with db.session_scope(db_url) as session:
        session.add(
            Problem(
                id="frozen-eval",
                source=ProblemSource.AIME,
                statement=eval_statement,
                split=DataSplit.EVAL,
                frozen=True,
            ).refresh_dedup_fields()
        )

    index = combo._build_dedup_index(db_url)
    issues = combo._static_draft_issues(
        {"statement": reordered}, {"crux": ""}, [], index
    )

    assert "near_duplicate_statement" in issues
    assert "canonical_duplicate" not in issues


def test_stale_failure_and_transition_cannot_rewind_newer_or_terminal_job(tmp_path):
    db_url = _create_pair_job(tmp_path, "cas-run")
    with db.session_scope(db_url) as session:
        job = session.exec(select(CombinationJob)).one()
        job.stage = "bridge_selected"
        session.add(job)

    combo._update_job(
        db_url,
        job.id,
        expected_stage="bridges_judged",
        stage="bridge_selected",
        selected_bridge={"stale": True},
    )
    assert not combo._append_failure(
        db_url,
        job.id,
        stage="orchestrator",
        kind="internal",
        message="stale catcher",
        expected_status=CombinationJobStatus.PENDING,
        expected_job_stage="pair_selected",
    )
    with db.session_scope(db_url) as session:
        current = session.get(CombinationJob, job.id)
        assert current.stage == "bridge_selected"
        assert current.selected_bridge == {}
        current.stage = "stored"
        current.status = CombinationJobStatus.STORED
        current.problem_id = "already-stored"
        session.add(current)

    assert not combo._append_failure(
        db_url,
        job.id,
        stage="orchestrator",
        kind="internal",
        message="late exception",
    )
    with db.session_scope(db_url) as session:
        current = session.get(CombinationJob, job.id)
        assert current.status is CombinationJobStatus.STORED
        assert current.stage == "stored"
        assert current.failures == []


@pytest.mark.parametrize("reordered_near_duplicate", [False, True])
def test_concurrent_storage_serializes_exact_and_fuzzy_duplicates(
    tmp_path, reordered_near_duplicate
):
    db_url = f"sqlite:///{tmp_path / 'concurrent-store.db'}"
    taxonomy = tmp_path / "concurrent-techniques.json"
    _write_taxonomy(taxonomy)
    db.init_db(db_url)
    with db.session_scope(db_url) as session:
        session.add(
            Problem(
                id="source-pair",
                source=ProblemSource.OTHER_COMPETITION,
                statement="An official source with a modular finite encoding.",
                provenance={"techniques": list(IDS)},
            ).refresh_dedup_fields()
        )
    catalog = load_technique_catalog(taxonomy)
    evidence = build_pair_evidence(catalog, db_url)
    config = {
        "generator_model": "fake",
        "judge_model": "fake",
        "target_difficulty": [4, 8],
    }
    for run_id in ("concurrent-a", "concurrent-b"):
        create_combination_jobs(
            run_id=run_id,
            count=1,
            seed=1,
            catalog=catalog,
            evidence=evidence,
            config=config,
            db_url=db_url,
            explicit_pair=IDS,
        )
    parsed_draft = parse_combo_draft(_draft(), "b2", IDS, (4, 8))
    selected = _bridge_candidates()["candidates"][1]
    with db.session_scope(db_url) as session:
        jobs = session.exec(
            select(CombinationJob).order_by(CombinationJob.run_id)
        ).all()
        for index, job in enumerate(jobs):
            job_draft = dict(parsed_draft)
            if reordered_near_duplicate and index == 1:
                job_draft["statement"] = (
                    "How many subsets have c(S) divisible by 3? For each subset S "
                    "of {0,1,2,3,4,5}, define c(S) as the sum of 2^j over all j in S."
                )
            job.stage = "preflight_passed"
            job.status = CombinationJobStatus.PENDING
            job.selected_bridge = selected
            job.draft = job_draft
            job.preflight = {"faithfulness": _faithfulness()}
            session.add(job)

    def no_calls(prompt, system=None, **kwargs):
        raise AssertionError("storage-only resume must not call a model")

    client = LLMClient(model="fake", backend=no_calls, db_url=db_url)
    with ThreadPoolExecutor(max_workers=2) as pool:
        reports = list(
            pool.map(
                lambda run_id: process_combination_run(
                    run_id=run_id,
                    generator=client,
                    judge=client,
                    db_url=db_url,
                ),
                ("concurrent-a", "concurrent-b"),
            )
        )

    assert sum(report.stored for report in reports) == 1
    with db.session_scope(db_url) as session:
        jobs = session.exec(select(CombinationJob)).all()
        generated = session.exec(
            select(Problem).where(Problem.source == ProblemSource.SYNTHETIC)
        ).all()
        claims = session.exec(select(CombinationStatementClaim)).all()
        assert Counter(job.status for job in jobs) == {
            CombinationJobStatus.STORED: 1,
            CombinationJobStatus.REJECTED: 1,
        }
        assert len(generated) == 1
        assert len(claims) == (2 if reordered_near_duplicate else 1)


def test_resume_refuses_unsupported_prompt_contract_before_model_call(tmp_path):
    db_url = _create_pair_job(tmp_path, "prompt-version-run")
    with db.session_scope(db_url) as session:
        job = session.exec(select(CombinationJob)).one()
        config = dict(job.config)
        config["prompt_versions"] = {"problem": "combo_problem_generation_v2"}
        job.config = config
        session.add(job)

    def no_calls(prompt, system=None, **kwargs):
        raise AssertionError("unsupported prompt must fail before a model call")

    client = LLMClient(model="fake", backend=no_calls, db_url=db_url)
    with pytest.raises(ValueError, match="unsupported problem prompt version"):
        process_combination_run(
            run_id="prompt-version-run",
            generator=client,
            judge=client,
            db_url=db_url,
        )


def test_same_family_warning_detects_claude_across_models_and_transports():
    assert _same_model_family(
        {
            "generator_model": "claude-opus-4-8",
            "generator_backend": "anthropic",
            "judge_model": "claude-sonnet-4-6",
            "judge_backend": "openai",
        }
    )
    assert not _same_model_family(
        {
            "generator_model": "claude-opus-4-8",
            "generator_backend": "anthropic",
            "judge_model": "gpt-5.4",
            "judge_backend": "openai",
        }
    )


def test_pipeline_output_token_defaults_are_validated_and_frozen(tmp_path):
    v1 = combo._validate_combination_config({})
    v2 = combo._validate_combination_config({"pipeline_version": "v2"})
    assert v1["generator_max_output_tokens"] == 32000
    assert v2["generator_max_output_tokens"] == 32000
    assert v2["effort_policy_version"] == combo.LEGACY_EFFORT_POLICY
    assert v2["novelty_gate_version"] == combo.CORPUS_NOVELTY_GATE_DISABLED
    frozen_v2 = combo._freeze_combination_config({"pipeline_version": "v2"})
    assert frozen_v2["generator_max_output_tokens"] == 48000
    assert frozen_v2["effort_policy_version"] == combo.STAGE_EFFORT_POLICY
    assert frozen_v2["novelty_gate_version"] == combo.CORPUS_NOVELTY_GATE_V1
    assert frozen_v2["novelty_neighbor_count"] == 8
    assert len(frozen_v2["novelty_prompt_sha256"]) == 64

    db_url = _create_v2_job(tmp_path, "v2-output-budget")
    with db.session_scope(db_url) as session:
        job = session.exec(select(CombinationJob)).one()
        assert job.config["generator_max_output_tokens"] == 48000
        assert job.config["effort_policy_version"] == combo.STAGE_EFFORT_POLICY
        assert job.config["novelty_gate_version"] == combo.CORPUS_NOVELTY_GATE_V1

        config = dict(job.config)
        config.pop("generator_max_output_tokens")
        job.config = config
        session.add(job)

    resumed = _config_for_resume("v2-output-budget", db_url)
    assert resumed["generator_max_output_tokens"] == 32000
    with db.session_scope(db_url) as session:
        job = session.exec(select(CombinationJob)).one()
        assert "generator_max_output_tokens" not in job.config

    v1_db_url = _create_pair_job(tmp_path, "v1-output-budget")
    with db.session_scope(v1_db_url) as session:
        job = session.exec(select(CombinationJob)).one()
        config = dict(job.config)
        config.pop("generator_max_output_tokens")
        job.config = config
        session.add(job)
    assert _config_for_resume("v1-output-budget", v1_db_url)[
        "generator_max_output_tokens"
    ] == 32000
    with db.session_scope(v1_db_url) as session:
        job = session.exec(select(CombinationJob)).one()
        assert "generator_max_output_tokens" not in job.config


def test_unknown_effort_policy_is_rejected():
    with pytest.raises(ValueError, match="effort_policy_version"):
        combo._validate_combination_config(
            {"pipeline_version": "v2", "effort_policy_version": "unknown"}
        )


def test_novelty_gate_config_and_prompt_hash_are_strict():
    with pytest.raises(ValueError, match="novelty_gate_version"):
        combo._validate_combination_config(
            {"pipeline_version": "v2", "novelty_gate_version": "unknown"}
        )
    frozen = combo._freeze_combination_config({"pipeline_version": "v2"})
    frozen["novelty_prompt_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="changed since run creation"):
        combo._validate_combination_config(frozen)


def test_combo_cli_passes_the_frozen_generation_budget_to_anthropic(
    monkeypatch, tmp_path
):
    captured = {}

    def fake_factory(model, **kwargs):
        captured.update(model=model, **kwargs)

        def backend(prompt, system=None, **call_kwargs):
            return RawCompletion(text="unused")

        return backend

    monkeypatch.setattr(combo_cli, "make_anthropic_backend", fake_factory)
    combo_cli._client(
        model="claude-opus-4-8",
        backend_name="anthropic",
        generation=True,
        max_output_tokens=48000,
        db_url=f"sqlite:///{tmp_path / 'budget-client.db'}",
    )
    assert captured["max_output_tokens"] == 48000
    assert captured["timeout"] == 840.0
    assert captured["effort"] == "high"


@pytest.mark.parametrize(
    "key,value",
    [
        ("generator_max_output_tokens", True),
        ("generator_max_output_tokens", 1023),
        ("generator_max_output_tokens", 48001),
        ("generator_max_output_tokens", 1.5),
    ],
)
def test_output_token_budgets_reject_invalid_values(key, value):
    with pytest.raises(ValueError, match=key):
        combo._validate_combination_config({key: value})


def _create_v2_job(tmp_path, run_id: str, *, stage_attempts: int = 2) -> str:
    db_url = f"sqlite:///{tmp_path / (run_id + '.db')}"
    taxonomy = tmp_path / (run_id + "-techniques.json")
    _write_taxonomy(taxonomy)
    db.init_db(db_url)
    with db.session_scope(db_url) as session:
        session.add(
            Problem(
                id=f"{run_id}-source",
                source=ProblemSource.OTHER_COMPETITION,
                statement="An official source with a finite modular representation.",
                provenance={"techniques": list(IDS)},
            ).refresh_dedup_fields()
        )
    catalog = load_technique_catalog(taxonomy)
    evidence = build_pair_evidence(catalog, db_url)
    create_combination_jobs(
        run_id=run_id,
        count=1,
        seed=19,
        catalog=catalog,
        evidence=evidence,
        config={
            "pipeline_version": "v2",
            "generator_model": "fake",
            "judge_model": "fake",
            "bridges_per_pair": 3,
            "shells_per_bridge": 4,
            "stage_attempts": stage_attempts,
            "target_difficulty": [4, 8],
            "creativity_floor": 4,
            "blind_difficulty_floor": 4.5,
            "max_creativity_repairs": 1,
        },
        db_url=db_url,
        explicit_pair=IDS,
    )
    return db_url


def test_v2_shell_draft_blind_and_faithfulness_contracts():
    shells = combo.parse_shell_proposals(
        json.dumps(_shell_proposals()), "b2", IDS, (4, 8)
    )
    assert [shell["shell_id"] for shell in shells["shells"]] == [
        "s1",
        "s2",
        "s3",
        "s4",
    ]
    judgment = combo.parse_shell_judgment(
        json.dumps(_shell_judgment()), ("s1", "s2", "s3", "s4"), IDS
    )
    assert judgment["computed_selected_shell_id"] == "s2"
    parsed = combo.parse_combo_draft_v2(
        _draft_v2(), "b2", "s2", IDS, (4, 8)
    )
    repaired = combo.parse_combo_draft_v2(
        _draft_v2(repair=True), "b2", "s2", IDS, (4, 8), repair=True
    )
    assert parsed["schema_version"] == "combo_problem_generation_v2"
    assert len(repaired["repair_summary"]["structural_changes"]) == 2

    accepted = combo.parse_blind_audit(
        json.dumps(_blind_audit("accept")), "22", (4, 8)
    )
    repairable = combo.parse_blind_audit(
        json.dumps(_blind_audit("repair")), "22", (4, 8)
    )
    fatal = combo.parse_blind_audit(
        json.dumps(_blind_audit("fatal")), "22", (4, 8)
    )
    assert accepted["computed_action"] == "accept"
    assert repairable["computed_action"] == "repair"
    assert fatal["computed_action"] == "reject"
    assert combo.parse_faithfulness(
        json.dumps(_faithfulness_v2()),
        IDS,
        schema_version="combo_faithfulness_v2",
        creativity_floor=4,
    )["computed_quality_pass"]

    duplicate_axis = _shell_proposals()
    duplicate_axis["shells"][1]["diversity_axis"] = duplicate_axis["shells"][0][
        "diversity_axis"
    ]
    with pytest.raises(ContractError, match="diversity_axis"):
        combo.parse_shell_proposals(json.dumps(duplicate_axis), "b2", IDS, (4, 8))
    wrong_winner = _shell_judgment()
    wrong_winner["selected_shell_id"] = "s1"
    normalized = combo.parse_shell_judgment(
        json.dumps(wrong_winner), ("s1", "s2", "s3", "s4"), IDS
    )
    assert normalized["selected_shell_id"] == "s1"
    assert normalized["reported_selected_shell_id"] == "s1"
    assert normalized["reported_selected_shell_id_consistent"] is False
    assert normalized["computed_selected_shell_id"] == "s2"

    wrong_winner["selected_shell_id"] = "unknown-shell"
    with pytest.raises(ContractError, match="evaluated shell"):
        combo.parse_shell_judgment(
            json.dumps(wrong_winner), ("s1", "s2", "s3", "s4"), IDS
        )


def test_v2_runtime_floors_are_parser_contracts():
    shell_judgment = _shell_judgment()
    shell_result = combo.parse_shell_judgment(
        json.dumps(shell_judgment),
        ("s1", "s2", "s3", "s4"),
        IDS,
        creativity_floor=5,
    )
    assert shell_result["computed_selected_shell_id"] is None
    assert shell_result["reported_decision_consistent"] is False
    assert [
        evaluation["reported_verdict_consistent"]
        for evaluation in shell_result["evaluations"]
    ] == [False, False, True, True]

    blind = _blind_audit("accept")
    creativity_failed = combo.parse_blind_audit(
        json.dumps(blind),
        "22",
        (4, 8),
        creativity_floor=5,
        difficulty_floor=4.5,
    )
    assert creativity_failed["computed_action"] == "repair"
    assert creativity_failed["policy_failures"] == [
        "surprise_compression",
        "resistance",
    ]
    assert creativity_failed["reported_verdict"] == "accept"
    assert creativity_failed["reported_verdict_consistent"] is False

    difficulty_failed = combo.parse_blind_audit(
        json.dumps(blind),
        "22",
        (4, 8),
        creativity_floor=4,
        difficulty_floor=6.0,
    )
    assert difficulty_failed["computed_action"] == "repair"
    assert difficulty_failed["policy_failures"] == ["difficulty_floor"]
    assert difficulty_failed["reported_verdict"] == "accept"
    assert difficulty_failed["reported_verdict_consistent"] is False

    blind["verdict"] = "reject"
    blind["reason"] = "The configured quality floor is not met."
    parsed = combo.parse_blind_audit(
        json.dumps(blind),
        "22",
        (4, 8),
        creativity_floor=5,
        difficulty_floor=4.5,
    )
    assert parsed["computed_action"] == "repair"
    assert parsed["reported_verdict"] == "reject"
    assert parsed["reported_verdict_consistent"] is True

    faithfulness = _faithfulness_v2()
    faithfulness_result = combo.parse_faithfulness(
        json.dumps(faithfulness),
        IDS,
        schema_version="combo_faithfulness_v2",
        creativity_floor=5,
    )
    assert faithfulness_result["verdict"] == "accept"
    assert faithfulness_result["reported_verdict"] == "accept"
    assert faithfulness_result["reported_verdict_consistent"] is False
    assert faithfulness_result["computed_quality_pass"] is False
    faithfulness.update(
        interaction_creativity=5,
        problem_creativity=5,
        naturalness=5,
    )
    assert combo.parse_faithfulness(
        json.dumps(faithfulness),
        IDS,
        schema_version="combo_faithfulness_v2",
        creativity_floor=5,
    )["computed_quality_pass"]


def test_v2_shortest_route_uses_accepts_either_order_and_normalizes():
    canonical_ids = json.dumps(list(IDS))
    reversed_ids = json.dumps(list(reversed(IDS)))
    draft = _draft_v2().replace(canonical_ids, reversed_ids)

    parsed = combo.parse_combo_draft_v2(draft, "b2", "s2", IDS, (4, 8))

    assert parsed["bypass_attempts"]["shortest_route_uses"] == list(IDS)

    for invalid_ids in (
        [IDS[0], IDS[0]],
        [IDS[0]],
        [IDS[0], "unknown.technique"],
    ):
        malformed = _draft_v2().replace(canonical_ids, json.dumps(invalid_ids))
        with pytest.raises(ContractError, match="each technique ID exactly once"):
            combo.parse_combo_draft_v2(malformed, "b2", "s2", IDS, (4, 8))


def test_stop_reason_is_normalized_for_exhaustion_detection():
    response = RawCompletion(text="", raw={"stop_reason": "  MAX_TOKENS  "})

    assert combo._stop_reason(response) == "max_tokens"


def test_corpus_novelty_contract_fails_closed_on_reused_kernel():
    neighbor_ids = ("omni-math-1555", "distinct-source")
    contradictory = _novelty_audit(
        neighbor_ids,
        blocked_id="omni-math-1555",
        reported_verdict="accept",
    )
    parsed = combo.parse_corpus_novelty(
        json.dumps(contradictory), neighbor_ids, distance_floor=3
    )

    assert parsed["reported_verdict"] == "accept"
    assert parsed["reported_verdict_consistent"] is False
    assert parsed["computed_novelty_pass"] is False
    assert parsed["computed_closest_neighbor_id"] == "omni-math-1555"
    assert "omni-math-1555:same_mathematical_kernel" in parsed["policy_failures"]
    assert "omni-math-1555:structural_distance" in parsed["policy_failures"]

    distinct = combo.parse_corpus_novelty(
        json.dumps(_novelty_audit(neighbor_ids)), neighbor_ids, distance_floor=3
    )
    assert distinct["computed_novelty_pass"] is True
    assert distinct["reported_verdict_consistent"] is True

    with pytest.raises(ContractError, match="nonempty unique"):
        combo.parse_corpus_novelty(
            json.dumps(
                {
                    "schema_version": "combo_corpus_novelty_v1",
                    "comparisons": [],
                    "closest_neighbor_id": None,
                    "verdict": "accept",
                    "reason": "No corpus neighbors were supplied for comparison.",
                }
            ),
            (),
        )
    with pytest.raises(ContractError, match="nonempty unique"):
        combo.parse_corpus_novelty(
            json.dumps(_novelty_audit(("dup", "dup"))), ("dup", "dup")
        )

    hallucinated = _novelty_audit(neighbor_ids)
    hallucinated["comparisons"][0]["neighbor_id"] = "not-supplied"
    with pytest.raises(ContractError, match="comparison IDs"):
        combo.parse_corpus_novelty(json.dumps(hallucinated), neighbor_ids)
    bad_closest = _novelty_audit(neighbor_ids)
    bad_closest["closest_neighbor_id"] = "not-supplied"
    with pytest.raises(ContractError, match="closest_neighbor_id"):
        combo.parse_corpus_novelty(json.dumps(bad_closest), neighbor_ids)


def test_novelty_retrieval_finds_hmmt_kernel_and_unions_evidence(tmp_path):
    run_id = "novelty-retrieval"
    db_url = _create_v2_job(tmp_path, run_id, stage_attempts=1)
    evidence_ids = ["evidence-one", "evidence-two", "evidence-three"]
    omni_statement = (
        "Michael picks a random subset of the complex numbers "
        "{1, omega, omega^2, ..., omega^2017}, where omega is a primitive "
        "2018th root of unity. If their sum is S, find the expected value of |S|^2."
    )
    with db.session_scope(db_url) as session:
        job = session.exec(select(CombinationJob)).one()
        sampler = dict(job.sampler_metadata or {})
        sampler["evidence_ids"] = evidence_ids
        job.sampler_metadata = sampler
        session.add(job)
        for index, problem_id in enumerate(evidence_ids, 1):
            session.add(
                Problem(
                    id=problem_id,
                    source=ProblemSource.OTHER_COMPETITION,
                    statement=f"A geometrically unrelated official problem number {index}.",
                ).refresh_dedup_fields()
            )
        session.add(
            Problem(
                id="omni-math-1555",
                source=ProblemSource.OTHER_COMPETITION,
                statement=omni_statement,
            ).refresh_dedup_fields()
        )
        session.add(
            Problem(
                id="pending-semantic-neighbor",
                source=ProblemSource.SYNTHETIC,
                statement=(
                    "For a random subset of roots of unity with complex sum S, "
                    "determine the expectation of its squared magnitude."
                ),
                review_status=ReviewStatus.PENDING,
            ).refresh_dedup_fields()
        )

    candidate_statement = (
        "Twenty-five sensors occupy positions 0 through 24. A uniformly random "
        "size-r activation subset A has complex response S=sum_{k in A} e^{ik pi/13}. "
        "Let f(r)=E[|S|^2] and compute 100 times the maximum of f(r)."
    )
    candidate_crux = (
        "Expand the expected squared complex sum over the random subset, then use "
        "the incomplete roots-of-unity sum and maximize the resulting quadratic."
    )
    with db.session_scope(db_url) as session:
        job = session.exec(select(CombinationJob)).one()
    index = combo._build_novelty_index(db_url)
    first = combo._novelty_neighbor_payload(
        job=job,
        draft={"statement": candidate_statement, "crux": candidate_crux},
        index=index,
        neighbor_count=8,
    )
    second = combo._novelty_neighbor_payload(
        job=job,
        draft={"statement": candidate_statement, "crux": candidate_crux},
        index=index,
        neighbor_count=8,
    )

    selected = {neighbor["neighbor_id"] for neighbor in first["neighbors"]}
    assert set(evidence_ids) <= selected
    assert "omni-math-1555" in selected
    assert "pending-semantic-neighbor" in index.by_id
    assert first == second
    assert all(neighbor["inclusion_reasons"] for neighbor in first["neighbors"])
    omni = next(
        neighbor
        for neighbor in first["neighbors"]
        if neighbor["neighbor_id"] == "omni-math-1555"
    )
    assert omni["structural_anchor_overlap"] >= 2
    assert not combo.is_near_duplicate(  # legacy lexical gate intentionally misses it
        combo.token_set(candidate_statement), [combo.token_set(omni_statement)]
    )

    with db.session_scope(db_url) as session:
        job = session.exec(select(CombinationJob)).one()
        sampler = dict(job.sampler_metadata)
        sampler["evidence_ids"] = [*evidence_ids, "deleted-evidence"]
        job.sampler_metadata = sampler
        session.add(job)
    with db.session_scope(db_url) as session:
        job = session.exec(select(CombinationJob)).one()
        missing = combo._novelty_neighbor_payload(
            job=job,
            draft={"statement": candidate_statement, "crux": candidate_crux},
            index=index,
            neighbor_count=8,
        )
        assert missing["missing_evidence_ids"] == ["deleted-evidence"]
        missing["round"] = "initial"
        missing["retrieval_hash"] = combo._json_hash(
            {
                key: value
                for key, value in missing.items()
                if key != "retrieval_hash"
            }
        )
        job.draft = {"statement": candidate_statement, "crux": candidate_crux}
        job.design_artifacts = combo._v2_design_put(
            job, "novelty_neighbors", "initial", missing
        )
        with pytest.raises(ValueError, match="missing pair evidence"):
            combo._current_v2_novelty_neighbors(job)


def test_v2_happy_path_is_resumable_and_blind_prompt_has_no_design_leak(tmp_path):
    db_url = _create_v2_job(tmp_path, "v2-happy", stage_attempts=1)
    observed_prompts: list[str] = []

    def backend(prompt, system=None, **kwargs):
        observed_prompts.append(prompt)
        if "STAGE: COMBO_BRIDGE_GENERATION_V1" in prompt:
            text = json.dumps(_bridge_candidates())
        elif "STAGE: COMBO_BRIDGE_JUDGE_V1" in prompt:
            text = json.dumps(_bridge_judgment())
        elif "STAGE: COMBO_SHELL_GENERATION_V1" in prompt:
            text = json.dumps(_shell_proposals())
        elif "STAGE: COMBO_SHELL_JUDGE_V1" in prompt:
            text = json.dumps(_shell_judgment())
        elif "STAGE: COMBO_PROBLEM_GENERATION_V2" in prompt:
            text = _draft_v2()
        elif "STAGE: COMBO_BLIND_AUDIT_V1" in prompt:
            text = json.dumps(_blind_audit("accept"))
        elif "STAGE: COMBO_FAITHFULNESS_V2" in prompt:
            text = json.dumps(_faithfulness_v2())
        elif "STAGE: COMBO_CORPUS_NOVELTY_V1" in prompt:
            text = json.dumps(_novelty_audit(("v2-happy-source",)))
        else:
            raise AssertionError("unexpected v2 prompt")
        return RawCompletion(text=text, raw={"stop_reason": "end_turn"})

    client = LLMClient(model="fake", backend=backend, db_url=db_url)
    report = process_combination_run(
        run_id="v2-happy", generator=client, judge=client, db_url=db_url
    )
    assert report.stored == 1
    assert len(observed_prompts) == 8
    blind_prompt = next(
        prompt for prompt in observed_prompts if "STAGE: COMBO_BLIND_AUDIT_V1" in prompt
    )
    assert IDS[0] not in blind_prompt
    assert IDS[1] not in blind_prompt
    assert "ACCEPTED BRIDGE" not in blind_prompt
    assert "SELECTED SHELL" not in blind_prompt
    assert "<answer>22</answer>" not in blind_prompt
    assert "MINIMUM ACCEPTABLE DIFFICULTY SCORE:\n4.5" in blind_prompt
    assert "CREATIVITY FLOOR FOR SURPRISE AND RESISTANCE (integer from 4 to 5):\n4" in blind_prompt
    for prompt in observed_prompts:
        if any(
            stage in prompt
            for stage in (
                "STAGE: COMBO_SHELL_GENERATION_V1",
                "STAGE: COMBO_SHELL_JUDGE_V1",
                "STAGE: COMBO_PROBLEM_GENERATION_V2",
                "STAGE: COMBO_FAITHFULNESS_V2",
            )
        ):
            assert "CREATIVITY FLOOR (integer from 4 to 5):\n4" in prompt
    compose_prompt = next(
        prompt
        for prompt in observed_prompts
        if "STAGE: COMBO_PROBLEM_GENERATION_V2" in prompt
    )
    assert "MINIMUM BLIND-AUDIT DIFFICULTY SCORE:\n4.5" in compose_prompt

    calls_before = len(observed_prompts)
    again = process_combination_run(
        run_id="v2-happy", generator=client, judge=client, db_url=db_url
    )
    assert again.stored == 1
    assert len(observed_prompts) == calls_before
    with db.session_scope(db_url) as session:
        job = session.exec(select(CombinationJob)).one()
        problem = session.exec(
            select(Problem).where(Problem.source == ProblemSource.SYNTHETIC)
        ).one()
        solutions = session.exec(
            select(Solution).where(Solution.problem_id == problem.id)
        ).all()
        calls = session.exec(
            select(LLMCall)
            .where(LLMCall.related_id == job.id)
            .order_by(LLMCall.id)
        ).all()
        assert job.design_artifacts["regeneration_count"] == 0
        assert set(job.design_artifacts["shells"]) == {
            "generation",
            "judgment",
            "selected",
        }
        assert set(job.design_artifacts["novelty_neighbors"]) == {"initial"}
        assert set(job.design_artifacts["novelty_audits"]) == {"initial"}
        assert set(job.call_ids) == {
            "bridge_proposal",
            "bridge_judgment",
            "shell_proposal",
            "shell_judgment",
            "compose",
            "blind_audit_r0",
            "preflight",
            "novelty_audit_r0",
        }
        efforts = {call.meta["stage"]: call.meta["requested_effort"] for call in calls}
        assert efforts == {
            "bridge_proposal": "high",
            "bridge_judgment": "medium",
            "shell_proposal": "medium",
            "shell_judgment": "medium",
            "compose": "medium",
            "blind_audit_r0": "medium",
            "preflight": "medium",
            "novelty_audit_r0": "medium",
        }
        assert all(
            call.meta["effort_policy_version"] == combo.STAGE_EFFORT_POLICY
            for call in calls
        )
        assert {
            call.meta["configured_max_output_tokens"]
            for call in calls
            if call.meta["stage"] in {"bridge_proposal", "shell_proposal", "compose"}
        } == {48000}
        assert {
            call.meta["configured_max_output_tokens"]
            for call in calls
            if call.meta["stage"] not in {"bridge_proposal", "shell_proposal", "compose"}
        } == {12000}
        assert problem.provenance["pipeline"] == "distill-combo-bridge-shell-v2"
        assert problem.provenance["crux"] == job.draft["crux"]
        assert problem.provenance["automated_creativity_gate_passed"] is True
        assert problem.provenance["corpus_novelty_gate_passed"] is True
        assert problem.provenance["corpus_novelty"]["audit"][
            "computed_novelty_pass"
        ] is True
        assert problem.provenance["corpus_novelty"]["retrieval"]["neighbors"][0][
            "neighbor_id"
        ] == "v2-happy-source"
        assert problem.difficulty == 5.5
        assert len(solutions) == 1
        assert solutions[0].crux_insight == job.draft["crux"]
        assert solutions[0].features["prompt_version"] == "combo_problem_generation_v2"


def test_v2_runs_one_durable_repair_with_independent_attempt_keys(tmp_path):
    db_url = _create_v2_job(tmp_path, "v2-repair", stage_attempts=1)
    blind_calls = 0

    def backend(prompt, system=None, **kwargs):
        nonlocal blind_calls
        if "STAGE: COMBO_BRIDGE_GENERATION_V1" in prompt:
            text = json.dumps(_bridge_candidates())
        elif "STAGE: COMBO_BRIDGE_JUDGE_V1" in prompt:
            text = json.dumps(_bridge_judgment())
        elif "STAGE: COMBO_SHELL_GENERATION_V1" in prompt:
            text = json.dumps(_shell_proposals())
        elif "STAGE: COMBO_SHELL_JUDGE_V1" in prompt:
            text = json.dumps(_shell_judgment())
        elif "STAGE: COMBO_PROBLEM_GENERATION_V2" in prompt:
            text = _draft_v2()
        elif "STAGE: COMBO_CREATIVITY_REPAIR_V1" in prompt:
            assert "MINIMUM BLIND-AUDIT DIFFICULTY SCORE:\n4.5" in prompt
            assert "CREATIVITY FLOOR (integer from 4 to 5):\n4" in prompt
            text = _draft_v2(repair=True)
        elif "STAGE: COMBO_BLIND_AUDIT_V1" in prompt:
            text = json.dumps(_blind_audit("repair" if blind_calls == 0 else "accept"))
            blind_calls += 1
        elif "STAGE: COMBO_FAITHFULNESS_V2" in prompt:
            text = json.dumps(_faithfulness_v2())
        elif "STAGE: COMBO_CORPUS_NOVELTY_V1" in prompt:
            text = json.dumps(_novelty_audit(("v2-repair-source",)))
        else:
            raise AssertionError("unexpected v2 repair prompt")
        return RawCompletion(text=text, raw={"stop_reason": "end_turn"})

    client = LLMClient(model="fake", backend=backend, db_url=db_url)
    report = process_combination_run(
        run_id="v2-repair", generator=client, judge=client, db_url=db_url
    )
    assert report.stored == 1
    assert blind_calls == 2
    with db.session_scope(db_url) as session:
        job = session.exec(select(CombinationJob)).one()
        problem = session.exec(
            select(Problem).where(Problem.source == ProblemSource.SYNTHETIC)
        ).one()
        solution = session.exec(
            select(Solution).where(Solution.problem_id == problem.id)
        ).one()
        assert job.design_artifacts["regeneration_count"] == 1
        assert set(job.design_artifacts["drafts"]) == {"initial", "revised"}
        assert set(job.design_artifacts["blind_audits"]) == {"initial", "revised"}
        assert job.attempts["blind_audit_r0"] == 1
        assert job.attempts["blind_audit_r1"] == 1
        assert job.attempts["creativity_repair"] == 1
        assert problem.statement.startswith("A revised family")
        assert solution.features["prompt_version"] == "combo_creativity_repair_v1"


def test_v2_corpus_novelty_failure_repairs_once_then_rejects(tmp_path):
    run_id = "v2-novelty-reject"
    db_url = _create_v2_job(tmp_path, run_id, stage_attempts=1)
    novelty_calls = 0
    repair_calls = 0

    def backend(prompt, system=None, **kwargs):
        nonlocal novelty_calls, repair_calls
        if "STAGE: COMBO_BRIDGE_GENERATION_V1" in prompt:
            text = json.dumps(_bridge_candidates())
        elif "STAGE: COMBO_BRIDGE_JUDGE_V1" in prompt:
            text = json.dumps(_bridge_judgment())
        elif "STAGE: COMBO_SHELL_GENERATION_V1" in prompt:
            text = json.dumps(_shell_proposals())
        elif "STAGE: COMBO_SHELL_JUDGE_V1" in prompt:
            text = json.dumps(_shell_judgment())
        elif "STAGE: COMBO_PROBLEM_GENERATION_V2" in prompt:
            text = _draft_v2()
        elif "STAGE: COMBO_CREATIVITY_REPAIR_V1" in prompt:
            repair_calls += 1
            assert "same_mathematical_kernel" in prompt
            assert f"{run_id}-source" in prompt
            text = _draft_v2(repair=True)
        elif "STAGE: COMBO_BLIND_AUDIT_V1" in prompt:
            text = json.dumps(_blind_audit("accept"))
        elif "STAGE: COMBO_FAITHFULNESS_V2" in prompt:
            text = json.dumps(_faithfulness_v2())
        elif "STAGE: COMBO_CORPUS_NOVELTY_V1" in prompt:
            novelty_calls += 1
            text = json.dumps(
                _novelty_audit(
                    (f"{run_id}-source",),
                    blocked_id=f"{run_id}-source",
                    reported_verdict="accept",
                )
            )
        else:
            raise AssertionError("unexpected novelty-rejection prompt")
        return RawCompletion(text=text, raw={"stop_reason": "end_turn"})

    client = LLMClient(model="fake", backend=backend, db_url=db_url)
    report = process_combination_run(
        run_id=run_id, generator=client, judge=client, db_url=db_url
    )

    assert report.rejected == 1
    assert report.exhausted == 0
    assert novelty_calls == 2
    assert repair_calls == 1
    with db.session_scope(db_url) as session:
        job = session.exec(select(CombinationJob)).one()
        assert job.design_artifacts["regeneration_count"] == 1
        assert set(job.design_artifacts["novelty_neighbors"]) == {
            "initial",
            "revised",
        }
        assert set(job.design_artifacts["novelty_audits"]) == {
            "initial",
            "revised",
        }
        for audit in job.design_artifacts["novelty_audits"].values():
            assert audit["reported_verdict"] == "accept"
            assert audit["reported_verdict_consistent"] is False
            assert audit["computed_novelty_pass"] is False
        assert job.attempts["novelty_audit_r0"] == 1
        assert job.attempts["novelty_audit_r1"] == 1
        assert job.attempts["creativity_repair"] == 1
        assert job.failures == []
        assert job.rejection_reason.startswith("corpus_novelty_rejected:")
        assert session.exec(
            select(Problem).where(Problem.source == ProblemSource.SYNTHETIC)
        ).all() == []


def test_enabled_novelty_gate_cannot_store_from_legacy_quality_checkpoint(tmp_path):
    def prepare(run_id: str, *, disable_gate: bool) -> str:
        db_url = _create_v2_job(tmp_path, run_id, stage_attempts=1)
        draft = combo.parse_combo_draft_v2(_draft_v2(), "b2", "s2", IDS, (4, 8))
        with db.session_scope(db_url) as session:
            job = session.exec(select(CombinationJob)).one()
            config = dict(job.config)
            if disable_gate:
                for key in list(config):
                    if key.startswith("novelty_"):
                        config.pop(key)
            job.config = config
            job.bridge_candidates = _bridge_candidates()
            job.bridge_judgment = _bridge_judgment()
            job.selected_bridge = _bridge_candidates()["candidates"][1]
            job.draft = draft
            job.stage = "quality_passed"
            job.status = CombinationJobStatus.PENDING
            session.add(job)
        return db_url

    def no_calls(prompt, system=None, **kwargs):
        raise AssertionError("checkpoint validation must not call a model")

    enabled_db = prepare("novelty-bypass-enabled", disable_gate=False)
    enabled_client = LLMClient(model="fake", backend=no_calls, db_url=enabled_db)
    enabled = process_combination_run(
        run_id="novelty-bypass-enabled",
        generator=enabled_client,
        judge=enabled_client,
        db_url=enabled_db,
    )
    assert enabled.rejected == 1 and enabled.stored == 0
    with db.session_scope(enabled_db) as session:
        assert session.exec(
            select(Problem).where(Problem.source == ProblemSource.SYNTHETIC)
        ).all() == []

    legacy_db = prepare("novelty-bypass-legacy", disable_gate=True)
    legacy_client = LLMClient(model="fake", backend=no_calls, db_url=legacy_db)
    legacy = process_combination_run(
        run_id="novelty-bypass-legacy",
        generator=legacy_client,
        judge=legacy_client,
        db_url=legacy_db,
    )
    assert legacy.stored == 1 and legacy.rejected == 0


def test_novelty_retrieval_checkpoint_resumes_without_reretrieval_and_binds_hash(
    tmp_path,
):
    def prepare(run_id: str) -> tuple[str, dict]:
        db_url = _create_v2_job(tmp_path, run_id, stage_attempts=1)
        draft = combo.parse_combo_draft_v2(_draft_v2(), "b2", "s2", IDS, (4, 8))
        with db.session_scope(db_url) as session:
            job = session.exec(select(CombinationJob)).one()
            job.bridge_candidates = _bridge_candidates()
            job.bridge_judgment = _bridge_judgment()
            job.selected_bridge = _bridge_candidates()["candidates"][1]
            job.draft = draft
            job.stage = "novelty_retrieved"
            job.status = CombinationJobStatus.PENDING
            session.add(job)
        index = combo._build_novelty_index(db_url)
        with db.session_scope(db_url) as session:
            job = session.exec(select(CombinationJob)).one()
            retrieval = combo._novelty_neighbor_payload(
                job=job,
                draft=draft,
                index=index,
                neighbor_count=8,
            )
            retrieval["round"] = "initial"
            retrieval["retrieval_hash"] = combo._json_hash(
                {
                    key: value
                    for key, value in retrieval.items()
                    if key != "retrieval_hash"
                }
            )
            job.design_artifacts = combo._v2_design_put(
                job, "novelty_neighbors", "initial", retrieval
            )
            session.add(job)
        return db_url, retrieval

    run_id = "novelty-resume"
    db_url, retrieval = prepare(run_id)
    with db.session_scope(db_url) as session:
        session.add(
            Problem(
                id="added-after-retrieval",
                source=ProblemSource.OTHER_COMPETITION,
                statement="A newly inserted corpus problem must not alter a persisted prompt.",
            ).refresh_dedup_fields()
        )
    calls = 0

    def backend(prompt, system=None, **kwargs):
        nonlocal calls
        calls += 1
        assert "STAGE: COMBO_CORPUS_NOVELTY_V1" in prompt
        assert "added-after-retrieval" not in prompt
        ids = tuple(
            neighbor["neighbor_id"] for neighbor in retrieval["neighbors"]
        )
        return RawCompletion(
            text=json.dumps(_novelty_audit(ids)),
            raw={"stop_reason": "end_turn"},
        )

    client = LLMClient(model="fake", backend=backend, db_url=db_url)
    report = process_combination_run(
        run_id=run_id, generator=client, judge=client, db_url=db_url
    )
    assert report.stored == 1
    assert calls == 1
    again = process_combination_run(
        run_id=run_id, generator=client, judge=client, db_url=db_url
    )
    assert again.stored == 1 and calls == 1

    stale_db, _ = prepare("novelty-stale-retrieval")
    with db.session_scope(stale_db) as session:
        job = session.exec(select(CombinationJob)).one()
        design = dict(job.design_artifacts)
        retrievals = dict(design["novelty_neighbors"])
        stale = dict(retrievals["initial"])
        neighbors = [dict(item) for item in stale["neighbors"]]
        neighbors[0]["statement"] += " silently mutated"
        stale["neighbors"] = neighbors
        retrievals["initial"] = stale
        design["novelty_neighbors"] = retrievals
        job.design_artifacts = design
        session.add(job)

    def stale_no_calls(prompt, system=None, **kwargs):
        raise AssertionError("corrupt retrieval must reject before a model call")

    stale_client = LLMClient(
        model="fake", backend=stale_no_calls, db_url=stale_db
    )
    stale_report = process_combination_run(
        run_id="novelty-stale-retrieval",
        generator=stale_client,
        judge=stale_client,
        db_url=stale_db,
    )
    assert stale_report.rejected == 1 and stale_report.stored == 0


def test_v2_contradictory_blind_accept_is_checkpointed_then_rejected(tmp_path):
    run_id = "v2-contradictory-blind-accept"
    db_url = _create_v2_job(tmp_path, run_id, stage_attempts=1)
    blind_calls = 0

    def backend(prompt, system=None, **kwargs):
        nonlocal blind_calls
        if "STAGE: COMBO_BRIDGE_GENERATION_V1" in prompt:
            text = json.dumps(_bridge_candidates())
        elif "STAGE: COMBO_BRIDGE_JUDGE_V1" in prompt:
            text = json.dumps(_bridge_judgment())
        elif "STAGE: COMBO_SHELL_GENERATION_V1" in prompt:
            text = json.dumps(_shell_proposals())
        elif "STAGE: COMBO_SHELL_JUDGE_V1" in prompt:
            text = json.dumps(_shell_judgment())
        elif "STAGE: COMBO_PROBLEM_GENERATION_V2" in prompt:
            text = _draft_v2()
        elif "STAGE: COMBO_CREATIVITY_REPAIR_V1" in prompt:
            text = _draft_v2(repair=True)
        elif "STAGE: COMBO_BLIND_AUDIT_V1" in prompt:
            blind_calls += 1
            audit = _blind_audit("repair")
            audit["verdict"] = "accept"
            audit["reason"] = "The statement-only audit passes every quality gate."
            text = json.dumps(audit)
        else:
            raise AssertionError("a contradictory final blind audit must stop the pipeline")
        return RawCompletion(text=text, raw={"stop_reason": "end_turn"})

    client = LLMClient(model="fake", backend=backend, db_url=db_url)
    report = process_combination_run(
        run_id=run_id, generator=client, judge=client, db_url=db_url
    )

    assert report.rejected == 1
    assert report.exhausted == 0
    assert blind_calls == 2
    with db.session_scope(db_url) as session:
        job = session.exec(select(CombinationJob)).one()
        audits = job.design_artifacts["blind_audits"]
        assert set(audits) == {"initial", "revised"}
        for audit in audits.values():
            assert audit["reported_verdict"] == "accept"
            assert audit["reported_verdict_consistent"] is False
            assert audit["computed_action"] == "repair"
            assert "routine_bypass" in audit["policy_failures"]
            assert "difficulty_floor" in audit["policy_failures"]
        assert job.attempts["blind_audit_r0"] == 1
        assert job.attempts["blind_audit_r1"] == 1
        assert job.failures == []
        assert job.status is CombinationJobStatus.REJECTED
        assert job.rejection_reason.startswith(
            "blind_audit_rejected: policy failures="
        )


def test_v2_faithfulness_critique_can_trigger_the_single_repair(tmp_path):
    db_url = _create_v2_job(tmp_path, "v2-faith-repair", stage_attempts=1)
    faith_calls = 0
    repair_calls = 0

    def backend(prompt, system=None, **kwargs):
        nonlocal faith_calls, repair_calls
        if "STAGE: COMBO_BRIDGE_GENERATION_V1" in prompt:
            text = json.dumps(_bridge_candidates())
        elif "STAGE: COMBO_BRIDGE_JUDGE_V1" in prompt:
            text = json.dumps(_bridge_judgment())
        elif "STAGE: COMBO_SHELL_GENERATION_V1" in prompt:
            text = json.dumps(_shell_proposals())
        elif "STAGE: COMBO_SHELL_JUDGE_V1" in prompt:
            text = json.dumps(_shell_judgment())
        elif "STAGE: COMBO_PROBLEM_GENERATION_V2" in prompt:
            text = _draft_v2()
        elif "STAGE: COMBO_CREATIVITY_REPAIR_V1" in prompt:
            repair_calls += 1
            text = _draft_v2(repair=True)
        elif "STAGE: COMBO_BLIND_AUDIT_V1" in prompt:
            text = json.dumps(_blind_audit("accept"))
        elif "STAGE: COMBO_FAITHFULNESS_V2" in prompt:
            verdict = _faithfulness_v2()
            if faith_calls == 0:
                verdict["problem_creativity"] = 3
                verdict["verdict"] = "reject"
                verdict["reason"] = "Valid but still too close to the canonical shell."
            faith_calls += 1
            text = json.dumps(verdict)
        elif "STAGE: COMBO_CORPUS_NOVELTY_V1" in prompt:
            text = json.dumps(_novelty_audit(("v2-faith-repair-source",)))
        else:
            raise AssertionError("unexpected faithfulness-repair prompt")
        return RawCompletion(text=text, raw={"stop_reason": "end_turn"})

    client = LLMClient(model="fake", backend=backend, db_url=db_url)
    report = process_combination_run(
        run_id="v2-faith-repair", generator=client, judge=client, db_url=db_url
    )
    assert report.stored == 1
    assert faith_calls == 2
    assert repair_calls == 1
    with db.session_scope(db_url) as session:
        job = session.exec(select(CombinationJob)).one()
        assert set(job.design_artifacts["preflights"]) == {"initial", "revised"}
        assert job.design_artifacts["preflights"]["initial"]["verdict"] == "reject"
        assert job.design_artifacts["preflights"]["revised"]["verdict"] == "accept"


@pytest.mark.parametrize("final_kind", ["repair", "fatal"])
def test_v2_never_loops_after_one_repair(tmp_path, final_kind):
    run_id = f"v2-final-{final_kind}"
    db_url = _create_v2_job(tmp_path, run_id, stage_attempts=1)
    blind_calls = 0
    repair_calls = 0

    def backend(prompt, system=None, **kwargs):
        nonlocal blind_calls, repair_calls
        if "STAGE: COMBO_BRIDGE_GENERATION_V1" in prompt:
            text = json.dumps(_bridge_candidates())
        elif "STAGE: COMBO_BRIDGE_JUDGE_V1" in prompt:
            text = json.dumps(_bridge_judgment())
        elif "STAGE: COMBO_SHELL_GENERATION_V1" in prompt:
            text = json.dumps(_shell_proposals())
        elif "STAGE: COMBO_SHELL_JUDGE_V1" in prompt:
            text = json.dumps(_shell_judgment())
        elif "STAGE: COMBO_PROBLEM_GENERATION_V2" in prompt:
            text = _draft_v2()
        elif "STAGE: COMBO_CREATIVITY_REPAIR_V1" in prompt:
            repair_calls += 1
            text = _draft_v2(repair=True)
        elif "STAGE: COMBO_BLIND_AUDIT_V1" in prompt:
            text = json.dumps(_blind_audit("repair" if blind_calls == 0 else final_kind))
            blind_calls += 1
        else:
            raise AssertionError("preflight must not run after failed final blind audit")
        return RawCompletion(text=text, raw={"stop_reason": "end_turn"})

    client = LLMClient(model="fake", backend=backend, db_url=db_url)
    report = process_combination_run(
        run_id=run_id, generator=client, judge=client, db_url=db_url
    )
    assert report.rejected == 1
    assert repair_calls == 1
    assert blind_calls == 2
    with db.session_scope(db_url) as session:
        job = session.exec(select(CombinationJob)).one()
        assert job.design_artifacts["regeneration_count"] == 1
        assert job.rejection_reason.startswith("blind_audit_rejected")
        assert session.exec(
            select(Problem).where(Problem.source == ProblemSource.SYNTHETIC)
        ).all() == []


def test_v2_fatal_initial_blind_audit_is_not_repaired(tmp_path):
    db_url = _create_v2_job(tmp_path, "v2-fatal", stage_attempts=1)
    prompts: list[str] = []

    def backend(prompt, system=None, **kwargs):
        prompts.append(prompt)
        if "STAGE: COMBO_BRIDGE_GENERATION_V1" in prompt:
            text = json.dumps(_bridge_candidates())
        elif "STAGE: COMBO_BRIDGE_JUDGE_V1" in prompt:
            text = json.dumps(_bridge_judgment())
        elif "STAGE: COMBO_SHELL_GENERATION_V1" in prompt:
            text = json.dumps(_shell_proposals())
        elif "STAGE: COMBO_SHELL_JUDGE_V1" in prompt:
            text = json.dumps(_shell_judgment())
        elif "STAGE: COMBO_PROBLEM_GENERATION_V2" in prompt:
            text = _draft_v2()
        elif "STAGE: COMBO_BLIND_AUDIT_V1" in prompt:
            text = json.dumps(_blind_audit("fatal"))
        else:
            raise AssertionError("fatal blind audit must stop the pipeline")
        return RawCompletion(text=text, raw={"stop_reason": "end_turn"})

    client = LLMClient(model="fake", backend=backend, db_url=db_url)
    report = process_combination_run(
        run_id="v2-fatal", generator=client, judge=client, db_url=db_url
    )
    assert report.rejected == 1
    assert not any("STAGE: COMBO_CREATIVITY_REPAIR_V1" in prompt for prompt in prompts)


def test_v2_prompt_hash_registry_is_frozen_independently_of_v1(tmp_path):
    db_url = _create_v2_job(tmp_path, "v2-hashes")
    with db.session_scope(db_url) as session:
        job = session.exec(select(CombinationJob)).one()
        assert set(job.config["prompt_hashes"]) == {
            "bridge",
            "bridge_judge",
            "shell",
            "shell_judge",
            "problem",
            "blind_audit",
            "preflight",
            "repair",
        }
        config = dict(job.config)
        hashes = dict(config["prompt_hashes"])
        hashes["shell"] = "0" * 64
        config["prompt_hashes"] = hashes
        job.config = config
        session.add(job)

    def no_calls(prompt, system=None, **kwargs):
        raise AssertionError("tampered v2 prompt hash must fail before a model call")

    client = LLMClient(model="fake", backend=no_calls, db_url=db_url)
    with pytest.raises(ValueError, match="changed since run creation"):
        process_combination_run(
            run_id="v2-hashes", generator=client, judge=client, db_url=db_url
        )


def test_v2_refuses_a_blind_audit_bound_to_another_statement(tmp_path):
    db_url = _create_v2_job(tmp_path, "v2-stale-audit")
    parsed_draft = combo.parse_combo_draft_v2(
        _draft_v2(), "b2", "s2", IDS, (4, 8)
    )
    audit = combo.parse_blind_audit(
        json.dumps(_blind_audit("accept")), "22", (4, 8)
    )
    audit["statement_hash"] = "not-the-current-statement"
    audit["round"] = "initial"
    with db.session_scope(db_url) as session:
        job = session.exec(select(CombinationJob)).one()
        job.stage = "blind_initial_judged"
        job.draft = parsed_draft
        job.design_artifacts = {
            "schema_version": "combo_design_artifacts_v2",
            "regeneration_count": 0,
            "blind_audits": {"initial": audit},
        }
        session.add(job)

    def no_calls(prompt, system=None, **kwargs):
        raise AssertionError("a stale persisted audit must fail without an API call")

    client = LLMClient(model="fake", backend=no_calls, db_url=db_url)
    report = process_combination_run(
        run_id="v2-stale-audit", generator=client, judge=client, db_url=db_url
    )
    assert report.rejected == 1
    with db.session_scope(db_url) as session:
        job = session.exec(select(CombinationJob)).one()
        assert job.rejection_reason.startswith("invalid checkpoint")


def test_additive_design_artifact_migration_preserves_legacy_v1_resume(tmp_path):
    db_url = _create_pair_job(tmp_path, "legacy-migration")
    engine = db.get_engine(db_url)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            'ALTER TABLE "combinationjob" DROP COLUMN "design_artifacts"'
        )
    assert "design_artifacts" not in {
        column["name"] for column in sa_inspect(engine).get_columns("combinationjob")
    }

    # Match a real application restart after upgrading the code/schema. This
    # also clears SQLite/SQLAlchemy schema caches held by pooled connections.
    engine.dispose()
    db.get_engine.cache_clear()
    engine = db.get_engine(db_url)
    db.init_db(db_url)
    assert "design_artifacts" in {
        column["name"] for column in sa_inspect(engine).get_columns("combinationjob")
    }
    with db.session_scope(db_url) as session:
        job = session.exec(select(CombinationJob)).one()
        assert job.config["pipeline_version"] == "v1"
        assert not job.design_artifacts

    def backend(prompt, system=None, **kwargs):
        if "STAGE: COMBO_BRIDGE_GENERATION_V1" in prompt:
            text = json.dumps(_bridge_candidates())
        elif "STAGE: COMBO_BRIDGE_JUDGE_V1" in prompt:
            text = json.dumps(_bridge_judgment())
        elif "STAGE: COMBO_PROBLEM_GENERATION_V1" in prompt:
            text = _draft()
        else:
            text = json.dumps(_faithfulness())
        return RawCompletion(text=text, raw={"stop_reason": "end_turn"})

    client = LLMClient(model="fake", backend=backend, db_url=db_url)
    report = process_combination_run(
        run_id="legacy-migration", generator=client, judge=client, db_url=db_url
    )
    assert report.stored == 1


@pytest.mark.parametrize(
    "config, message",
    [
        ({"prompt_versions": []}, "prompt_versions must be an object"),
        ({"prompt_versions": {"problem": ""}}, "unsupported problem prompt"),
        ({"prompt_hashes": {}}, "prompt_hashes must contain exactly"),
        (
            {
                "prompt_hashes": {
                    "bridge": "0" * 64,
                    "bridge_judge": "0" * 64,
                    "problem": "0" * 64,
                    "preflight": "0" * 64,
                }
            },
            "changed since run creation",
        ),
        ({"lease_seconds": 1200.0}, "lease_seconds must be an integer"),
        ({"generator_backend": "anthorpic"}, "generator_backend must be"),
        ({"judge_model": ""}, "judge_model must be a nonempty string"),
    ],
)
def test_combination_config_rejects_falsey_or_weak_guardrails(config, message):
    with pytest.raises(ValueError, match=message):
        combo._validate_combination_config(config)
