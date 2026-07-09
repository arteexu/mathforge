"""Tests for the human labeling tool's logic (selection, parsing, recording)."""

from __future__ import annotations

import pytest
from sqlmodel import select

from mathforge import db
from mathforge.labeling import (
    HUMAN_EVALUATOR,
    already_labeled_ids,
    parse_difficulty,
    parse_elegance,
    record_human_label,
    select_label_batch,
    visible_solutions,
)
from mathforge.schema import (
    DataSplit,
    Evaluation,
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


def _seed(session, n_per_stratum=3):
    topics = ["Algebra", "Geometry", "Number Theory"]
    idx = 0
    for topic in topics:
        for band in (2, 5, 8):
            for _ in range(n_per_stratum):
                session.add(
                    Problem(
                        id=f"omni-math-{idx}",
                        source=ProblemSource.OTHER_COMPETITION,
                        statement=f"stmt {idx}",
                        difficulty=float(band),
                        topic=topic,
                    )
                )
                idx += 1
    return idx


# --------------------------------------------------------------------------- #
# Input parsing
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw,expected", [("5", 5.0), ("6.5", 6.5), ("10", 10.0), ("1", 1.0)])
def test_parse_difficulty_ok(raw, expected):
    assert parse_difficulty(raw) == expected


@pytest.mark.parametrize("raw", ["0", "11", "-3", "abc", ""])
def test_parse_difficulty_bad(raw):
    with pytest.raises(ValueError):
        parse_difficulty(raw)


@pytest.mark.parametrize(
    "raw,expected", [("0", 0.0), ("2", 2.0), ("3", 3.0), ("5", 5.0), ("4.5", 4.5)]
)
def test_parse_elegance_ok(raw, expected):
    assert parse_elegance(raw) == expected


@pytest.mark.parametrize("raw", ["-1", "5.1", "6", "x", ""])
def test_parse_elegance_bad(raw):
    with pytest.raises(ValueError):
        parse_elegance(raw)


# --------------------------------------------------------------------------- #
# Selection: stratified, excludes labeled, deterministic under seed
# --------------------------------------------------------------------------- #
def test_select_batch_is_stratified_and_seeded(db_url):
    with db.session_scope(db_url) as session:
        _seed(session)

    with db.session_scope(db_url) as session:
        first = select_label_batch(session, count=9, split="train", seed=42)
        second = select_label_batch(session, count=9, split="train", seed=42)

    assert first == second  # reproducible under a fixed seed
    assert len(first) == len(set(first)) == 9

    # 9 picks over 9 strata (3 topics x 3 bands) => every stratum covered once.
    with db.session_scope(db_url) as session:
        chosen = [session.get(Problem, pid) for pid in first]
    assert {p.topic for p in chosen} == {"Algebra", "Geometry", "Number Theory"}
    assert {int(p.difficulty) for p in chosen} == {2, 5, 8}


def test_select_batch_excludes_already_labeled(db_url):
    with db.session_scope(db_url) as session:
        _seed(session)
        # Label a handful.
        for pid in ("omni-math-0", "omni-math-1", "omni-math-2"):
            record_human_label(session, pid, 5.0, 1.0)

    with db.session_scope(db_url) as session:
        assert already_labeled_ids(session) == {"omni-math-0", "omni-math-1", "omni-math-2"}
        batch = select_label_batch(session, count=100, split="train", seed=1)
        assert not ({"omni-math-0", "omni-math-1", "omni-math-2"} & set(batch))


def test_select_batch_respects_split(db_url):
    with db.session_scope(db_url) as session:
        session.add(Problem(id="omni-math-0", source=ProblemSource.OTHER_COMPETITION,
                            statement="t", difficulty=5.0, topic="Algebra"))
        session.add(Problem(id="aime-1", source=ProblemSource.AIME, statement="e",
                            difficulty=None, topic=None, split=DataSplit.EVAL))
    with db.session_scope(db_url) as session:
        assert select_label_batch(session, count=10, split="train") == ["omni-math-0"]
        # eval problem has no difficulty/topic -> not stratifiable -> excluded
        assert select_label_batch(session, count=10, split="eval") == []


# --------------------------------------------------------------------------- #
# Visible solutions hide machine analysis; recording writes a human Evaluation
# --------------------------------------------------------------------------- #
def test_visible_solutions_hide_teacher_rows(db_url):
    with db.session_scope(db_url) as session:
        session.add(Problem(id="p1", source=ProblemSource.AIME, statement="s"))
        session.add(Solution(problem_id="p1", text="official worked soln", source=SolutionSource.OFFICIAL))
        session.add(Solution(problem_id="p1", text="teacher analysis (has difficulty_estimate)",
                            source=SolutionSource.TEACHER))
    with db.session_scope(db_url) as session:
        vis = visible_solutions(session, "p1")
        assert vis == ["official worked soln"]


def test_record_human_label_writes_evaluation(db_url):
    with db.session_scope(db_url) as session:
        session.add(Problem(id="p1", source=ProblemSource.AIME, statement="s"))
    with db.session_scope(db_url) as session:
        record_human_label(session, "p1", 6.5, 2.0, "clean invariant")
    with db.session_scope(db_url) as session:
        ev = session.exec(select(Evaluation)).one()
        assert ev.evaluator == HUMAN_EVALUATOR
        assert ev.difficulty_score == 6.5
        assert ev.elegance_score == 2.0
        assert ev.rationale == "clean invariant"
