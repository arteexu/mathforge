#!/usr/bin/env python3
"""Render behavior-generation JSONL as a readable Markdown gallery."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--title", default="Behavior-evaluation generations")
    args = parser.parse_args()

    rows = [
        json.loads(line)
        for line in args.input.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    lines = [
        f"# {args.title}",
        "",
        f"Model: `{rows[0].get('model', 'unknown') if rows else 'unknown'}`  ",
        f"Outputs: {len(rows)}",
        "",
        "> These are unedited model outputs. Parser failures and mathematical errors are preserved.",
        "",
    ]
    for row in rows:
        parse = row.get("parse") or {}
        techniques = ", ".join(row.get("technique_names") or [])
        lines.extend(
            [
                f"## {row.get('scenario_id')} — repetition {row.get('repeat_index')}",
                "",
                f"- Topic: {row.get('topic')}",
                f"- Required techniques: {techniques}",
                f"- Strict format pass: {bool(parse.get('format_pass'))}",
                "- Parser issues: " + ", ".join(parse.get("issues") or ["none"]),
                "",
                "```text",
                str(row.get("output") or ""),
                "```",
                "",
            ]
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {len(rows)} outputs to {args.output}")


if __name__ == "__main__":
    main()
