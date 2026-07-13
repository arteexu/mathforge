"""Backfill correct, verified solutions onto accepted distill problems.

The generator's stored ``model`` solution is wrong for every problem whose answer
we corrected (it reached the wrong number). This replaces that solution text with
a correct one -- each verified by exact Python computation earlier this session --
and marks the problem ``solution_backfilled``. Only problems personally verified
this session are touched; earlier-session accepts are left alone (and reported).
"""

from __future__ import annotations

from sqlmodel import select

from mathforge import db
from mathforge.schema import Problem, Solution, SolutionSource

MODEL = "claude-opus-4.8 (in-chat, backfilled)"

# id-suffix -> correct solution (verified by exact computation this session).
SOLUTIONS: dict[str, str] = {
    # ---- batch 1 ----
    "aa38a7b4": "X = sum_{k=1..6} I_{2k}, where I_{2k}=1 iff the first 2k draws are k red and k blue. The first 2k balls form a uniform 2k-subset, so P(I_{2k}=1)=C(6,k)^2/C(12,2k). Summing gives 6/11+5/11+100/231+5/11+6/11+1 = 793/231. Hence m+n = 793+231 = 1024.",
    "259e1b15": "R_n = (10^n-1)/9. Since gcd(2021,9)=1, 2021 | R_n iff 10^n == 1 (mod 2021), where 2021=43*47. The multiplicative order of 10 mod 2021 is 966, so within 1<=n<=999 only n=966 qualifies. Count = 1.",
    "c38f1a9c": "A filling with consecutive numbers adjacent is a Hamiltonian path; row- and column-monotonicity means each cell may be filled only after its top and left neighbors. A backtracking search over the 6x6 grid finds no valid filling. Answer 0.",
    "cddabc19": "From a_7=0, since every m divides 0 the sequence jumps to a_{m+1}=m and then decrements. Zeros recur at 7,15,31,...,1023,2047 (each is 2*prev+1). The last zero <=2025 is 1023, so a_n = 2047-n for n in [1024,2047] (no divisor triggers, as 2047=23*89). Thus a_2025 = 2047-2025 = 22.",
    "20d146f4": "Track the relevant suffix state (empty, H, HH, HT). With x = P(HHH first): x_empty=x_H, x_HT=x_empty/2, x_HH=1/2+x_HT/2, x_H=x_HH/2+x_HT/2. Solving gives x_empty = 2/5, so p=2/5 and m+n = 7.",
    "56e80bd4": "'Uses only the digit 1 and contains exactly six 1s' forces the number to be 111111 = 37 * 3003, the unique such multiple of 37. It has 6 digits.",
    "451dff87": "Place 1..12 in a 3x4 grid so that differ-by-1 = horizontally adjacent and differ-by-4 = vertically adjacent. The condition becomes 'independent set of the grid graph'. A transfer matrix over the 5 valid column patterns (000,001,010,100,101) gives 191 subsets (including the empty set).",
    # ---- batch 2 ----
    "0f1d349f": "Analyzing the smallest prime factor of n forces n into a small set; the solutions n<=1000 of n | 2^n+3^n+4^n are {1,3,9,27,33,81,143,243,729}, so the count is 9.",
    "5582c154": "Enumerate the 2^10 sequences of steps in {+1,-2}; a sequence is counted iff the running position never repeats (all 11 visited positions distinct). Exactly 61 are self-avoiding.",
    "eb412279": "gcd(a_{n+1},a_n) is NOT always 1 -- it runs 1,1,1,1,3,3,9,9,27,... (powers of 3). Iterating a_{n+2}=a_{n+1}+a_n+gcd gives a_20 = 32805 = 5*3^8, so a_20 mod 1000 = 805.",
    "8242aac0": "tan t + tan 2t + tan 3t = (tan t + tan 2t)(2 - tan t tan 2t)/(1 - tan t tan 2t); its roots in (0, pi/2) are arctan(1/sqrt 2) and pi/3. The largest expressible as p*pi/q is pi/3, so p+q = 4.",
    "dcad0f80": "S(a)+S(b)-S(a+b) = 9*(carries in a+b), so S(n)+S(2n)=S(3n) means adding n and 2n produces no carries. Counting such n in [1,2025] gives 400.",
    "30959dc0": "Since cos k = sin(90-k), the cosine sum equals the sine sum over k=1..89, so the ratio is 1 and theta = 45 degrees.",
    "a70f2239": "Eliminating y and z gives x = 9(x-1)/(4x-3), i.e. (2x-3)^2 = 0, so x=3/2, y=2/5, z=5/3, and xyz=1. Hence 100xyz = 100.",
    "69a9e3ba": "By distance-to-D symmetry: h1 = 1 + h2/2, h2 = 1 + (h3+h1)/2, h3 = 1 + h2. Solving gives h2 = 8 and E = h3 = 9.",
    "e05cfd4e": "The probability generating function from 0 is g0(z) = z^3/(4 - 3z^2). A cube-roots-of-unity filter gives p = (1/3)(1 + 1/(4-3w) + 1/(4-3w^2)) = (1/3)(1 + 11/37) = 16/37, so m+n = 53.",
    "c219d506": "This Rowland-type sequence a_{n+1}=a_n+gcd(a_n,n) climbs roughly linearly (differences 1 or a prime). Iterating, a_n first equals 1000 at n = 999.",
    "5025a52e": "A balanced set takes k elements from each half, so sum of |S| = sum_k 2k*C(6,k)^2 = 2*6*C(11,5) = 5544 (Vandermonde/derivative identity). Mod 1000 this is 544.",
    "c66abf7b": "n^n mod 1000 is a repdigit for 104 values of n<=1000. Of these, 100 are the trivial multiples of 10 (n^n == 000); only 4 are nontrivial.",
    "6291d1d4": "With the right angle at C, CXIY is a square of side r, so the touch-chord XY is the line x+y=r near C, which meets line AB only on its extension. With B between A and P, the points are collinear: AB = PA - PB = 63 - 25 = 38 (a valid triangle exists, legs ~17.4 and ~33.8).",
    "bba37e20": "Newton's sums give e1=6, e2=5, e3=-12, so x,y,z are the roots of t^3-6t^2+5t+12 = (t+1)(t-3)(t-4) = {-1,3,4}. Thus x^4+y^4+z^4 = 1+81+256 = 338.",
    "ac72ab65": "Set sqrt(x+2y)=t and sqrt(2x+y)=3-t for t in [0,3]; then x=(2(3-t)^2 - t^2)/3, y=(2t^2-(3-t)^2)/3. Substituting into x^2+xy+y^2=7 yields exactly two solutions, (x,y) ~ (3.03,-1.20) and its swap. Count = 2.",
    "c6a099c4": "The map g(x)=(x-1)/x has order 3 (cycle 2 -> 1/2 -> -1 -> 2). The three instances give f(2)+f(1/2)=3, f(1/2)+f(-1)=3/2, f(-1)+f(2)=0; solving, f(2)=3/4, so m+n = 7.",
    "6b9fed6d": "DM = |AC^2 - AB^2|/(2*BC) = |225-169|/(2*BC) = 28/BC. Setting 28/BC = 2 gives BC = 14 -- the 13-14-15 triangle, whose area is 84 by Heron's formula.",
    # ---- batch 3 ----
    "2cbabca1": "s(n)=s(3n) forces 9|n (s(n)==n and s(3n)==3n mod 9). Among the multiples of 9 up to 1000, exactly 75 satisfy s(n)=s(3n).",
    "3466b4aa": "For n=100a+10b+c, n - reverse(n) = 99(a-c), and 99 == 1 (mod 7), so the condition is 7|(a-c). There are 14 valid leading pairs (a,c) times 10 choices for b = 140.",
    "41be2a75": "Exhaustively, n^n == n (mod 100) for 445 values of n <= 2025.",
    "6863bdcf": "Exhaustively over n <= 10^4, s(n)+s(2n)+s(3n) = s(6n) holds for 16 values.",
    "76086ce7": "The concatenation of n and n+1 equals n*(10^d+1)+1 where d = #digits of n+1. For 3-digit n+1, 10^3+1 = 1001 = 7*11*13 == 0 (mod 7), so that entire range is impossible; only 14 solutions remain.",
    "860395b0": "Over all 2^12 subsets, |S| equals the boundary count (the number of k with exactly one of k, k+1 in S) for 675 of them.",
    "9dce6b88": "For n>=3 the gcd stays 1, so a_n = n+1; hence a_n = n only at n=1 and n=2. The count is 2.",
    "c06047c6": "Avoiding 3, 6, 9 forces a +2 straddle across each barrier; the remaining free segments give 2*1*1*2 = 4 sequences from 0 to 12.",
    "c7dafdd2": "All 41 integers in [-20,20] are reachable in 10 jumps; only the 11 even values in [-10,10] are reachable with length-1 jumps alone. So 41 - 11 = 30 positions require at least one length-2 jump.",
    "956eaa86": "The recurrence linearizes: (a_n + a_{n+2})/a_{n+1} = 5 is constant, so a_{n+2} = 5a_{n+1} - a_n (an integer sequence). Iterating, a_20 mod 1000 = 578.",
    "75ebb116": "tanA+tanB+tanC = tanA tanB tanC iff sin(A+B+C)=0; here A+B+C=6theta, so the equation means sin(6theta)=0. The only in-range solution with all tangents defined is theta=60 degrees, so the sum of solutions is 60 and p+q = 61.",
    "8a6939c0": "Reaching vertex 3 without ever visiting 5 is gambler's ruin on the path 5-0-1-2-3, starting at position 1 of 4. So p = 1/4 and m+n = 5.",
    "9b6a6ba9": "The score difference is a walk that is +1 or -1 with probability 5/12 each and 0 (tie) with probability 1/6, absorbed at +-2. Solving, E[rolls] = 24/5, and by symmetry this equals the expectation given Ana wins, so m+n = 29.",
    "b14470d3": "After the first H appears, the next flip decides: H gives HH (Alice), T gives HT (Bob). So p = 1/2 and m+n = 3.",
    "a2e23952": "The unique point that is the centroid of its own cevian triangle is the centroid of ABC; then DEF is the medial triangle with area 84/4 = 21, so m+n = 22.",
    "8b3efa54": "The circle through B, C is tangent to AB at B, so the power of A gives AB^2 = AP*AC, i.e. 169 = 15*AP, AP = 169/15. Hence m+n = 184.",
    # ---- batch 4 ----
    "0307fb27": "The two equations are Re and -Im of (x+iy)^3, so |x+iy|^6 = 39^2 + 26^2 = 2197 = 13^3. Therefore x^2+y^2 = |x+iy|^2 = 13.",
    "129789d5": "Searching downward from 999, the largest n < 1000 with n | 2^n + 2 is 946.",
    "16d40688": "After the first H, the next flip decides HH vs HT, so p = 1/2 (a+b=3). The expected wait for HT is 4. Thus 100(a+b) + q = 300 + 4 = 304.",
    "5147c19c": "Encode a stable (no 3-in-a-row) string by its runs of length 1 or 2. Counting length-10 strings with exactly 5 H and 5 T gives 84.",
    "be5fa9df": "Shift each element by 3: sum(x) = 3|S| becomes sum(x-3) = 0 over values {-2,-1,0,...,9}. Counting these signed-subset-sums gives 10 balanced subsets (including the empty set).",
    "c37de9ad": "Refusing to land on multiples of 4 (i.e. 4 and 8) splits the trip into segments with forced straddles; the product over segments gives 18 sequences from 0 to 12.",
    "73022c6d": "Let b_n = a_n - 1; then b_{n+2} = b_{n+1} b_n, so b_n = 2^{F_n} with F a Fibonacci exponent (F_1=1, F_2=2). Since F_2024 == 50 (mod 100) and 2^k mod 1000 has period 100 for k >= 3, 2^{F_2024} == 2^50 == 624, so a_2024 == 625 (mod 1000).",
    "848875b7": "The map (x-1)/x has order 3, so applying the equation to the 3-cycle of 2024 gives a solvable linear system: f(2024) = 8291467799/8189104. Then (p+q) mod 1000 = 903.",
    "b8bde435": "The probability of ever landing on n satisfies p_n = 1 - p_{n-1}/2 with p_0 = 1. This gives p_20 = 699051/1048576, so m+n = 1747627 and mod 1000 = 627.",
    "e2bfeb68": "Writing everything in c = cos 2x, cos x cos 2x cos 3x = 1/8 and sin^2 x + sin^2 2x + sin^2 3x reduce to one variable; over the valid roots the largest value of the sum is 7/4, so m+n = 11.",
    "120ffe06": "Equal perimeters force PB = PA+1 and PC = PA-1 (differences of side lengths). Solving this isoperimetric point for the 13-14-15 triangle gives PA = 91/11 exactly (all three perimeters equal 30.545...), so m+n = 102.",
    "461abd64": "n^n mod 100 is a 2-digit repdigit for 160 values of n <= 1000 (100 of them the trivial multiples of 10, which give 00).",
}


def main() -> None:
    db.init_db()
    updated = 0
    with db.session_scope() as ses:
        accepted = {
            p.id: p
            for p in ses.exec(db.training_problems_select()).all()
            if p.id.startswith("distill-")
            and p.review_status
            and p.review_status.value == "accepted"
        }
        missing_verified = []
        for suffix, text in SOLUTIONS.items():
            pid = f"distill-{suffix}"
            p = accepted.get(pid)
            if p is None:
                missing_verified.append(pid)
                continue
            sols = ses.exec(select(Solution).where(Solution.problem_id == pid)).all()
            model_sols = [s for s in sols if s.source == SolutionSource.MODEL]
            panel_sols = [s for s in sols if s.source == SolutionSource.SOLVER_PANEL]
            # Rewrite the (flawed) generator solution with the verified one.
            target = model_sols[0] if model_sols else (sols[0] if sols else None)
            if target is None:
                target = Solution(problem_id=pid, source=SolutionSource.MODEL)
                ses.add(target)
            target.text = text
            target.extractor_model = MODEL
            # Drop redundant duplicate verification stubs, keep at most one.
            for extra in model_sols[1:] + panel_sols[1:]:
                ses.delete(extra)
            prov = dict(p.provenance or {})
            prov["solution_backfilled"] = True
            p.provenance = prov
            ses.add(target)
            ses.add(p)
            updated += 1

        # Accepted problems NOT verified this session (left untouched).
        unverified = sorted(
            pid for pid in accepted if f"{pid}"[8:] not in SOLUTIONS
        )

    print(f"backfilled correct solutions for {updated} verified problems")
    if missing_verified:
        print("verified ids not found as accepted:", missing_verified)
    print(f"\n{len(unverified)} accepted problems NOT verified this session (left as-is):")
    print("  " + ", ".join(u[8:] for u in unverified))


if __name__ == "__main__":
    main()
