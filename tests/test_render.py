"""Tests for LaTeX -> terminal Unicode rendering."""

from __future__ import annotations

from mathforge.render import render_math


def test_superscripts_and_boundaries():
    assert render_math(r"$x^{20}+y^{20}=20$") == "x²⁰+y²⁰=20"
    # brace boundary preserved: 2^{10}+1, not 2^{10+1}
    assert render_math(r"$2^{10}+1$") == "2¹⁰+1"


def test_subscripts_and_operators():
    assert render_math(r"$a_{ij}$") == "aᵢⱼ"
    # named operator not dropped; sum glyph preserved
    assert "gcd(m,n)=1" in render_math(r"$\gcd(m,n)=1$")
    assert render_math(r"$\sum_{i=1}^n a_i$").startswith("∑")


def test_fraction_sqrt_greek():
    assert render_math(r"$\frac{m}{n}$") == "m/n"
    assert "√" in render_math(r"$\sqrt{2b-1}$")
    assert render_math(r"$\alpha \le \beta$") == "α≤β"


def test_disabled_and_empty():
    assert render_math(r"$x^2$", enabled=False) == r"$x^2$"
    assert render_math("") == ""
    # plain text passes through unchanged
    assert render_math("Find the number of ordered pairs.") == (
        "Find the number of ordered pairs."
    )
