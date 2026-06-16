"""Tiny on-disk cache for the Amazon scraper.

Two reasons it exists: (1) driving a real browser against Amazon is slow and
rate-limited, so re-runs while iterating on the parser shouldn't re-hit the
network; (2) the raw returns are written under human-readable names so you can
open them and "follow along" — the rendered search HTML and each product's
extracted ``#landingImage`` attributes land as files you can inspect.

Entries live under ``~/.review/cache/amazon/`` (``CACHE_DIR``). A logical key is
slugified into the filename. A read is used only when the entry exists and is
younger than the TTL; pass ``refresh=True`` to force a re-fetch (the CLI exposes
this as ``--refresh``).
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Callable

from .config import CACHE_DIR

AMAZON_CACHE = CACHE_DIR / "amazon"
DEFAULT_TTL = 7 * 24 * 3600  # one week


def _slug(key: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", key).strip("-").lower()
    return s[:120] or "entry"


def _fresh(path: Path, ttl: float) -> bool:
    if not path.exists():
        return False
    return ttl <= 0 or (time.time() - path.stat().st_mtime) < ttl


def cached_text(
    key: str,
    producer: Callable[[], str],
    *,
    ttl: float = DEFAULT_TTL,
    refresh: bool = False,
    ext: str = "html",
) -> str:
    """Return cached text for ``key``, else call ``producer`` and cache it."""
    path = AMAZON_CACHE / f"{_slug(key)}.{ext}"
    if not refresh and _fresh(path, ttl):
        return path.read_text(encoding="utf-8")
    value = producer()
    AMAZON_CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    return value


def cached_bytes(
    key: str,
    producer: Callable[[], bytes | None],
    *,
    ttl: float = DEFAULT_TTL,
    refresh: bool = False,
    ext: str = "jpg",
) -> bytes | None:
    """Return cached bytes for ``key``, else call ``producer`` and cache them.

    Used to keep the full-resolution cover masters on disk so re-processing a
    cover (regenerating cover.jpg / og-cover.jpg) never re-downloads. Files land
    under ``amazon/images/``. A ``None``/empty producer result (failed download)
    is *not* cached, so the next run retries.
    """
    path = AMAZON_CACHE / "images" / f"{_slug(key)}.{ext}"
    if not refresh and _fresh(path, ttl):
        return path.read_bytes()
    value = producer()
    if value:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
    return value


def cached_json(
    key: str,
    producer: Callable[[], Any],
    *,
    ttl: float = DEFAULT_TTL,
    refresh: bool = False,
) -> Any:
    """Return cached JSON for ``key``, else call ``producer`` and cache it.

    ``producer`` may return ``None`` (e.g. a missing element); that is cached and
    round-trips as ``None``.
    """
    path = AMAZON_CACHE / f"{_slug(key)}.json"
    if not refresh and _fresh(path, ttl):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            pass  # corrupt entry → re-produce
    value = producer()
    AMAZON_CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
    return value
