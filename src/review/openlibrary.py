from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

SEARCH_URL = "https://openlibrary.org/search.json"
COVER_URL = "https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg"
WORLDCAT_COVER_URL = "https://covers.worldcat.org/isbn/{isbn}-L.jpg"
LIBRARYTHING_REST_URL = "https://www.librarything.com/services/rest/1.1/"
FIELDS = "title,author_name,isbn,first_publish_year,cover_i,subject,key,number_of_pages_median"
CACHE_DIR = Path.home() / ".review" / "cache"


def _cache_path(query: str) -> Path:
    key = hashlib.sha256(query.encode()).hexdigest()[:16]
    return CACHE_DIR / f"{key}.json"


def search(query: str, limit: int = 6) -> list[dict]:
    cache_file = _cache_path(query)
    if cache_file.exists():
        return json.loads(cache_file.read_text())

    params = {"q": query, "fields": FIELDS, "limit": limit}
    try:
        resp = httpx.get(SEARCH_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []

    results = [_normalise(doc) for doc in data.get("docs", [])]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(results))
    return results


def _normalise(doc: dict) -> dict:
    isbns = doc.get("isbn") or []
    isbn = isbns[0] if isbns else None

    authors_raw = doc.get("author_name") or []
    authors = []
    for name in authors_raw:
        parts = name.rsplit(" ", 1)
        last = parts[-1] if parts else name
        first = parts[0] if len(parts) > 1 else ""
        authors.append({"first": first, "last": last, "role": "author"})

    subjects = doc.get("subject") or []

    return {
        "title": doc.get("title", ""),
        "authors": authors,
        "isbn": isbn,
        "year": doc.get("first_publish_year"),
        "page_count": doc.get("number_of_pages_median"),
        "cover_i": doc.get("cover_i"),
        "subjects": subjects[:10],
        "ol_key": doc.get("key", ""),
    }


def cover_url(isbn: str) -> str:
    return COVER_URL.format(isbn=isbn)


def fetch_cover_bytes(isbn: str, cover_i: int | None = None) -> bytes | None:
    # 1. Open Library by ISBN
    try:
        resp = httpx.get(cover_url(isbn), timeout=15, follow_redirects=True)
        resp.raise_for_status()
        content = resp.content
        # Open Library returns a tiny GIF placeholder when no cover exists
        if len(content) >= 2000:
            return content
    except Exception:
        pass

    # 2. Open Library by cover_i (different index, higher hit rate than ISBN lookup)
    if cover_i:
        result = fetch_cover_by_ol_id(cover_i)
        if result:
            return result

    # 3. WorldCat
    result = _fetch_cover_worldcat(isbn)
    if result:
        return result

    # Google Books disabled — API returns 429 (rate-limited without a key)
    # LibraryThing disabled — API blocked by Cloudflare JS challenge

    return None


def fetch_cover_by_ol_id(cover_i: int) -> bytes | None:
    url = f"https://covers.openlibrary.org/b/id/{cover_i}-L.jpg"
    try:
        resp = httpx.get(url, timeout=15, follow_redirects=True)
        resp.raise_for_status()
        content = resp.content
        if len(content) < 2000:
            return None
        return content
    except Exception:
        return None


GOOGLE_BOOKS_URL = "https://www.googleapis.com/books/v1/volumes"


def _fetch_cover_worldcat(isbn: str) -> bytes | None:
    try:
        url = WORLDCAT_COVER_URL.format(isbn=isbn)
        resp = httpx.get(url, timeout=15, follow_redirects=True)
        resp.raise_for_status()
        content = resp.content
        if len(content) < 2000:
            return None
        return content
    except Exception:
        return None


# Google Books: disabled — returns 429 without an API key; re-enable by passing
# ?key=... once a Google Books API key is added to config.
def _fetch_cover_google_books(isbn: str) -> bytes | None:
    try:
        resp = httpx.get(GOOGLE_BOOKS_URL, params={"q": f"isbn:{isbn}"}, timeout=10)
        resp.raise_for_status()
        items = resp.json().get("items") or []
        if not items:
            return None
        links = items[0].get("volumeInfo", {}).get("imageLinks", {})
        # prefer largest available
        img_url = (
            links.get("extraLarge")
            or links.get("large")
            or links.get("medium")
            or links.get("small")
            or links.get("thumbnail")
        )
        if not img_url:
            return None
        # Google Books serves http; force https and strip zoom for full size
        img_url = img_url.replace("http://", "https://").replace("&zoom=1", "&zoom=0")
        img_resp = httpx.get(img_url, timeout=15, follow_redirects=True)
        img_resp.raise_for_status()
        content = img_resp.content
        if len(content) < 2000:
            return None
        return content
    except Exception:
        return None


# LibraryThing: disabled — REST API blocked by Cloudflare JS challenge.
def _fetch_cover_librarything(isbn: str, api_key: str) -> bytes | None:
    try:
        resp = httpx.get(
            LIBRARYTHING_REST_URL,
            params={"method": "librarything.ck.getwork", "isbn": isbn, "apikey": api_key},
            timeout=10,
        )
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        if root.get("stat") != "ok":
            return None
        src = root.findtext(".//covers/cover/src")
        if not src:
            return None
        img_resp = httpx.get(src, timeout=15, follow_redirects=True)
        img_resp.raise_for_status()
        content = img_resp.content
        if len(content) < 2000:
            return None
        return content
    except Exception:
        return None
