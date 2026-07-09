"""Round-trip tests: Pydantic (de)serialization and SQLite persistence."""

from __future__ import annotations

import pytest
from sqlmodel import select

from mathforge import db
from mathforge.llm import LLMClient
from mathforge.schema import (
    DifficultyBand,
    Evaluation,
    Insight,
    LLMCall,
    Problem,
    ProblemSource,
    ProblemTier,
    Solution,
    SolutionSource,
    normalize_statement,
    parse_evaluator,
    statement_hash,
    tier_for_difficulty,
)


@pytest.fixture()
def db_url(tmp_path):
    """An isolated on-disk SQLite database for each test."""
    url = f"sqlite:///{tmp_path / 'test.db'}"
    db.init_db(url)
    return url


# --------------------------------------------------------------------------- #
# Pydantic round-tripping
# --------------------------------------------------------------------------- #
def test_problem_pydantic_roundtrip():
    p = Problem(
        id="AIME_2020_I_10",
        source=ProblemSource.AIME,
        statement="Find the number of ordered pairs...",
        answer="042",
        provenance={"year": 2020, "round": "I", "number": 10},
    ).refresh_dedup_fields()

    dumped = p.model_dump()
    restored = Problem.model_validate(dumped)
    assert restored == p

    # JSON mode preserves enums (as values) and nested dicts.
    json_dumped = p.model_dump(mode="json")
    assert json_dumped["source"] == "aime"
    assert json_dumped["provenance"]["round"] == "I"
    assert Problem.model_validate(json_dumped) == p


def test_solution_pydantic_roundtrip():
    s = Solution(
        problem_id="AIME_2020_I_10",
        text="By symmetry, ...",
        techniques=["symmetry", "generating functions"],
        crux_insight="Recast the count as a coefficient.",
        crux_count=1,
        routine_step_count=4,
        source=SolutionSource.HUMAN,
    )
    restored = Solution.model_validate(s.model_dump())
    assert restored == s
    assert restored.techniques == ["symmetry", "generating functions"]


def test_evaluation_pydantic_roundtrip():
    e = Evaluation(
        problem_id="AIME_2020_I_10",
        difficulty_score=7.5,
        elegance_score=9.0,
        evaluator="judge_v3",
        rationale="Single crux, minimal casework.",
    )
    assert Evaluation.model_validate(e.model_dump()) == e


def test_insight_pydantic_roundtrip():
    ins = Insight(
        id="ins_1",
        text="A telescoping identity hidden behind a substitution.",
        concept_tags=["algebra", "telescoping"],
        difficulty_band=DifficultyBand.AIME_HARD,
        source_problem_ids=["AIME_2020_I_10", "AIME_2019_II_12"],
        embedding=[0.01, -0.2, 0.33],
    )
    restored = Insight.model_validate(ins.model_dump())
    assert restored == ins
    assert restored.embedding == [0.01, -0.2, 0.33]


# --------------------------------------------------------------------------- #
# SQLite persistence round-tripping
# --------------------------------------------------------------------------- #
def test_problem_db_roundtrip(db_url):
    p = Problem(
        id="AIME_2021_II_11",
        source=ProblemSource.AIME,
        statement="Let  S   be the set of...",
        answer="123",
        provenance={"year": 2021, "round": "II", "number": 11},
    ).refresh_dedup_fields()

    with db.session_scope(db_url) as session:
        session.add(p)

    with db.session_scope(db_url) as session:
        got = session.get(Problem, "AIME_2021_II_11")
        assert got is not None
        assert got.source is ProblemSource.AIME
        assert got.answer == "123"
        assert got.provenance == {"year": 2021, "round": "II", "number": 11}
        # dedup fields survive the trip and are normalized.
        assert got.statement_hash == statement_hash(got.statement)
        assert got.normalized_statement == normalize_statement(got.statement)


def test_full_graph_db_roundtrip(db_url):
    problem = Problem(
        id="SYN_0001",
        source=ProblemSource.SYNTHETIC,
        statement="A synthetic gem about invariants.",
        answer="007",
        provenance={"model": "gpt-4o", "seed_insight": "ins_1"},
    ).refresh_dedup_fields()
    solution = Solution(
        problem_id="SYN_0001",
        text="Track the invariant mod 3.",
        techniques=["invariants", "modular arithmetic"],
        crux_insight="The quantity mod 3 never changes.",
        crux_count=1,
        routine_step_count=2,
        source=SolutionSource.MODEL,
    )
    evaluation = Evaluation(
        problem_id="SYN_0001",
        difficulty_score=6.0,
        elegance_score=8.5,
        evaluator="human",
        rationale="One clean invariant.",
    )
    insight = Insight(
        id="ins_1",
        text="Invariants mod small primes.",
        concept_tags=["invariants"],
        difficulty_band=DifficultyBand.AIME_HARD,
        source_problem_ids=["SYN_0001"],
        embedding=None,
    )

    with db.session_scope(db_url) as session:
        session.add_all([problem, solution, evaluation, insight])

    with db.session_scope(db_url) as session:
        got = session.get(Problem, "SYN_0001")
        assert len(got.solutions) == 1
        assert len(got.evaluations) == 1
        assert got.solutions[0].techniques == ["invariants", "modular arithmetic"]
        assert got.solutions[0].crux_count == 1
        assert got.evaluations[0].evaluator == "human"

        stored_insight = session.get(Insight, "ins_1")
        assert stored_insight.concept_tags == ["invariants"]
        assert stored_insight.difficulty_band is DifficultyBand.AIME_HARD
        assert stored_insight.embedding is None
        assert stored_insight.source_problem_ids == ["SYN_0001"]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def test_normalize_and_hash_are_format_invariant():
    a = "Find   the\nNUMBER of pairs."
    b = "find the number of pairs."
    assert normalize_statement(a) == normalize_statement(b)
    assert statement_hash(a) == statement_hash(b)


@pytest.mark.parametrize(
    "difficulty,expected",
    [
        (1.0, ProblemTier.EASY),
        (3.9, ProblemTier.EASY),
        (4.0, ProblemTier.HARD),
        (9.5, ProblemTier.HARD),
        (None, None),
    ],
)
def test_tier_for_difficulty(difficulty, expected):
    assert tier_for_difficulty(difficulty) is expected


def test_problem_tier_db_roundtrip(db_url):
    easy = Problem(
        id="P_EASY",
        source=ProblemSource.OTHER_COMPETITION,
        statement="An easy warmup.",
        difficulty=2.5,
        tier=tier_for_difficulty(2.5),
    )
    hard = Problem(
        id="P_HARD",
        source=ProblemSource.OTHER_COMPETITION,
        statement="A hard gem.",
        difficulty=7.0,
        tier=tier_for_difficulty(7.0),
    )
    with db.session_scope(db_url) as session:
        session.add_all([easy, hard])

    with db.session_scope(db_url) as session:
        got_easy = session.get(Problem, "P_EASY")
        got_hard = session.get(Problem, "P_HARD")
        assert got_easy.tier is ProblemTier.EASY
        assert got_hard.tier is ProblemTier.HARD
        # Filtering by section works for downstream per-tier generation.
        hard_rows = session.exec(
            select(Problem).where(Problem.tier == ProblemTier.HARD)
        ).all()
        assert [p.id for p in hard_rows] == ["P_HARD"]


@pytest.mark.parametrize("good", ["human", "solver_panel", "judge_v1", "JUDGE_V12"])
def test_parse_evaluator_accepts_valid(good):
    parsed = parse_evaluator(good)
    assert parsed == good.strip().lower()


@pytest.mark.parametrize("bad", ["judge", "judge_v", "robot", "judgev1", ""])
def test_parse_evaluator_rejects_invalid(bad):
    with pytest.raises(ValueError):
        parse_evaluator(bad)


# --------------------------------------------------------------------------- #
# LLM logging
# --------------------------------------------------------------------------- #
def test_llm_client_logs_every_call(db_url):
    client = LLMClient(model="echo", db_url=db_url, purpose="generate")
    resp = client.complete("Invent a problem about telescoping.", related_id="ins_1")

    assert resp.text.startswith("[echo]")
    assert resp.total_tokens == resp.prompt_tokens + resp.completion_tokens
    assert resp.cost_usd == 0.0
    assert resp.call_id is not None

    with db.session_scope(db_url) as session:
        calls = session.exec(select(LLMCall)).all()
        assert len(calls) == 1
        logged = calls[0]
        assert logged.model == "echo"
        assert logged.purpose == "generate"
        assert logged.related_id == "ins_1"
        assert logged.total_tokens == resp.total_tokens
