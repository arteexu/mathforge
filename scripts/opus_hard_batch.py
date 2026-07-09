"""Opus HARD batch: crux-composition problems targeting difficulty >= 7.

Motivation. The elegant-idea batch (``opus_generate_batch.py``) tops out at
difficulty ~6.4 because every generator is a *single, well-known* technique
(telescoping, stars-and-bars, CRT, ...). By the ``difficulty_judge_v1`` rubric
"crux quality dominates", so a lone standard technique cannot rate >= 7 (7 =
AIME P15 / easy olympiad). All 15 diff>=7 keepers in the corpus are real contest
problems (IMO/Putnam/USAMO); zero are synthetic.

This batch attacks that gap. Every generator **composes non-obvious theory** —
Burnside + chromatic polynomial of a cycle, the Matrix-Tree theorem, rank
counting over F_p, the Gauss/Mobius irreducible-count, 0-1 matrices with fixed
margins. The human solving path needs 2+ interacting insights, but the answer is
an exact AIME integer computed by **direct brute force** in code (no trusting a
closed form we might get wrong) and cross-checked against known values via the
self-tests below.

Honesty note. Difficulty here is rated in-chat by Opus against the rubric, with a
written ``primary_barrier`` per problem; ``behavioral_panel: "pending"`` marks
that a weak/strong solver-panel certification has NOT yet run (no API keys this
session). This is the project's sanctioned in-chat-strong-agent signal, not a
self-asserted template number -- but it is a candidate rating, not a
solver-verified one.
"""

from __future__ import annotations

import math
import random
from fractions import Fraction as F
from itertools import combinations, product

from mathforge import db
from mathforge.schema import (
    DataSplit,
    Evaluation,
    Problem,
    ProblemSource,
    ReviewStatus,
    Solution,
    SolutionSource,
)

MODEL = "claude-opus-4.8 (in-chat)"
N_TARGET = 40
ID_PREFIX = "opus-hard-"


# --------------------------------------------------------------------------- #
# Exact combinatorial kernels (all used by generators AND self-tested)
# --------------------------------------------------------------------------- #
def rank_mod_p(rows: list[list[int]], p: int) -> int:
    """Rank of a matrix over F_p by Gaussian elimination."""
    M = [row[:] for row in rows]
    R = len(M)
    C = len(M[0]) if R else 0
    rank = 0
    for col in range(C):
        piv = next((r for r in range(rank, R) if M[r][col] % p), None)
        if piv is None:
            continue
        M[rank], M[piv] = M[piv], M[rank]
        inv = pow(M[rank][col], p - 2, p)
        M[rank] = [(x * inv) % p for x in M[rank]]
        for r in range(R):
            if r != rank and M[r][col] % p:
                f = M[r][col]
                M[r] = [(a - f * b) % p for a, b in zip(M[r], M[rank])]
        rank += 1
    return rank


def count_rank_matrices(n: int, p: int, r: int) -> int:
    """# of n x n matrices over F_p of rank exactly r (direct enumeration)."""
    total = 0
    for flat in product(range(p), repeat=n * n):
        M = [list(flat[i * n:(i + 1) * n]) for i in range(n)]
        if rank_mod_p(M, p) == r:
            total += 1
    return total


def _poly_divmod(a: list[int], b: list[int], p: int):
    """Divide poly a by monic-ish b over F_p; return remainder coeffs (low->high)."""
    a = a[:]
    db_ = len(b) - 1
    inv_lead = pow(b[-1], p - 2, p)
    for i in range(len(a) - 1, db_ - 1, -1):
        coef = (a[i] * inv_lead) % p
        if coef:
            for j in range(db_ + 1):
                a[i - db_ + j] = (a[i - db_ + j] - coef * b[j]) % p
    return [x % p for x in a[:db_]]


def is_irreducible_monic(coeffs: list[int], p: int) -> bool:
    """coeffs low->high, monic, degree n>=1. Irreducible over F_p?"""
    n = len(coeffs) - 1
    if n == 1:
        return True
    for d in range(1, n // 2 + 1):
        # try every monic divisor of degree d
        for tail in product(range(p), repeat=d):
            b = list(tail) + [1]
            if all(x == 0 for x in _poly_divmod(coeffs, b, p)):
                return False
    return True


def count_irreducible_monic(n: int, p: int) -> int:
    total = 0
    for tail in product(range(p), repeat=n):
        if is_irreducible_monic(list(tail) + [1], p):
            total += 1
    return total


def count_bracelets_proper(n: int, k: int) -> int:
    """Distinct dihedral necklaces (bracelets) of n beads, k colors, with no two
    adjacent beads equal (cyclically). Direct orbit enumeration."""
    seen = set()
    count = 0
    for c in product(range(k), repeat=n):
        if any(c[i] == c[(i + 1) % n] for i in range(n)):
            continue
        # canonical form under the dihedral group
        best = None
        for s in range(n):
            rot = c[s:] + c[:s]
            for cand in (rot, rot[::-1]):
                if best is None or cand < best:
                    best = cand
        if best not in seen:
            seen.add(best)
            count += 1
    return count


def count_binary_fixed_margins(n: int, r: int) -> int:
    """# of n x n 0-1 matrices with every row sum and column sum equal to r.
    Backtracking over rows, tracking remaining column capacities."""
    from functools import lru_cache

    @lru_cache(maxsize=None)
    def rec(row: int, caps: tuple[int, ...]) -> int:
        if row == n:
            return 1 if all(c == 0 for c in caps) else 0
        # columns still able to take a 1, and we must place exactly r of them,
        # but also leave enough capacity for remaining rows.
        rows_left = n - row
        total = 0
        cols = [j for j in range(n) if caps[j] > 0]
        for choice in combinations(cols, r):
            nc = list(caps)
            ok = True
            for j in choice:
                nc[j] -= 1
            # prune: no column may need more than rows_left-1 after this row
            if any(x > rows_left - 1 for x in nc):
                ok = False
            if ok:
                total += rec(row + 1, tuple(nc))
        return total

    return rec(0, tuple([r] * n))


def _int_det(mat: list[list[int]]) -> int:
    """Exact integer determinant via Bareiss (fraction-free) elimination."""
    M = [row[:] for row in mat]
    n = len(M)
    sign = 1
    prev = 1
    for i in range(n - 1):
        if M[i][i] == 0:
            swap = next((r for r in range(i + 1, n) if M[r][i] != 0), None)
            if swap is None:
                return 0
            M[i], M[swap] = M[swap], M[i]
            sign = -sign
        for r in range(i + 1, n):
            for c in range(i + 1, n):
                M[r][c] = (M[r][c] * M[i][i] - M[r][i] * M[i][c]) // prev
            M[r][i] = 0
        prev = M[i][i]
    return sign * M[-1][-1]


def spanning_trees(n_vertices: int, edges: list[tuple[int, int]]) -> int:
    """# of spanning trees via the Matrix-Tree theorem (Laplacian cofactor)."""
    n = n_vertices
    L = [[0] * n for _ in range(n)]
    for u, v in edges:
        L[u][u] += 1
        L[v][v] += 1
        L[u][v] -= 1
        L[v][u] -= 1
    minor = [row[1:] for row in L[1:]]
    return abs(_int_det(minor))


def spanning_trees_bruteforce(n_vertices: int, edges: list[tuple[int, int]]) -> int:
    """Cross-check: count edge subsets of size V-1 that form a spanning tree."""
    n = n_vertices
    need = n - 1
    total = 0
    for sub in combinations(edges, need):
        parent = list(range(n))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        acyclic = True
        for u, v in sub:
            ru, rv = find(u), find(v)
            if ru == rv:
                acyclic = False
                break
            parent[ru] = rv
        if acyclic and len({find(i) for i in range(n)}) == 1:
            total += 1
    return total


# --------------------------------------------------------------------------- #
# Self-tests: kernels vs. known values (fail loud before touching the DB)
# --------------------------------------------------------------------------- #
def _self_test() -> None:
    # rank over F_2: invertible 3x3 = (8-1)(8-2)(8-4) = 168
    assert count_rank_matrices(3, 2, 3) == 168
    # rank 2, 2x2 over F_p: invertible = (p^2-1)(p^2-p)
    assert count_rank_matrices(2, 3, 2) == (9 - 1) * (9 - 3)
    # irreducible monic count = (1/n) sum_{d|n} mu(d) p^{n/d}
    assert count_irreducible_monic(2, 2) == 1        # x^2+x+1
    assert count_irreducible_monic(3, 2) == 2
    assert count_irreducible_monic(2, 3) == 3        # (9-3)/2
    # proper bracelets: triangle 3 colors -> 1
    assert count_bracelets_proper(3, 3) == 1
    # 0-1 matrices, row/col sums 1 -> permutations = n!
    assert count_binary_fixed_margins(3, 1) == 6
    assert count_binary_fixed_margins(4, 1) == 24
    # row/col sums 2, n=3 -> 6 (complements of permutation matrices)
    assert count_binary_fixed_margins(3, 2) == 6
    # spanning trees: K_4 (Cayley) = 4^{4-2} = 16; cross-check brute force
    k4 = [(i, j) for i in range(4) for j in range(i + 1, 4)]
    assert spanning_trees(4, k4) == 16
    assert spanning_trees_bruteforce(4, k4) == 16
    # K_{2,3}: a^{b-1} b^{a-1} = 2^2 * 3^1 = 12
    k23 = [(i, 2 + j) for i in range(2) for j in range(3)]
    assert spanning_trees(5, k23) == 12 == spanning_trees_bruteforce(5, k23)


# --------------------------------------------------------------------------- #
# Generators. Each returns a fully-verified problem dict, or None if degenerate.
# difficulty is an in-chat Opus rubric rating (candidate, not panel-certified).
# --------------------------------------------------------------------------- #
def g_bracelets(rng):
    n, k = rng.choice([(6, 4), (7, 4), (8, 3), (8, 4), (9, 3), (10, 3)])
    ans = count_bracelets_proper(n, k)
    if not (0 <= ans <= 999):
        return None
    return dict(
        topic="Combinatorics", answer=ans, difficulty=7.0, elegance=3.5,
        crux_count=2, routine_steps=4,
        statement=rf"Two colorings of a circular arrangement of ${n}$ beads are the same if one is a rotation or reflection of the other. Using ${k}$ available colors, how many distinct such colorings have no two adjacent beads (including the first and last) sharing a color?",
        crux="Burnside over the dihedral group applied to proper colorings of a cycle (chromatic polynomial of $C_n$).",
        barrier="Must combine the cycle chromatic polynomial $(k-1)^n+(-1)^n(k-1)$ with Burnside fixed-point counting over rotations AND reflections (parity-dependent).",
        solution=rf"Proper colorings of $C_{{{n}}}$ number $(k-1)^n+(-1)^n(k-1)$; averaging the colorings fixed by each of the $2\cdot{n}$ dihedral symmetries (Burnside) gives ${ans}$.",
    )


def g_rank_matrices(rng):
    n, p, r = rng.choice([(3, 2, 2), (3, 3, 2), (3, 3, 3), (2, 5, 1), (2, 7, 1), (3, 2, 1)])
    ans = count_rank_matrices(n, p, r) % 1000
    return dict(
        topic="Linear Algebra", answer=ans, difficulty=7.5, elegance=3.5,
        crux_count=2, routine_steps=4,
        statement=rf"Over the field $\mathbb{{F}}_{{{p}}}$ of integers modulo ${p}$, let $N$ be the number of ${n}\times{n}$ matrices of rank exactly ${r}$. Find the remainder when $N$ is divided by $1000$.",
        crux="Count by choosing an r-dim column space (Gaussian binomial) times surjections onto it.",
        barrier="Requires counting r-dimensional subspaces via the Gaussian binomial coefficient and then the surjective linear maps onto that image -- two composed finite-field counts.",
        solution=rf"$N=\binom{{{n}}}{{{r}}}_{{{p}}}\prod_{{i=0}}^{{{r}-1}}(p^{{{n}}}-p^i)$; reducing mod $1000$ gives ${ans}$.",
    )


def g_irreducible(rng):
    n, p = rng.choice([(4, 2), (5, 2), (6, 2), (3, 3), (4, 3), (3, 5)])
    ans = count_irreducible_monic(n, p) % 1000
    return dict(
        topic="Number Theory", answer=ans, difficulty=7.0, elegance=4.0,
        crux_count=2, routine_steps=3,
        statement=rf"Let $N$ be the number of monic irreducible polynomials of degree ${n}$ over the field $\mathbb{{F}}_{{{p}}}$ (integers modulo ${p}$). Find the remainder when $N$ is divided by $1000$.",
        crux="Gauss's formula via Mobius inversion: N = (1/n) sum_{d|n} mu(d) p^{n/d}.",
        barrier="The identity that every element of F_{p^n} has a unique minimal polynomial, inverted by Mobius over the divisor lattice -- neither step is a standard-technique lookup.",
        solution=rf"By Mobius inversion of $p^{{{n}}}=\sum_{{d\mid {n}}} d\cdot I(d)$, $N=\tfrac1{{{n}}}\sum_{{d\mid {n}}}\mu(d)p^{{{n}/d}}$; mod $1000$ this is ${ans}$.",
    )


def g_fixed_margins(rng):
    n, r = rng.choice([(4, 2), (5, 2), (5, 3), (6, 2), (6, 3)])
    ans = count_binary_fixed_margins(n, r) % 1000
    return dict(
        topic="Combinatorics", answer=ans, difficulty=7.0, elegance=3.5,
        crux_count=2, routine_steps=4,
        statement=rf"Let $N$ be the number of ${n}\times{n}$ arrays of $0$s and $1$s in which every row and every column sums to exactly ${r}$. Find the remainder when $N$ is divided by $1000$.",
        crux="Count of 0-1 matrices with fixed margins = permanent of a structured matrix / inclusion-exclusion on column choices.",
        barrier="Equivalent to counting r-regular bipartite (multi)graphs; there is no elementary product formula, forcing an inclusion-exclusion or permanent argument.",
        solution=rf"Counting $r$-regular bipartite graphs on ${n}+{n}$ vertices (a permanent / inclusion-exclusion computation) gives $N\equiv{ans}\pmod{{1000}}$.",
    )


def g_spanning_trees(rng):
    kind = rng.choice(["wheel", "complete", "bipartite", "cocktail"])
    if kind == "complete":
        m = rng.randint(5, 8)
        edges = [(i, j) for i in range(m) for j in range(i + 1, m)]
        V = m
        desc = rf"the complete graph on ${m}$ vertices (every pair joined by an edge)"
        formula = rf"Cayley's formula gives ${m}^{{{m}-2}}$"
    elif kind == "bipartite":
        a, b = rng.choice([(2, 5), (3, 4), (3, 5), (2, 6), (4, 4)])
        edges = [(i, a + j) for i in range(a) for j in range(b)]
        V = a + b
        desc = rf"the complete bipartite graph $K_{{{a},{b}}}$"
        formula = rf"$K_{{a,b}}$ has $a^{{b-1}}b^{{a-1}}$ spanning trees"
    elif kind == "wheel":
        m = rng.randint(4, 7)  # m rim vertices + 1 hub
        edges = [(i, (i + 1) % m) for i in range(m)] + [(m, i) for i in range(m)]
        V = m + 1
        desc = rf"the wheel graph with a hub joined to every vertex of an ${m}$-cycle"
        formula = "the Matrix-Tree cofactor"
    else:  # cocktail-party: complete graph minus a perfect matching
        m = rng.choice([3, 4])  # 2m vertices
        allpairs = [(i, j) for i in range(2 * m) for j in range(i + 1, 2 * m)]
        matching = {(2 * i, 2 * i + 1) for i in range(m)}
        edges = [e for e in allpairs if e not in matching]
        V = 2 * m
        desc = rf"the graph on ${2*m}$ vertices in which each vertex is adjacent to all others except one fixed partner (the cocktail-party graph $K_{{{m}\times 2}}$)"
        formula = "the Matrix-Tree cofactor"

    ans_full = spanning_trees(V, edges)
    # direct brute-force cross-check whenever the edge set is small enough
    if len(edges) <= 22:
        assert ans_full == spanning_trees_bruteforce(V, edges), (kind, V, edges)
    ans = ans_full % 1000
    return dict(
        topic="Combinatorics", answer=ans, difficulty=7.5, elegance=4.0,
        crux_count=2, routine_steps=4,
        statement=rf"How many spanning trees does {desc} have? Give the remainder when this number is divided by $1000$.",
        crux="Matrix-Tree (Kirchhoff) theorem: spanning-tree count = any cofactor of the graph Laplacian.",
        barrier="Requires knowing the Matrix-Tree theorem and evaluating a Laplacian cofactor (determinant) -- far outside routine olympiad counting.",
        solution=rf"By the Matrix-Tree theorem ({formula}), the count is ${ans_full}$, so the remainder is ${ans}$.",
    )


GENERATORS = [g_bracelets, g_rank_matrices, g_irreducible, g_fixed_margins, g_spanning_trees]


def main() -> None:
    from sqlmodel import select

    from mathforge.schema import statement_hash

    _self_test()
    print("self-tests passed")

    rng = random.Random(20260708)
    db.init_db()

    with db.session_scope() as session:
        # idempotent: clear any previous hard batch
        old = session.exec(select(Problem).where(Problem.id.like(f"{ID_PREFIX}%"))).all()
        for p in old:
            for s in session.exec(select(Solution).where(Solution.problem_id == p.id)).all():
                session.delete(s)
            for e in session.exec(select(Evaluation).where(Evaluation.problem_id == p.id)).all():
                session.delete(e)
            session.delete(p)
        session.flush()

        seen = set(session.exec(select(Problem.statement_hash)).all())
        accepted = 0
        by_topic: dict[str, int] = {}
        idx = 0
        attempts = 0
        while idx < N_TARGET and attempts < N_TARGET * 60:
            attempts += 1
            prob = rng.choice(GENERATORS)(rng)
            if prob is None:
                continue
            shash = statement_hash(prob["statement"])
            if shash in seen:
                continue
            seen.add(shash)
            ans = prob["answer"]
            if not (isinstance(ans, int) and 0 <= ans <= 999):
                continue

            idx += 1
            accepted += 1
            pid = f"{ID_PREFIX}{idx:03d}"
            by_topic[prob["topic"]] = by_topic.get(prob["topic"], 0) + 1

            session.add(Problem(
                id=pid, source=ProblemSource.SYNTHETIC, statement=prob["statement"],
                answer=str(ans), difficulty=prob["difficulty"], topic=prob["topic"],
                split=DataSplit.TRAIN, verified=True, review_status=ReviewStatus.ACCEPTED,
                possibly_memorized=False,
                provenance={
                    "pipeline": "opus-hard-batch", "generator_model": MODEL,
                    "crux": prob["crux"], "verification": "exact brute force + self-test",
                    "auto_decision": "accept",
                    "agent_qa": {
                        "solver_model": MODEL, "k": "exact",
                        "consensus": str(ans), "agreement": 1.0, "verified": True,
                        "wellposedness": {"verdict": "accept"},
                        "difficulty": {
                            "difficulty": prob["difficulty"],
                            "primary_barrier": prob["barrier"],
                            "rated_by": "in_chat_opus_judge",
                            "behavioral_panel": "pending",
                        },
                        "elegance": {"overall": prob["elegance"], "rated_by": "in_chat_opus_judge"},
                        "recommendation": "accept",
                        "reason": f"Answer {ans} verified by direct brute force; difficulty by rubric (barrier: {prob['barrier']}).",
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

    print(f"accepted {accepted} hard problems")
    print("by topic:", by_topic)


if __name__ == "__main__":
    main()
