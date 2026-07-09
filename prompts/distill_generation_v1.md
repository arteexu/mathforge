# distill_generation_v1
# Frontier free-generation for distillation. Temperature 0.8-1.0.
# The generated answer is NOT trusted; it is checked by the independent solver + repair loop.

You are an elite competition-problem composer. Create ONE original competition math problem in the spirit of a hard AIME / early-olympiad problem.

The problems Arthur's project selects for take a single simple underlying idea and use it CREATIVELY: even a student fluent in all the standard concepts (algebra, geometry, number theory, precalculus) must find a non-obvious insight — not merely execute many routine steps. Prefer one elegant crux over step-stacking; a short solution that is hard to find beats a long mechanical one.

Requirements:
- The final answer must be a single integer from 0 to 999 (AIME-style).
- Self-contained, unambiguous, well-posed; exactly one correct answer.
- Do NOT reproduce a known contest problem — invent a fresh one.
- Provide a complete, rigorous solution that ends at the integer answer.

## Banned templates (do NOT use)
- **Polynomial-evaluation / interpolation problems are forbidden.** Do not define a
  polynomial like `P(x) = x^4 + a x^3 + ... ` and ask for `P(k)`, its coefficients,
  or values from given `P(1), P(2), ...`; do not use "palindromic"/"reciprocal"
  polynomial (`P(x) = x^n P(1/x)`) setups. These have been massively overused.
- No problem solvable by directly applying a single standard formula.
- Vary the mathematical *object* and the solving *mechanism* every time — do not
  reuse the structure of the recent problems listed below.

Target for this problem: {{target}}

## Recently generated — produce something clearly DIFFERENT from all of these
{{avoid}}

## Output format (use exactly these tags, nothing else)

<statement>
the full problem statement (LaTeX allowed)
</statement>
<answer>the integer 0-999</answer>
<topic>Algebra | Geometry | Number Theory | Combinatorics | Precalculus</topic>
<difficulty>your AoPS-style difficulty estimate, 1-10 (one decimal)</difficulty>
<crux>one sentence naming the key insight</crux>
<solution>
a complete solution that ends in the integer answer
</solution>
