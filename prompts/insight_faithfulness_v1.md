# insight_faithfulness_v1
# Phases 4-5, runs AFTER answer consistency passes. Temperature 0.1. JSON only.
# Reads the INDEPENDENT solver transcripts, not the setter's intended solution — the question is what the problem
# actually requires, not what the setter hoped.

A problem was generated from a seed insight. Independent solvers (who never saw the seed) have solved it. Determine whether the problem genuinely requires the seeded insight, or whether it can be finished by routine methods / a different idea.

Definitions:
- **faithful**: the majority of successful independent solutions pivot on the seeded insight (possibly in different words).
- **bypassed**: successful solutions mostly use routine methods or a different, easier idea — the seed is decoration.
- **partial**: the seed is used but only as a minor step; the main difficulty lies elsewhere.

Judge by the mathematical content of the solve, not by vocabulary overlap with the seed text.

## Input

SEED INSIGHT:
{{insight}}

PROBLEM:
{{statement}}

INDEPENDENT SOLUTIONS (successful ones, numbered):
{{independent_solutions}}

## Output — JSON only

{
  "per_solution": [
    {"index": 1, "pivots_on_seed": true, "pivot_quote": "<shortest excerpt showing the pivotal move>"}
  ],
  "verdict": "faithful" | "bypassed" | "partial",
  "bypass_description": "<if bypassed/partial: the easier route that works, one sentence>",
  "repair_hint": "<if bypassed: one sentence on how the statement could close the bypass, for regeneration>"
}
