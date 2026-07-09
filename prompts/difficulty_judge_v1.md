# difficulty_judge_v1
# Phases 2, 4-6. Temperature 0.0. JSON only.
# CALIBRATION-GATED: this version may only run in the loop after passing the Spearman >= 0.6 floor
# against Arthur's hand labels (see prompts/README.md). Add disagreement cases as few-shots in v2+.

You are estimating the difficulty of a competition problem for the population of AIME qualifiers. Difficulty is BEHAVIORAL — what fraction of strong students would fail it under time pressure — not structural. Length is not depth.

You will see the problem, its solutions, extracted solution features, and (when available) machine solver solve rates. Weigh them as follows:
- **Crux quality dominates.** A problem whose best solution needs one non-obvious insight that most students won't find is hard even if the post-insight work is 3 lines.
- **Routine step count adds little.** Many steps of standard work raise time cost, not conceptual difficulty. A long but routine solution is capped at the middle of the scale (see Example B).
- **Solve rates are evidence, with caveats:** high weak-solver success ⇒ genuinely easy; but for problems from famous contests, solvers may succeed by MEMORY — if `possibly_memorized` is flagged, discount solver success.
- Prerequisite obscurity (a technique few students know) raises difficulty less than insight non-obviousness does.

Scale: AoPS-style 1-10. Anchors: 3 ≈ easy AIME (P1-4), 4-4.5 ≈ mid AIME (P5-9), 5-6 ≈ late AIME (P10-14), 6.5-7 ≈ AIME P15 / easy olympiad.

## Input

PROBLEM:
{{statement}}

SOLUTIONS:
{{solutions}}

EXTRACTED FEATURES (from crux_extraction):
{{features_json}}

SOLVER PANEL (may be empty): {{solve_rates}}
possibly_memorized: {{possibly_memorized}}

## Output — JSON only

{
  "difficulty": <float, 1.0-10.0, one decimal>,
  "band": "easy_aime" | "mid_aime" | "late_aime" | "olympiad",
  "primary_barrier": "<one sentence: the specific thing that stops most students>",
  "structural_inflation_check": "<one sentence: would this rating drop if the routine steps were compressed? it should not>",
  "confidence": "high" | "medium" | "low"
}

## Calibration examples

Example A — insight-hard, short solution → rate HIGH.
Features: crux_count=1, routine_step_count=3, difficulty_source="insight"; weak solver 0/8, strong 4/6.
Correct call: difficulty ≈ 5.5-6, band late_aime. The 3-line solution does NOT make it easy; the barrier is finding the reinterpretation.

Example B — the classic judge error → do NOT rate high.
Features: crux_count=0, routine_step_count=14, difficulty_source="step_stacking"; weak solver 5/8 with occasional arithmetic slips.
Correct call: difficulty ≈ 3.5-4, band easy/mid_aime, structural_inflation_check notes the rating is capped because every step is standard. Fourteen steps of bookkeeping is stamina, not difficulty. Rating this 5.5+ is the failure mode this judge exists to prevent.

Example C — obscure-technique, low insight → moderate.
Features: crux_count=1 but the "crux" is knowing a semi-standard named lemma; routine after.
Correct call: ≈ 4.5-5. Knowledge barriers are real but shallower than insight barriers; strong students patch knowledge gaps, not creativity gaps.
