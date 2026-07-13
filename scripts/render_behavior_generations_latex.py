#!/usr/bin/env python3
"""Render behavior-generation JSONL as a compilable LaTeX anthology."""

from __future__ import annotations

import argparse
import json
import unicodedata
from pathlib import Path


def escape_latex(value: object) -> str:
    text = ascii_text(str(value))
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(character, character) for character in text)


def ascii_text(text: str) -> str:
    """Make arbitrary model text safe for portable pdfLaTeX listings."""
    replacements = {
        "−": "-",
        "–": "-",
        "—": "--",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "≠": "!=",
        "≤": "<=",
        "≥": ">=",
        "→": "->",
        "∞": "infinity",
        "√": "sqrt",
        "∑": "sum",
        "π": "pi",
        "ω": "omega",
        "φ": "phi",
        "·": "*",
        "×": "x",
        "²": "^2",
        "。": ".",
    }
    normalized = "".join(replacements.get(character, character) for character in text)
    normalized = unicodedata.normalize("NFKD", normalized)
    return normalized.encode("ascii", "backslashreplace").decode("ascii")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--title", default="MathForge SLM Generated Problems")
    args = parser.parse_args()

    rows = [
        json.loads(line)
        for line in args.input.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    model = rows[0].get("model", "unknown") if rows else "unknown"
    lines = [
        r"\documentclass[11pt]{article}",
        r"\usepackage[margin=0.8in,headheight=14pt]{geometry}",
        r"\usepackage[utf8]{inputenc}",
        r"\usepackage[T1]{fontenc}",
        r"\usepackage{lmodern}",
        r"\usepackage{xcolor}",
        r"\usepackage{listings}",
        r"\usepackage{fancyhdr}",
        r"\usepackage{multicol}",
        r"\usepackage[hidelinks]{hyperref}",
        r"\setlength{\parindent}{0pt}",
        r"\definecolor{metadata}{HTML}{555555}",
        r"\definecolor{listingbg}{HTML}{F7F7F7}",
        r"\definecolor{listingrule}{HTML}{D8D8D8}",
        r"\lstdefinestyle{modeloutput}{%",
        r"  basicstyle=\ttfamily\footnotesize,%",
        r"  backgroundcolor=\color{listingbg},%",
        r"  frame=single,%",
        r"  rulecolor=\color{listingrule},%",
        r"  framesep=6pt,%",
        r"  breaklines=true,%",
        r"  breakatwhitespace=false,%",
        r"  columns=fullflexible,%",
        r"  keepspaces=true,%",
        r"  showstringspaces=false,%",
        r"  upquote=true,%",
        r"  aboveskip=8pt,%",
        r"  belowskip=8pt",
        r"}",
        r"\pagestyle{fancy}",
        r"\fancyhf{}",
        r"\lhead{MathForge SLM evaluation outputs}",
        r"\rhead{\thepage}",
        r"\renewcommand{\headrulewidth}{0.3pt}",
        r"\title{" + escape_latex(args.title) + "}",
        r"\author{Model: \texttt{" + escape_latex(model) + "}}",
        r"\date{}",
        r"\begin{document}",
        r"\maketitle",
        r"\section*{Contents}",
        r"\begin{multicols}{2}",
        r"\small",
        r"\makeatletter",
        r"\@starttoc{toc}",
        r"\makeatother",
        r"\end{multicols}",
        r"\medskip",
        r"\noindent\fbox{\begin{minipage}{0.93\textwidth}",
        r"\textbf{Important:} These are the model's unedited evaluation outputs.",
        r"Malformed mathematics, repeated text, formatting failures, and truncation",
        r"are intentionally preserved. Literal typesetting ensures the document",
        r"compiles without silently repairing the generations.",
        r"\end{minipage}}",
        r"\clearpage",
    ]

    for index, row in enumerate(rows, 1):
        scenario = row.get("scenario_id", "unknown")
        repeat = row.get("repeat_index", "?")
        topic = row.get("topic", "unknown")
        techniques = ", ".join(row.get("technique_names") or [])
        parse = row.get("parse") or {}
        output = ascii_text(str(row.get("output") or ""))
        output = output.replace(r"\end{lstlisting}", "[end-lstlisting]")
        lines.extend(
            [
                rf"\section{{{escape_latex(scenario)} --- repetition {escape_latex(repeat)}}}",
                r"\begin{minipage}{\textwidth}",
                r"\color{metadata}\small\raggedright",
                rf"\textbf{{Entry:}} {index} of {len(rows)}\quad",
                rf"\textbf{{Topic:}} {escape_latex(topic)}\\[2pt]",
                rf"\textbf{{Required techniques:}} {escape_latex(techniques)}\\[2pt]",
                rf"\textbf{{Strict format pass:}} {escape_latex(bool(parse.get('format_pass')))}",
                r"\end{minipage}",
                "",
                r"\subsection*{Generated problem, answer, and solution}",
                r"\begin{lstlisting}[style=modeloutput]",
                output,
                r"\end{lstlisting}",
                r"\clearpage",
            ]
        )

    lines.append(r"\end{document}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {len(rows)} outputs to {args.output}")


if __name__ == "__main__":
    main()
