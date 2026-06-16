"""Amazon cover sourcing: product-page scrape + image-URL resolution upgrader.

Amazon's product page embeds the genuine full-resolution cover master on the
``m.media-amazon.com/images/I/`` item-image path, carrying a size suffix, e.g.
``..._SY466_.jpg`` / ``..._AC_UF1000,1000_QL80_.jpg``. Stripping that modifier
block yields the original asset (2560px tall in practice, vs ~500px from
Goodreads/Open Library/the ISBN ``/images/P/`` endpoint — those all serve
re-compressed copies). Recovering that master is the whole point of sourcing here.

The ``/images/I/`` URL is keyed by an internal image id, so it can't be built
from an ISBN — it has to be read off the rendered product page. Amazon serves a
captcha to plain HTTP clients, so the page is fetched through a real browser
(:mod:`review.browser`). HTML parsing is kept pure so it can be unit-tested
against saved fixtures.
"""
from __future__ import annotations

import json
import re
from urllib.parse import quote_plus

from .cache import cached_json, cached_text

BASE = "https://www.amazon.com"
HOME_URL = f"{BASE}/"
SEARCH_URL = f"{BASE}/s"

# Matches the trailing ``._<MODIFIERS>_.<ext>`` block Amazon appends to scale an
# image, e.g. ``._SX318_.jpg`` / ``._SY466_.jpg`` / ``._AC_UF1000,1000_QL80_.jpg``.
_SUFFIX_RE = re.compile(r"\._[A-Z0-9_,]+_\.(jpg|jpeg|png|gif)$", re.IGNORECASE)

# A product link on a search-results page: ``/<slug>/dp/<ASIN>/...``.
_PRODUCT_PATH_RE = re.compile(r'href="(/[^"]*?/dp/[A-Z0-9]{10}[^"]*)"')
_ASIN_RE = re.compile(r"/dp/([A-Z0-9]{10})")

# Slug fragments that mark a bundle/omnibus rather than a single edition. Their
# main product image is a multi-spine montage or a 3-D box photo, not a single
# book cover — exactly the "not actually covers" results we want to drop. Matched
# against the human slug portion of the product path (before ``/dp/``).
#
# Only STRONG, unambiguous bundle markers belong here. Bare "trilogy"/"saga"/
# "collection" are *series names* that single volumes carry too (e.g. "Blue Mars
# (Mars Trilogy)", "Annihilation (Southern Reach Trilogy)"), so matching them
# wrongly dropped legit single editions before they were ever visited. "trilogy"
# now only counts when paired with a bundle word (boxed set / collection). The
# title-overlap gate in :func:`title_matches` is the backstop for the residual
# ambiguous omnibus (e.g. "The Great Dune Trilogy").
_BUNDLE_RE = re.compile(
    r"box(ed)?[- ]?set|omnibus|\d+[- ]book|book[- ]set|"
    r"(saga|trilogy)[- ]collection|complete[- ](series|collection|saga|trilogy)",
    re.IGNORECASE,
)


def upgrade_resolution(url: str) -> str:
    """Strip the Amazon size suffix so the URL points at the full-res original.

    Idempotent: a URL with no size suffix (including an already-upgraded one) is
    returned unchanged.
    """
    return _SUFFIX_RE.sub(r".\1", url)


# --------------------------------------------------------------------------
# Pure parsers
# --------------------------------------------------------------------------


def asin_of(path: str) -> str:
    """The 10-char ASIN from a ``/dp/<ASIN>`` path, or the path if none found."""
    m = _ASIN_RE.search(path)
    return m.group(1) if m else path


_IMAGE_ID_RE = re.compile(r"/images/I/([^/.]+)")


def image_id(url: str) -> str | None:
    """The stable Amazon image id from an ``/images/I/<id>...`` URL, if present.

    The id uniquely identifies the asset regardless of size suffix, so it makes a
    compact, collision-free cache key for the downloaded master.
    """
    m = _IMAGE_ID_RE.search(url or "")
    return m.group(1) if m else None


# Product titles that aren't the book itself: study guides, summaries, etc. Their
# covers are real but wrong, and a title-token check can't catch them because the
# book's title is *contained* in "Summary of <title>". Reject by keyword instead.
_TITLE_JUNK_RE = re.compile(
    r"\b(summary|summaries|study guide|workbook|analysis|sparknotes|"
    r"cliffs?notes|trivia|quiz|companion|key takeaways|conversation starters|"
    r"a guide to|insight|booknotes)\b",
    re.IGNORECASE,
)
_TITLE_STOP = {"a", "an", "the", "of", "and", "or", "in", "on", "to", "for", "&"}


def _title_tokens(text: str) -> set[str]:
    # Tokens before any subtitle (": …"), lowercased, stopwords dropped.
    # Parenthetical series/edition notes are stripped first: our stored titles
    # carry "(Series, #1-3)" tags whose tokens ("1", "3", series words) inflate
    # the denominator and sink a plain edition below the overlap gate — e.g.
    # title_matches("Cyteen (Cyteen, #1-3)", "Cyteen") must accept.
    head = text.split(":", 1)[0]
    head = re.sub(r"\([^)]*\)", " ", head)
    words = re.findall(r"[a-z0-9]+", head.lower())
    return {w for w in words if w not in _TITLE_STOP}


def title_matches(want: str, got: str, *, min_overlap: float = 0.6) -> bool:
    """True if product title ``got`` plausibly names the same book as ``want``.

    Used only on the fuzzy search-fallback path (ISBN-direct needs no check). A
    study-guide/summary keyword is an immediate reject; otherwise enough of the
    wanted title's significant tokens must appear in the product title.
    """
    if not got:
        return True  # nothing to judge against → don't over-filter
    if _TITLE_JUNK_RE.search(got):
        return False
    want_tokens = _title_tokens(want)
    if not want_tokens:
        return True
    overlap = len(want_tokens & _title_tokens(got)) / len(want_tokens)
    return overlap >= min_overlap


def is_single_volume(path: str) -> bool:
    """False for box-set / collection / omnibus / multi-book product paths.

    Bundle products carry a montage or box-photo as their main image rather than
    a single cover, so they are filtered out before we bother visiting them.
    Tested only against the slug part (before ``/dp/``) so an ASIN never matches.
    """
    slug = path.split("/dp/", 1)[0]
    return _BUNDLE_RE.search(slug) is None


def parse_search_product_paths(html: str) -> list[str]:
    """Distinct ``/dp/<ASIN>`` product paths from a search-results page, in order."""
    seen: set[str] = set()
    paths: list[str] = []
    for path in _PRODUCT_PATH_RE.findall(html):
        # Key on the ASIN so the same product via different tracking params dedups.
        asin = asin_of(path)
        if asin in seen:
            continue
        seen.add(asin)
        paths.append(path)
    return paths


# Attributes on the ``#landingImage`` element that carry the main cover URL, in
# preference order. ``upgrade_resolution`` collapses any of them to the same
# full-res master, so the choice only matters when some are absent.
LANDING_IMG_SELECTOR = "#landingImage"
LANDING_IMG_ATTRS = ("data-old-hires", "data-a-dynamic-image", "src")
PRODUCT_TITLE_SELECTOR = "#productTitle"

# One navigation reads the cover-image attributes and the product title together.
_PRODUCT_QUERIES = tuple((a, LANDING_IMG_SELECTOR, a) for a in LANDING_IMG_ATTRS) + (
    ("title", PRODUCT_TITLE_SELECTOR, None),
)


def pick_largest_dynamic_image(dynamic_json: str) -> str | None:
    """Largest-area URL from a ``data-a-dynamic-image`` ``{url: [w, h]}`` blob."""
    try:
        sizes = json.loads(dynamic_json.replace("&quot;", '"'))
    except (ValueError, AttributeError):
        return None
    if not sizes:
        return None
    return max(sizes.items(), key=lambda kv: kv[1][0] * kv[1][1])[0]


def main_cover_url(attrs: dict[str, str | None] | None) -> str | None:
    """Resolve the main cover URL from a ``#landingImage`` element's attributes.

    Critically, this reads only the *product's own* image — regexing every
    ``/images/I/`` URL off the page would also scoop up the "customers also
    bought" carousels, i.e. other books' covers.
    """
    if not attrs:
        return None
    hires = attrs.get("data-old-hires")
    if hires:
        return hires
    dynamic = attrs.get("data-a-dynamic-image")
    if dynamic:
        largest = pick_largest_dynamic_image(dynamic)
        if largest:
            return largest
    return attrs.get("src") or None


# --------------------------------------------------------------------------
# Browser-driven sourcing (edge)
# --------------------------------------------------------------------------


def product_fields(
    page, path: str, cache_key: str, settle_ms: int, refresh: bool = False
) -> dict[str, str | None]:
    """The cover-image attrs + product title for one product page (cached).

    Reading a specific DOM element keeps us to the product's own cover and off
    neighbouring carousels. Returns a dict whose image attrs may all be ``None``
    when the page isn't a real product (e.g. a 404), which :func:`main_cover_url`
    then reports as "no cover".
    """
    url = path if path.startswith("http") else BASE + path
    try:
        return cached_json(
            cache_key,
            lambda: page.read_fields(url, _PRODUCT_QUERIES, settle_ms=settle_ms),
            refresh=refresh,
        )
    except Exception:
        # A nav timeout / transient browser error on one product must not abort
        # the batch; treat it as "no cover here". Nothing is cached, so a re-run
        # retries this product.
        return {}


def search_products(
    page, query: str, max_products: int = 5, settle_ms: int = 2500, refresh: bool = False
) -> list[tuple[str, str]]:
    """``(cover_url, product_title)`` for the top single-volume search results.

    Box sets / collections / omnibus volumes are dropped (:func:`is_single_volume`)
    before they cost a page load, each survivor's main cover is upgraded to full
    resolution, and results are de-duplicated by cover URL. Caching as per
    :mod:`review.cache`.
    """
    search_url = f"{SEARCH_URL}?k={quote_plus(query)}&i=stripbooks"
    try:
        search_html = cached_text(
            f"search__{query}",
            lambda: page.html(search_url, settle_ms=settle_ms),
            refresh=refresh,
        )
    except Exception:
        return []  # search nav failed; nothing cached, retried on re-run
    paths = [p for p in parse_search_product_paths(search_html) if is_single_volume(p)]

    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for path in paths[:max_products]:
        fields = product_fields(page, path, f"product__{asin_of(path)}", settle_ms, refresh)
        raw = main_cover_url(fields)
        if not raw:
            continue
        url = upgrade_resolution(raw)
        if url in seen:
            continue
        seen.add(url)
        out.append((url, (fields.get("title") or "").strip()))
    return out


def search_cover_urls(
    title: str,
    author: str = "",
    max_products: int = 5,
    settle_ms: int = 2500,
    page=None,
    refresh: bool = False,
) -> list[str]:
    """Search Amazon Books and return full-res cover URLs for the top editions.

    Thin wrapper over :func:`search_products` kept for ``find-covers``. Pass
    ``page`` (from a warmed :func:`review.browser.browser_session`) to reuse one
    browser; otherwise a fresh session is opened. May raise
    :class:`review.browser.BrowserUnavailable`.
    """
    query = f"{title} {author}".strip()
    if page is not None:
        return [u for u, _ in search_products(page, query, max_products, settle_ms, refresh)]

    from .browser import browser_session

    with browser_session(warmup_url=HOME_URL) as p:
        return [u for u, _ in search_products(p, query, max_products, settle_ms, refresh)]
