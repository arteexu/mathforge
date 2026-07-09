# wild_insight_v1
# Phase 3, invented tranche — cap at ~15% of the bank. Temperature 0.9. JSON only.
# Every output still goes through insight_vagueness_check before entering the bank.

You are a competition problem-setter collecting raw material. Produce surprising, ELEMENTARY observations at the intersection of the given concept areas — facts a strong AIME student would not immediately think of, but could verify in a few lines once stated. Each should be usable as the crux of a problem.

Requirements per insight:
- Elementary: provable with pre-calculus contest tools (no heavy machinery name-drops).
- Surprising: connects two things not obviously related, or inverts a familiar pattern.
- Generative: you can immediately imagine a problem that falls to it.
- NOT a named theorem's statement verbatim (those are known to strong students; a non-obvious *consequence* or *combination* of named results is fine).

## Input

CONCEPT AREAS: {{concept_tags}}
COUNT: {{n}}

## Output — JSON only

{
  "insights": [
    {
      "insight": "<1-3 sentences>",
      "why_surprising": "<one sentence>",
      "sketch_of_use": "<one sentence: the kind of problem it would seed>",
      "verification_sketch": "<one sentence: why it's true>"
    }
  ]
}
