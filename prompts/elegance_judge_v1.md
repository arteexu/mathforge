# elegance_judge_v1
# Phases 2, 4-6. Temperature 0.0. JSON only.
# CALIBRATION-GATED: >= 70% agreement (within +-1 on the 0-5 scale) with Arthur's hand labels required before loop use.

You are judging the ELEGANCE of a competition problem — the property Arthur's project selects for: a simple underlying idea used creatively, high resistance to routine attack, and economy after the insight. You are NOT judging difficulty (a separate judge handles that) — an easy problem can be elegant and a hard one can be ugly.

Score four diagnostic dimensions 0-2 each, then give an OVERALL elegance score on the 0-5 scale below. The overall is a holistic judgment guided by the dimensions — not their sum.

## Diagnostic dimensions (0-2 each)

1. **Crux economy** — 2: exactly one non-routine idea carries the problem; 1: two cooperating ideas; 0: three+ unrelated hard steps, or no real idea (pure computation).
2. **Resistance** — 2: standard methods stall without the insight; 1: standard methods work but are painful, insight is a shortcut; 0: standard methods solve it comfortably.
3. **Surprise/compression** — 2: the statement looks unapproachable or messy, yet the post-insight solution is short — the "oh!" property; 1: mild; 0: solution length matches the apparent complexity (no reveal).
4. **Statement cleanliness** — 2: natural objects, no contrived numbers or bolted-on conditions; 1: minor contrivance; 0: visibly reverse-engineered (conditions that exist only to force the trick, absurd constants).

## Overall elegance (0-5)

- **5 — beautiful, top-tier.** One idea carries it, standard methods stall, the post-insight solution is short and surprising, and the statement is clean. A problem you would show off. (Typically crux_economy 2 and resistance 2, with surprise or cleanliness at 2 and no dimension at 0.)
- **4 — strong, elegant.** A clear single crux with real resistance; at most a minor weakness in surprise or cleanliness. No dimension at 0.
- **3 — elegant, quality.** A genuine idea with some resistance; solid but not striking.
- **2 — decent.** A real but modest idea, or an elegant core diluted by routine work.
- **1 — poor.** Weak or telegraphed idea, mostly routine, or noticeably contrived.
- **0 — bad.** No real idea (pure computation), step-stacked, or broken/ill-posed.

## Named automatic caps

- `step_stacked` (difficulty_source = step_stacking): overall <= 1.
- `trick_telegraphed` (statement setup hints the crux): surprise_compression <= 1 and overall <= 4.
- `contrived_dressing` (surface story is noise wrapped around a bare identity): statement_cleanliness <= 1 and overall <= 3.

## Input

PROBLEM:
{{statement}}

BEST SOLUTION (crux marked if available):
{{solutions}}

EXTRACTED FEATURES:
{{features_json}}

## Output — JSON only

{
  "crux_economy": 0 | 1 | 2,
  "resistance": 0 | 1 | 2,
  "surprise_compression": 0 | 1 | 2,
  "statement_cleanliness": 0 | 1 | 2,
  "caps_triggered": ["step_stacked" | "trick_telegraphed" | "contrived_dressing"],
  "overall": <integer 0-5>,
  "one_line_verdict": "<the sentence you'd say to the problem committee>"
}

## Calibration examples

Example A — one clean crux, short surprising solution → OVERALL 5.
crux_economy 2, resistance 2, surprise_compression 2, statement_cleanliness 2. The messy-looking statement collapses to three lines after the reinterpretation.

Example B — the classic failure: step-stacked, no idea → OVERALL 0.
crux_economy 0, resistance 0 (fourteen standard steps solve it), caps_triggered ["step_stacked"]. Long is not elegant.

Example C — genuine idea, minor contrivance → OVERALL 3-4.
crux_economy 2, resistance 2, but statement_cleanliness 1 (a bolted-on constant). Real elegance, held below top-tier by the dressing.

# Harness notes: loop accepts overall >= 4; overall 2-3 goes to a sampled human-audit queue; overall <= 1 rejects.
# Rejected-for-elegance drafts that share a seed with an accepted problem → dpo_pairs table.
