"""Tests for per-solution difficulty feature extraction."""

from __future__ import annotations

import json

import pytest
from sqlmodel import select

from mathforge import db
from mathforge.features import (
    SolutionFeatures,
    extract_features,
    feature_rows,
    heuristic_features,
    parse_feature_response,
    run_extraction,
)
from mathforge.llm import LLMClient, RawCompletion
from mathforge.schema import (
    DataSplit,
    Problem,
    ProblemSource,
    Solution,
    SolutionSource,
)


@pytest.fixture()
def db_url(tmp_path):
    url = f"sqlite:///{tmp_path / 'test.db'}"
    db.init_db(url)
    return url


def _seed(session, pid, difficulty, split=DataSplit.TRAIN, solution_text="Notice that x=1. Therefore done."):
    p = Problem(
        id=pid,
        source=ProblemSource.OTHER_COMPETITION,
        statement=f"Prove something ({pid}).",
        difficulty=difficulty,
        split=split,
    )
    session.add(p)
    session.add(
        Solution(problem_id=pid, text=solution_text, source=SolutionSource.OFFICIAL)
    )


# --------------------------------------------------------------------------- #
# Schema round-trip for the new fields
# --------------------------------------------------------------------------- #
def test_teacher_solution_fields_roundtrip(db_url):
    with db.session_scope(db_url) as session:
        session.add(
            Problem(id="p1", source=ProblemSource.AIME, statement="s")
        )
        session.add(
            Solution(
                problem_id="p1",
                text="sketch",
                techniques=["induction", "invariant"],
                crux_insight="track the invariant",
                crux_count=1,
                routine_step_count=3,
                prerequisite_level=4,
                standard_method_solves=False,
                extractor_model="gpt-4o",
                features={"confidence": 0.8},
                source=SolutionSource.TEACHER,
            )
        )
    with db.session_scope(db_url) as session:
        sol = session.exec(
            select(Solution).where(Solution.source == SolutionSource.TEACHER)
        ).one()
        assert sol.prerequisite_level == 4
        assert sol.standard_method_solves is False
        assert sol.extractor_model == "gpt-4o"
        assert sol.features["confidence"] == 0.8
        assert sol.techniques == ["induction", "invariant"]


# --------------------------------------------------------------------------- #
# Contract parsing + heuristic
# --------------------------------------------------------------------------- #
def test_parse_feature_response_tolerates_fences_and_prose():
    text = (
        "Sure! Here you go:\n```json\n"
        + json.dumps(
            {
                "techniques": ["telescoping"],
                "crux_insight": "collapse the sum",
                "crux_count": 1,
                "routine_step_count": 2,
                "prerequisite_level": 3,
                "standard_method_solves": True,
            }
        )
        + "\n```"
    )
    feats = parse_feature_response(text)
    assert feats.techniques == ["telescoping"]
    assert feats.crux_count == 1


def test_feature_validators_clamp_values():
    feats = SolutionFeatures(crux_count=-5, routine_step_count=-1, prerequisite_level=99)
    assert feats.crux_count == 0
    assert feats.routine_step_count == 0
    assert feats.prerequisite_level == 5


def test_heuristic_features_uses_difficulty():
    easy = heuristic_features("stmt", "Notice the pattern.\nThus done.", 2.0)
    hard = heuristic_features("stmt", "Observe the invariant.", 9.0)
    assert easy.standard_method_solves is True
    assert hard.standard_method_solves is False
    assert 1 <= easy.prerequisite_level <= 5
    assert hard.prerequisite_level > easy.prerequisite_level


# --------------------------------------------------------------------------- #
# LLM extractor with a stub JSON backend (still logs the call)
# --------------------------------------------------------------------------- #
def test_llm_extractor_parses_json_and_logs(db_url):
    payload = {
        "techniques": ["vieta"],
        "crux_insight": "sum/product of roots",
        "crux_count": 2,
        "routine_step_count": 4,
        "prerequisite_level": 3,
        "standard_method_solves": False,
        "difficulty_estimate": 6.5,
    }

    def json_backend(prompt, system=None, **kw):
        return RawCompletion(text=json.dumps(payload), prompt_tokens=10, completion_tokens=20)

    client = LLMClient(model="teacher-test", backend=json_backend, db_url=db_url)
    problem = Problem(id="q1", source=ProblemSource.AIME, statement="find xy", difficulty=6.0)

    feats, extras = extract_features(problem, "ref", extractor="llm", client=client)
    assert feats.techniques == ["vieta"]
    assert feats.crux_count == 2
    assert extras.get("parse_error") is None
    assert extras["llm_call_id"] is not None


def test_llm_extractor_falls_back_on_bad_json(db_url):
    client = LLMClient(model="echo", db_url=db_url)  # echo returns non-JSON
    problem = Problem(id="q2", source=ProblemSource.AIME, statement="x", difficulty=3.0)
    feats, extras = extract_features(problem, "Notice x.", extractor="llm", client=client)
    assert "parse_error" in extras  # fell back to heuristic
    assert isinstance(feats, SolutionFeatures)


# --------------------------------------------------------------------------- #
# Batch runner + predictor bridge
# --------------------------------------------------------------------------- #
def test_run_extraction_respects_split_and_is_idempotent(db_url):
    with db.session_scope(db_url) as session:
        _seed(session, "tr1", 3.0)
        _seed(session, "tr2", 7.0)
        _seed(session, "ev1", 5.0, split=DataSplit.EVAL)

    r1 = run_extraction(extractor="heuristic", limit=None, split="train", db_url=db_url)
    assert r1.extracted == 2  # only train problems

    # Idempotent second pass.
    r2 = run_extraction(extractor="heuristic", limit=None, split="train", db_url=db_url)
    assert r2.extracted == 0
    assert r2.skipped_existing == 2

    with db.session_scope(db_url) as session:
        teacher = session.exec(
            select(Solution).where(Solution.source == SolutionSource.TEACHER)
        ).all()
        assert {s.problem_id for s in teacher} == {"tr1", "tr2"}

    rows = feature_rows(db_url=db_url, split="train", model="heuristic")
    assert len(rows) == 2
    assert {r["difficulty"] for r in rows} == {3.0, 7.0}
    assert all("prerequisite_level" in r for r in rows)
