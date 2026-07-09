# problem_repair_v1
# Repair a draft whose stated answer failed verification. Temperature 0.2-0.4.
# Trust the independent solver's reasoning; make the PROBLEM match a correct solution.

An independent solver worked the DRAFT problem below and reached the solution and answer shown. Its stated draft answer did not verify. Trust the solver's reasoning as correct.

Produce a CORRECTED problem statement that is well-posed and whose unique correct answer is EXACTLY the solver's answer. Change as little as possible — adjust the givens/constraints/numbers so the intended answer becomes the solver's answer — and keep the problem elegant and self-contained. Do not introduce ambiguity. The answer must remain a single integer from 0 to 999.

DRAFT PROBLEM:
{{statement}}

SOLVER SOLUTION (treat as correct):
{{solution}}

SOLVER ANSWER: {{answer}}

## Output format (use exactly these tags, nothing else)

<statement>
the corrected, well-posed problem statement
</statement>
<answer>{{answer}}</answer>
