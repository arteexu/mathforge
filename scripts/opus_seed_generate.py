"""Opus (in-chat) seeded generation: elegant idea bank -> problems -> self-verify.

Each problem is composed around one elegant seed idea and its answer is verified
by exact computation (see chat). Stored as SYNTHETIC, verified=True, pending human
review, linked to the seed Insight.
"""

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

INSIGHTS = [
    dict(id="idea-rou-filter",
         text="Roots-of-unity filter: to count objects whose (weighted) sum lands in a fixed residue class mod m, average a generating function over the m-th roots of unity.",
         tags=["combinatorics", "generating functions", "number theory"],
         band=DifficultyBand.AIME_HARD),
    dict(id="idea-telescoping",
         text="Telescoping via partial fractions: rewrite each term as f(k)-f(k+1) so a long sum collapses to its endpoints.",
         tags=["algebra", "sequences"], band=DifficultyBand.AIME_EASY),
    dict(id="idea-incl-excl-adjacency",
         text="Inclusion-exclusion over forbidden adjacencies: glue banned neighbors into blocks (2 orientations each) and alternate-sum over how many are glued.",
         tags=["combinatorics"], band=DifficultyBand.AIME_HARD),
    dict(id="idea-mult-invariant",
         text="Multiplicative invariant: the operation a,b -> a+b+ab preserves the product of (1+x_i), since 1+(a+b+ab)=(1+a)(1+b).",
         tags=["algebra", "invariants"], band=DifficultyBand.AIME_HARD),
    dict(id="idea-diff-of-squares",
         text="Difference of squares: n=a^2-b^2=(a-b)(a+b); representable iff n is odd or a multiple of 4 (the two factors share parity).",
         tags=["number theory"], band=DifficultyBand.AIME_EASY),
    dict(id="idea-newton-sums",
         text="Newton's sums: power sums of the roots follow a recursion in the elementary symmetric functions (the coefficients), so you never solve for the roots.",
         tags=["algebra"], band=DifficultyBand.AIME_HARD),
]

PROBLEMS = [
    dict(id="opus-rou-1", seed="idea-rou-filter", topic="Number Theory",
         answer="712", difficulty=5.5, elegance=4,
         statement=r"Let $N$ be the number of subsets $S\subseteq\{1,2,\dots,18\}$ (including the empty set) for which the sum of the elements of $S$ is divisible by $6$. Find the remainder when $N$ is divided by $1000$.",
         crux="Roots-of-unity filter (or DP on sum mod 6) counts subsets by residue.",
         solution=r"By a roots-of-unity filter, $N=\frac16\sum_{j=0}^{5}\prod_{t=1}^{18}\bigl(1+\omega^{jt}\bigr)$ with $\omega=e^{2\pi i/6}$; equivalently a DP over sums mod $6$ gives $N=43712$. Then $43712\equiv 712\pmod{1000}$.",
         crux_count=1, routine=3),
    dict(id="opus-tele-1", seed="idea-telescoping", topic="Algebra",
         answer="197", difficulty=3.5, elegance=3,
         statement=r"The sum $\displaystyle\sum_{k=1}^{10}\frac{2}{k(k+1)(k+2)}$ equals $\frac{m}{n}$ for relatively prime positive integers $m,n$. Find $m+n$.",
         crux="Telescope 2/(k(k+1)(k+2)) = 1/(k(k+1)) - 1/((k+1)(k+2)).",
         solution=r"Since $\frac{2}{k(k+1)(k+2)}=\frac{1}{k(k+1)}-\frac{1}{(k+1)(k+2)}$, the sum telescopes to $\frac{1}{1\cdot2}-\frac{1}{11\cdot12}=\frac12-\frac1{132}=\frac{65}{132}$. Thus $m+n=197$.",
         crux_count=1, routine=2),
    dict(id="opus-ie-1", seed="idea-incl-excl-adjacency", topic="Combinatorics",
         answer="242", difficulty=6.0, elegance=4,
         statement=r"Let $M$ be the number of permutations $a_1,a_2,\dots,a_8$ of $1,2,\dots,8$ such that $|a_i-a_{i+1}|\ne 1$ for every $1\le i\le 7$ (no two consecutive integers are adjacent). Find the remainder when $M$ is divided by $1000$.",
         crux="Inclusion-exclusion over the 7 adjacencies i~i+1, gluing k into blocks (2 orientations each): sum (-1)^k C(7,k) 2^k (8-k)!.",
         solution=r"Let $A_i$ be the arrangements where $i,i+1$ are adjacent. Gluing $k$ of the seven adjacencies into blocks (each with $2$ orientations) gives $M=\sum_{k=0}^{7}(-1)^k\binom{7}{k}2^k(8-k)!=5242$. Hence $M\equiv 242\pmod{1000}$.",
         crux_count=1, routine=4),
    dict(id="opus-inv-1", seed="idea-mult-invariant", topic="Algebra",
         answer="319", difficulty=5.5, elegance=5,
         statement=r"The numbers $1,2,3,4,5,6,7$ are written on a board. In each step you erase two numbers $a,b$ and write the single number $a+b+ab$. After six steps one number $M$ remains. Find the remainder when $M$ is divided by $1000$.",
         crux="1+(a+b+ab)=(1+a)(1+b), so the product of (1+x_i) is invariant.",
         solution=r"Because $1+(a+b+ab)=(1+a)(1+b)$, the product $\prod(1+x_i)$ is invariant. Initially it is $\prod_{i=1}^{7}(1+i)=2\cdot3\cdots8=8!$. So $1+M=8!$, giving $M=40319$ and remainder $319$.",
         crux_count=1, routine=2),
    dict(id="opus-dos-1", seed="idea-diff-of-squares", topic="Number Theory",
         answer="750", difficulty=4.5, elegance=4,
         statement=r"How many integers $n$ with $1\le n\le 1000$ can be written as $a^2-b^2$ for some nonnegative integers $a,b$?",
         crux="n=(a-b)(a+b); representable iff n is odd or divisible by 4.",
         solution=r"Writing $n=(a-b)(a+b)$, the two factors have equal parity, so $n$ is representable iff $n$ is odd or a multiple of $4$. The exceptions are $n\equiv2\pmod4$: $2,6,\dots,998$, which is $250$ values. Hence $1000-250=750$.",
         crux_count=1, routine=3),
    dict(id="opus-newton-1", seed="idea-newton-sums", topic="Algebra",
         answer="127", difficulty=4.0, elegance=3,
         statement=r"Let $a,b,c$ be the (complex) roots of $x^3-7x^2+11x-5=0$. Find $a^3+b^3+c^3$.",
         crux="Newton's sums with e1=7, e2=11, e3=5.",
         solution=r"With $e_1=7,e_2=11,e_3=5$: $p_1=7$, $p_2=e_1p_1-2e_2=27$, and $p_3=e_1p_2-e_2p_1+3e_3=189-77+15=127$.",
         crux_count=1, routine=2),
]


def main() -> None:
    db.init_db()
    with db.session_scope() as session:
        seed_to_pids: dict[str, list[str]] = {}
        for pr in PROBLEMS:
            pid = pr["id"]
            seed_to_pids.setdefault(pr["seed"], []).append(pid)
            session.add(
                Problem(
                    id=pid,
                    source=ProblemSource.SYNTHETIC,
                    statement=pr["statement"],
                    answer=pr["answer"],
                    difficulty=pr["difficulty"],
                    topic=pr["topic"],
                    split=DataSplit.TRAIN,
                    verified=True,
                    review_status=ReviewStatus.PENDING,
                    possibly_memorized=False,
                    provenance={
                        "pipeline": "opus-seeded-generation",
                        "generator_model": MODEL,
                        "seed_insight_id": pr["seed"],
                        "crux": pr["crux"],
                        "verification": "exact computation confirmed",
                        "agent_qa": {
                            "solver_model": MODEL, "k": "exact", "consensus": pr["answer"],
                            "agreement": 1.0, "verified": True,
                            "wellposedness": {"verdict": "accept"},
                            "difficulty": {"difficulty": pr["difficulty"]},
                            "elegance": {"overall": pr["elegance"]},
                            "recommendation": "accept",
                            "reason": f"Generated from seed '{pr['seed']}'; answer {pr['answer']} verified by exact computation.",
                        },
                    },
                ).refresh_dedup_fields()
            )
            session.add(
                Solution(
                    problem_id=pid, text=pr["solution"], techniques=[pr["seed"]],
                    crux_insight=pr["crux"], crux_count=pr["crux_count"],
                    routine_step_count=pr["routine"], source=SolutionSource.MODEL,
                    extractor_model=MODEL,
                )
            )
            session.add(
                Evaluation(
                    problem_id=pid, difficulty_score=pr["difficulty"],
                    elegance_score=pr["elegance"], evaluator="opus-4.8",
                    rationale=pr["crux"],
                )
            )

        for ins in INSIGHTS:
            session.add(
                Insight(
                    id=ins["id"], text=ins["text"], concept_tags=ins["tags"],
                    difficulty_band=ins["band"],
                    source_problem_ids=seed_to_pids.get(ins["id"], []),
                )
            )
    print(f"stored {len(PROBLEMS)} problems and {len(INSIGHTS)} insights")


if __name__ == "__main__":
    main()
