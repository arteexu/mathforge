#!/usr/bin/env python3
"""Render tagged frontier generations as normal mathematical LaTeX."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import unicodedata
from pathlib import Path


def extract_tag(text: str, tag: str) -> tuple[str, bool]:
    closed = re.search(
        rf"<{tag}>\s*(.*?)\s*</{tag}>", text, flags=re.I | re.S
    )
    if closed:
        return closed.group(1).strip(), True
    opened = re.search(rf"<{tag}>\s*(.*)$", text, flags=re.I | re.S)
    return (opened.group(1).strip(), False) if opened else ("", False)


def normalize_unicode(text: str) -> str:
    replacements = {
        "—": "--",
        "–": "-",
        "✓": "[check]",
        "ő": "o",
    }
    text = "".join(replacements.get(character, character) for character in text)
    return unicodedata.normalize("NFKC", text)


def trim_unclosed_math(text: str) -> tuple[str, bool]:
    """Drop only a final incomplete dollar-delimited expression."""
    state: str | None = None
    opener = -1
    index = 0
    while index < len(text):
        if text[index] == "\\":
            index += 2
            continue
        if text.startswith("$$", index):
            if state is None:
                state, opener = "display", index
            elif state == "display":
                state, opener = None, -1
            index += 2
            continue
        if text[index] == "$":
            if state is None:
                state, opener = "inline", index
            elif state == "inline":
                state, opener = None, -1
            index += 1
            continue
        index += 1
    if state is not None:
        return text[:opener].rstrip(), True
    return text.rstrip(), False


def clean_section(text: str) -> tuple[str, bool]:
    text = normalize_unicode(text)
    text = re.sub(r"</?[A-Za-z_]+>", "", text)
    text = text.replace(r"^\*", r"^{*}").replace(r"_\*", r"_{*}")
    # Pandoc requires the closing inline-math delimiter to touch a non-space
    # character. A few generated drafts end an intentionally blank equation
    # with `= $`; make that malformed but compilable as `=$`.
    text = text.replace("= $", "=$")
    text, trimmed = trim_unclosed_math(text)
    text = text.rstrip(" \\n")
    return text, trimmed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    args = parser.parse_args()

    rows = [
        json.loads(line)
        for line in args.input.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    args.work_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = args.work_dir / "opus_generated_problems_math.md"
    header_path = args.work_dir / "opus_latex_header.tex"

    document = [
        "---",
        'title: "Claude Opus 4.8: Generated Problems and Solutions"',
        'author: "MathForge basic behavior evaluation"',
        "date: \"\"",
        "---",
        "",
        "> **Evaluation notice.** These are unedited mathematical claims from the",
        "> frontier generation run. All 24 responses reached the output-token limit,",
        "> so their generated solutions are incomplete. Claimed answers and errors",
        "> are preserved; no missing reasoning has been invented.",
        "",
    ]

    for index, row in enumerate(rows, 1):
        problem, problem_closed = extract_tag(row["output"], "problem")
        answer, answer_closed = extract_tag(row["output"], "answer")
        solution, solution_closed = extract_tag(row["output"], "solution")
        problem, problem_trimmed = clean_section(problem)
        answer, answer_trimmed = clean_section(answer)
        solution, solution_trimmed = clean_section(solution)
        scenario = normalize_unicode(str(row.get("scenario_id", "unknown")))
        topic = normalize_unicode(str(row.get("topic", "unknown")))
        techniques = ", ".join(row.get("technique_names") or [])
        repeat = row.get("repeat_index", "?")
        stopped = (row.get("usage") or {}).get("stop_reason")

        document.extend(
            [
                f"# {scenario} - repetition {repeat}",
                "",
                f"**Entry:** {index} of {len(rows)}  ",
                f"**Topic:** {topic}  ",
                f"**Required techniques:** {techniques}",
                "",
                "## Problem",
                "",
                problem or "*No problem section was returned.*",
                "",
                "## Claimed answer",
                "",
                rf"\[\boxed{{{answer}}}\]" if answer else "*No answer was returned.*",
                "",
                "## Generated solution",
                "",
                solution or "*No solution text was returned.*",
                "",
            ]
        )
        if stopped == "max_tokens" or not solution_closed or solution_trimmed:
            document.extend(
                [
                    "> **Truncation notice:** The response ended at the output-token",
                    "> limit. The generated solution is incomplete at this point.",
                    "",
                ]
            )
        if not problem_closed or problem_trimmed or not answer_closed or answer_trimmed:
            document.extend(
                [
                    "> **Formatting notice:** At least one tagged section was incomplete",
                    "> and was closed only for typesetting safety.",
                    "",
                ]
            )
        document.extend([r"\clearpage", ""])

    markdown_path.write_text("\n".join(document), encoding="utf-8")
    header_path.write_text(
        "\n".join(
            [
                r"\usepackage{amsmath,amssymb,mathtools}",
                r"\usepackage{fancyhdr}",
                r"\setlength{\emergencystretch}{3em}",
                r"\allowdisplaybreaks",
                r"\setcounter{tocdepth}{1}",
                r"\pagestyle{fancy}",
                r"\fancyhf{}",
                r"\lhead{Claude Opus 4.8 evaluation outputs}",
                r"\rhead{\thepage}",
                r"\renewcommand{\headrulewidth}{0.3pt}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "pandoc",
            str(markdown_path),
            "--standalone",
            "--toc",
            "--toc-depth=1",
            "--number-sections",
            "--from=markdown+tex_math_dollars+raw_tex",
            "--to=latex",
            "--metadata=documentclass:article",
            "--metadata=papersize:letter",
            "--metadata=fontsize:11pt",
            "-V",
            "geometry:margin=0.8in,headheight=14pt",
            "--include-in-header",
            str(header_path),
            "--output",
            str(args.output),
        ],
        check=True,
    )
    print(f"wrote {len(rows)} typeset outputs to {args.output}")


if __name__ == "__main__":
    main()
