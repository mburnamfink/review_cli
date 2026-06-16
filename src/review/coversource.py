"""Unified cover sourcing for the individual-edit commands.

There are two ways to get a cover, with very different quality:

* **Amazon master** (:mod:`review.covermatch` → :mod:`review.amazon`) — the genuine
  full-resolution cover (~2560px), but it needs a headless browser (Playwright +
  Chrome), a heavy optional dependency.
* **OpenLibrary / WorldCat** (:func:`review.openlibrary.fetch_cover_bytes`) —
  httpx-only, works everywhere with no setup, but serves re-compressed ~500px
  copies.

The bulk repair pipeline (``stage-covers``) exists precisely because ``new`` and
``fetch-cover`` have historically used only the low-res httpx path. This module
lets them prefer the Amazon master *when it's available*, while always degrading
gracefully to the httpx path so creating a review is never blocked by a missing or
broken browser. The default stays ``"openlibrary"`` (bulletproof); a user who has
the browser extra installed sets ``cover_source = "auto"`` (or ``"amazon"``).
"""
from __future__ import annotations

import importlib.util

from .openlibrary import fetch_cover_bytes

# Resolved-source labels callers may see back from :func:`source_cover`.
AMAZON = "amazon"
OPENLIBRARY = "openlibrary"

VALID_SOURCES = ("openlibrary", "amazon", "auto")


def browser_available() -> bool:
    """Fast, side-effect-free test of whether the Amazon path can even be tried.

    Just checks that Playwright is importable — it does *not* launch a browser, so
    it's instant. A launch that fails later (no Chrome, sandbox, etc.) is still
    caught and falls back; this probe only avoids paying that cost on the common
    minimal install where Playwright isn't present at all.
    """
    return importlib.util.find_spec("playwright") is not None


def resolve_order(source: str) -> list[str]:
    """The ordered source cascade for a configured/flagged ``source`` value.

    * ``"openlibrary"`` → httpx only (no browser ever touched).
    * ``"amazon"`` → Amazon first, then httpx fallback.
    * ``"auto"`` → Amazon first *iff* a browser is installed, then httpx fallback.
    """
    if source == "amazon":
        return [AMAZON, OPENLIBRARY]
    if source == "auto":
        return [AMAZON, OPENLIBRARY] if browser_available() else [OPENLIBRARY]
    return [OPENLIBRARY]


def _try_amazon(title: str, author: str, isbn: str | None, refresh: bool) -> bytes | None:
    """Best full-res Amazon master for a book, or ``None`` on any failure.

    Deliberately swallows every error (no browser, captcha, timeout, no match) so
    the caller can fall through to the httpx path — the Amazon path is always a
    best-effort upgrade, never a hard requirement.
    """
    # Imported lazily: pulls in the browser stack only when Amazon is actually tried.
    from . import covermatch
    from .browser import BrowserUnavailable

    try:
        matches = covermatch.gather_matches(
            title, author, isbn, refresh=refresh, skip_title_if_isbn=True
        )
        ranked = covermatch.download_candidates(matches, cap=1, refresh=refresh)
    except BrowserUnavailable:
        return None
    except Exception:
        return None
    return ranked[0].data if ranked else None


def source_cover(
    title: str,
    author: str = "",
    isbn: str | None = None,
    *,
    cover_i: int | None = None,
    source: str = "auto",
    refresh: bool = False,
) -> tuple[bytes | None, str]:
    """Fetch cover bytes via the configured cascade.

    Returns ``(data, used_source)`` where ``used_source`` is the label of the
    source that produced the bytes (``"amazon"`` / ``"openlibrary"``) or ``""``
    when nothing was found.
    """
    for src in resolve_order(source):
        if src == AMAZON:
            data = _try_amazon(title, author, isbn, refresh)
        else:
            data = fetch_cover_bytes(isbn, cover_i=cover_i) if isbn else None
        if data:
            return data, src
    return None, ""
