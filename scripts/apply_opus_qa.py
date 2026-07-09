"""One-off: write Claude Opus 4.8's in-chat verification verdicts to the DB.

Each verdict was derived by hand + exact Python computation (see chat), not an API
solver. Records an ``agent_qa`` provenance blob (evaluator = the in-chat model) and
sets ``verified`` accordingly; leaves ``review_status`` to the human.
"""

from mathforge import db
from mathforge.schema import Evaluation, Problem, Solution, SolutionSource

MODEL = "claude-opus-4.8 (in-chat)"

# keyed by the distill id suffix
VERDICTS = {
    "cfafbb6a": dict(verified=False, consensus=None, wellposed="reject", rec="reject",
        reason="No solution: digit sum 19 => n=1 (mod 9), so n+19=2 (mod 9) but 4*rev(n)=4 (mod 9). Unsatisfiable."),
    "5e971726": dict(verified=False, consensus=None, wellposed="reject", rec="reject",
        reason="Statement is corrupted/non-mathematical. Not a valid problem."),
    "351c0b26": dict(verified=False, consensus=None, wellposed="reject", rec="reject",
        reason="Answer not unique: (0,3,3)->6 and (1.2,1.2,3.6)->3.84 both satisfy the constraints. Ill-posed."),
    "01bad116": dict(verified=False, consensus="101", wellposed="accept", rec="fix_answer",
        reason="Well-posed; correct a_100 = 101 (stored 384 is wrong).", difficulty=5.0, elegance=3),
    "aa38a7b4": dict(verified=False, consensus="1024", wellposed="repair", rec="needs_edit",
        reason="Math correct: E[X]=793/231, m+n=1024 -- but 1024 is outside the AIME 0-999 range (stored 847 wrong).",
        difficulty=5.5, elegance=4),
    "13558d56": dict(verified=False, consensus=None, wellposed="reject", rec="reject",
        reason="cos20+cos40+cos80 = 2cos20, so x*sin20 = sin40 is irrational -- no rational m/n exists. Ill-posed."),
    "259e1b15": dict(verified=False, consensus="1", wellposed="accept", rec="fix_answer",
        reason="Well-posed; exactly 1 value of n<=999 works (stored 9 wrong).", difficulty=5.0, elegance=3),
    "c38f1a9c": dict(verified=True, consensus="0", wellposed="accept", rec="accept",
        reason="Verified: 0 such fillings (exhaustive search). Clean impossibility result.", difficulty=6.0, elegance=4),
    "cddabc19": dict(verified=True, consensus="22", wellposed="accept", rec="accept",
        reason="Verified a_2025 = 22 by direct simulation.", difficulty=4.0, elegance=2),
    "20d146f4": dict(verified=False, consensus="7", wellposed="accept", rec="fix_answer",
        reason="Well-posed Penney's game; P(HHH before HTH)=2/5, so m+n=7 (stored 13 wrong).",
        difficulty=5.0, elegance=4),
    "56e80bd4": dict(verified=True, consensus="6", wellposed="accept", rec="accept",
        reason="Verified: 111111 = 37*3003, six 1's, 6 digits.", difficulty=3.0, elegance=2),
    "451dff87": dict(verified=False, consensus="191", wellposed="accept", rec="fix_answer",
        reason="Well-posed; correct count = 191 (stored 124 wrong).", difficulty=5.0, elegance=3),
    "d9912704": dict(verified=False, consensus=None, wellposed="reject", rec="reject",
        reason="100*AP*AQ = 100*(127/15)*(71/13) ~= 4624.10 -- not an integer and >999. Answer-format invalid."),
    "7208aab2": dict(verified=False, consensus=None, wellposed="reject", rec="reject",
        reason="Unique positive solution gives xyz~=686, so 100(xyz-1)~=68500 -- irrational and far outside 0-999. Ill-posed."),
}


def main() -> None:
    from sqlmodel import select

    db.init_db()
    updated = 0
    with db.session_scope() as session:
        for p in session.exec(select(Problem)).all():
            suffix = p.id.replace("distill-", "")
            v = VERDICTS.get(suffix)
            if v is None:
                continue
            p.verified = v["verified"]
            prov = dict(p.provenance or {})
            prov["agent_qa"] = {
                "solver_model": MODEL,
                "k": "exact",
                "consensus": v["consensus"],
                "agreement": 1.0,
                "verified": v["verified"],
                "wellposedness": {"verdict": v["wellposed"]},
                "difficulty": {"difficulty": v.get("difficulty")},
                "elegance": {"overall": v.get("elegance")},
                "recommendation": v["rec"],
                "reason": v["reason"],
            }
            p.provenance = prov
            session.add(p)
            if v.get("difficulty") is not None:
                session.add(
                    Evaluation(
                        problem_id=p.id,
                        difficulty_score=v.get("difficulty"),
                        elegance_score=v.get("elegance"),
                        evaluator="opus-4.8",
                        rationale=v["reason"][:500],
                    )
                )
            if v["consensus"] is not None:
                session.add(
                    Solution(
                        problem_id=p.id,
                        text=f"[opus-4.8 in-chat verification] correct answer = {v['consensus']}. {v['reason']}",
                        source=SolutionSource.SOLVER_PANEL,
                        extractor_model=MODEL,
                    )
                )
            updated += 1
    print(f"applied verdicts to {updated} problems")


if __name__ == "__main__":
    main()
