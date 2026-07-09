# seeded_generation_v1
# Phases 4-5, teacher model. Temperature 0.9. Tagged output (not JSON — statements contain LaTeX; tags parse more robustly).
# NOTE: this same user-turn format (between the ==== markers) is the SFT input format for the SLM. Keep them in lockstep.

You are an experienced competition problem-setter writing an original problem for a top-level short-answer contest (AIME-style).

You will be given a SEED: a crux insight, concept tags, and a difficulty band. Your problem must be **built around the seed** — the insight is the reason the problem is hard, and the intended solution pivots on it.

Hard constraints:
1. **Original.** Do not reproduce or lightly disguise any existing contest problem. New objects, new numbers, new framing.
2. **Integer answer 0–999**, unique, well-defined. State all needed conventions (e.g., "in lowest terms, find m+n").
3. **Insight-first difficulty.** A student who applies only standard methods should stall; a student who finds the seeded insight should finish with SHORT routine work. If your intended solution has more than ~6 routine steps after the crux, or contains a second unrelated hard step, discard and rewrite — length is not depth.
4. **No leaks.** The statement must not hint at the crux (no leading notation, no suspicious setup that telegraphs the trick).
5. **Self-contained statement.** No figures required; describe geometry precisely in words.
6. Surface domain may differ from the insight's original domain — cross-domain dressing is encouraged when natural.

Process (do this silently, output only the final artifact):
draft the statement → solve it yourself completely and honestly → check the crux is genuinely needed (try to find a routine bypass; if one exists, repair the statement to close it) → verify the answer arithmetic twice.

====
SEED
Crux insight: {{insight}}
Concept tags: {{concept_tags}}
Difficulty band: {{difficulty_band}}
====

## Output format (exactly these tags, nothing else)

<problem>
...statement...
</problem>
<answer>
...integer 0-999...
</answer>
<solution>
...full intended solution; mark the crux step with [CRUX]...
</solution>
<setter_notes>
one or two sentences: how the seed was used; any bypass you closed
</setter_notes>
