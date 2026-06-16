"""Tests for the scrape cache (review.cache)."""
from __future__ import annotations

import review.cache as cache


def _point_cache_at(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "AMAZON_CACHE", tmp_path / "amazon")


def test_cached_text_produces_then_reuses(tmp_path, monkeypatch):
    _point_cache_at(tmp_path, monkeypatch)
    calls = []

    def produce():
        calls.append(1)
        return "<html>hi</html>"

    assert cache.cached_text("search__dune", produce) == "<html>hi</html>"
    assert cache.cached_text("search__dune", produce) == "<html>hi</html>"
    assert len(calls) == 1  # second call served from disk
    assert (tmp_path / "amazon" / "search__dune.html").exists()


def test_cached_text_refresh_bypasses(tmp_path, monkeypatch):
    _point_cache_at(tmp_path, monkeypatch)
    calls = []

    def produce():
        calls.append(1)
        return f"v{len(calls)}"

    assert cache.cached_text("k", produce) == "v1"
    assert cache.cached_text("k", produce, refresh=True) == "v2"
    assert len(calls) == 2


def test_cached_text_ttl_expiry(tmp_path, monkeypatch):
    _point_cache_at(tmp_path, monkeypatch)
    calls = []

    def produce():
        calls.append(1)
        return f"v{len(calls)}"

    # A tiny positive TTL with a backdated mtime counts as stale → re-produced.
    assert cache.cached_text("k", produce, ttl=1000) == "v1"
    path = tmp_path / "amazon" / "k.html"
    import os, time
    old = time.time() - 5000
    os.utime(path, (old, old))
    assert cache.cached_text("k", produce, ttl=1000) == "v2"
    assert len(calls) == 2
    # ttl<=0 means "never expires": served from disk regardless of age.
    assert cache.cached_text("k", produce, ttl=0) == "v2"
    assert len(calls) == 2


def test_cached_json_roundtrips_none(tmp_path, monkeypatch):
    _point_cache_at(tmp_path, monkeypatch)
    calls = []

    def produce():
        calls.append(1)
        return None

    assert cache.cached_json("product__X", produce) is None
    assert cache.cached_json("product__X", produce) is None
    assert len(calls) == 1  # None is cached, not re-produced


def test_cached_json_roundtrips_dict(tmp_path, monkeypatch):
    _point_cache_at(tmp_path, monkeypatch)
    val = {"data-old-hires": "https://example/x.jpg", "src": None}
    assert cache.cached_json("p", lambda: val) == val
    assert cache.cached_json("p", lambda: {"never": "used"}) == val


def test_corrupt_json_is_reproduced(tmp_path, monkeypatch):
    _point_cache_at(tmp_path, monkeypatch)
    (tmp_path / "amazon").mkdir(parents=True)
    (tmp_path / "amazon" / "p.json").write_text("{bad json", encoding="utf-8")
    assert cache.cached_json("p", lambda: {"ok": 1}) == {"ok": 1}


def test_cached_bytes_produces_then_reuses(tmp_path, monkeypatch):
    _point_cache_at(tmp_path, monkeypatch)
    calls = []

    def produce():
        calls.append(1)
        return b"\xff\xd8imagebytes"

    assert cache.cached_bytes("image__abc", produce) == b"\xff\xd8imagebytes"
    assert cache.cached_bytes("image__abc", produce) == b"\xff\xd8imagebytes"
    assert len(calls) == 1
    assert (tmp_path / "amazon" / "images" / "image__abc.jpg").exists()


def test_cached_bytes_does_not_cache_failed_download(tmp_path, monkeypatch):
    _point_cache_at(tmp_path, monkeypatch)
    calls = []

    def produce():
        calls.append(1)
        return None

    assert cache.cached_bytes("image__x", produce) is None
    assert cache.cached_bytes("image__x", produce) is None
    assert len(calls) == 2  # a failed download is retried, not cached
    assert not (tmp_path / "amazon" / "images" / "image__x.jpg").exists()
