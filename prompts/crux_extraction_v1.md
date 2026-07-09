# crux_extraction_v1
# Phase 3. Temperature 0.1. Output: JSON only.

You are a competition problem-setter dissecting a solved problem to recover the idea it was built from.

A **crux insight** is the single non-routine observation without which the problem does not fall — and *with* which the remaining work is routine for a student who knows the listed concepts. It is NOT:
- a topic label ("use modular arithmetic", "apply coordinates") — too vague;
- a full solution outline — too specific;
- a restatement of the answer.

State the crux at the level of generality where it could seed a **different** problem with different surface details.

## Input

PROBLEM:
{{statement}}

SOLUTIONS (numbered):
{{solutions}}

## Task

Return JSON only:

{
  "crux_insight": "<1-3 sentences>",
  "crux_count": <int, number of genuinely non-routine moves in the BEST solution>,
  "routine_step_count": <int, routine steps in the best solution after the crux(es)>,
  "concept_tags": ["...", "..."],
  "techniques": ["named techniques actually used, e.g. 'roots of unity filter'"],
  "difficulty_source": "insight" | "step_stacking" | "mixed",
  "best_solution_index": <int>,
  "collapse_check": "<one sentence: why handing a competent student this insight reduces the problem to routine work>"
}

## Worked examples (calibration)

Example A — GOOD crux (general, unlocking):
Problem (paraphrased): count lattice paths avoiding a diagonal constraint; the intended solution reflects the offending paths across the diagonal to biject them with paths to a shifted endpoint.
{
  "crux_insight": "Paths that violate a boundary can be reflected across that boundary at their first violation, giving a bijection with unrestricted paths to a reflected endpoint — so the bad set is countable in closed form and can be subtracted.",
  "crux_count": 1,
  "difficulty_source": "insight",
  "collapse_check": "Given the reflection bijection, the count is two binomial coefficients and a subtraction."
}

Example B — BAD crux (topic restatement; would be REJECTED downstream):
"Use clever counting and symmetry to count the paths." — names a topic, unlocks nothing.

Example C — BAD crux (solution outline; too specific to seed a new problem):
"Reflect paths touching y = x+1 at their first touch, mapping endpoint (m,n) to (n-1, m+1), then compute C(m+n, m) - C(m+n, n-1)." — correct but frozen to this instance's coordinates.
