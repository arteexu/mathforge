# prompts/

Versioned prompt files for the factory. Conventions:

- **Never edit a prompt in place once it has produced DB rows.** Copy to `_v2`, edit, and update the stage config. Every `Solution`, `Insight`, and `Evaluation` row stores the prompt version that produced it.
- Template variables use `{{double_braces}}`. Your `llm.py` should fail loudly on unfilled variables.
- All judge/annotation prompts demand **JSON only** — no prose, no markdown fences. Parse with a strict schema and route failures to a retry-with-error-message, then to a reject queue. Never "best-effort parse."
- Temperature guidance: annotation & judges 0.0–0.2; generation 0.8–1.0; independent solver 0.6–0.7 (you *want* solve-path diversity across the k samples).

## Which prompt runs where

| Prompt | Phase | Purpose |
|---|---|---|
| `crux_extraction_v1` | 3 | Reverse-engineer harvested problems into seeds |
| `insight_vagueness_check_v1` | 3 | Reject topic-restatement "insights" |
| `insight_merge_v1` | 3 | Canonicalize clustered duplicate insights |
| `wild_insight_v1` | 3 | Small tranche of invented insights (cap ~15%) |
| `seeded_generation_v1` | 4–5 | Teacher drafts problem from a seed |
| `independent_solver_v1` | 1, 4–5 | Answer-consistency verification (k samples) |
| `insight_faithfulness_v1` | 4–5 | Did the real solve pivot on the seed? |
| `wellposedness_v1` | 4–5 | Ambiguity / missing constraints / answer-format check |
| `difficulty_judge_v1` | 2, 4–6 | Difficulty band from solutions + features + solve rates |
| `elegance_judge_v1` | 2, 4–6 | Elegance 0–5 (overall) with step-stacking as a named failure |
| `combo_bridge_generation_v1` | combination | Propose three fused technique bridges before drafting |
| `combo_bridge_judge_v1` | combination | Hard-gate bridges for soundness, essentiality, and stapling |
| `combo_problem_generation_v1` | combination | Compose one strict AIME draft from the selected bridge |
| `combo_faithfulness_v1` | combination | Preliminary load-bearing/bypass check before candidate storage |
| `combo_shell_generation_v1` | combination v2 | Diversify one sound bridge into four non-canonical shells |
| `combo_shell_judge_v1` | combination v2 | Select a validity-passing shell lexicographically by novelty and necessity |
| `combo_problem_generation_v2` | combination v2 | Compose from both the accepted bridge and selected shell |
| `combo_blind_audit_v1` | combination v2 | Solve the statement alone; expose bypasses and independently rate difficulty |
| `combo_faithfulness_v2` | combination v2 | Reconcile the blind shortest route with intended technique necessity |
| `combo_creativity_repair_v1` | combination v2 | Perform the single allowed feedback-guided structural rewrite |
| `combo_corpus_novelty_v1` | combination v2 | Compare the final draft with retrieved corpus neighbors and reject reused mathematical kernels |

## Calibration protocol (applies to difficulty & elegance judges)

1. Run the judge over your hand-labeled set (Phase 2: real problems; Phase 4: synthetic survivors).
2. Compute Spearman (difficulty) / agreement (elegance) vs. your labels. Floors: **≥0.6 Spearman, ≥70% agreement** (elegance agreement is within-±1 on the 0–5 overall scale).
3. If below floor: inspect the disagreements, add the 3–5 most representative as few-shot counterexamples in a new version, re-run. The most common judge error is over-rating long step-stacked solutions as "hard" — the shipped few-shots already target this, but expect to add your own.
4. Log `(prompt_version, calibration_score, date)` in the DB. The Phase-5 loop refuses to run with an uncalibrated judge version.

## Placeholder glossary

`{{statement}}` problem text · `{{solutions}}` all known solutions, numbered · `{{answer}}` intended integer answer · `{{insight}}` crux text · `{{concept_tags}}` list · `{{difficulty_band}}` e.g. "AIME P10–12 (AoPS ~5–6)" · `{{features_json}}` extracted solution features · `{{solve_rates}}` weak/strong panel rates · `{{independent_solutions}}` solver transcripts from verification · `{{cluster}}` list of near-duplicate insights
