"""Render LaTeX to readable terminal Unicode (a "compiled" view for labeling).

A terminal can't typeset LaTeX, so we approximate: convert ``$x^{20}+y^{20}=20$``
to ``x²⁰+y²⁰=20``, ``\\frac{a}{b}`` to ``a/b``, ``\\sqrt{2b-1}`` to ``√(2b-1)``,
Greek/relation macros to their Unicode glyphs, etc.

:mod:`pylatexenc` resolves macros/Greek/fractions (with ``keep_braced_groups`` so
super/subscript boundaries survive, e.g. ``2^{10}+1`` stays distinct from
``2^{10+1}``); we then convert those braced scripts to Unicode ourselves and add
back a few named operators pylatexenc drops (``\\gcd``, ``\\lcm``, ...).
"""

from __future__ import annotations

import re
from functools import lru_cache

__all__ = ["render_math"]

_SUP = {
    "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵", "6": "⁶",
    "7": "⁷", "8": "⁸", "9": "⁹", "+": "⁺", "-": "⁻", "=": "⁼", "(": "⁽",
    ")": "⁾", "n": "ⁿ", "i": "ⁱ",
}
_SUB = {
    "0": "₀", "1": "₁", "2": "₂", "3": "₃", "4": "₄", "5": "₅", "6": "₆",
    "7": "₇", "8": "₈", "9": "₉", "+": "₊", "-": "₋", "=": "₌", "(": "₍",
    ")": "₎", "a": "ₐ", "e": "ₑ", "h": "ₕ", "i": "ᵢ", "j": "ⱼ", "k": "ₖ",
    "l": "ₗ", "m": "ₘ", "n": "ₙ", "o": "ₒ", "p": "ₚ", "r": "ᵣ", "s": "ₛ",
    "t": "ₜ", "u": "ᵤ", "v": "ᵥ", "x": "ₓ",
}

_BRACED_RE = re.compile(r"([_^])\{([^{}]*)\}")
_SINGLE_RE = re.compile(r"([_^])([^\s{}$\\])")


def _to_script(chars: str, mapping: dict[str, str]) -> str | None:
    if chars and all(c in mapping for c in chars):
        return "".join(mapping[c] for c in chars)
    return None


def _apply_scripts(text: str) -> str:
    def braced(m: re.Match) -> str:
        marker, inner = m.group(1), m.group(2)
        conv = _to_script(inner, _SUP if marker == "^" else _SUB)
        if conv is not None:
            return conv
        return f"{marker}({inner})" if len(inner) > 1 else f"{marker}{inner}"

    def single(m: re.Match) -> str:
        marker, ch = m.group(1), m.group(2)
        # Only convert a standalone alphanumeric script (x^2, a_i, x^n); leave
        # punctuation like the parens of a non-mappable fallback untouched.
        if not ch.isalnum():
            return m.group(0)
        return _to_script(ch, _SUP if marker == "^" else _SUB) or m.group(0)

    return _SINGLE_RE.sub(single, _BRACED_RE.sub(braced, text))


@lru_cache(maxsize=1)
def _converter():
    from pylatexenc.latex2text import (
        LatexNodes2Text,
        MacroTextSpec,
        get_default_latex_context_db,
    )

    db = get_default_latex_context_db()
    ops = ["gcd", "lcm", "deg", "mod", "lim", "sup", "inf", "det", "dim", "arg"]
    db.add_context_category(
        "mathforge-ops",
        prepend=True,
        macros=[MacroTextSpec(name, simplify_repl=name) for name in ops],
    )
    return LatexNodes2Text(
        latex_context=db,
        math_mode="text",
        keep_braced_groups=True,
        keep_braced_groups_minlen=1,
    )


def render_math(text: str, enabled: bool = True) -> str:
    """Best-effort LaTeX -> Unicode. Returns input unchanged on any failure."""
    if not text or not enabled:
        return text
    try:
        rendered = _converter().latex_to_text(text)
        rendered = _apply_scripts(rendered)
    except Exception:
        return text
    # Drop any residual bare braces pylatexenc kept, and collapse blank runs.
    rendered = rendered.replace("{", "").replace("}", "")
    return re.sub(r"\n{3,}", "\n\n", rendered).strip()
