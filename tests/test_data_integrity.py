"""Regression tests for leak-free, duplicate-free training exports."""

from __future__ import annotations

import json

import pytest

from mathforge import db
from mathforge.integrity import (
    answer_type,
    audit_export_records,
    canonical_statement_hash,
    deduplicated_training_problems,
    is_export_eligible,
    normalize_aime_answer,
    normalize_solution_text,
    preferred_solution,
    techniques_for,
)
from mathforge.schema import (
    DataSplit,
    Problem,
    ProblemSource,
    ReviewStatus,
    Solution,
    SolutionSource,
)
from scripts.export_creative import build_prompt


@pytest.fixture()
def db_url(tmp_path):
    url = f"sqlite:///{tmp_path / 'integrity.db'}"
    db.init_db(url)
    return url


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("042", "42"),
        (r"\boxed{999}", "999"),
        (r"\[ 17 \]", "17"),
        ("1000", None),
        (r"3^{100}", None),
        ("1, 3", None),
        (None, None),
    ],
)
def test_normalize_aime_answer_is_conservative(raw, expected):
    assert normalize_aime_answer(raw) == expected
    assert answer_type(raw) == ("integer" if expected is not None else (
        "none" if raw is None else "integer_other" if raw == "1000" else "symbolic"
    ))


def test_canonical_hash_ignores_presentation_and_asy():
    a = r"Find $x$ such that \dfrac{x}{2}\leq 3."
    b = r"[asy]draw((0,0)--(1,1));[/asy] Find \(x\) such that \frac { x } { 2 } ≤ 3!"
    assert canonical_statement_hash(a) == canonical_statement_hash(b)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("['A complete proof.']", "A complete proof."),
        ('["A proof with \\n two lines."]', "A proof with \n two lines."),
        ("[x,y] is a vector.", "[x,y] is a vector."),
        ("['first proof', 'second proof']", "first proof"),
        ("ordinary proof", "ordinary proof"),
    ],
)
def test_normalize_solution_text_unwraps_serialized_solution_lists(raw, expected):
    assert normalize_solution_text(raw) == expected


def test_creative_prompt_contains_actual_seed_and_techniques():
    prompt = build_prompt("Number Theory", 7.0, "Turn the recurrence into an invariant.", ["nt.invariant"])
    assert "Seed crux: Turn the recurrence into an invariant." in prompt
    assert "Required techniques: nt.invariant." in prompt
    assert "integer from 0 to 999" in prompt


def test_required_techniques_are_not_overwritten_by_later_inference():
    problem = Problem(
        source=ProblemSource.SYNTHETIC,
        statement="Synthetic",
        provenance={
            "required_techniques": ["required.a", "required.b"],
            "inferred_techniques": ["classifier.c"],
            "techniques": ["legacy.d"],
        },
    )

    assert techniques_for(problem, None) == ["required.a", "required.b"]


def test_training_dedup_excludes_eval_format_copy(db_url):
    eval_problem = Problem(
        id="eval",
        source=ProblemSource.AIME,
        statement=r"Find $x$ such that x \leq 3.",
        answer="3",
        split=DataSplit.EVAL,
        frozen=True,
    ).refresh_dedup_fields()
    train_copy = Problem(
        id="copy",
        source=ProblemSource.OTHER_COMPETITION,
        statement=r"Find \(x\) such that x ≤ 3!",
        answer="3",
    ).refresh_dedup_fields()
    train_unique = Problem(
        id="unique",
        source=ProblemSource.OTHER_COMPETITION,
        statement="Compute 20+22.",
        answer="42",
    ).refresh_dedup_fields()
    with db.session_scope(db_url) as session:
        session.add_all([eval_problem, train_copy, train_unique])

    with db.session_scope(db_url) as session:
        got = deduplicated_training_problems(session)
    assert [problem.id for problem in got] == ["unique"]


def test_reviewed_duplicate_group_honors_explicit_keeper(
    db_url, tmp_path, monkeypatch
):
    manifest = tmp_path / "dedup.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "cross_split": [],
                "train_groups": [
                    {
                        "id": "reviewed-1",
                        "members": ["lower-id", "preferred-id"],
                        "keeper_id": "preferred-id",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MATHFORGE_DEDUP_MANIFEST", str(manifest))
    with db.session_scope(db_url) as session:
        session.add_all(
            [
                Problem(
                    id="lower-id",
                    source=ProblemSource.OTHER_COMPETITION,
                    statement="First reviewed rendering.",
                    answer="7",
                ).refresh_dedup_fields(),
                Problem(
                    id="preferred-id",
                    source=ProblemSource.OTHER_COMPETITION,
                    statement="Second reviewed rendering.",
                    answer="7",
                ).refresh_dedup_fields(),
            ]
        )

    with db.session_scope(db_url) as session:
        got = deduplicated_training_problems(session)
        stale_report = audit_export_records(
            session, [{"meta": {"id": "lower-id"}}]
        )
        keeper_report = audit_export_records(
            session, [{"meta": {"id": "preferred-id"}}]
        )

    assert [problem.id for problem in got] == ["preferred-id"]
    assert stale_report["quarantined_ids"] == ["lower-id"]
    assert not stale_report["ok"]
    assert keeper_report["ok"]


def test_reviewed_duplicate_group_rejects_nonmember_keeper(
    db_url, tmp_path, monkeypatch
):
    manifest = tmp_path / "bad-dedup.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "cross_split": [],
                "train_groups": [
                    {
                        "id": "bad",
                        "members": ["member-a", "member-b"],
                        "keeper_id": "not-a-member",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MATHFORGE_DEDUP_MANIFEST", str(manifest))

    with db.session_scope(db_url) as session:
        with pytest.raises(ValueError, match="keeper_id"):
            deduplicated_training_problems(session)


def test_synthetic_requires_verification_and_acceptance():
    official = Problem(source=ProblemSource.AIME, statement="Official")
    pending = Problem(
        source=ProblemSource.SYNTHETIC,
        statement="Pending",
        verified=True,
        review_status=ReviewStatus.PENDING,
    )
    accepted = Problem(
        source=ProblemSource.SYNTHETIC,
        statement="Accepted",
        verified=True,
        review_status=ReviewStatus.ACCEPTED,
    )
    assert is_export_eligible(official)
    assert not is_export_eligible(pending)
    assert is_export_eligible(accepted)


def test_preferred_solution_uses_official_and_backfilled_model():
    problem = Problem(id="p", source=ProblemSource.OTHER_COMPETITION, statement="P")
    model = Solution(problem_id="p", text="long model solution", source=SolutionSource.MODEL)
    official = Solution(problem_id="p", text="official", source=SolutionSource.OFFICIAL)
    assert preferred_solution(problem, [model, official]) is official

    synthetic = Problem(
        id="s",
        source=ProblemSource.SYNTHETIC,
        statement="S",
        provenance={"solution_backfilled": True},
    )
    corrected = Solution(problem_id="s", text="correct full solution", source=SolutionSource.MODEL)
    stub = Solution(problem_id="s", text="answer=7", source=SolutionSource.SOLVER_PANEL)
    assert preferred_solution(synthetic, [stub, corrected]) is corrected


def test_preferred_solution_preserves_v2_audited_generator_proof():
    problem = Problem(
        id="v2",
        source=ProblemSource.SYNTHETIC,
        statement="A V2 generated problem",
        provenance={
            "prefer_generator_solution": True,
            "combo_job_id": "combo-job-1",
        },
    )
    generated = Solution(
        problem_id="v2",
        text="The complete generator proof using both required techniques.",
        source=SolutionSource.MODEL,
        features={"combo_job_id": "combo-job-1"},
    )
    unrelated_model = Solution(
        problem_id="v2",
        text=(
            "A much longer later model solution that was not audited for the "
            "required technique pair."
        ),
        source=SolutionSource.MODEL,
        features={"combo_job_id": "another-job"},
    )
    panel = Solution(
        problem_id="v2",
        text="A correct but technique-agnostic independent proof.",
        source=SolutionSource.SOLVER_PANEL,
    )
    human = Solution(
        problem_id="v2",
        text="A human-reviewed replacement proof.",
        source=SolutionSource.HUMAN,
    )
    official = Solution(
        problem_id="v2",
        text="An official replacement proof.",
        source=SolutionSource.OFFICIAL,
    )

    assert preferred_solution(problem, [panel, unrelated_model, generated]) is generated
    assert preferred_solution(
        problem, [panel, unrelated_model, generated, human]
    ) is human
    assert preferred_solution(
        problem, [panel, unrelated_model, generated, human, official]
    ) is official


def test_export_audit_rejects_duplicates_eval_and_unverified_synthetic(db_url):
    eval_problem = Problem(
        id="eval",
        source=ProblemSource.AIME,
        statement="Eval problem",
        answer="1",
        split=DataSplit.EVAL,
        frozen=True,
    ).refresh_dedup_fields()
    synthetic = Problem(
        id="syn",
        source=ProblemSource.SYNTHETIC,
        statement="Synthetic problem",
        answer="2",
        verified=None,
        review_status=ReviewStatus.PENDING,
    ).refresh_dedup_fields()
    with db.session_scope(db_url) as session:
        session.add_all([eval_problem, synthetic])
    rows = [{"meta": {"id": "eval"}}, {"meta": {"id": "syn"}}, {"meta": {"id": "syn"}}]
    with db.session_scope(db_url) as session:
        report = audit_export_records(session, rows)
    assert not report["ok"]
    assert report["duplicate_ids"] == ["syn"]
    assert report["frozen_ids"] == ["eval"]
    assert report["unverified_synthetic_ids"] == ["syn"]
