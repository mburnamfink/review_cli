"""Cover-matching cascade: turn a book into ranked, on-disk cover candidates.

Anchors on identity first. When the book has an ISBN we load the exact Amazon
product page (``/dp/<isbn10>``) and trust its main image — no search, so no wrong
edition or box-set montage. Only when that's unavailable (no ISBN-10, or the
unattended pass is told ISBN-only) do we fall back to a fuzzy title+author search,
and there a title-identity gate rejects summaries / study-guides / wrong books.

Downloaded full-res masters are cached to disk (:func:`review.cache.cached_bytes`)
so re-processing a cover never re-downloads.
"""
from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image

from . import amazon
from .cache import cached_bytes
from .goodreads import fetch_image
from .isbn import normalize_isbn
from .ranking import Candidate, rank_candidates

# Book covers are portrait; product pages also carry square A+ art, author photos
# and the occasional landscape promo banner. Require portrait-ish and non-thumbnail.
MIN_COVER_WIDTH = 400
MIN_ASPECT = 1.15  # height / width


@dataclass
class Match:
    url: str
    title: str
    source: str  # "isbn-search" | "search" | "manual"


def gather_matches(
    title: str,
    author: str = "",
    isbn: str | None = None,
    *,
    page=None,
    max_products: int = 5,
    settle_ms: int = 2500,
    refresh: bool = False,
    isbn_only: bool = False,
    skip_title_if_isbn: bool = False,
) -> list[Match]:
    """Candidate cover matches for a book: search by ISBN first, then title.

    Searching Amazon by ISBN-13 is the reliable exact-identity lookup — it lands
    the right book in all its editions (a direct ``/dp/<isbn10>`` doesn't, because
    Amazon's print ASIN usually isn't the book's ISBN-10). A title-identity gate
    drops study-guides / summaries / wrong books that ride along. ``isbn_only``
    skips the fuzzy title search entirely; ``skip_title_if_isbn`` runs the title
    search only when the ISBN search found nothing (the fast staging profile —
    fewer page loads for the ~91% of books with a working ISBN). Pass ``page`` to
    reuse a warmed browser session; otherwise one is opened. May raise
    :class:`review.browser.BrowserUnavailable`.
    """

    def _collect(p, query, source, out, seen):
        for url, ptitle in amazon.search_products(p, query, max_products, settle_ms, refresh):
            if url in seen or not amazon.title_matches(title, ptitle):
                continue
            seen.add(url)
            out.append(Match(url, ptitle, source))

    def _run(p) -> list[Match]:
        out: list[Match] = []
        seen: set[str] = set()
        isbn_q = normalize_isbn(isbn)
        if isbn_q:
            _collect(p, isbn_q, "isbn-search", out, seen)
        do_title = not isbn_only and not (skip_title_if_isbn and out)
        if do_title:
            _collect(p, f"{title} {author}".strip(), "search", out, seen)
        return out

    if page is not None:
        return _run(page)

    from .browser import browser_session

    with browser_session(warmup_url=amazon.HOME_URL) as p:
        return _run(p)


def download_candidate(
    url: str, *, title: str = "", refresh: bool = False, enforce_cover: bool = True
) -> Candidate | None:
    """Download one image (cached master) into a Candidate, or ``None``.

    With ``enforce_cover`` the image must be a non-thumbnail portrait (drops
    square A+ art / landscape promos); a deliberate ``manual_url`` override passes
    ``enforce_cover=False`` so the user's explicit choice is honoured as-is.
    """
    key = f"image__{amazon.image_id(url) or url}"
    data = cached_bytes(key, lambda: fetch_image(url), refresh=refresh)
    if not data:
        return None
    try:
        img = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        return None
    if enforce_cover and (img.width < MIN_COVER_WIDTH or img.height < img.width * MIN_ASPECT):
        return None
    return Candidate(image=img, source_url=url, data=data, title=title)


def download_candidates(
    matches: list[Match], cap: int = 8, refresh: bool = False
) -> list[Candidate]:
    """Download each match's master (cached), drop non-covers, dedup and rank."""
    candidates: list[Candidate] = []
    for m in matches:
        cand = download_candidate(m.url, title=m.title, refresh=refresh)
        if cand is not None:
            candidates.append(cand)
    return rank_candidates(candidates, cap=cap)
