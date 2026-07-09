# MathForge

A pipeline for generating **elegant, AIME/olympiad-level competition math
problems** — problems where a single simple concept is used creatively, rather
than problems that are merely long.

The core idea: mine *interesting patterns / insights* from strong problems, then
grow fully-formed problems around each insight. Solutions are collected and
scored for **difficulty** and **elegance** (few genuine "crux" leaps, little
routine bookkeeping), and the best problems are curated into a dataset used to
train a small model (SLM) that can generate quality problems itself.

This repository is the **data-and-tooling skeleton**: schema, SQLite
persistence, a CLI with the pipeline stages stubbed out, and an audited LLM
wrapper. The stages are ready to be filled in.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)

## Setup

```bash
uv sync
```

## Data model (`src/mathforge/schema.py`)

All models are SQLModel classes — they are Pydantic models *and* SQLite tables.

| Model        | Key fields |
| ------------ | ---------- |
| `Problem`    | `id`, `source`, `statement`, `answer`, `provenance`, dedup fields (`statement_hash`, `normalized_statement`, `dedup_group_id`) |
| `Solution`   | `problem_id`, `text`, `techniques[]`, `crux_insight`, `crux_count`, `routine_step_count`, `source` |
| `Evaluation` | `problem_id`, `difficulty_score`, `elegance_score`, `evaluator` (`human` / `solver_panel` / `judge_v<N>`), `rationale` |
| `Insight`    | `id`, `text`, `concept_tags[]`, `difficulty_band`, `source_problem_ids[]`, `embedding` |
| `LLMCall`    | audit row: `model`, token counts, `cost_usd`, `latency_ms`, previews |

`crux_count` vs `routine_step_count` is the elegance signal: great problems have
a small number of real insight leaps relative to routine steps.

## Source datasets (`src/mathforge/datasets.py`)

Two HuggingFace datasets seed the pipeline:

| Dataset | Repo | Size | Notable fields |
| ------- | ---- | ---- | -------------- |
| Omni-MATH | `KbsdJames/Omni-MATH` | 4,428 problems (~7.5 MB) | `problem`, `solution`, `answer`, human `difficulty` rating, `domain[]`, `source` |
| NuminaMath-1.5 | `AI-MO/NuminaMath-1.5` | 896,215 problems (~531 MB dl / ~1.66 GB) | `problem`, `solution`, `answer`, `problem_type`, `question_type`, `source`, `synthetic` |

Download + cache them (stored in the standard HF cache, e.g.
`~/.cache/huggingface`, **not** in this iCloud-synced folder — override with
`MATHFORGE_HF_CACHE` or `HF_HOME`):

```bash
uv run mathforge fetch all          # or: omni-math | numina
```

Loader + schema mappers:

```python
from mathforge.datasets import load_omni_math, omni_row_to_records

ds = load_omni_math()                       # cached HF Dataset
problem, solution, evaluation = omni_row_to_records(ds[0], 0)
# Omni-MATH's difficulty rating becomes a human Evaluation (difficulty only);
# domains become the solution's techniques. NuminaMath maps via
# numina_row_to_records -> (Problem, Solution).
```

## Ingest & the two Omni-MATH sections

Omni-MATH is the **primary** working set (detailed solutions + human difficulty
ratings). Ingest splits it into two labeled sections by difficulty, because the
problems we want to generate from each are qualitatively different:

- **easy** section: difficulty `< threshold`
- **hard** section: difficulty `>= threshold` (default `threshold = 4.0`)

```bash
uv run mathforge ingest omni-math               # threshold 4.0
uv run mathforge ingest omni-math --threshold 5 # or pick your own cutoff
uv run mathforge stats                          # shows the tier breakdown
```

Each problem is stored with `difficulty` and `tier` (`easy`/`hard`), plus its
official `Solution` and an `Evaluation` carrying the human difficulty rating.
Ingest is deduped by normalized-statement hash and idempotent. On the current
dataset the default split yields **880 easy** and **3,526 hard** problems (22
exact-duplicate statements are skipped). Query a single section with:

```python
from sqlmodel import select
from mathforge import db
from mathforge.schema import Problem, ProblemTier

with db.session_scope() as s:
    hard = s.exec(select(Problem).where(Problem.tier == ProblemTier.HARD)).all()
```

NuminaMath-1.5 is downloaded/cached but intentionally left for a later pass.

## Frozen eval split (held out, `src/mathforge/holdout.py`)

A held-out evaluation set is **frozen once** and recorded in an immutable
manifest at `eval/frozen_eval_v1.json`. It contains **240 problems**:

- **90 AIME** — 2024/2025/2026 AIME I & II (15 each), from authoritative
  round-labeled sources (`Maxwell-Jia/AIME_2024`, `opencompass/AIME2025`,
  `MathArena/aime_2026`), answers normalized to integers.
- **150 Omni-MATH** — selected deterministically to span **distinct difficulty
  bands and topics** (round-robin over `topic × difficulty_band` strata). The
  current freeze covers all 7 topics and difficulty bands d1–d9.

Every eval problem is stored with `split = "eval"` and `frozen = True`. The
**only** way upstream stages read problems is via
`db.training_problems_select()`, which filters to `split == train` and
`frozen == False` — so the eval set can never leak into annotation, insight
mining, generation, or export.

```bash
uv run mathforge freeze-eval        # one-time; refuses to overwrite an existing manifest
uv run mathforge eval-verify        # checks the DB still matches the frozen manifest (integrity hash)
uv run mathforge stats              # shows train / eval / frozen counts
```

The manifest is self-contained (full statements, answers, provenance,
`statement_hash`, and a SHA-256 integrity hash over the sorted set), so the exact
eval set is reproducible and tamper-evident even if the DB is rebuilt.

> Note: `freeze-eval` is guarded — it raises if `eval/frozen_eval_v1.json`
> already exists (pass `--force` to intentionally re-freeze).

## Eval harness (`src/mathforge/evalharness.py`)

Ranks problems by quality so a few deep, elegant ones rise above the rest — one
great problem beats fifty mediocre ones. Ranking is **lexicographic**:

1. **elegance** (0–5) — the dominant axis,
2. then **difficulty** (1–10),
3. then **crux economy** (one crux is best) and an anti-step-stacking penalty,

behind a hard **correctness gate** (unverified / ill-posed / below the elegance
floor can't rank). Attributes come from the richest signal per problem
(`Evaluation` rows: human ▸ opus ▸ judge ▸ dataset, or the `agent_qa` blob).

```bash
uv run mathforge rank --source synthetic --elegance-min 3          # leaderboard + grades (S/A/B/C/D)
uv run mathforge rank --elegance-min 4 --difficulty-min 5          # only deep + elegant keepers
uv run mathforge rank --elegance-min 4 --apply                     # auto-accept keepers, reject the rest
```

`--apply` sets `review_status` from the gate, turning the harness into a
one-command curator that keeps the elegant few. `--no-trust-sources` disables the
bypass below.

### Ranking real contest problems (trusted sources)
Official contest problems (Omni-MATH, AIME, etc.) are consensus-vetted but never
went through our verify loop, so the gate treats their sources as correct via
`QualityWeights.trusted_sources` (default on). They still need an elegance score
to rank; use the Opus/out-of-band elegance loop:

```bash
uv run mathforge elegance-export elegance_sample.json --target 72   # stratified sample
# rate each 0-5 (elegance_judge_v1 rubric) -> ratings.json [{id, elegance, reason}]
uv run mathforge elegance-apply ratings.json                        # write elegance Evaluations
uv run mathforge rank --id-prefix omni-math-                        # now rankable
```

### Synthetic vs HF finding (Opus-rated sample)
Ranking both sets with the same Opus rater: elegance is comparable (avg 3.6
synthetic vs 3.72 Omni-MATH), but the synthetic bank is **shallower** - avg
difficulty 4.75 vs 6.66 and **0 vs 15** "hard" keepers (difficulty >= 7). The gap
is depth, not elegance.

## Difficulty features (`src/mathforge/features.py`)

Feature extraction for the difficulty predictor. Per problem, a **teacher** pass
writes a `Solution` row (`source=teacher`) with the signals that predict how hard
a problem is:

- `techniques` — methods used
- `crux_insight` / `crux_count` — the key idea and number of genuine insight leaps
- `routine_step_count` — routine/mechanical steps
- `prerequisite_level` — required background, 1 (elementary) .. 5 (olympiad-deep)
- `standard_method_solves` — does a standard/textbook method suffice?

Two extractors:

- `heuristic` (default, offline, deterministic) — derives features from the
  problem/solution text and difficulty. Runs with no API keys.
- `llm` — a teacher model via `LLMClient` (every call's tokens/cost is logged).
  Expects strict JSON; if parsing fails it falls back to the heuristic and flags
  `parse_error` in `Solution.features`.

```bash
uv run mathforge extract-features                       # heuristic, TRAIN split, idempotent
uv run mathforge extract-features --extractor llm --model gpt-4o
uv run mathforge annotate                               # shorthand for heuristic extraction
```

Extraction defaults to the **train** split (the frozen eval set is untouched)
and is idempotent per `extractor_model`. `features.feature_rows(split=...)`
joins the teacher features with each problem's `difficulty` label to produce the
feature matrix the predictor will train on.

## Solver panel (`src/mathforge/solver.py`)

The **behavioral** difficulty signal: difficulty measured by what models actually
do. Two solvers run the `independent_solver_v1` prompt (loaded from `prompts/`):

- **weak** — a ~7B open model, 8 attempts
- **strong** — a frontier model, 4 attempts

Each attempt's verdict (`final_answer`, `recognized_as_existing`, `ambiguity_flag`)
is parsed and checked against the intended answer (integer matching is reliable
for AIME). We store **solve rates**; the pair locates the problem:

| weak rate | strong rate | classification |
| --- | --- | --- |
| high (≥ 0.5) | — | `exercise` |
| low | > 0 | `target` (hard-but-well-posed) |
| 0 | 0 | `broken` (probably ill-posed) |

**Aggressive caching** — the dominant API cost. Every `SolverAttempt` is stored
with a unique key `(problem, model, prompt_version, attempt_index)`, so a problem
is *never solved twice*; re-runs reuse cached attempts (0 new API calls).

**Memorization** — famous-contest problems (AIME/AMC/USAMO/USAJMO/IMO/Putnam), or
any problem a solver flags `recognized_as_existing`, get `possibly_memorized` set.
`difficulty_judge_v1` is told to discount solver success when it is set.

```bash
uv run mathforge solve-panel --weak-model qwen2.5-7b-instruct --weak-attempts 8 \
                             --strong-model o3 --strong-attempts 4
```

Plug real solver backends into `LLMClient` (via `make_llm_solver`) for meaningful
rates; every call's tokens/cost is logged to `LLMCall`. Runs on the **train**
split by default so the frozen eval set is untouched.

## Distillation (`src/mathforge/distill.py`)

Distill verified, judged problems from a frontier model into the synthetic bank:

1. **Generate** an original AIME-hard problem (`distill_generation_v1`). To avoid
   mode-collapse, the target **rotates across topics/difficulty** each call, the
   prompt **bans the polynomial-evaluation cliché** and shows the model its recent
   outputs to diverge from, and any banned-template problem that slips through is
   hard-filtered (never stored).
2. **Verify** by solving it independently `k` times (`independent_solver_v1`,
   strict-majority answer). Match ⇒ verified.
3. **Repair** on mismatch: rewrite the problem to match the solver's consensus
   answer (`problem_repair_v1`), then re-verify once.
4. **Judge** elegance (0–5) and difficulty (1–10) with the calibrated judges
   (verified problems only).
5. **Store everything** as `SYNTHETIC`, `review_status=pending`. Verified problems
   are judged and stored; problems that *fail* verification are **not discarded** —
   they're stored `verified=False` with the solver's answers recorded, so you can
   inspect them in `review` (a hard-but-correct problem often just fails an
   automated solve).

Generator/solver/judge are independent `LLMClient`s (verify with a *different*
model family to decorrelate errors). The backend is any OpenAI-compatible API
(`make_openai_backend`), so it works with OpenAI, Z.ai/GLM, OpenRouter, etc.

### Recommended flow: generate, then verify with a strong out-of-band model

The built-in API self-verification is unreliable (a model rubber-stamps its own
errors). The higher-quality flow separates generation from verification and uses
a strong model (e.g. Claude Opus, which can compute exact answers) to verify and
correct:

```bash
# 1. Generate diverse candidates only (no API self-verify), stored pending:
uv run mathforge distill --no-verify --n 25 --generator-model gpt-5.4

# 2. Export the unverified candidates:
uv run mathforge qa-export candidates.json

# 3. Have a strong model solve/verify each (exact computation) and write a
#    verdicts JSON: [{id, correct_answer?, wellposed, recommendation, reason,
#    difficulty?, elegance?}], recommendation ∈ {accept, fix_answer, needs_edit, reject}

# 4. Apply the verdicts (corrects wrong answers, records QA + judgments):
uv run mathforge qa-apply verdicts.json [--apply-status]

# 5. Final human pass (now QA-informed):
uv run mathforge review
```

`qa-apply` sets `verified`, records an `agent_qa` provenance blob (shown in
`review`), corrects the stored answer for `fix_answer` verdicts, and (with
`--apply-status`) sets `review_status` from each recommendation.

### One-shot API variant

```bash
uv run mathforge distill --n 25 --generator-model gpt-5.4 \
  --solver-model glm-5.2 --solver-base-url https://api.z.ai/api/paas/v4 --solver-key-env ZAI_API_KEY
uv run mathforge review
```

## Agent QA (`src/mathforge/agents.py`)

Before you hand-review, spawn **strong math agents** to vet the distilled
candidates. For each problem, `k` independent strong solvers attempt it and we:

- **verify correctness** — strict-majority answer vs. the stored answer (sets
  `verified`);
- **check well-posedness** — an adversarial rules-chair pass (`wellposedness_v1`)
  flags ambiguous / ill-posed / unsolvable statements; and
- **rate quality** — the difficulty (1–10) and elegance (0–5) judges.

Results are written back (`verified`, an `Evaluation`, a stored strong-agent
`Solution`, and an `agent_qa` provenance blob that `review` shows), so your human
pass starts from the agents' assessment.

```bash
uv run mathforge qa --k 4 --solver-model gpt-5.4        # QA pending + needs_edit candidates
uv run mathforge qa --solver-model glm-5.2 --base-url https://api.z.ai/api/paas/v4 --api-key-env ZAI_API_KEY
uv run mathforge review                                  # then human-review, now QA-informed
```

Defaults to `pending,needs_edit` candidates, is idempotent per problem (skip
unless `--overwrite`), and one bad item won't kill the batch. Use a **different
model family** than the generator for trustworthy verification.

## Human labeling (`src/mathforge/labeling.py`)

The highest-leverage manual step: encode the AIME-experienced human's judgment as
ground-truth `Evaluation` rows (`evaluator=human`) that every judge is calibrated
against.

```bash
uv run mathforge label                 # ~150 problems, train split
uv run mathforge label --count 200 --split all
```

For each problem it shows the **statement + worked solutions** and asks for a
difficulty (1–10, AoPS-style) and elegance (0–5: 5 beautiful/top-tier, 4 strong &
elegant, 3 elegant & quality, 2 decent, 1 poor, 0 bad). The problem's current
source difficulty is revealed *after* you enter your own difficulty (so it can't
anchor it) and stays visible while you score elegance. Design choices that protect
label quality:

- **Anchor-free**: presentation order is randomized, and every existing rating is
  hidden — source difficulty, prior evaluations, the teacher's difficulty
  estimate, and even the problem id/source are not shown.
- **Stratified**: problems are sampled across difficulty bands × topics so a few
  focused hours cover the space.
- **Resumable**: already-labeled problems are skipped; press `s` to skip, `q` to
  quit (each label is committed immediately).
- **Rendered math**: statements/solutions are shown as readable Unicode
  (`$x^{20}+y^{20}=20$` → `x²⁰+y²⁰=20`, `\frac{a}{b}` → `a/b`, `\sqrt{}` → `√`,
  Greek/relations → glyphs) via `mathforge.render`. Pass `--raw` to see the
  original LaTeX instead.

> Note: source-provided ratings (e.g. Omni-MATH's difficulty) are stored as
> `evaluator=dataset`, kept strictly separate from your `evaluator=human` labels
> so they never contaminate the ground-truth set or the calibration comparison.

## Data report (`src/mathforge/report.py`)

A one-page report of dataset counts by **source**, **difficulty band**, and
**topic** (each split into train vs. held-out eval):

```bash
uv run mathforge report                 # rich tables in the terminal
uv run mathforge report --json out.json # also write a JSON snapshot
```

`build_report()` returns a JSON-serializable snapshot used by both the CLI and
the one-page canvas report.

## Persistence (`src/mathforge/db.py`)

SQLite via SQLModel. The database defaults to `./mathforge.db`, overridable with
the `MATHFORGE_DB` environment variable or a `--db-url` option.

```bash
uv run mathforge init
```

## CLI (`src/mathforge/cli.py`)

Pipeline stages (currently stubs that initialize state and describe their work):

```bash
uv run mathforge ingest ./data/aime --source aime   # import official problems
uv run mathforge annotate                            # solve + label cruxes, mine insights
uv run mathforge generate --n 10 --band aime_hard    # grow problems from insights
uv run mathforge evaluate --evaluator judge_v1       # score difficulty + elegance
uv run mathforge loop --rounds 5 --keep 20           # generate -> evaluate -> select
uv run mathforge export dataset.jsonl                # export curated dataset
uv run mathforge stats                               # row counts + logged LLM spend
```

## LLM wrapper (`src/mathforge/llm.py`)

`LLMClient` wraps a text-completion backend and **logs every call** (model,
tokens, cost, latency) to the `LLMCall` table. It ships with an offline `echo`
backend so the pipeline runs without API keys; pass a `backend` callable to plug
in a real provider. Pricing lives in an editable `PRICING` table.

```python
from mathforge.llm import LLMClient

client = LLMClient(model="gpt-4o-mini", purpose="generate")
resp = client.complete("Invent a problem seeded by a telescoping identity.")
print(resp.total_tokens, resp.cost_usd, resp.call_id)  # persisted to the DB
```

## Tests

```bash
uv run pytest
```

Covers Pydantic (de)serialization round-trips, SQLite persistence round-trips
(including JSON list/dict fields, enums, and relationships), dedup/normalization
helpers, evaluator validation, and LLM call logging.

## Notes

- The project is configured to run tests directly from `src/` (pytest
  `pythonpath`), so tests don't depend on the install mode.
- If `uv run mathforge` ever reports `No module named 'mathforge'` (an editable
  install artifact on iCloud-synced folders), run `uv sync --no-editable` to
  reinstall a copied build.
