"""Tests for the solver panel: parsing, checking, caching, classification."""

from __future__ import annotations

import pytest
from sqlmodel import select

from mathforge import db
from mathforge.schema import (
    DataSplit,
    Problem,
    ProblemSource,
    SolverAttempt,
    SolverClassification,
    SolverPanel,
    SolverRole,
)
from mathforge.solver import (
    SolverConfig,
    SolverOutput,
    check_answer,
    classify,
    is_possibly_memorized,
    parse_solver_verdict,
    run_solver_panel,
)


@pytest.fixture()
def db_url(tmp_path):
    url = f"sqlite:///{tmp_path / 'test.db'}"
    db.init_db(url)
    return url


def _verdict(ans, recognized=False, ambiguity=False):
    return (
        "reasoning...\n<verdict>\n"
        f"final_answer: {ans}\n"
        "confidence: high\n"
        f"ambiguity_flag: {str(ambiguity).lower()}\n"
        "ambiguity_note: \n"
        f"recognized_as_existing: {str(recognized).lower()}\n"
        "</verdict>"
    )


# --------------------------------------------------------------------------- #
# Parsing + checking + classification
# --------------------------------------------------------------------------- #
def test_parse_verdict():
    v = parse_solver_verdict(_verdict("204", recognized=True, ambiguity=False))
    assert v["final_answer"] == "204"
    assert v["recognized_as_existing"] is True
    assert v["ambiguity_flag"] is False
    none = parse_solver_verdict(_verdict("NONE"))
    assert none["final_answer"] is None


@pytest.mark.parametrize(
    "pred,gold,ok",
    [
        ("204", "204", True),
        ("042", "42", True),  # integer-normalized
        ("$\\boxed{7}$", "7", True),
        ("NONE", "5", False),
        (None, "5", False),
        ("5", None, False),
        ("apple", "apple", True),
    ],
)
def test_check_answer(pred, gold, ok):
    assert check_answer(pred, gold) is ok


def test_classify():
    assert classify(0.75, 1.0) is SolverClassification.EXERCISE
    assert classify(0.0, 0.5) is SolverClassification.TARGET
    assert classify(0.0, 0.0) is SolverClassification.BROKEN
    assert classify(0.25, 0.0) is SolverClassification.INCONCLUSIVE


def test_is_possibly_memorized():
    assert is_possibly_memorized(ProblemSource.AIME) is True
    assert is_possibly_memorized(ProblemSource.OTHER_COMPETITION) is False


# --------------------------------------------------------------------------- #
# Panel runner with a fake, deterministic solver
# --------------------------------------------------------------------------- #
def _seed(session):
    # exercise: both solvers answer correctly
    session.add(Problem(id="ex", source=ProblemSource.OTHER_COMPETITION, statement="easy", answer="1"))
    # target: weak wrong, strong right
    session.add(Problem(id="tg", source=ProblemSource.OTHER_COMPETITION, statement="hard", answer="2"))
    # broken: both wrong
    session.add(Problem(id="bk", source=ProblemSource.OTHER_COMPETITION, statement="broken", answer="3"))
    # famous -> possibly_memorized
    session.add(Problem(id="famous", source=ProblemSource.AIME, statement="aime", answer="4"))


def _fake_weak(problem, i):
    # weak solves only the "exercise" and "famous" problems
    ans = problem.answer if problem.id in ("ex", "famous") else "999"
    return SolverOutput(text=_verdict(ans))


def _fake_strong(problem, i):
    # strong solves everything except "broken"
    ans = problem.answer if problem.id != "bk" else "999"
    return SolverOutput(text=_verdict(ans))


def _run(db_url, overwrite=False):
    return run_solver_panel(
        db_url=db_url,
        weak_config=SolverConfig(SolverRole.WEAK, "weak-test", attempts=8),
        strong_config=SolverConfig(SolverRole.STRONG, "strong-test", attempts=4),
        limit=None,
        split="train",
        weak_solver=_fake_weak,
        strong_solver=_fake_strong,
        overwrite=overwrite,
    )


def test_panel_classifies_and_caches(db_url):
    with db.session_scope(db_url) as session:
        _seed(session)

    r1 = _run(db_url)
    assert r1.problems == 4
    # 4 problems x (8 weak + 4 strong) = 48 attempts on the first pass
    assert r1.attempts_run == 48
    assert r1.attempts_cached == 0
    assert r1.by_classification["exercise"] >= 1
    assert r1.by_classification["target"] == 1
    assert r1.by_classification["broken"] == 1

    with db.session_scope(db_url) as session:
        panels = {p.problem_id: p for p in session.exec(select(SolverPanel)).all()}
        assert panels["ex"].classification is SolverClassification.EXERCISE
        assert panels["tg"].classification is SolverClassification.TARGET
        assert panels["tg"].weak_solve_rate == 0.0
        assert panels["tg"].strong_solve_rate == 1.0
        assert panels["bk"].classification is SolverClassification.BROKEN
        # famous problem is flagged even though solvers succeed
        assert panels["famous"].possibly_memorized is True

        total_attempts = len(session.exec(select(SolverAttempt)).all())
        assert total_attempts == 48

    # Second pass: everything cached, zero new API calls, no duplicate attempts.
    r2 = _run(db_url)
    assert r2.attempts_run == 0
    assert r2.attempts_cached == 48
    with db.session_scope(db_url) as session:
        assert len(session.exec(select(SolverAttempt)).all()) == 48


def test_panel_respects_split_and_missing_answers(db_url):
    with db.session_scope(db_url) as session:
        session.add(Problem(id="tr", source=ProblemSource.OTHER_COMPETITION, statement="s", answer="1"))
        session.add(Problem(id="noans", source=ProblemSource.OTHER_COMPETITION, statement="p", answer=None))
        session.add(
            Problem(id="ev", source=ProblemSource.AIME, statement="e", answer="1", split=DataSplit.EVAL)
        )

    report = _run(db_url)
    # only "tr" qualifies (has answer, train split); "noans" skipped, "ev" is eval
    assert report.problems == 1
    with db.session_scope(db_url) as session:
        panels = session.exec(select(SolverPanel)).all()
        assert [p.problem_id for p in panels] == ["tr"]
