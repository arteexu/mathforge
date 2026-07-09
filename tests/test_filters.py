"""Statement-quality / diversity filters and the answer-range guard."""

from mathforge.agents import _valid_aime_answer
from mathforge.distill import is_garbled, is_near_duplicate, token_set


def test_is_garbled_flags_self_correction():
    assert is_garbled("Wait -- instead, suppose theta satisfies cos x = 0.")
    assert is_garbled("Actually, instead compute the following: find p.")
    assert is_garbled("Let x be real. On second thought, ignore the above.")
    # Clean competition statements must NOT be flagged.
    assert not is_garbled("Find the number of positive integers n <= 1000 with n | 2^n.")
    assert not is_garbled("Let f be a function with f(x)+f((x-1)/x)=1+x. Find f(2).")
    # 'instead' without the comma pattern (legit usage) is fine.
    assert not is_garbled("Count arrangements where 2 is used instead of 3.")


def test_near_duplicate_catches_reused_setup():
    # Same setup, only the final question tweaked -> caught (real pair jaccard 0.78).
    base = ("Let x, y, z be real numbers satisfying the system "
            "x + 1/y = 4, y + 1/z = 1, z + 1/x = 7/3, with all quantities defined. ")
    a = token_set(base + "Find the value of 100 x y z.")
    b = token_set(base + "Find the floor of 100 x y z.")
    assert is_near_duplicate(b, [a])


def test_near_duplicate_keeps_genuinely_different_problems():
    # Shared boilerplate opening but distinct content (real jaccard ~0.67) -> kept.
    # The 0.75 threshold stays safely above this so good problems are never dropped.
    p1 = token_set("Find the number of positive integers n <= 1000 such that n divides "
                   "2^n + 3^n + 4^n.")
    p2 = token_set("Find the number of positive integers n <= 1000 such that the sum of "
                   "the digits of n equals the sum of the digits of 3n.")
    assert not is_near_duplicate(p2, [p1])


def test_valid_aime_answer_range():
    assert _valid_aime_answer("500")
    assert _valid_aime_answer(0) and _valid_aime_answer(999)
    assert not _valid_aime_answer("1024")   # > 999
    assert not _valid_aime_answer("2025")
    assert not _valid_aime_answer("-3")
    assert not _valid_aime_answer("3.5")
    assert not _valid_aime_answer("abc")
    assert not _valid_aime_answer(None)
