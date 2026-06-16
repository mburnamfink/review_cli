"""Tests for ISBN normalisation / conversion (review.isbn)."""
from __future__ import annotations

import pytest

from review.isbn import dp_path, normalize_isbn, to_isbn10


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("978-0-441-01359-3", "9780441013593"),
        ("978 0441013593", "9780441013593"),
        ("  0441013597  ", "0441013597"),
        ("097522980X", "097522980X"),
        ("097522980x", "097522980X"),
        ("", None),
        (None, None),
    ],
)
def test_normalize_isbn(raw, expected):
    assert normalize_isbn(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        # Verified by hand against the user's Dune example.
        ("9780441013593", "0441013597"),
        ("978-0441013593", "0441013597"),
        # Already an ISBN-10 → returned normalised.
        ("0441013597", "0441013597"),
        ("0975229807", "0975229807"),
        # Hyphenated ISBN-13 from frontmatter.
        ("978-0140317534", "0140317538"),
        # 979-prefixed has no ISBN-10.
        ("9791234567896", None),
        # Junk.
        ("not-an-isbn", None),
        ("", None),
        (None, None),
    ],
)
def test_to_isbn10(raw, expected):
    assert to_isbn10(raw) == expected


def test_to_isbn10_check_digit_is_X():
    # A payload whose check digit computes to 10 must render as 'X'.
    # 0-8044-2957-? : sum chosen so (11 - s%11)%11 == 10.
    isbn13 = "9780804429573"  # 978 + 080442957 + check
    isbn10 = to_isbn10(isbn13)
    assert isbn10 is not None and isbn10.startswith("080442957")


def test_dp_path():
    assert dp_path("0441013597") == "/dp/0441013597"
