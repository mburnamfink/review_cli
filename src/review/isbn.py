"""ISBN normalisation and ISBN-13 → ISBN-10 conversion (pure).

Amazon's print-book ASIN is, in practice, the book's ISBN-10, so
``amazon.com/dp/<isbn10>`` lands directly on the exact product page — no search,
no wrong edition, no box-set contamination. Frontmatter stores ISBN-13 (often
hyphenated) for ~91% of the catalogue, so converting 13 → 10 unlocks an exact
lookup for almost every book. 979-prefixed ISBN-13s have no ISBN-10 equivalent
and fall back to search.
"""
from __future__ import annotations


def normalize_isbn(raw: str | None) -> str | None:
    """Strip an ISBN down to its significant characters (digits, trailing X).

    Hyphens, spaces and surrounding whitespace are removed; a check ``X`` (only
    valid as the last char of an ISBN-10) is upper-cased and kept. Returns
    ``None`` for empty/None input.
    """
    if not raw:
        return None
    chars = [c for c in str(raw) if c.isdigit() or c in "Xx"]
    return "".join(chars).upper() or None


def to_isbn10(raw: str | None) -> str | None:
    """Return the ISBN-10 for ``raw``, or ``None`` if there isn't one.

    Accepts an ISBN-10 (returned as-is after normalisation) or a 978-prefixed
    ISBN-13 (converted). 979-prefixed ISBN-13s and anything malformed yield
    ``None``.
    """
    n = normalize_isbn(raw)
    if n is None:
        return None
    if len(n) == 10:
        return n
    if len(n) == 13 and n.startswith("978") and n.isdigit():
        core = n[3:12]  # the 9 payload digits
        total = sum((10 - i) * int(d) for i, d in enumerate(core))
        check = (11 - total % 11) % 11
        return core + ("X" if check == 10 else str(check))
    return None


def dp_path(isbn10: str) -> str:
    """The Amazon product path for an ISBN-10 (== print ASIN), e.g. ``/dp/0441013597``."""
    return f"/dp/{isbn10}"
