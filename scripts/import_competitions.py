"""Import real competition problems (AMC/AIME/AoPS/olympiad) from HuggingFace.

A source REGISTRY maps each dataset to the mathforge Problem schema. Only rows with
a solution are kept (crux extraction needs it); figures/trivial rows are dropped;
duplicates are skipped by statement_hash. Per-row commit -> idempotent/resumable.

Usage:
    PYTHONPATH=src python scripts/import_competitions.py <source|all> <limit_per_source>
e.g. PYTHONPATH=src python scripts/import_competitions.py math 300
"""

from __future__ import annotations

import re
import sys
import uuid

from datasets import load_dataset
from sqlmodel import select

from mathforge import db
from mathforge.schema import (
    DataSplit, Problem, ProblemSource, ReviewStatus, Solution, SolutionSource,
    statement_hash,
)


def _boxed(text: str):
    m = re.findall(r"\\boxed\{([^{}]+)\}", text or "")
    return m[-1].strip() if m else None


def _lvl_to_diff(level: str):
    m = re.search(r"\d+", str(level) or "")
    return round(1.2 * int(m.group()) + 1, 1) if m else None   # MATH level 1-5 -> ~2.2..7.0


# --- per-source mappers: raw row -> normalized dict (or None to skip) --------- #
def _map_math(r, subject):
    lvl = r.get("level", "")
    if (re.search(r"\d+", str(lvl)) or [None]) and int(re.search(r"\d+", str(lvl)).group()) < 4:
        return None                                            # keep competition-grade only
    sol = r.get("solution") or ""
    if not sol.strip():
        return None
    return dict(statement=r["problem"], solution=sol, answer=_boxed(sol),
                topic=(r.get("type") or subject or "").strip() or None,
                difficulty=_lvl_to_diff(lvl), source=ProblemSource.OTHER_COMPETITION,
                prov={"competition": "MATH/AoPS", "level": str(lvl)})


def _map_aime(r):
    stmt = r.get("Problem") or r.get("problem")
    sol = r.get("Solution") or r.get("solution") or ""
    ans = r.get("Answer") or r.get("answer")
    if not (stmt and str(sol).strip()):
        return None
    return dict(statement=stmt, solution=str(sol), answer=(str(ans) if ans is not None else None),
                topic=None, difficulty=7.0, source=ProblemSource.AIME,
                prov={"competition": "AIME"})


def _map_olympiadbench(r):
    if any(r.get(k) for k in ("image_1", "image_2", "image_3")):
        return None                                            # skip figure problems
    stmt = r.get("question"); sol = r.get("solution") or ""
    if not (stmt and str(sol).strip()):
        return None
    fa = r.get("final_answer")
    ans = ", ".join(map(str, fa)) if isinstance(fa, list) else (str(fa) if fa else None)
    return dict(statement=stmt, solution=str(sol), answer=ans, topic=None, difficulty=7.5,
                source=ProblemSource.OTHER_COMPETITION,
                prov={"competition": "OlympiadBench", "raw": str(r.get("context") or "")[:80]})


REGISTRY = {
    # key: (hf_id, config, split, mapper, id_prefix)
    "math_nt":   ("EleutherAI/hendrycks_math", "number_theory", "test",
                  lambda r: _map_math(r, "Number Theory"), "math"),
    "math_alg":  ("EleutherAI/hendrycks_math", "algebra", "test",
                  lambda r: _map_math(r, "Algebra"), "math"),
    "math_count":("EleutherAI/hendrycks_math", "counting_and_probability", "test",
                  lambda r: _map_math(r, "Combinatorics"), "math"),
    "math_geo":  ("EleutherAI/hendrycks_math", "geometry", "test",
                  lambda r: _map_math(r, "Geometry"), "math"),
    "math_inter":("EleutherAI/hendrycks_math", "intermediate_algebra", "test",
                  lambda r: _map_math(r, "Intermediate Algebra"), "math"),
    "math_precalc":("EleutherAI/hendrycks_math", "precalculus", "test",
                  lambda r: _map_math(r, "Precalculus"), "math"),
    "aime2024":  ("Maxwell-Jia/AIME_2024", None, "train", _map_aime, "aime"),
    "aime_val":  ("AI-MO/aimo-validation-aime", None, "train", _map_aime, "aime"),
    "olympiad":  ("Hothan/OlympiadBench", "OE_TO_maths_en_COMP", "train", _map_olympiadbench, "olymp"),
}


def _load_seen():
    with db.session_scope() as ses:
        return set(ses.exec(select(Problem.statement_hash)).all())


def run_source(key, limit, seen):
    hf, cfg, split, mapper, prefix = REGISTRY[key]
    ds = load_dataset(hf, cfg, split=split) if cfg else load_dataset(hf, split=split)
    kept = skipped = dup = 0
    for r in ds:
        if limit and kept >= limit:
            break
        norm = mapper(r)
        if norm is None:
            skipped += 1
            continue
        sh = statement_hash(norm["statement"])
        if sh in seen:
            dup += 1
            continue
        seen.add(sh)
        pid = f"{prefix}-{uuid.uuid4().hex[:8]}"
        with db.session_scope() as s:
            s.add(Problem(
                id=pid, source=norm["source"], statement=norm["statement"],
                answer=norm["answer"], difficulty=norm["difficulty"], topic=norm["topic"],
                split=DataSplit.TRAIN, review_status=ReviewStatus.PENDING,
                provenance={"pipeline": "import", "dataset": hf, "source_key": key, **norm["prov"]},
            ).refresh_dedup_fields())
            s.add(Solution(problem_id=pid, text=norm["solution"], source=SolutionSource.HUMAN,
                           extractor_model=hf))
        kept += 1
    print(f"[{key}] {hf}: kept {kept}, skipped {skipped}, dup {dup}", flush=True)
    return kept


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    db.init_db()
    seen = _load_seen()
    keys = list(REGISTRY) if which == "all" else [which]
    total = sum(run_source(k, limit, seen) for k in keys)
    print(f"done: imported {total} problems across {len(keys)} source(s)", flush=True)


if __name__ == "__main__":
    main()
