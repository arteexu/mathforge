"""Tests for the train/eval split, upstream protection, and eval selection."""

from __future__ import annotations

import pytest
from sqlmodel import select

from mathforge import db
from mathforge.holdout import _integrity_hash, select_omni_eval_ids
from mathforge.schema import (
    DataSplit,
    Problem,
    ProblemSource,
    difficulty_band,
)


@pytest.fixture()
def db_url(tmp_path):
    url = f"sqlite:///{tmp_path / 'test.db'}"
    db.init_db(url)
    return url


def test_split_defaults_to_train():
    p = Problem(source=ProblemSource.AIME, statement="x")
    assert p.split is DataSplit.TRAIN
    assert p.frozen is False


@pytest.mark.parametrize(
    "d,expected",
    [(None, None), (1.0, "d1"), (3.4, "d3"), (3.6, "d4"), (9.5, "d10")],
)
def test_difficulty_band(d, expected):
    assert difficulty_band(d) == expected


def test_training_select_excludes_eval_and_frozen(db_url):
    train = Problem(id="t1", source=ProblemSource.OTHER_COMPETITION, statement="a")
    eval_row = Problem(
        id="e1",
        source=ProblemSource.AIME,
        statement="b",
        split=DataSplit.EVAL,
        frozen=True,
    )
    frozen_train = Problem(  # frozen but mislabeled train -> still excluded
        id="f1", source=ProblemSource.OTHER_COMPETITION, statement="c", frozen=True
    )
    with db.session_scope(db_url) as session:
        session.add_all([train, eval_row, frozen_train])

    with db.session_scope(db_url) as session:
        got = session.exec(db.training_problems_select()).all()
        assert [p.id for p in got] == ["t1"]

    counts = db.count_by_split(db_url)
    assert counts["train"] == 2  # t1 + f1 are split=train
    assert counts["eval"] == 1
    assert counts["frozen"] == 2  # e1 + f1


def test_select_omni_eval_ids_is_stratified_and_deterministic(db_url):
    topics = ["Algebra", "Geometry", "Number Theory"]
    rows = []
    n = 0
    for t_i, topic in enumerate(topics):
        for band in range(1, 6):  # difficulty 1..5
            for k in range(4):  # 4 problems per (topic, band)
                rows.append(
                    Problem(
                        id=f"omni-math-{n}",
                        source=ProblemSource.OTHER_COMPETITION,
                        statement=f"stmt {n}",
                        difficulty=float(band),
                        topic=topic,
                    )
                )
                n += 1
    with db.session_scope(db_url) as session:
        session.add_all(rows)

    with db.session_scope(db_url) as session:
        first = select_omni_eval_ids(session, n=30)
        second = select_omni_eval_ids(session, n=30)

    assert first == second  # deterministic
    assert len(first) == 30
    assert len(set(first)) == 30  # no duplicates

    # Round-robin over 15 strata should cover all topics and all bands.
    with db.session_scope(db_url) as session:
        chosen = {
            pid: session.get(Problem, pid) for pid in first
        }
    assert {p.topic for p in chosen.values()} == set(topics)
    assert {difficulty_band(p.difficulty) for p in chosen.values()} == {
        "d1", "d2", "d3", "d4", "d5"
    }


def test_integrity_hash_stable_and_order_independent():
    a = [
        {"id": "p2", "statement_hash": "h2", "answer": "2"},
        {"id": "p1", "statement_hash": "h1", "answer": "1"},
    ]
    b = list(reversed(a))
    assert _integrity_hash(a) == _integrity_hash(b)
    # Changing an answer changes the hash.
    c = [dict(x) for x in a]
    c[0]["answer"] = "999"
    assert _integrity_hash(c) != _integrity_hash(a)
