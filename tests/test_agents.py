"""Tests for the strong-agent QA pass (solve + verify + quality)."""

from __future__ import annotations

import json

import pytest
from sqlmodel import select

from mathforge import db
from mathforge.agents import (
    apply_elegance_ratings,
    apply_verdicts,
    export_candidates,
    export_elegance_sample,
    run_agent_qa,
)
from mathforge.llm import LLMClient, RawCompletion
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


def make_backend(*, solver_seq=("42",), wellposed="accept", difficulty=6.0, elegance=4):
    state = {"i": 0}

    def be(prompt, system=None, **kwargs):
        p = prompt
        if "rules chair" in p:  # wellposedness_v1
            return RawCompletion(text=json.dumps({"issues": [], "verdict": wellposed}))
        if "ELEGANCE" in p:  # elegance_judge_v1
            return RawCompletion(text=json.dumps({"overall": elegance}))
        if "estimating the difficulty" in p:  # difficulty_judge_v1
            return RawCompletion(text=json.dumps({"difficulty": difficulty, "band": "late_aime"}))
        # else: independent solver
        ans = solver_seq[state["i"] % len(solver_seq)]
        state["i"] += 1
        return RawCompletion(
            text=f"<verdict>\nfinal_answer: {ans}\nconfidence: high\n"
            "ambiguity_flag: false\nrecognized_as_existing: false\n</verdict>"
        )

    return be


def _candidate(session, pid="distill-1", answer="42", status=ReviewStatus.PENDING):
    session.add(
        Problem(
            id=pid,
            source=ProblemSource.SYNTHETIC,
            statement=f"candidate {pid}",
            answer=answer,
            split=DataSplit.TRAIN,
            verified=False,
            review_status=status,
            provenance={},
        )
    )


def test_qa_verifies_correct_and_rates(db_url):
    with db.session_scope(db_url) as session:
        _candidate(session, answer="42")
    c = LLMClient(model="strong", backend=make_backend(solver_seq=("42",), difficulty=6.5, elegance=5), db_url=db_url)

    report = run_agent_qa(db_url=db_url, solver=c, judge=c, k=4)
    assert report.processed == 1
    assert report.verified_correct == 1

    with db.session_scope(db_url) as session:
        p = session.get(Problem, "distill-1")
        assert p.verified is True
        assert p.difficulty == 6.5
        qa = p.provenance["agent_qa"]
        assert qa["consensus"] == "42"
        assert qa["agreement"] == 1.0
        assert qa["wellposedness"]["verdict"] == "accept"
        # a strong-agent solution + a judge evaluation were stored
        assert session.exec(
            select(Solution).where(Solution.source == SolutionSource.SOLVER_PANEL)
        ).all()
        assert session.exec(select(Evaluation)).all()


def test_qa_flags_answer_mismatch(db_url):
    with db.session_scope(db_url) as session:
        _candidate(session, answer="10")  # stored answer wrong; agents say 42
    c = LLMClient(model="strong", backend=make_backend(solver_seq=("42",)), db_url=db_url)

    report = run_agent_qa(db_url=db_url, solver=c, judge=c, k=4)
    assert report.answer_mismatch == 1
    assert report.verified_correct == 0
    with db.session_scope(db_url) as session:
        p = session.get(Problem, "distill-1")
        assert p.verified is False
        assert p.provenance["agent_qa"]["consensus"] == "42"


def test_qa_flags_illposed(db_url):
    with db.session_scope(db_url) as session:
        _candidate(session, answer="42")
    c = LLMClient(model="strong", backend=make_backend(solver_seq=("42",), wellposed="reject"), db_url=db_url)

    report = run_agent_qa(db_url=db_url, solver=c, judge=c, k=4)
    assert report.ill_posed == 1


def test_export_and_apply_verdicts(db_url):
    with db.session_scope(db_url) as session:
        _candidate(session, pid="distill-good", answer="0", status=ReviewStatus.PENDING)
        _candidate(session, pid="distill-wrong", answer="99", status=ReviewStatus.PENDING)
        _candidate(session, pid="distill-bad", answer="5", status=ReviewStatus.PENDING)

    rows = export_candidates(db_url=db_url, statuses=("pending",))
    assert {r["id"] for r in rows} == {"distill-good", "distill-wrong", "distill-bad"}

    verdicts = [
        {"id": "distill-good", "correct_answer": "0", "wellposed": "accept",
         "recommendation": "accept", "reason": "ok", "difficulty": 6.0, "elegance": 4},
        {"id": "distill-wrong", "correct_answer": "42", "wellposed": "accept",
         "recommendation": "fix_answer", "reason": "answer was wrong"},
        {"id": "distill-bad", "wellposed": "reject", "recommendation": "reject",
         "reason": "ill-posed"},
    ]
    counts = apply_verdicts(verdicts, db_url=db_url, apply_status=True)
    assert counts["applied"] == 3
    assert counts["corrected"] == 1

    with db.session_scope(db_url) as session:
        good = session.get(Problem, "distill-good")
        wrong = session.get(Problem, "distill-wrong")
        bad = session.get(Problem, "distill-bad")
        assert good.verified is True and good.review_status is ReviewStatus.ACCEPTED
        assert wrong.answer == "42" and wrong.verified is True  # corrected
        assert wrong.provenance["answer_override"]["old"] == "99"
        assert bad.verified is False and bad.review_status is ReviewStatus.REJECTED
        # difficulty/elegance evaluation recorded for the good one
        assert session.exec(
            select(Evaluation).where(Evaluation.problem_id == "distill-good")
        ).all()


def test_elegance_sample_and_apply_enables_ranking(db_url):
    from mathforge.evalharness import rank_problems
    from mathforge.schema import DataSplit

    with db.session_scope(db_url) as session:
        session.add(Problem(id="omni-math-9", source=ProblemSource.OTHER_COMPETITION,
            statement="real problem", answer="7", difficulty=8.0, topic="Algebra",
            split=DataSplit.TRAIN, verified=None, review_status=ReviewStatus.PENDING,
            provenance={}))
        session.add(Solution(problem_id="omni-math-9", text="official", source=SolutionSource.OFFICIAL))

    # export picks it up (unrated so far)
    sample = export_elegance_sample(db_url=db_url, target=10)
    assert any(r["id"] == "omni-math-9" for r in sample)

    # before rating: no elegance -> gated out
    assert not any(s.passes_gate for s in rank_problems(db_url=db_url))

    # apply an elegance-only rating
    n = apply_elegance_ratings([{"id": "omni-math-9", "elegance": 4, "reason": "nice"}], db_url=db_url)
    assert n["applied"] == 1

    ranked = rank_problems(db_url=db_url)
    top = ranked[0]
    assert top.problem_id == "omni-math-9" and top.passes_gate and top.elegance == 4.0
    # a subsequent export skips the now-rated problem
    assert not any(r["id"] == "omni-math-9" for r in export_elegance_sample(db_url=db_url, target=10))


def test_qa_is_idempotent_and_scoped(db_url):
    with db.session_scope(db_url) as session:
        _candidate(session, pid="distill-1", answer="42", status=ReviewStatus.PENDING)
        _candidate(session, pid="distill-2", answer="42", status=ReviewStatus.ACCEPTED)
    c = LLMClient(model="strong", backend=make_backend(solver_seq=("42",)), db_url=db_url)

    r1 = run_agent_qa(db_url=db_url, solver=c, judge=c, k=4, statuses=("pending",))
    assert r1.processed == 1  # only the pending one (accepted is out of scope)

    r2 = run_agent_qa(db_url=db_url, solver=c, judge=c, k=4, statuses=("pending",))
    assert r2.processed == 0 and r2.skipped == 1  # already QA'd
