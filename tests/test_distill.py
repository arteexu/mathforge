"""Tests for the distill pipeline using fake, deterministic backends."""

from __future__ import annotations

import json

import pytest
from sqlmodel import select

from mathforge import db
from mathforge.distill import (
    _extract_json,
    generate_problem,
    is_banned_template,
    repair_problem,
    run_distill,
    verify_answer,
)
from mathforge.llm import LLMClient, RawCompletion
from mathforge.schema import (
    Evaluation,
    Problem,
    ProblemSource,
    ReviewStatus,
    Solution,
)


@pytest.fixture()
def db_url(tmp_path):
    url = f"sqlite:///{tmp_path / 'test.db'}"
    db.init_db(url)
    return url


def make_fake_backend(
    *,
    gen_answer="10",
    gen_statement="A generated problem about symmetry.",
    solver_seq=("42",),
    repair_statement="A repaired problem about symmetry.",
    difficulty=6.0,
    elegance=4,
):
    """Route by prompt content to emulate generator/solver/repair/judges."""
    state = {"solve": 0}

    def be(prompt, system=None, **kwargs):
        p = prompt
        if "composer" in p:  # distill_generation_v1
            txt = (
                f"<statement>{gen_statement}</statement>\n"
                f"<answer>{gen_answer}</answer>\n<topic>Algebra</topic>\n"
                f"<difficulty>6.0</difficulty>\n<crux>the key idea</crux>\n"
                f"<solution>work ... the answer is {gen_answer}</solution>"
            )
        elif "CORRECTED" in p:  # problem_repair_v1
            txt = f"<statement>{repair_statement}</statement>\n<answer>0</answer>"
        elif "ELEGANCE" in p:  # elegance_judge_v1
            txt = json.dumps({"overall": elegance, "crux_economy": 2})
        elif "estimating the difficulty" in p:  # difficulty_judge_v1
            txt = json.dumps({"difficulty": difficulty, "band": "late_aime"})
        else:  # independent_solver_v1
            i = state["solve"]
            state["solve"] += 1
            ans = solver_seq[i % len(solver_seq)]
            txt = (
                "reasoning...\n<verdict>\n"
                f"final_answer: {ans}\nconfidence: high\n"
                "ambiguity_flag: false\nrecognized_as_existing: false\n</verdict>"
            )
        return RawCompletion(text=txt, prompt_tokens=5, completion_tokens=5)

    return be


def _client(be, db_url, model="fake"):
    return LLMClient(model=model, backend=be, db_url=db_url)


# --------------------------------------------------------------------------- #
# Units
# --------------------------------------------------------------------------- #
def test_extract_json_after_prose_and_math_braces():
    text = r"""The set is \{x \in \mathbb{R}: x^{2}=1\}, so the exponent is fixed.
Final assessment:
{"difficulty": 6.5, "band": "late_aime"}"""

    assert _extract_json(text) == {"difficulty": 6.5, "band": "late_aime"}


def test_extract_json_from_fenced_block():
    text = '```json\n{"overall": 4, "crux_economy": 2}\n```'

    assert _extract_json(text) == {"overall": 4, "crux_economy": 2}


def test_extract_json_from_plain_object():
    assert _extract_json('{"outer": {"inner": 1}, "ok": true}') == {
        "outer": {"inner": 1},
        "ok": True,
    }


def test_extract_json_uses_final_complete_object():
    text = 'For example {"verdict": "repair"}. Final: {"verdict": "accept"}'

    assert _extract_json(text) == {"verdict": "accept"}


def test_generate_problem_parses(db_url):
    c = _client(make_fake_backend(gen_answer="42"), db_url)
    g = generate_problem(c)
    assert g["ok"] is True
    assert g["answer"] == "42"
    assert g["topic"] == "Algebra"
    assert g["difficulty"] == 6.0


def test_verify_answer_majority(db_url):
    c = _client(make_fake_backend(solver_seq=("42", "42", "7")), db_url)
    vr = verify_answer(c, "stmt", k=3)
    assert vr["consensus"] == "42"  # 2/3 majority

    c2 = _client(make_fake_backend(solver_seq=("1", "2", "3")), db_url)
    vr2 = verify_answer(c2, "stmt", k=3)
    assert vr2["consensus"] is None  # no majority


# --------------------------------------------------------------------------- #
# End-to-end
# --------------------------------------------------------------------------- #
def test_distill_direct_verify_and_store(db_url):
    # generator says 42, solver agrees 42 -> verified directly
    be = make_fake_backend(gen_answer="42", solver_seq=("42",), difficulty=6.5, elegance=5)
    c = _client(be, db_url, model="frontier-x")
    report = run_distill(n=1, generator=c, solver=c, judge=c, k=3, db_url=db_url)

    assert report.verified_direct == 1
    assert report.stored == 1
    assert report.unverified == 0

    with db.session_scope(db_url) as session:
        p = session.exec(select(Problem).where(Problem.source == ProblemSource.SYNTHETIC)).one()
        assert p.verified is True
        assert p.review_status is ReviewStatus.PENDING
        assert p.answer == "42"
        assert p.difficulty == 6.5
        ev = session.exec(select(Evaluation).where(Evaluation.problem_id == p.id)).one()
        assert ev.elegance_score == 5
        assert ev.evaluator == "judge_v1"
        assert session.exec(select(Solution).where(Solution.problem_id == p.id)).one()


def test_distill_repairs_mismatch(db_url):
    # generator says 10, but solver consistently says 42 -> repair -> verified
    be = make_fake_backend(gen_answer="10", solver_seq=("42",))
    c = _client(be, db_url)
    report = run_distill(n=1, generator=c, solver=c, judge=c, k=3, db_url=db_url)

    assert report.verified_direct == 0
    assert report.repaired == 1
    assert report.stored == 1
    with db.session_scope(db_url) as session:
        p = session.exec(select(Problem)).one()
        assert p.answer == "42"  # answer now matches the solver consensus
        assert p.provenance["repaired"] is True


@pytest.mark.parametrize(
    "statement,banned",
    [
        ("Let P(x)=x^4+ax^3+bx^2+cx+1 with P(1)=16, P(2)=49. Find P(3).", True),
        ("Let f(x) be a polynomial with f(2)=45. Compute f(5).", True),
        ("How many ordered triples (a,b,c) of positive integers satisfy a+b+c=12?", False),
        ("Find the number of subsets of {1,...,10} whose sum is divisible by 3.", False),
    ],
)
def test_is_banned_template(statement, banned):
    assert is_banned_template(statement) is banned


def test_distill_skips_banned_polynomial_template(db_url):
    poly = "Let P(x)=x^4+ax^3+bx^2+cx+1 with P(1)=16 and P(2)=49. Find P(3)."
    be = make_fake_backend(gen_statement=poly, gen_answer="42", solver_seq=("42",))
    c = _client(be, db_url)
    report = run_distill(n=1, generator=c, solver=c, judge=c, k=3, db_url=db_url)

    assert report.template_skipped == 1
    assert report.stored == 0
    with db.session_scope(db_url) as session:
        assert session.exec(select(Problem)).all() == []


def test_distill_generation_only_stores_raw(db_url):
    be = make_fake_backend(gen_statement="A fresh combinatorics problem.", gen_answer="42")
    c = _client(be, db_url)
    report = run_distill(n=1, generator=c, solver=c, judge=c, verify=False, db_url=db_url)

    assert report.raw_stored == 1
    assert report.verified_direct == 0 and report.unverified == 0
    with db.session_scope(db_url) as session:
        p = session.exec(select(Problem)).one()
        assert p.verified is None
        assert p.provenance["mode"] == "generation_only"
        assert p.answer == "42"


def test_distill_keeps_unverifiable_for_review(db_url):
    # solvers never agree -> no consensus -> kept as UNVERIFIED (not discarded)
    be = make_fake_backend(gen_answer="10", solver_seq=("1", "2", "3"))
    c = _client(be, db_url)
    report = run_distill(n=1, generator=c, solver=c, judge=c, k=3, db_url=db_url)

    assert report.unverified == 1
    assert report.stored == 1
    with db.session_scope(db_url) as session:
        p = session.exec(select(Problem)).one()
        assert p.verified is False
        assert p.review_status is ReviewStatus.PENDING
        assert p.answer == "10"  # the generated (unverified) answer is preserved
        # unverified problems are not judged, so no Evaluation row
        assert session.exec(select(Evaluation).where(Evaluation.problem_id == p.id)).all() == []
        assert p.provenance["solver_answers"]  # solver attempts recorded for review
