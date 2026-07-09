# independent_solver_v1
# Phases 1, 4-5. Run k=4-6 independent samples at temperature 0.6-0.7. Tagged output.
# CRITICAL: the solver must NEVER see the intended solution, the seed insight, or other samples' outputs.

Solve the following competition problem. Work carefully and completely; if the problem is ambiguous, under-constrained, or appears to have no valid answer, say so instead of guessing.

PROBLEM:
{{statement}}

Instructions:
- Reason step by step, fully.
- The answer should be an integer from 0 to 999. If your result is not such an integer, report what you got and flag it.
- If you recognize this as an existing contest problem you have seen before, still solve it fully, and set the recognition flag.

## Output format (end your response with exactly this block)

<verdict>
final_answer: <integer 0-999, or "NONE">
confidence: <"high" | "medium" | "low">
ambiguity_flag: <true | false>
ambiguity_note: <"" or one sentence>
recognized_as_existing: <true | false>
</verdict>

# Harness notes (not part of the prompt):
# - Strict majority of k samples must agree AND match the intended answer → pass.
# - Any ambiguity_flag=true → route to wellposedness check regardless of answer agreement.
# - recognized_as_existing=true on a SYNTHETIC problem → route to dedupe review (likely regurgitation).
