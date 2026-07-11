# MathForge — Insight Bank & Technique-Combination Pipeline

Goal: make the generator **deeper and more diverse** by (A) mining cruxes from real
competition problems, (B) distilling those into a **structured technique taxonomy**,
and (C) generating novel problems by **combining a small number of techniques**.

Reframe: the "insight bank" is a pool of *cruxes*; depth/diversity = **coverage across
distinct techniques**, not raw count. Everything below optimizes coverage, not volume.

> Caveat carried from benchmarking: the binding constraint on output quality is
> **well-posedness (~10%)**, not insight count. This pipeline improves diversity/depth
> and must run *alongside* the validity gate (best-of-N) and DPO — not instead of them.
> Every generation stage here therefore ends in a **well-posedness gate**.

---

## Stage A — Ingest real competition problems  (`scripts/import_competitions.py`)

A **source registry**: each entry maps a HuggingFace dataset to the `Problem` schema.
Verified-loadable sources (this environment can pull them):

| source | HF dataset | fields | coverage | notes |
|---|---|---|---|---|
| MATH (AoPS/AMC/AIME) | `EleutherAI/hendrycks_math` (7 subject configs) | problem, solution, level(1–5), type | large, graded | keep level ≥ 4 for competition-grade |
| AIME | `Maxwell-Jia/AIME_2024`, `AI-MO/aimo-validation-aime` | Problem, Solution, Answer | exact AIME | integer answers |
| Olympiad | `Hothan/OlympiadBench` (`OE_TO_maths_en_COMP`) | question, solution, final_answer | olympiad, open-ended | drop rows with images |
| Olympiad | `KbsdJames/Omni-MATH` | already imported (4,406) | mixed olympiad/TST/SL | — |
| Putnam / HMMT | *(registry slot)* | — | partial via above | no clean solution mirror; flag as TODO |

Normalization → `Problem`: `source` (enum: AMC/AIME/IMO/PUTNAM/OTHER_COMPETITION),
`statement`, `answer` (if short/integer), `difficulty` (map level·k or dataset rating),
`topic`, `provenance={dataset, competition, year, raw_source, level}`.
Store a `Solution` too (needed for crux extraction).

Rules: **require a solution**; drop image/figure problems; drop trivial (`level<4` for MATH);
dedup by `statement_hash` + near-duplicate Jaccard against existing DB; per-row commit
(idempotent/resumable); id prefixes `math-`, `aime-`, `olymp-`, etc.

## Stage B — Extract cruxes  (`scripts/extract_crux.py`, source mode)

Reuse the existing Opus one-line crux extractor, run over the newly imported ids
(prefix filter, no elegance gate). Stored in `provenance["crux"]` + `Solution.crux_insight`.
Concurrent, per-row commit. Idea-level dedup keeps the bank diverse, not just large.

## Stage C — Technique taxonomy  (`scripts/build_technique_taxonomy.py` → `data/techniques.json`)

The heart. Each technique is a rich, combination-ready record:

```json
{
  "id": "nt.lte",
  "name": "Lifting the Exponent (LTE)",
  "area": "Number Theory",
  "family": "p-adic valuation",
  "one_liner": "v_p(a^n ± b^n) = v_p(a±b) + v_p(n) under mild conditions.",
  "trigger": "exponent/divisibility questions on a^n ± b^n",
  "objects": ["integers", "prime powers"],        // what it acts on
  "mechanism": "valuation",                          // how it works
  "difficulty_band": [5.5, 8.5],
  "aliases": ["lifting the exponent"],
  "example_crux": "v_3(R_k)=v_3(k) via LTE, so the product's valuation is v_3(100!).",
  "combinability": {"pairs_well_with": ["nt.crt"], "avoid_with": []},
  "source_count": 0
}
```

Built two ways and **merged**:
- **Top-down** — Opus enumerates named techniques per area (canonical name, `objects`,
  `mechanism`, difficulty band, example). ~300–500 leaves across NT / Combinatorics /
  Algebra / Geometry / Precalc / Probability / Inequalities.
- **Bottom-up** — tag every extracted crux with its technique(s); any crux that matches
  no existing technique proposes a **new** one. Keeps the taxonomy grounded in real
  problems and fills `source_count` (→ a diversity/coverage map).

`objects` + `mechanism` are the levers the combination engine uses.

## Stage D — Technique combination + generation  (`scripts/generate_from_techniques.py`)

Sample **1–3 techniques** (default **2**; 3 only when all pairwise-compatible) and
have Opus (max thinking) compose an original, **well-posed** problem that *genuinely
requires* the combination.

Combination logic ("creative but not clunky"):
- **Compatibility(t1,t2)** high when they share ≥1 `objects` type (can act on the same
  object) but have **different `mechanism`s** (the combo creates a real twist, not
  redundancy). `avoid_with` blocks known-bad pairs.
- **Novelty weighting**: prefer under-used techniques (low `source_count`, not recently
  used) → pushes into gaps, increasing diversity.
- **Cap**: 2 by default; allow 3 only if pairwise-compatible and combined difficulty ≤ target.
- **Essentiality**: prompt demands each technique be load-bearing (removing one breaks
  the problem); the solution's crux must name how the techniques interact.
- **Validity gate**: every candidate passes the Opus well-posed/non-trivial check
  (from best-of-N) before it is stored. Reject clunky/contrived combos.

Stored as `distill-combo-` rich problems with `provenance={techniques, crux, elegance}`,
feeding the same weighted training export.

## Diversity measurement (do this throughout)

Group cruxes by assigned technique → **coverage report** (which areas/techniques are
over/under-represented). Target generation at gaps. Bigger ≠ deeper; coverage is the metric.

## Phased rollout

1. Import MATH(level≥4) + AIME + OlympiadBench → extract cruxes (bulk of the bank).
2. Build taxonomy v1 (top-down Opus) → tag imported cruxes (bottom-up) → coverage report.
3. Combination generator + validity gate → first `distill-combo-` batch → blind-judge vs current.
4. Fold survivors into the weighted training set; retrain; re-run the 30-pair benchmark.
