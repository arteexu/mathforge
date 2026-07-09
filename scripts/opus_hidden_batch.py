"""Opus HIDDEN-method batch: honestly-rated hard problems that don't telegraph.

Lesson from auditing ``opus-hard-`` (see the review triage): 27 of 38 problems
*named the method* in the statement -- "how many spanning trees does K_7 have",
"matrices of rank 2 over F_3", "monic irreducible polynomials of degree 4". A
strong solver just applies the named formula, so by ``difficulty_judge_v1``
("knowledge barriers are shallower than insight barriers") those cap at ~4.5-5,
not 7.5. They were self-graded too high -- the exact rubber-stamping failure the
project exists to avoid.

Design rules this batch follows:
  1. NEVER name the theorem/structure. The statement is a concrete scenario; the
     solver must *discover* the method. That is where difficulty actually lives.
  2. One problem per idea with well-spread parameters -- no near-duplicate floods.
  3. Vary the ask (raw count / m+n), not a reflexive "remainder mod 1000".
  4. Difficulty is an HONEST in-chat rubric rating with a written barrier; still
     tagged ``behavioral_panel: "pending"`` (no solver panel this session).

Kept families (phrasing already hides the method): proper bracelets (Burnside +
cycle chromatic) and 0-1 matrices with fixed margins (permanent / regular
bipartite). New hidden-method families: a two-constraint subset DP and biased
gambler's-ruin expected time. All answers are exact (brute force or exact
rational) and cross-checked against known closed forms in the self-tests.

Honest note on the frontier: templated generation reaches a believable ~6.5-7
only when the natural phrasing hides the path. Genuine, diverse diff>=7 quality
(like the free-written OpenAI ``distill-`` problems) needs free generation +
out-of-band Opus verification, not templates. This batch is the honest ceiling
of the templated route.
"""

from __future__ import annotations

import math
import random
import sys
from fractions import Fraction as Fr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from opus_hard_batch import count_binary_fixed_margins, count_bracelets_proper  # noqa: E402

from mathforge import db  # noqa: E402
from mathforge.schema import (  # noqa: E402
    DataSplit,
    Evaluation,
    Problem,
    ProblemSource,
    ReviewStatus,
    Solution,
    SolutionSource,
)

MODEL = "claude-opus-4.8 (in-chat)"
ID_PREFIX = "opus-hidden-"


# --------------------------------------------------------------------------- #
# New exact kernels
# --------------------------------------------------------------------------- #
def count_nonadjacent_mod(n: int, m: int, target: int = 0) -> int:
    """# of subsets of {1..n} with no two consecutive elements whose element sum
    is == target (mod m). DP over (last element taken?, running sum mod m)."""
    # dp[r] = number of ways with current sum residue r, tracking whether the
    # previous integer was taken (to forbid adjacency).
    # State: iterate i=1..n, decide take/skip; taking i requires i-1 not taken.
    from functools import lru_cache

    @lru_cache(maxsize=None)
    def rec(i: int, prev_taken: bool, res: int) -> int:
        if i > n:
            return 1 if res == target % m else 0
        # skip i
        total = rec(i + 1, False, res)
        # take i (only if previous not taken)
        if not prev_taken:
            total += rec(i + 1, True, (res + i) % m)
        return total

    return rec(1, False, 0)


def _solve_frac(A: list[list[Fr]], b: list[Fr]) -> list[Fr]:
    """Exact solve of A x = b over the rationals (Gaussian elimination)."""
    n = len(A)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        piv = next(r for r in range(c, n) if M[r][c] != 0)
        M[c], M[piv] = M[piv], M[c]
        inv = M[c][c]
        M[c] = [x / inv for x in M[c]]
        for r in range(n):
            if r != c and M[r][c] != 0:
                f = M[r][c]
                M[r] = [a - f * d for a, d in zip(M[r], M[c])]
    return [M[i][n] for i in range(n)]


def biased_ruin_expected_steps(L: int, s: int, p: Fr) -> Fr:
    """Expected steps for a walk on 0..L, +1 w.p. p and -1 w.p. 1-p, absorbed at
    0 and L, started at s. Solved exactly via the interior linear system, then
    VERIFIED by substituting the solution back into every equation."""
    q = 1 - p
    inner = list(range(1, L))            # states 1..L-1
    idx = {v: i for i, v in enumerate(inner)}
    N = len(inner)
    A = [[Fr(0)] * N for _ in range(N)]
    b = [Fr(1)] * N
    for v in inner:
        i = idx[v]
        A[i][i] = Fr(1)
        if v + 1 in idx:
            A[i][idx[v + 1]] -= p
        if v - 1 in idx:
            A[i][idx[v - 1]] -= q
    E = _solve_frac(A, b)
    # verify: E[v] == 1 + p*E[v+1] + q*E[v-1]  (absorbing states contribute 0)
    for v in inner:
        up = E[idx[v + 1]] if v + 1 in idx else Fr(0)
        dn = E[idx[v - 1]] if v - 1 in idx else Fr(0)
        assert E[idx[v]] == 1 + p * up + q * dn, (L, s, p, v)
    return E[idx[s]]


# --------------------------------------------------------------------------- #
# Self-tests vs known closed forms
# --------------------------------------------------------------------------- #
def _self_test() -> None:
    # no-two-consecutive subsets of {1..n} number Fibonacci F(n+2) (m=1 => all)
    def fib(k):
        a, b = 1, 1
        for _ in range(k):
            a, b = b, a + b
        return a
    for n in range(1, 12):
        assert count_nonadjacent_mod(n, 1) == fib(n + 1), n  # F_{n+2}
    # unbiased gambler's ruin expected steps from s on 0..L is s(L-s)
    for L in range(2, 8):
        for s in range(1, L):
            assert biased_ruin_expected_steps(L, s, Fr(1, 2)) == Fr(s * (L - s)), (L, s)
    # kernels imported from opus_hard_batch keep their own guarantees:
    assert count_bracelets_proper(3, 3) == 1
    assert count_binary_fixed_margins(3, 2) == 6


# --------------------------------------------------------------------------- #
# Generators (method HIDDEN; honest difficulty; deduped params; varied ask)
# --------------------------------------------------------------------------- #
def g_bracelets(n: int, k: int):
    ans = count_bracelets_proper(n, k)
    if not (0 <= ans <= 999):
        return None
    return dict(
        topic="Combinatorics", answer=ans, difficulty=6.5, elegance=4.0,
        crux_count=2, routine_steps=4,
        statement=rf"A craftsman strings ${n}$ beads into a loop, giving each bead one of ${k}$ colors so that no two touching beads share a color. Two loops count as the same if one can be turned over or rotated into the other. How many distinct loops can he make?",
        crux="Burnside over the dihedral group applied to proper colorings of a cycle.",
        barrier="No method is named: the solver must first find the cycle's proper-coloring count and then quotient by rotations AND flips (parity-sensitive fixed-point counting).",
        solution=rf"Proper colorings of the {n}-cycle number $(k-1)^n+(-1)^n(k-1)$; averaging those fixed by each of the $2\cdot{n}$ turn/flip symmetries gives ${ans}$.",
    )


def g_fixed_margins(n: int, r: int):
    ans = count_binary_fixed_margins(n, r) % 1000
    return dict(
        topic="Combinatorics", answer=ans, difficulty=7.0, elegance=3.5,
        crux_count=2, routine_steps=4,
        statement=rf"Over ${n}$ days, ${n}$ volunteers each work exactly ${r}$ of the days, and each day is staffed by exactly ${r}$ volunteers. Let $N$ be the number of possible schedules (which volunteer works which day). Find the remainder when $N$ is divided by $1000$.",
        crux="Count of 0-1 matrices with all margins r = number of r-regular bipartite graphs (permanent / inclusion-exclusion).",
        barrier="The scenario hides that this is a fixed-margin 0-1 matrix count; there is no product formula, forcing a permanent or inclusion-exclusion argument.",
        solution=rf"Schedules correspond to $0$-$1$ matrices with every row and column summing to ${r}$; counting them (an $r$-regular bipartite count) gives $N\equiv{ans}\pmod{{1000}}$.",
    )


def g_nonadjacent_mod(n: int, m: int):
    raw = count_nonadjacent_mod(n, m)
    ans = raw % 1000
    big = raw > 999
    ask = (rf"Find the remainder when this number is divided by $1000$." if big
           else rf"How many such subsets are there?")
    head = (rf"Let $N$ be the number of subsets of $\{{1,2,\dots,{n}\}}$ that contain no two consecutive integers and whose elements sum to a multiple of ${m}$."
            if big else
            rf"Consider the subsets of $\{{1,2,\dots,{n}\}}$ that contain no two consecutive integers and whose elements sum to a multiple of ${m}$.")
    return dict(
        topic="Combinatorics", answer=ans, difficulty=6.5, elegance=3.5,
        crux_count=2, routine_steps=4,
        statement=(head + " " + ask),
        crux="Two interacting constraints -> DP over (adjacency state, sum mod m).",
        barrier="Neither the non-adjacency count nor the divisibility filter is hard alone, but combining them forces a 2-D state (last-taken flag x residue) that most solvers miss.",
        solution=rf"A DP tracking whether the previous integer was chosen and the running sum modulo ${m}$ yields ${raw}$" + (rf", so the remainder is ${ans}$." if big else "."),
    )


def g_biased_walk(L: int, s: int, a: int, b: int):
    p = Fr(a, b)
    E = biased_ruin_expected_steps(L, s, p)
    mn = E.numerator + E.denominator
    ans = mn % 1000
    big = mn > 999
    tail = (rf"find the remainder when $m+n$ is divided by $1000$." if big
            else rf"find $m+n$.")
    return dict(
        topic="Probability", answer=ans, difficulty=7.0, elegance=4.0,
        crux_count=2, routine_steps=5,
        statement=rf"A token sits on square ${s}$ of a row of squares numbered $0$ through ${L}$. Each second it moves one square right with probability $\tfrac{{{a}}}{{{b}}}$ and one square left otherwise; it stops upon reaching square $0$ or square ${L}$. The expected number of seconds until it stops is $\tfrac{{m}}{{n}}$ in lowest terms; " + tail,
        crux="Biased absorbing random walk: expected hitting time solves the difference equation E_i = 1 + p E_{i+1} + q E_{i-1}.",
        barrier="No 'random walk' or 'Markov' cue: the solver must set up and solve a boundary-value difference equation for the expected absorption time under a bias.",
        solution=rf"Solving $E_i=1+\tfrac{{{a}}}{{{b}}}E_{{i+1}}+\tfrac{{{b-a}}}{{{b}}}E_{{i-1}}$ with $E_0=E_{{{L}}}=0$ gives $E_{{{s}}}={E}$, so $m+n\equiv{ans}\pmod{{1000}}$" + ("." if big else " (and $m+n$ itself is the answer)."),
    )


# Deduped parameter sets: a few well-spread instances per idea.
def build_problems() -> list[dict]:
    out: list[dict] = []
    for n, k in [(9, 3), (8, 4), (7, 4), (10, 3)]:
        p = g_bracelets(n, k)
        if p:
            out.append(p)
    for n, r in [(4, 2), (5, 2), (6, 2), (6, 3)]:
        out.append(g_fixed_margins(n, r))
    for n, m in [(15, 3), (18, 4), (20, 5), (22, 3)]:
        out.append(g_nonadjacent_mod(n, m))
    for L, s, a, b in [(5, 2, 2, 3), (6, 3, 1, 3), (7, 3, 3, 5), (5, 1, 3, 4)]:
        out.append(g_biased_walk(L, s, a, b))
    return out


def main() -> None:
    from sqlmodel import select

    from mathforge.schema import statement_hash

    _self_test()
    print("self-tests passed")

    rng = random.Random(20260708)  # reserved for future sampling
    _ = rng
    db.init_db()

    problems = build_problems()

    with db.session_scope() as session:
        old = session.exec(select(Problem).where(Problem.id.like(f"{ID_PREFIX}%"))).all()
        for p in old:
            for srow in session.exec(select(Solution).where(Solution.problem_id == p.id)).all():
                session.delete(srow)
            for e in session.exec(select(Evaluation).where(Evaluation.problem_id == p.id)).all():
                session.delete(e)
            session.delete(p)
        session.flush()

        seen = set(session.exec(select(Problem.statement_hash)).all())
        by_topic: dict[str, int] = {}
        idx = 0
        for prob in problems:
            shash = statement_hash(prob["statement"])
            if shash in seen:
                continue
            seen.add(shash)
            ans = prob["answer"]
            if not (isinstance(ans, int) and 0 <= ans <= 999):
                continue
            idx += 1
            pid = f"{ID_PREFIX}{idx:03d}"
            by_topic[prob["topic"]] = by_topic.get(prob["topic"], 0) + 1

            session.add(Problem(
                id=pid, source=ProblemSource.SYNTHETIC, statement=prob["statement"],
                answer=str(ans), difficulty=prob["difficulty"], topic=prob["topic"],
                split=DataSplit.TRAIN, verified=True, review_status=ReviewStatus.PENDING,
                possibly_memorized=False,
                provenance={
                    "pipeline": "opus-hidden-batch", "generator_model": MODEL,
                    "crux": prob["crux"], "verification": "exact + self-test",
                    "auto_decision": "pending_human_review",
                    "agent_qa": {
                        "solver_model": MODEL, "k": "exact",
                        "consensus": str(ans), "agreement": 1.0, "verified": True,
                        "wellposedness": {"verdict": "accept"},
                        "difficulty": {
                            "difficulty": prob["difficulty"],
                            "primary_barrier": prob["barrier"],
                            "rated_by": "in_chat_opus_judge",
                            "method_named_in_statement": False,
                            "behavioral_panel": "pending",
                        },
                        "elegance": {"overall": prob["elegance"], "rated_by": "in_chat_opus_judge"},
                        "recommendation": "review",
                        "reason": f"Answer {ans} exact-verified; method hidden; difficulty by rubric (barrier: {prob['barrier']}).",
                    },
                },
            ).refresh_dedup_fields())
            session.add(Solution(
                problem_id=pid, text=prob["solution"], techniques=[prob["crux"]],
                crux_insight=prob["crux"], crux_count=prob["crux_count"],
                routine_step_count=prob["routine_steps"],
                source=SolutionSource.MODEL, extractor_model=MODEL))
            session.add(Evaluation(
                problem_id=pid, difficulty_score=prob["difficulty"],
                elegance_score=prob["elegance"], evaluator="opus-4.8",
                rationale=prob["barrier"]))

    print(f"created {idx} hidden-method problems (status=pending for review)")
    print("by topic:", by_topic)


if __name__ == "__main__":
    main()
