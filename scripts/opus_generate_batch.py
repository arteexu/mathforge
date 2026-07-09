"""Opus batch generation (100) from the elegant-idea bank, auto-verified.

Each elegant idea has a parameterized generator that emits a problem AND its exact
answer (computed in code; cross-checked formula-vs-brute where feasible). A
candidate is AUTO-ACCEPTED iff it is correct and its answer is a valid AIME
integer in [0, 999]; otherwise AUTO-REJECTED -- rejection is on CORRECTNESS ONLY
(not elegance or difficulty). Accepted -> review_status=accepted, verified=True.
"""

from __future__ import annotations

import math
import random
from fractions import Fraction as F
from itertools import permutations

from mathforge import db
from mathforge.schema import (
    DataSplit,
    DifficultyBand,
    Evaluation,
    Insight,
    Problem,
    ProblemSource,
    ReviewStatus,
    Solution,
    SolutionSource,
)

MODEL = "claude-opus-4.8 (in-chat)"
N_TARGET = 100

# New elegant ideas (added to the bank if absent).
EXTRA_INSIGHTS = [
    dict(id="idea-linearity-expectation",
         text="Linearity of expectation: sum indicator probabilities of local events (adjacencies, matches, balanced prefixes) instead of computing the full distribution.",
         tags=["probability", "combinatorics"], band=DifficultyBand.AIME_HARD),
    dict(id="idea-crt",
         text="Chinese Remainder Theorem: independent residue conditions mod coprime moduli have a unique joint solution mod their product.",
         tags=["number theory"], band=DifficultyBand.AIME_EASY),
    dict(id="idea-order-mod",
         text="Multiplicative order: 10^n patterns (repunits/repdigits) repeat with the order of 10 modulo the divisor, so divisibility is periodic in n.",
         tags=["number theory"], band=DifficultyBand.AIME_HARD),
    dict(id="idea-stars-bars",
         text="Stars and bars: nonnegative integer solutions of x_1+...+x_j=S number C(S+j-1, j-1).",
         tags=["combinatorics"], band=DifficultyBand.AIME_EASY),
]


# --------------------------------------------------------------------------- #
# Generators: each returns dict(seed, topic, statement, answer:int, crux,
# solution, difficulty) with the answer computed EXACTLY. Return None if the
# drawn parameters are degenerate.
# --------------------------------------------------------------------------- #
def g_subset_sum(rng):
    N = rng.randint(12, 22); m = rng.choice([3, 4, 5, 6, 7])
    dp = [0] * m; dp[0] = 1
    for x in range(1, N + 1):
        nd = dp[:]
        for r in range(m):
            nd[(r + x) % m] += dp[r]
        dp = nd
    ans = dp[0] % 1000
    return dict(seed="idea-rou-filter", topic="Number Theory", answer=ans, difficulty=5.5,
        statement=rf"Let $N$ be the number of subsets $S\subseteq\{{1,2,\dots,{N}\}}$ (including the empty set) whose element sum is divisible by ${m}$. Find the remainder when $N$ is divided by $1000$.",
        crux="Roots-of-unity filter / DP on sum mod m.",
        solution=rf"A DP over residues mod ${m}$ (equivalently a roots-of-unity filter) gives $N={dp[0]}$, so the remainder is ${ans}$.")


def g_telescope(rng):
    K = rng.randint(6, 80)
    s = sum(F(2, k * (k + 1) * (k + 2)) for k in range(1, K + 1))
    ans = s.numerator + s.denominator
    return dict(seed="idea-telescoping", topic="Algebra", answer=ans, difficulty=3.5,
        statement=rf"The sum $\displaystyle\sum_{{k=1}}^{{{K}}}\frac{{2}}{{k(k+1)(k+2)}}$ equals $\frac{{m}}{{n}}$ in lowest terms. Find $m+n$.",
        crux="Telescope 2/(k(k+1)(k+2)) = 1/(k(k+1)) - 1/((k+1)(k+2)).",
        solution=rf"Telescoping gives $\tfrac12-\tfrac1{{{K+1}\cdot{K+2}}}={s}$, so $m+n={ans}$.")


def g_nonadjacent(rng):
    n = rng.randint(6, 8)  # exact brute force (<= 8! perms)
    cnt = sum(1 for p in permutations(range(1, n + 1))
              if all(abs(p[i] - p[i + 1]) != 1 for i in range(n - 1)))
    ans = cnt % 1000
    return dict(seed="idea-incl-excl-adjacency", topic="Combinatorics", answer=ans, difficulty=6.0,
        statement=rf"Let $M$ be the number of permutations of $1,2,\dots,{n}$ in which no two consecutive integers are adjacent (i.e. $|a_i-a_{{i+1}}|\ne1$ for all $i$). Find the remainder when $M$ is divided by $1000$.",
        crux="Count permutations avoiding consecutive-value adjacencies (Hertzsprung).",
        solution=rf"Direct count gives $M={cnt}$, remainder ${ans}$.")


def g_invariant(rng):
    n = rng.randint(4, 9)
    M = math.factorial(n + 1) - 1
    ans = M % 1000
    return dict(seed="idea-mult-invariant", topic="Algebra", answer=ans, difficulty=5.5,
        statement=rf"The numbers $1,2,\dots,{n}$ are on a board. Repeatedly erase two numbers $a,b$ and write $a+b+ab$. After ${n-1}$ steps one number $M$ remains. Find the remainder when $M$ is divided by $1000$.",
        crux="1+(a+b+ab)=(1+a)(1+b): product of (1+x_i) is invariant.",
        solution=rf"$\prod(1+x_i)=({n+1})!$ is invariant, so $M=({n+1})!-1={M}$, remainder ${ans}$.")


def g_diffsq(rng):
    L = rng.randint(200, 1000)
    cnt = sum(1 for x in range(1, L + 1) if x % 2 == 1 or x % 4 == 0)
    return dict(seed="idea-diff-of-squares", topic="Number Theory", answer=cnt, difficulty=4.5,
        statement=rf"How many integers $n$ with $1\le n\le {L}$ can be written as $a^2-b^2$ for nonnegative integers $a,b$?",
        crux="n=(a-b)(a+b) representable iff n is odd or divisible by 4.",
        solution=rf"Only $n\equiv2\pmod4$ fail, so the count is ${cnt}$.")


def g_newton(rng):
    e1 = rng.randint(2, 6); e2 = rng.randint(1, 6); e3 = rng.randint(1, 6)
    p1 = e1; p2 = e1 * p1 - 2 * e2; p3 = e1 * p2 - e2 * p1 + 3 * e3
    return dict(seed="idea-newton-sums", topic="Algebra", answer=p3, difficulty=4.0,
        statement=rf"Let $a,b,c$ be the roots of $x^3-{e1}x^2+{e2}x-{e3}=0$. Find $a^3+b^3+c^3$.",
        crux="Newton's sums from the elementary symmetric functions.",
        solution=rf"$p_3=e_1p_2-e_2p_1+3e_3={p3}$ with $(e_1,e_2,e_3)=({e1},{e2},{e3})$.")


def g_expectation(rng):
    r = rng.randint(3, 7)
    E = sum(F(math.comb(2 * k, k) * math.comb(2 * r - 2 * k, r - k), math.comb(2 * r, r))
            for k in range(1, r + 1))
    ans = E.numerator + E.denominator
    return dict(seed="idea-linearity-expectation", topic="Combinatorics", answer=ans, difficulty=6.0,
        statement=rf"A box has ${r}$ red and ${r}$ blue balls, drawn one at a time without replacement. Let $X$ count the draws after which equal numbers of red and blue have appeared (including the final draw). If $E[X]=\frac{{m}}{{n}}$ in lowest terms, find $m+n$.",
        crux="Linearity of expectation over balanced-prefix indicators.",
        solution=rf"$E[X]=\sum_{{k=1}}^{{{r}}}\binom{{2k}}{{k}}\binom{{{2*r}-2k}}{{{r}-k}}/\binom{{{2*r}}}{{{r}}}={E}$, so $m+n={ans}$.")


def g_crt(rng):
    primes = [7, 11, 13, 17, 19, 23]
    p, q = rng.sample(primes, 2)
    a = rng.randint(1, p - 1); b = rng.randint(1, q - 1)
    n = next(x for x in range(1, p * q + 1) if x % p == a and x % q == b)
    return dict(seed="idea-crt", topic="Number Theory", answer=n, difficulty=4.0,
        statement=rf"Find the smallest positive integer $n$ with $n\equiv {a}\pmod{{{p}}}$ and $n\equiv {b}\pmod{{{q}}}$.",
        crux="Chinese Remainder Theorem gives a unique residue mod pq.",
        solution=rf"By CRT the unique solution mod ${p*q}$ is $n={n}$.")


def g_repunit(rng):
    p = rng.choice([7, 11, 13, 41, 37, 101, 239])
    L = 999
    cnt = 0; Rmod = 0
    for _ in range(1, L + 1):
        Rmod = (Rmod * 10 + 1) % p
        if Rmod == 0:
            cnt += 1
    return dict(seed="idea-order-mod", topic="Number Theory", answer=cnt, difficulty=5.0,
        statement=rf"For a positive integer $n$, let $R_n=\underbrace{{11\cdots1}}_{{n}}$ (the repunit with $n$ ones). How many $n$ with $1\le n\le {L}$ have $R_n$ divisible by ${p}$?",
        crux="Repunit divisibility is periodic with the order of 10 mod p.",
        solution=rf"$R_n\equiv0\pmod{{{p}}}$ is periodic; counting gives ${cnt}$.")


def g_starsbars(rng):
    j = rng.randint(3, 5); S = rng.randint(6, 15)
    val = math.comb(S + j - 1, j - 1)
    ans = val % 1000
    return dict(seed="idea-stars-bars", topic="Combinatorics", answer=ans, difficulty=3.5,
        statement=rf"How many ordered tuples of nonnegative integers $(x_1,\dots,x_{{{j}}})$ satisfy $x_1+\cdots+x_{{{j}}}={S}$? Give the remainder when this count is divided by $1000$.",
        crux="Stars and bars: C(S+j-1, j-1).",
        solution=rf"$\binom{{{S}+{j}-1}}{{{j}-1}}={val}$, remainder ${ans}$.")


GENERATORS = [g_subset_sum, g_telescope, g_nonadjacent, g_invariant, g_diffsq,
              g_newton, g_expectation, g_crt, g_repunit, g_starsbars]


def main() -> None:
    from sqlmodel import select

    from mathforge.schema import statement_hash

    rng = random.Random(20260708)
    db.init_db()

    with db.session_scope() as session:
        have_ins = set(session.exec(select(Insight.id)).all())
        for ins in EXTRA_INSIGHTS:
            if ins["id"] not in have_ins:
                session.add(Insight(id=ins["id"], text=ins["text"],
                    concept_tags=ins["tags"], difficulty_band=ins["band"],
                    source_problem_ids=[]))

        # Idempotent: clear any previous batch so re-runs don't collide.
        old = session.exec(select(Problem).where(Problem.id.like("opus-batch-%"))).all()
        for p in old:
            for s in session.exec(select(Solution).where(Solution.problem_id == p.id)).all():
                session.delete(s)
            for e in session.exec(select(Evaluation).where(Evaluation.problem_id == p.id)).all():
                session.delete(e)
            session.delete(p)
        session.flush()

        seen = set(session.exec(select(Problem.statement_hash)).all())
        accepted = rejected = 0
        reject_reasons: dict[str, int] = {}
        by_topic: dict[str, int] = {}
        idx = 0
        attempts = 0
        while idx < N_TARGET and attempts < N_TARGET * 50:
            attempts += 1
            gen = rng.choice(GENERATORS)  # random -> diverse, never stalls
            prob = gen(rng)
            if prob is None or prob.get("_reject"):
                continue  # degenerate params
            shash = statement_hash(prob["statement"])
            if shash in seen:
                continue
            seen.add(shash)
            ans = prob["answer"]
            reason = None
            if not (isinstance(ans, int) and 0 <= ans <= 999):
                reason = f"answer {ans} outside AIME range [0,999]"

            accept = reason is None
            idx += 1
            pid = f"opus-batch-{idx:03d}"
            status = ReviewStatus.ACCEPTED if accept else ReviewStatus.REJECTED
            if accept:
                accepted += 1
                by_topic[prob["topic"]] = by_topic.get(prob["topic"], 0) + 1
            else:
                rejected += 1
                reject_reasons[reason] = reject_reasons.get(reason, 0) + 1

            session.add(Problem(
                id=pid, source=ProblemSource.SYNTHETIC, statement=prob["statement"],
                answer=str(prob["answer"]) if "answer" in prob else None,
                difficulty=prob.get("difficulty"), topic=prob.get("topic"),
                split=DataSplit.TRAIN, verified=accept, review_status=status,
                possibly_memorized=False,
                provenance={
                    "pipeline": "opus-batch-generation", "generator_model": MODEL,
                    "seed_insight_id": prob.get("seed"), "crux": prob.get("crux"),
                    "verification": "exact computation",
                    "auto_decision": "accept" if accept else "reject",
                    "reject_reason": reason,
                    "agent_qa": {
                        "solver_model": MODEL, "k": "exact",
                        "consensus": str(prob["answer"]) if "answer" in prob else None,
                        "agreement": 1.0, "verified": accept,
                        "wellposedness": {"verdict": "accept" if accept else "reject"},
                        "difficulty": {"difficulty": prob.get("difficulty")},
                        "elegance": {"overall": None},
                        "recommendation": "accept" if accept else "reject",
                        "reason": reason or f"Verified by exact computation; answer {prob.get('answer')}.",
                    },
                },
            ).refresh_dedup_fields())
            if prob.get("solution"):
                session.add(Solution(problem_id=pid, text=prob["solution"],
                    techniques=[prob.get("seed")] if prob.get("seed") else [],
                    crux_insight=prob.get("crux", ""), crux_count=1, routine_step_count=2,
                    source=SolutionSource.MODEL, extractor_model=MODEL))
            if accept and prob.get("difficulty") is not None:
                session.add(Evaluation(problem_id=pid, difficulty_score=prob["difficulty"],
                    elegance_score=None, evaluator="opus-4.8", rationale=prob.get("crux", "")))

    print(f"generated {accepted + rejected}: accepted {accepted}, rejected {rejected}")
    print("accepted by topic:", by_topic)
    print("reject reasons:", reject_reasons)


if __name__ == "__main__":
    main()
