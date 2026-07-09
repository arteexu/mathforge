# insight_vagueness_check_v1
# Phase 3, run on every extracted crux. Temperature 0.0. JSON only.

You are auditing a candidate "crux insight" extracted from a competition problem.

An insight PASSES only if it satisfies BOTH tests:

1. **Collapse test:** a strong student who knows the listed concepts, handed this insight, would find the rest of the problem routine. (If the problem stays hard even with the insight, the insight is incomplete.)
2. **Generativity test:** the insight is stated generally enough that a problem-setter could build a *different* problem around it, with different objects and numbers. (If it references this problem's specific values, endpoints, or named quantities, it is a solution fragment, not an insight.)

Automatic FAIL categories:
- Topic or technique name alone ("use generating functions", "apply Vieta").
- Restates the question or the answer.
- A list of steps.

## Input

PROBLEM:
{{statement}}

CANDIDATE INSIGHT:
{{insight}}

CONCEPT TAGS: {{concept_tags}}

## Output — JSON only

{
  "collapse_test": "pass" | "fail",
  "generativity_test": "pass" | "fail",
  "verdict": "accept" | "reject",
  "failure_category": "topic_restatement" | "solution_fragment" | "incomplete" | "answer_leak" | null,
  "rationale": "<one sentence>"
}
