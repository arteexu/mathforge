"""Loader for the versioned prompt files in the top-level ``prompts/`` directory.

Conventions (see ``prompts/README.md``):

* Template variables use ``{{double_braces}}``; :func:`render_prompt` fails loudly
  on any variable left unfilled.
* Leading ``#`` metadata/comment lines and the trailing ``# Harness notes`` block
  are stripped so only the actual prompt body is sent to the model.
* Every row produced by a prompt stores its version string (e.g.
  ``independent_solver_v1``) so prompts are never silently edited in place.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

__all__ = [
    "INDEPENDENT_SOLVER_V1",
    "DIFFICULTY_JUDGE_V1",
    "ELEGANCE_JUDGE_V1",
    "WELLPOSEDNESS_V1",
    "prompts_dir",
    "load_prompt",
    "render_prompt",
]

INDEPENDENT_SOLVER_V1 = "independent_solver_v1"
DIFFICULTY_JUDGE_V1 = "difficulty_judge_v1"
ELEGANCE_JUDGE_V1 = "elegance_judge_v1"
WELLPOSEDNESS_V1 = "wellposedness_v1"

_VAR_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def prompts_dir() -> Path:
    """Resolve the prompts directory (env override, cwd, then repo-relative)."""
    env = os.environ.get("MATHFORGE_PROMPTS_DIR")
    if env:
        return Path(env)
    cwd = Path.cwd() / "prompts"
    if cwd.is_dir():
        return cwd
    return Path(__file__).resolve().parents[2] / "prompts"


def _strip_metadata(text: str) -> str:
    """Remove leading ``#`` comment block and the trailing harness-notes block."""
    lines = text.splitlines()

    # Cut everything from a "# Harness notes" marker onward.
    for j, line in enumerate(lines):
        if line.strip().lower().startswith("# harness"):
            lines = lines[:j]
            break

    # Drop leading blank / '#'-comment lines until the first body line.
    i = 0
    while i < len(lines) and (not lines[i].strip() or lines[i].lstrip().startswith("#")):
        i += 1

    return "\n".join(lines[i:]).strip()


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    """Load and clean a prompt template by name (without the ``.md`` suffix)."""
    path = prompts_dir() / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"prompt not found: {path}")
    return _strip_metadata(path.read_text(encoding="utf-8"))


def render_prompt(name: str, **variables: object) -> str:
    """Fill ``{{variables}}`` in a prompt template, failing on any left unfilled."""
    template = load_prompt(name)
    for key, value in variables.items():
        template = template.replace(f"{{{{{key}}}}}", str(value))
    leftover = sorted(set(_VAR_RE.findall(template)))
    if leftover:
        raise ValueError(
            f"prompt {name!r} has unfilled variables: {', '.join(leftover)}"
        )
    return template
