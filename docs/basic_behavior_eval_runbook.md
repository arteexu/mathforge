# Basic SLM-versus-frontier behavior evaluation

This is a small presentation pilot, not a statistically decisive benchmark. It
uses 12 frozen technique-interaction briefs and two repetitions per brief, for
24 paired trials per model.

## Fairness rules

- Freeze the adapter and frontier model identifiers before generating.
- Give both models the exact same rendered prompt, temperature (`0.8`), top-p
  (`0.95`), output limit (`1200`), attempt count, and no tools or repairs.
- Do not discard malformed or mathematically invalid outputs.
- Keep model identities hidden while reviewing `review_packet.md`.
- If the frontier generator is Claude, do not use Claude alone to judge it.

## 1. Generate the SLM arm on the GPU

```bash
PYTHONPATH=src python scripts/run_behavior_eval.py slm \
  --adapter /content/drive/MyDrive/YOUR-ADAPTER-DIRECTORY \
  --output /content/drive/MyDrive/mathforge-evals/basic-v1/slm.jsonl
```

The default is two fixed-seed generations for each of 12 prompts. Pass
`--resume` after an interrupted run.

## 2. Generate the frontier arm

Set the appropriate API credentials, then run one exact frozen model version:

```bash
PYTHONPATH=src python scripts/run_behavior_eval.py frontier \
  --provider anthropic \
  --model YOUR-EXACT-FRONTIER-MODEL-ID \
  --output /content/drive/MyDrive/mathforge-evals/basic-v1/frontier.jsonl
```

This makes 24 paid calls. It preserves full prompts, outputs, request IDs,
usage, latency, and parsing outcomes. Pass `--resume` after interruption.

## 3. Create blinded pairs

```bash
PYTHONPATH=src python scripts/run_behavior_eval.py blind \
  --slm /content/drive/MyDrive/mathforge-evals/basic-v1/slm.jsonl \
  --frontier /content/drive/MyDrive/mathforge-evals/basic-v1/frontier.jsonl \
  --output-dir /content/drive/MyDrive/mathforge-evals/basic-v1/blind
```

Review `blind/review_packet.md` without opening `blind_key.json`. Fill every row
of `blind/human_labels.csv` using:

- `validity_*`: `valid`, `repairable`, or `invalid`;
- `interaction_*`, `novelty_*`, `elegance_*`: integer 1-5;
- `difficulty_pass_*`: 0 or 1;
- `winner`: `A`, `B`, or `TIE`.

Validity is the hard gate. All-gates success additionally requires interaction
at least 4, novelty at least 3, elegance at least 3, and difficulty pass.

## 4. Produce the report

```bash
PYTHONPATH=src python scripts/run_behavior_eval.py report \
  --blind-dir /content/drive/MyDrive/mathforge-evals/basic-v1/blind
```

The command writes `summary.json` and `report.md`, including all-gates rates,
fully-valid counts, blinded wins/ties/losses, paired delta, and a family-level
bootstrap confidence interval.

For a headline superiority claim, expand the suite before presenting: at least
40 private scenario families with canonical/adversarial variants and multiple
repetitions. The basic suite is appropriate for debugging and an honestly
labelled pilot.
