"""Tests for the quality eval harness (elegance-first lexicographic ranking)."""

from __future__ import annotations

import pytest

from mathforge import db
from mathforge.evalharness import QualityWeights, grade_for, rank_problems, score_problem
from mathforge.schema import (
    DataSplit,
    Evaluation,
    Problem,
    ProblemSource,
    ReviewStatus,
    Solution,
    SolutionSource,
)


@pytest.fixture()
def db_url(tmp_path):
    url = f"sqlite:///{tmp_path / 'test.db'}"
    db.init_db(url)
    return url


def _add(session, pid, elegance, difficulty, crux=1, routine=2, verified=True):
    session.add(Problem(id=pid, source=ProblemSource.SYNTHETIC, statement=f"s {pid}",
        answer="1", difficulty=difficulty, topic="Algebra", split=DataSplit.TRAIN,
        verified=verified, review_status=ReviewStatus.PENDING, provenance={}))
    session.add(Solution(problem_id=pid, text="sol", crux_count=crux,
        routine_step_count=routine, source=SolutionSource.MODEL))
    session.add(Evaluation(problem_id=pid, difficulty_score=difficulty,
        elegance_score=elegance, evaluator="opus-4.8", rationale=""))


def test_grade_tiers():
    assert grade_for(5) == "S"
    assert grade_for(4) == "A"
    assert grade_for(3) == "B"
    assert grade_for(1) == "D"
    assert grade_for(None) == "D"


def test_elegance_dominates_difficulty(db_url):
    with db.session_scope(db_url) as session:
        _add(session, "high-eleg", elegance=4, difficulty=3)   # elegant, easy
        _add(session, "high-diff", elegance=3, difficulty=9)   # hard, less elegant

    ranked = rank_problems(db_url=db_url)
    ids = [s.problem_id for s in ranked]
    # elegance is the primary key, so the more elegant problem ranks first
    assert ids[0] == "high-eleg"


def test_difficulty_breaks_elegance_ties(db_url):
    with db.session_scope(db_url) as session:
        _add(session, "easy", elegance=4, difficulty=3)
        _add(session, "hard", elegance=4, difficulty=8)

    ranked = rank_problems(db_url=db_url)
    assert [s.problem_id for s in ranked][:2] == ["hard", "easy"]


def test_gate_excludes_unverified_and_low_elegance(db_url):
    with db.session_scope(db_url) as session:
        _add(session, "good", elegance=4, difficulty=6, verified=True)
        _add(session, "unverified", elegance=5, difficulty=7, verified=False)
        _add(session, "meh", elegance=2, difficulty=6, verified=True)

    ranked = rank_problems(db_url=db_url, weights=QualityWeights(elegance_floor=3.0))
    keepers = {s.problem_id for s in ranked if s.passes_gate}
    assert keepers == {"good"}  # unverified fails gate; elegance 2 below floor


def test_step_stacking_penalized(db_url):
    with db.session_scope(db_url) as session:
        _add(session, "clean", elegance=4, difficulty=6, crux=1, routine=2)
        _add(session, "stacked", elegance=4, difficulty=6, crux=1, routine=20)
    ranked = rank_problems(db_url=db_url)
    # same elegance+difficulty+crux; fewer routine steps ranks higher and scores more
    assert [s.problem_id for s in ranked][:2] == ["clean", "stacked"]
    by_id = {s.problem_id: s for s in ranked}
    assert by_id["clean"].score > by_id["stacked"].score


def test_trusted_source_passes_gate_without_verified(db_url):
    # An official-contest problem, not run through our verify loop (verified=None),
    # still passes the correctness gate via the trusted-source bypass.
    with db.session_scope(db_url) as session:
        session.add(Problem(id="omni-math-1", source=ProblemSource.OTHER_COMPETITION,
            statement="real contest problem", answer="42", difficulty=8.0, topic="Number Theory",
            split=DataSplit.TRAIN, verified=None, review_status=ReviewStatus.PENDING, provenance={}))
        session.add(Evaluation(problem_id="omni-math-1", elegance_score=4.0,
            evaluator="opus-4.8", rationale=""))

    ranked = rank_problems(db_url=db_url)  # trusted_sources default includes other_competition
    assert ranked and ranked[0].problem_id == "omni-math-1" and ranked[0].passes_gate

    # Turning off the trusted-source bypass gates it out (verified is None).
    from mathforge.evalharness import QualityWeights
    ranked2 = rank_problems(db_url=db_url, weights=QualityWeights(trusted_sources=frozenset()))
    assert not any(s.passes_gate for s in ranked2)


def test_score_weights_elegance_over_difficulty():
    w = QualityWeights()
    elegant = score_problem({"elegance": 5, "difficulty": 1, "crux_count": 1, "routine_step_count": 2}, w)
    hard = score_problem({"elegance": 3, "difficulty": 10, "crux_count": 1, "routine_step_count": 2}, w)
    assert elegant > hard  # a 5-elegance easy problem outscores a 3-elegance hard one
