# insight_merge_v1
# Phase 3, run per embedding cluster. Temperature 0.1. JSON only.

You are canonicalizing a cluster of crux insights that embedding similarity flagged as near-duplicates. They were extracted from different problems and may be (a) the same idea in different words, (b) genuinely different ideas that share vocabulary, or (c) one general idea plus special cases of it.

Rules:
- Merge only insights that are the SAME generative idea — a problem-setter seeded with the canonical form could produce all the source problems.
- A special case merges into its generalization; note it in `subsumed_variants`.
- When in doubt, do NOT merge. False merges destroy family diversity; false splits are harmless.
- The canonical statement should be the most general form that still passes the collapse test for every source problem.

## Input

CLUSTER (each with id, insight text, source problem ids):
{{cluster}}

## Output — JSON only

{
  "groups": [
    {
      "canonical_insight": "<1-3 sentences, most general valid form>",
      "member_ids": ["..."],
      "subsumed_variants": ["<special-case phrasings folded in>"],
      "concept_tags": ["..."]
    }
  ],
  "kept_separate": [
    {"id": "...", "reason": "<why it is a different idea despite similar wording>"}
  ]
}
