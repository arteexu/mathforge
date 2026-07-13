# MathForge basic behavior evaluation — Opus-blind-judged pilot

## Result

This 24-pair pilot does **not** show the SLM beating the frontier model. Claude
Opus 4.8 preferred the frontier output in 20/24 pairs, the SLM in
4/24, with 0 ties. All four SLM wins occurred when both
outputs were still judged mathematically invalid.

| Metric | SLM | Frontier |
|---|---:|---:|
| Valid | 0/24 | 1/24 |
| Repairable | 0/24 | 2/24 |
| Invalid | 24/24 | 21/24 |
| Mean technique interaction (1–5) | 1.167 | 2.458 |
| Mean novelty (1–5) | 1.292 | 2.375 |
| Mean elegance (1–5) | 1.083 | 2.125 |
| Difficulty pass | 0/24 | 3/24 |
| Content-gate pass | 0/24 | 1/24 |
| Strict format pass | 0/24 | 0/24 |
| Strict all-gates pass | 0/24 | 0/24 |

## Interpretation

The dominant failure is mathematical validity, not merely formatting. Opus
marked every SLM output invalid. Its notes repeatedly cite wrong or unsupported
answers, incoherent or duplicated solution text, failure to use the requested
techniques, and incomplete generations. Frontier outputs showed stronger
technique interaction, but only one was fully valid; truncation and incorrect or
unsupported final answers remained common.

Strict format is a separate failure: neither model produced a parser-passing
response. Accordingly, the formal all-gates result is 0/24 for both arms. The
content-only scores above are included diagnostically and do not replace the
frozen strict metric.

## Method and limitations

- Frozen suite: 12 technique-interaction briefs, two repetitions each.
- Generation: identical rendered prompts and a 1,200-token output ceiling.
- Pairing: A/B order randomized before judgment.
- Judge: claude-opus-4-8; identities hidden during judging.
- Prompt hashes for all 24 judgments match the preserved blind pairs.
- The frontier generator and judge are both Opus 4.8. This creates a material
  self-preference risk, so the result is an exploratory model-judged pilot, not
  an independent or human evaluation.
- The suite is small and public. It is unsuitable for a superiority claim.

## Demo-safe conclusion

On this pilot, the trained SLM did not beat Opus 4.8. The experiment identified
a concrete bottleneck: the current adapter does not reliably follow the target
generation schema or produce mathematically valid, technique-faithful problems.
The next iteration should prioritize clean target formatting, shorter complete
solutions, validity-filtered training examples, and a rerun with an independent
judge family.
