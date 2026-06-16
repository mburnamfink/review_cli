"""Cover-source cascade: ordering and graceful fallback (no network)."""
from __future__ import annotations

import review.coversource as cs


# --- resolve_order -------------------------------------------------------


def test_openlibrary_never_touches_browser():
    assert cs.resolve_order("openlibrary") == ["openlibrary"]


def test_amazon_falls_back_to_openlibrary():
    assert cs.resolve_order("amazon") == ["amazon", "openlibrary"]


def test_auto_uses_amazon_when_browser_available(monkeypatch):
    monkeypatch.setattr(cs, "browser_available", lambda: True)
    assert cs.resolve_order("auto") == ["amazon", "openlibrary"]


def test_auto_skips_amazon_without_browser(monkeypatch):
    monkeypatch.setattr(cs, "browser_available", lambda: False)
    assert cs.resolve_order("auto") == ["openlibrary"]


# --- source_cover cascade ------------------------------------------------


def test_amazon_hit_short_circuits_openlibrary(monkeypatch):
    monkeypatch.setattr(cs, "_try_amazon", lambda *a, **k: b"amazon-bytes")
    called = {"ol": False}

    def _ol(isbn, cover_i=None):
        called["ol"] = True
        return b"ol-bytes"

    monkeypatch.setattr(cs, "fetch_cover_bytes", _ol)
    data, used = cs.source_cover("T", "A", "123", source="amazon")
    assert (data, used) == (b"amazon-bytes", "amazon")
    assert called["ol"] is False  # OL never consulted once Amazon succeeds


def test_amazon_miss_falls_through_to_openlibrary(monkeypatch):
    monkeypatch.setattr(cs, "_try_amazon", lambda *a, **k: None)
    monkeypatch.setattr(cs, "fetch_cover_bytes", lambda isbn, cover_i=None: b"ol-bytes")
    data, used = cs.source_cover("T", "A", "123", source="amazon")
    assert (data, used) == (b"ol-bytes", "openlibrary")


def test_openlibrary_skipped_without_isbn(monkeypatch):
    # With no ISBN and the httpx-only source, there is nothing to try.
    sentinel = {"called": False}

    def _ol(isbn, cover_i=None):
        sentinel["called"] = True
        return b"x"

    monkeypatch.setattr(cs, "fetch_cover_bytes", _ol)
    data, used = cs.source_cover("T", "A", None, source="openlibrary")
    assert (data, used) == (None, "")
    assert sentinel["called"] is False


def test_nothing_found_returns_empty(monkeypatch):
    monkeypatch.setattr(cs, "_try_amazon", lambda *a, **k: None)
    monkeypatch.setattr(cs, "fetch_cover_bytes", lambda isbn, cover_i=None: None)
    assert cs.source_cover("T", "A", "123", source="amazon") == (None, "")


def test_try_amazon_swallows_browser_unavailable(monkeypatch):
    # A missing/broken browser must degrade to None, never raise.
    import review.covermatch as covermatch
    from review.browser import BrowserUnavailable

    def _boom(*a, **k):
        raise BrowserUnavailable("no browser")

    monkeypatch.setattr(covermatch, "gather_matches", _boom)
    assert cs._try_amazon("T", "A", "123", refresh=False) is None
