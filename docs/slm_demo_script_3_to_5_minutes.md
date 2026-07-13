# MathForge SLM demo script (3-5 minutes)

Approximate spoken length: 4 minutes at 150 words per minute. Text in brackets
is an on-screen cue, not spoken narration.

## 0:00-0:35 - Hook and BrainLift thesis

[Show title: **Problem Generation Is the Inverse of Problem Solving**]

Most language models make a math problem “harder” by adding steps or uglier
numbers. That often creates a long exercise, not a creative competition problem.

My BrainLift starts from the opposite direction: begin with the surprising
observation—the crux—and engineer the statement outward so everything falls to
that insight. Problem generation is the inverse of problem solving.

MathForge targets one narrow behavior: given a crux and two techniques, generate
an original, well-posed AIME-style problem with a unique integer answer, where
both techniques are genuinely necessary.

## 0:35-1:15 - Model architecture

[Show pipeline diagram: **Sources -> Crux/techniques -> Verified examples -> QLoRA -> Generator**]

The model starts with Qwen2.5-Math-7B-Instruct, quantized to four-bit NF4. Its
base weights stay frozen while supervised fine-tuning trains rank-32 LoRA
adapters in the attention and feed-forward layers.

This fits on one cloud GPU. The base preserves mathematical knowledge while the
adapter learns to turn insights into problems. I can also compare the same
model with the adapter enabled or disabled.

There are two training views: 2,956 unique problems for breadth, and a curated
205-problem subset with the strongest creativity signals. Each example names
the intended crux and techniques, then supplies the problem, solution, and
answer.

## 1:15-2:25 - What makes the project unique

[Show three labels: **Insight-first. Verification-first. Corpus-aware.**]

First, the data is insight-first. Topic is metadata; the crux is the unit of
generation. That lets surface details vary while the deep mathematical
structure stays controlled.

Second, synthetic output never becomes training data automatically. The
verification funnel checks independent solvability, answer consistency,
short-answer format, and whether both techniques are load-bearing. It rejects
difficulty created only by stacking steps, and records human acceptance.

Third, the combination generator searches for real interaction between two
techniques. It proposes mathematical bridges, expands the best one into
different problem shells, and judges validity before novelty. A blind solver
sees only the statement. A candidate gets at most one structural repair, then a
corpus-aware gate compares it with the nearest training and contest problems.

The funnel is deliberately selective: in a five-job pilot, four ideas failed at
the bridge stage and only one was stored. Rejection is evidence that the gates
are doing work.

## 2:25-3:10 - Integrity and evaluation

[Show: **2,956 unique training rows | 240 frozen holdout problems | 0 train/eval overlap**]

The data layer is auditable: training rows are deduplicated, semantic duplicates
are quarantined, and a frozen holdout of 90 AIME and 150 Omni-MATH problems is
excluded from every training export.

Evaluation is validity-first. A beautiful invalid problem scores zero. Only
after correctness and uniqueness do I score technique interaction, difficulty,
elegance, and novelty.

The comparison suite uses 12 technique-interaction briefs, repeated twice. The
SLM and frontier model receive identical prompts and sampling budgets, with no
repair. Outputs are randomized as A and B, reviewed blind, and reported with
validity, all-gates pass rate, head-to-head results, and confidence intervals.

[After evaluation, replace the previous sentence with one measured result
sentence. Do not claim a win if the confidence interval crosses zero.]

## 3:10-3:45 - Live generation

[Open the inference notebook. Show the frozen prompt before running it.]

Here I provide a topic, difficulty band, two techniques, and how they should
interact. The model must return a problem, integer answer, complete solution,
and an explanation of why both techniques are necessary.

[Run one fixed-seed generation. Show the statement first, then reveal the
solution and the automatic format result. Do not improvise a second generation
if the first one is weak; the fixed output is part of the evidence.]

This is not merely “make a hard problem.” The mathematical mechanism is a
controllable input, and the output is judged against that contract.

## 3:45-4:05 - Close

[Return to title slide.]

I am not claiming that a seven-billion-parameter model is universally smarter
than a frontier model. MathForge tests whether carefully structured data can
make a small local model more reliable at one constrained creative behavior.

The shortest summary is the final line of my BrainLift: the dataset is the
deliverable, and the model is the dataset made runnable.

## Optional cuts for a 3-minute version

- Remove the details about NF4, rank 32, and projection modules; say “single-GPU
  QLoRA adapter” instead.
- Remove the numerical five-job pilot example.
- Condense the integrity paragraph to one sentence.
- Keep the BrainLift thesis, combination funnel, evaluation rule, live sample,
  and closing line.

## Demo preparation checklist

- Freeze the exact adapter directory and record its manifest/hash.
- Pre-run the fixed-seed sample once; keep that exact output for the live demo.
- Keep the frontier comparison report open in a separate tab.
- Show `report.md` and `summary.json`, not informal hand-selected examples.
- If the live runtime fails, use the preserved fixed-seed output rather than
  silently switching seeds.
- Disclose that the basic 24-pair suite is a pilot unless it has been expanded.
