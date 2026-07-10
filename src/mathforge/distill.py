"""Distill verified, judged problems from a frontier model.

Per problem:

1. **Generate** an original AIME-hard/olympiad problem (``distill_generation_v1``).
2. **Verify** by solving it independently ``k`` times (``independent_solver_v1``)
   and taking a strict-majority answer. If it matches the drafted answer, the
   problem is verified.
3. **Repair** on mismatch: rewrite the problem so its answer equals the solver's
   consensus (``problem_repair_v1``), then re-verify once. Unrepairable drafts
   are discarded (likely broken).
4. **Judge** elegance (0-5) and difficulty (1-10) with the calibrated judges.
5. **Store** survivors as SYNTHETIC problems with ``review_status=pending`` for
   the human to check.

Generator / solver / judge are independent :class:`~mathforge.llm.LLMClient`s, so
you can (and should) verify with a *different* model family than you generate
with. Every call is logged to ``LLMCall``.
"""

from __future__ import annotations

import json
import re
import uuid
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlmodel import select

from mathforge import db
from mathforge.llm import LLMClient
from mathforge.prompts import (
    DIFFICULTY_JUDGE_V1,
    ELEGANCE_JUDGE_V1,
    INDEPENDENT_SOLVER_V1,
    render_prompt,
)
from mathforge.schema import (
    DataSplit,
    Evaluation,
    Problem,
    ProblemSource,
    ReviewStatus,
    Solution,
    SolutionSource,
    statement_hash,
)
from mathforge.solver import check_answer, normalize_answer, parse_solver_verdict

__all__ = [
    "DEFAULT_TARGET",
    "DistillReport",
    "generate_problem",
    "is_garbled",
    "token_set",
    "is_near_duplicate",
    "verify_answer",
    "repair_problem",
    "judge_difficulty",
    "judge_elegance",
    "run_distill",
]

DEFAULT_TARGET = (
    "a hard AIME problem (AoPS difficulty ~5-7); choose any topic; one elegant "
    "crux rather than many routine steps."
)

# Rotated to force topic/style diversity across a batch (the fixed single target
# caused mode-collapse onto polynomial-evaluation problems).
DIVERSITY_TOPICS = [
    "Number Theory (divisibility, modular arithmetic, or digits)",
    "Combinatorics / counting",
    "Geometry (triangles, circles, or coordinates)",
    "Algebra WITHOUT polynomial-evaluation (functional equations, systems, inequalities)",
    "Sequences and recursion",
    "Probability / expected value",
    "Trigonometry / precalculus",
]
DIFFICULTY_BANDS = [
    "a hard AIME problem (AoPS difficulty ~5-6)",
    "a late-AIME problem (AoPS difficulty ~6-7)",
    "an AIME #15 / easy-olympiad problem (AoPS difficulty ~7)",
]

# Detects the overused polynomial-evaluation cliché, e.g. "P(x) = ... find P(3)".
_FUNC_OF_X_RE = re.compile(r"[A-Za-z]\s*\(\s*x\s*\)")
_FUNC_EVAL_RE = re.compile(
    r"(find|compute|determine|value of)\s+[A-Za-z]\s*\(|[A-Za-z]\s*\(\s*-?\d+\s*\)\s*=",
    re.IGNORECASE,
)


def _rotate_target(i: int, topics: list[str]) -> str:
    topic = topics[i % len(topics)]
    band = DIFFICULTY_BANDS[(i // len(topics)) % len(DIFFICULTY_BANDS)]
    return (
        f"Topic area: {topic}. Aim for {band}. Build the problem on ONE non-obvious "
        "insight; avoid step-stacking; do NOT use any polynomial-evaluation template."
    )


def _avoid_block(recent: list[str], window: int = 28) -> str:
    if not recent:
        return "(none yet — this is the first problem)"
    return "\n".join(f"- {sig}" for sig in recent[-window:])


def is_banned_template(statement: Optional[str]) -> bool:
    """True for the overused 'define f(x)/P(x) and evaluate it' cliché."""
    s = statement or ""
    return bool(_FUNC_OF_X_RE.search(s)) and bool(_FUNC_EVAL_RE.search(s))


# --------------------------------------------------------------------------- #
# Statement-quality / diversity filters (applied before storing a candidate)
# --------------------------------------------------------------------------- #
# The model sometimes rewrites itself mid-statement ("Wait -- instead, suppose
# ...", "Actually, instead compute ..."). Those statements are unusable.
_GARBLE_RE = re.compile(
    r"\b(?:wait|on second thought|scratch that|let me reconsider"
    r"|ignore the (?:above|previous))\b|actually,\s|instead,\s",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"[a-zA-Z]+")


def is_garbled(statement: Optional[str]) -> bool:
    """True if the statement shows the model second-guessing itself mid-problem."""
    return bool(_GARBLE_RE.search(statement or ""))


def token_set(statement: Optional[str]) -> frozenset:
    """Lowercased alphabetic tokens of a statement (for near-duplicate detection)."""
    return frozenset(_WORD_RE.findall((statement or "").lower()))


def is_near_duplicate(
    sig: frozenset, seen: list[frozenset], threshold: float = 0.75
) -> bool:
    """True if ``sig`` has Jaccard overlap above ``threshold`` with any prior set.

    Catches problems that reuse a whole setup and change only the question or the
    constants (e.g. the recurring ``x + 1/y`` systems), which the exact
    statement-hash misses.
    """
    if not sig:
        return False
    for other in seen:
        union = len(sig | other)
        if union and len(sig & other) / union > threshold:
            return True
    return False


# --------------------------------------------------------------------------- #
# Parsing helpers
# --------------------------------------------------------------------------- #
def _tag(name: str, text: str) -> Optional[str]:
    m = re.search(rf"<{name}>\s*(.*?)\s*</{name}>", text or "", re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else None


def _to_int_answer(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    m = re.search(r"-?\d+", raw)
    if not m:
        return None
    val = int(m.group())
    return str(val) if 0 <= val <= 999 else None


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> Optional[dict]:
    m = _JSON_RE.search(text or "")
    if not m:
        return None
    try:
        return json.loads(m.group())
    except json.JSONDecodeError:
        return None


# --------------------------------------------------------------------------- #
# Steps
# --------------------------------------------------------------------------- #
def generate_problem(
    generator: LLMClient, target: str = DEFAULT_TARGET, avoid: str = ""
) -> dict:
    """Generate one candidate problem; returns parsed fields + cost/call id."""
    prompt = render_prompt(
        "distill_generation_v1", target=target, avoid=avoid or "(none yet)"
    )
    resp = generator.complete(prompt, purpose="distill-generate", temperature=0.9)
    statement = _tag("statement", resp.text)
    solution = _tag("solution", resp.text)
    return {
        "statement": statement,
        "answer": _to_int_answer(_tag("answer", resp.text)),
        "topic": _tag("topic", resp.text),
        "difficulty": _safe_float(_tag("difficulty", resp.text)),
        "crux": _tag("crux", resp.text) or "",
        "solution": solution,
        "ok": bool(statement and solution),
        "cost": resp.cost_usd,
    }


def _safe_float(raw: Optional[str]) -> Optional[float]:
    if raw is None:
        return None
    m = re.search(r"-?\d+(\.\d+)?", raw)
    return float(m.group()) if m else None


def verify_answer(
    solver: LLMClient, statement: str, k: int = 3
) -> dict:
    """Solve ``statement`` ``k`` times; return consensus + per-attempt data.

    ``consensus`` is the strict-majority normalized answer (or ``None``).
    """
    answers: list[Optional[str]] = []
    solutions: list[str] = []
    cost = 0.0
    for _ in range(k):
        resp = solver.complete(
            render_prompt(INDEPENDENT_SOLVER_V1, statement=statement),
            purpose="distill-verify",
            temperature=0.6,
        )
        cost += resp.cost_usd
        verdict = parse_solver_verdict(resp.text)
        answers.append(verdict["final_answer"])
        solutions.append(resp.text)

    counts = Counter(normalize_answer(a) for a in answers if a)
    consensus = None
    if counts:
        top, n = counts.most_common(1)[0]
        if n > k // 2:  # strict majority
            consensus = top
    return {"consensus": consensus, "answers": answers, "solutions": solutions, "cost": cost}


def _solution_for_answer(vr: dict, answer: str) -> str:
    for a, s in zip(vr["answers"], vr["solutions"]):
        if a and normalize_answer(a) == normalize_answer(answer):
            return s
    return vr["solutions"][0] if vr["solutions"] else ""


def repair_problem(
    repairer: LLMClient, statement: str, solution: str, answer: str
) -> dict:
    """Rewrite the problem so its answer equals ``answer`` (the solver consensus)."""
    prompt = render_prompt(
        "problem_repair_v1", statement=statement, solution=solution, answer=answer
    )
    resp = repairer.complete(prompt, purpose="distill-repair", temperature=0.3)
    new_statement = _tag("statement", resp.text)
    return {"statement": new_statement, "cost": resp.cost_usd}


def judge_difficulty(
    judge: LLMClient, statement: str, solution: str, solve_rates: str
) -> dict:
    resp = judge.complete(
        render_prompt(
            DIFFICULTY_JUDGE_V1,
            statement=statement,
            solutions=solution,
            features_json="{}",
            solve_rates=solve_rates,
            possibly_memorized="false",
        ),
        purpose="distill-judge-difficulty",
        temperature=0.0,
    )
    return {"data": _extract_json(resp.text), "cost": resp.cost_usd}


def judge_elegance(judge: LLMClient, statement: str, solution: str) -> dict:
    resp = judge.complete(
        render_prompt(
            ELEGANCE_JUDGE_V1, statement=statement, solutions=solution, features_json="{}"
        ),
        purpose="distill-judge-elegance",
        temperature=0.0,
    )
    return {"data": _extract_json(resp.text), "cost": resp.cost_usd}


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #
@dataclass
class DistillReport:
    generated: int = 0
    parse_failures: int = 0
    template_skipped: int = 0  # banned polynomial-evaluation cliché, not stored
    garbled_skipped: int = 0  # self-correcting/garbled statement, not stored
    near_dup_skipped: int = 0  # too similar to an existing problem, not stored
    raw_stored: int = 0  # generation-only mode (Opus verifies later)
    verified_direct: int = 0
    repaired: int = 0
    unverified: int = 0  # stored but not machine-verified (shown for review)
    stored: int = 0
    duplicates: int = 0
    errors: int = 0
    last_error: Optional[str] = None
    cost_usd: float = 0.0
    records: list[dict] = field(default_factory=list)


def run_distill(
    n: int = 25,
    *,
    generator: LLMClient,
    solver: LLMClient,
    judge: Optional[LLMClient] = None,
    k: int = 3,
    target: Optional[str] = None,
    topics: Optional[list[str]] = None,
    verify: bool = True,
    db_url: Optional[str] = None,
    store: bool = True,
) -> DistillReport:
    """Generate, verify (+repair), judge, and store ``n`` distilled problems.

    ``target=None`` rotates topic/difficulty per problem for diversity; pass an
    explicit ``target`` to force a single fixed target for every problem.

    ``verify=False`` is *generation-only*: diverse candidates are stored raw
    (``verified=None``, pending) without the API solve/repair/judge, ready for a
    stronger out-of-band verifier (e.g. Opus, via ``qa-export`` / ``qa-apply``).
    """
    judge = judge or solver
    topics = topics or DIVERSITY_TOPICS
    db.init_db(db_url)
    report = DistillReport()
    recent: list[str] = []  # signatures of recent problems, to diverge from

    with db.session_scope(db_url) as session:
        seen: set[Optional[str]] = set(
            session.exec(select(Problem.statement_hash)).all()
        )
        # Token-set signatures of every existing statement, for near-dup rejection.
        seen_sigs: list[frozenset] = [
            token_set(s) for s in session.exec(select(Problem.statement)).all() if s
        ]

        for i in range(n):
          try:
            problem_target = target or _rotate_target(i, topics)
            gen = generate_problem(generator, problem_target, avoid=_avoid_block(recent))
            report.generated += 1
            report.cost_usd += gen["cost"]
            if not gen["ok"] or gen["answer"] is None:
                report.parse_failures += 1
                continue

            # Never store the banned polynomial-evaluation cliché (skip early to
            # save verification cost) and log it so we diverge next time.
            if is_banned_template(gen["statement"]):
                report.template_skipped += 1
                recent.append(f"[{gen['topic']}] {gen['statement'][:100]}")
                continue
            # Drop statements where the model second-guessed itself mid-problem.
            if is_garbled(gen["statement"]):
                report.garbled_skipped += 1
                recent.append(f"[{gen['topic']}] {gen['statement'][:100]}")
                continue
            # Drop near-duplicates of anything already generated (motif diversity).
            sig = token_set(gen["statement"])
            if is_near_duplicate(sig, seen_sigs):
                report.near_dup_skipped += 1
                recent.append(f"[{gen['topic']}] {gen['statement'][:100]}")
                continue
            seen_sigs.append(sig)
            recent.append(f"[{gen['topic']}] {gen['statement'][:100]}")

            # Generation-only: store raw candidate for out-of-band verification.
            if not verify:
                shash = statement_hash(gen["statement"])
                if shash in seen:
                    report.duplicates += 1
                    continue
                seen.add(shash)
                report.raw_stored += 1
                rec = {
                    "answer": gen["answer"], "difficulty": gen["difficulty"],
                    "elegance": None, "topic": gen["topic"], "repaired": False,
                    "verified": None,
                }
                if store:
                    pid = f"distill-{uuid.uuid4().hex[:8]}"
                    session.add(
                        Problem(
                            id=pid,
                            source=ProblemSource.SYNTHETIC,
                            statement=gen["statement"],
                            answer=gen["answer"],
                            difficulty=gen["difficulty"],
                            topic=gen["topic"],
                            split=DataSplit.TRAIN,
                            verified=None,
                            review_status=ReviewStatus.PENDING,
                            possibly_memorized=False,
                            provenance={
                                "pipeline": "distill",
                                "mode": "generation_only",
                                "generator_model": generator.model,
                                "target": problem_target,
                                "generated_answer": gen["answer"],
                            },
                        ).refresh_dedup_fields()
                    )
                    session.add(
                        Solution(
                            problem_id=pid,
                            text=gen["solution"],
                            crux_insight=gen["crux"],
                            source=SolutionSource.MODEL,
                            extractor_model=generator.model,
                        )
                    )
                    rec["id"] = pid
                    report.stored += 1
                report.records.append(rec)
                continue

            statement = gen["statement"]
            solution = gen["solution"]
            answer = gen["answer"]
            repaired = False

            vr = verify_answer(solver, statement, k=k)
            report.cost_usd += vr["cost"]
            verified = vr["consensus"] is not None and check_answer(
                vr["consensus"], answer
            )

            if verified:
                report.verified_direct += 1
            elif vr["consensus"] is not None:
                # Repair to match the solver's consensus, then re-verify once.
                rep = repair_problem(
                    judge, statement, _solution_for_answer(vr, vr["consensus"]), vr["consensus"]
                )
                report.cost_usd += rep["cost"]
                if rep["statement"]:
                    vr2 = verify_answer(solver, rep["statement"], k=k)
                    report.cost_usd += vr2["cost"]
                    if vr2["consensus"] is not None and check_answer(
                        vr2["consensus"], vr["consensus"]
                    ):
                        statement = rep["statement"]
                        answer = vr2["consensus"]
                        solution = _solution_for_answer(vr2, answer) or solution
                        verified = True
                        repaired = True
                        report.repaired += 1
            # Dedup on the (possibly repaired) statement.
            shash = statement_hash(statement)
            if shash in seen:
                report.duplicates += 1
                continue
            seen.add(shash)

            # Verified problems are judged; UNVERIFIED ones are stored raw and
            # surfaced for human review (not discarded).
            if verified:
                dj = judge_difficulty(
                    judge, statement, solution, solve_rates=f"strong solver {k}/{k}"
                )
                ej = judge_elegance(judge, statement, solution)
                report.cost_usd += dj["cost"] + ej["cost"]
                dj_data, ej_data = dj["data"], ej["data"]
                difficulty = (dj_data or {}).get("difficulty") or gen["difficulty"]
                elegance = (ej_data or {}).get("overall")
            else:
                report.unverified += 1
                dj_data = ej_data = None
                difficulty = gen["difficulty"]
                elegance = None

            record = {
                "answer": answer,
                "difficulty": difficulty,
                "elegance": elegance,
                "topic": gen["topic"],
                "repaired": repaired,
                "verified": verified,
            }
            report.records.append(record)

            if store:
                pid = f"distill-{uuid.uuid4().hex[:8]}"
                session.add(
                    Problem(
                        id=pid,
                        source=ProblemSource.SYNTHETIC,
                        statement=statement,
                        answer=answer,
                        difficulty=difficulty,
                        topic=gen["topic"],
                        split=DataSplit.TRAIN,
                        verified=verified,
                        review_status=ReviewStatus.PENDING,
                        possibly_memorized=False,
                        provenance={
                            "pipeline": "distill",
                            "generator_model": generator.model,
                            "solver_model": solver.model,
                            "judge_model": judge.model,
                            "k": k,
                            "repaired": repaired,
                            "verified": verified,
                            "target": target,
                            "generated_answer": gen["answer"],
                            "solver_consensus": vr["consensus"],
                            "solver_answers": vr["answers"],
                            "difficulty_judge": dj_data,
                            "elegance_judge": ej_data,
                        },
                    ).refresh_dedup_fields()
                )
                session.add(
                    Solution(
                        problem_id=pid,
                        text=solution,
                        crux_insight=gen["crux"],
                        source=SolutionSource.MODEL,
                        extractor_model=generator.model,
                    )
                )
                if verified:
                    session.add(
                        Evaluation(
                            problem_id=pid,
                            difficulty_score=difficulty,
                            elegance_score=elegance,
                            evaluator="judge_v1",
                            rationale=json.dumps(
                                {"difficulty": dj_data, "elegance": ej_data}
                            )[:2000],
                        )
                    )
                record["id"] = pid
                report.stored += 1
          except Exception as exc:  # one bad/flagged item must not kill the batch
              report.errors += 1
              report.last_error = f"{type(exc).__name__}: {exc}"
              continue

    return report
