"""Goodreads edition scraper (Slice 3, deep module).

Finds alternate editions of a book so the user has real choices for a better
cover. Goodreads serves Amazon/gr-assets-hosted cover thumbnails carrying a size
suffix; pair this with :func:`review.amazon.upgrade_resolution` to recover the
full-resolution originals.

Network lives at the edge (:func:`_fetch`, :func:`fetch_image`). HTML parsing is
pure (:func:`parse_first_book_url`, :func:`parse_work_editions_url`,
:func:`parse_editions`) so it can be exercised against saved fixtures. Per the
PRD these parsers are validated by manual run rather than committed fixtures,
because Goodreads markup drifts.

Goodreads sits behind CloudFront bot-blocking; a challenged request comes back
non-200 (often 202) with an empty body. That is detected and surfaced as
:class:`GoodreadsBlocked` so callers can report it cleanly. This is a known,
accepted risk — residential IPs typically pass where datacenter IPs do not.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

BASE = "https://www.goodreads.com"
SEARCH_URL = f"{BASE}/search"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Upgrade-Insecure-Requests": "1",
}

# Cover assets live on the books-cover CDN path, e.g.
# https://i.gr-assets.com/images/S/compressed.photo.goodreads.com/books/1390052879i/13547180._SY475_.jpg
_COVER_URL_RE = re.compile(
    r"https://[^\s\"'<>]*?/books/\d+i?/[^\s\"'<>]+?\.(?:jpg|jpeg|png)", re.IGNORECASE
)
_BOOK_SHOW_RE = re.compile(r"/book/show/(\d+)")
_WORK_EDITIONS_RE = re.compile(r"/work/editions/(\d+)")


class GoodreadsBlocked(RuntimeError):
    """Raised when Goodreads returns a bot-challenge instead of real content."""


@dataclass
class Edition:
    cover_url: str
    title: str | None = None


# --------------------------------------------------------------------------
# Pure parsers
# --------------------------------------------------------------------------


def parse_first_book_url(html: str) -> str | None:
    """The first ``/book/show/<id>`` link on a search results page."""
    m = _BOOK_SHOW_RE.search(html)
    return f"{BASE}/book/show/{m.group(1)}" if m else None


def parse_work_editions_url(html: str) -> str | None:
    """The ``/work/editions/<id>`` link from a book page."""
    m = _WORK_EDITIONS_RE.search(html)
    return f"{BASE}/work/editions/{m.group(1)}?per_page=100" if m else None


def parse_editions(html: str) -> list[Edition]:
    """All distinct cover-image URLs on the page, in document order."""
    seen: set[str] = set()
    editions: list[Edition] = []
    for url in _COVER_URL_RE.findall(html):
        if url not in seen:
            seen.add(url)
            editions.append(Edition(cover_url=url))
    return editions


# --------------------------------------------------------------------------
# Network edge
# --------------------------------------------------------------------------


def _fetch(url: str, params: dict | None = None, timeout: float = 20.0) -> str:
    resp = httpx.get(url, params=params, headers=HEADERS, timeout=timeout, follow_redirects=True)
    # A challenged request returns non-200 (often 202) with an empty/tiny body.
    if resp.status_code != 200 or len(resp.text) < 500:
        raise GoodreadsBlocked(f"Goodreads returned {resp.status_code} for {url}")
    return resp.text


def fetch_image(url: str, timeout: float = 20.0) -> bytes | None:
    try:
        resp = httpx.get(url, headers=HEADERS, timeout=timeout, follow_redirects=True)
        resp.raise_for_status()
        content = resp.content
        return content if len(content) >= 2000 else None
    except Exception:
        return None


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------


def search_editions(title: str, author: str = "", max_editions: int = 40) -> list[Edition]:
    """Search Goodreads for a book and return its alternate editions' covers.

    Resolves search → first book → its editions page, falling back to whatever
    covers are on the page already if a step can't be resolved. Raises
    :class:`GoodreadsBlocked` if Goodreads serves a bot-challenge.
    """
    query = f"{title} {author}".strip()
    search_html = _fetch(SEARCH_URL, params={"q": query})

    book_url = parse_first_book_url(search_html)
    if not book_url:
        return parse_editions(search_html)[:max_editions]

    book_html = _fetch(book_url)
    work_url = parse_work_editions_url(book_html)
    if not work_url:
        return parse_editions(book_html)[:max_editions]

    editions_html = _fetch(work_url)
    return parse_editions(editions_html)[:max_editions]
