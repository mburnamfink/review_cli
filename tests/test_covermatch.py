"""Tests for the cover-matching cascade (review.covermatch), no browser/network.

A fake page serves canned search HTML and product fields keyed by a substring of
the requested URL (the ``k=<query>`` for searches, the ASIN for product reads).
The cache is redirected to tmp so cached_json/text writes don't touch the real
cache. The cascade searches Amazon by ISBN-13 first, then (unless isbn_only) by
title+author, applying a title-identity gate to both.
"""
from __future__ import annotations

import review.cache as cache
from review import covermatch

HIRES = "https://m.media-amazon.com/images/I/818wSuWyOgL._SL1500_.jpg"
MASTER = "https://m.media-amazon.com/images/I/818wSuWyOgL.jpg"
OTHER_HIRES = "https://m.media-amazon.com/images/I/71m91l0treL._SL1500_.jpg"
OTHER_MASTER = "https://m.media-amazon.com/images/I/71m91l0treL.jpg"


class FakePage:
    def __init__(self, html_by_marker, fields_by_marker):
        self.html_by_marker = html_by_marker
        self.fields_by_marker = fields_by_marker

    def html(self, url, **_):
        for marker, html in self.html_by_marker.items():
            if marker in url:
                return html
        return ""

    def read_fields(self, url, queries, **_):
        for marker, fields in self.fields_by_marker.items():
            if marker in url:
                return fields
        return {key: None for key, _sel, _attr in queries}


def _fields(title, hires=HIRES):
    return {"data-old-hires": hires, "data-a-dynamic-image": None, "src": None, "title": title}


def test_isbn_search_is_exact_and_upgraded(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "AMAZON_CACHE", tmp_path)
    page = FakePage(
        {"k=9780441013593": '<a href="/Dune/dp/0441013597/ref=sr_1_1">Dune</a>'},
        {"0441013597": _fields("Dune")},
    )
    matches = covermatch.gather_matches(
        "Dune", "Frank Herbert", isbn="9780441013593", page=page, isbn_only=True
    )
    assert len(matches) == 1
    assert matches[0].source == "isbn-search"
    assert matches[0].url == MASTER  # size suffix stripped to the master
    assert matches[0].title == "Dune"


def test_isbn_only_returns_nothing_when_no_results(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "AMAZON_CACHE", tmp_path)
    page = FakePage({}, {})  # empty search page → no products
    matches = covermatch.gather_matches(
        "Dune", "Frank Herbert", isbn="9780441013593", page=page, isbn_only=True
    )
    assert matches == []


def test_title_search_applies_identity_gate(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "AMAZON_CACHE", tmp_path)
    search_html = (
        '<a href="/Dune/dp/0441013597/ref=sr_1_1">Dune</a>'
        '<a href="/Summary-of-Dune/dp/B000000001/ref=sr_1_2">Summary</a>'
    )
    page = FakePage(
        {"k=Dune": search_html},
        {
            "0441013597": _fields("Dune"),
            "B000000001": _fields("Summary of Dune by Frank Herbert", hires=OTHER_HIRES),
        },
    )
    matches = covermatch.gather_matches(
        "Dune", "Frank Herbert", isbn=None, page=page, isbn_only=False
    )
    # The summary is rejected by the title gate; only the real edition survives.
    assert [m.source for m in matches] == ["search"]
    assert matches[0].url == MASTER


def test_isbn_then_title_combined_and_deduped(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "AMAZON_CACHE", tmp_path)
    page = FakePage(
        {
            "k=9780441013593": '<a href="/Dune/dp/0441013597/ref=sr_1_1">Dune</a>',
            "k=Dune": (
                '<a href="/Dune/dp/0441013597/ref=sr_1_1">Dune</a>'         # dup of ISBN hit
                '<a href="/Dune-ebook/dp/B00B7NPRY8/ref=sr_1_2">Dune</a>'  # different edition
            ),
        },
        {
            "0441013597": _fields("Dune"),
            "B00B7NPRY8": _fields("Dune (Kindle Edition)", hires=OTHER_HIRES),
        },
    )
    matches = covermatch.gather_matches(
        "Dune", "Frank Herbert", isbn="9780441013593", page=page, isbn_only=False
    )
    assert [m.source for m in matches] == ["isbn-search", "search"]
    assert {m.url for m in matches} == {MASTER, OTHER_MASTER}


def test_skip_title_if_isbn_skips_title_when_isbn_found(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "AMAZON_CACHE", tmp_path)
    page = FakePage(
        {
            "k=9780441013593": '<a href="/Dune/dp/0441013597/ref=sr_1_1">Dune</a>',
            "k=Dune": '<a href="/Dune-ebook/dp/B00B7NPRY8/ref=sr_1_2">Dune</a>',
        },
        {
            "0441013597": _fields("Dune"),
            "B00B7NPRY8": _fields("Dune (Kindle Edition)", hires=OTHER_HIRES),
        },
    )
    matches = covermatch.gather_matches(
        "Dune", "Frank Herbert", isbn="9780441013593", page=page, skip_title_if_isbn=True
    )
    # ISBN search found a cover → title search is skipped entirely.
    assert [m.source for m in matches] == ["isbn-search"]


def test_skip_title_if_isbn_falls_back_when_isbn_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "AMAZON_CACHE", tmp_path)
    page = FakePage(
        {"k=Dune": '<a href="/Dune/dp/0441013597/ref=sr_1_1">Dune</a>'},  # only title search has results
        {"0441013597": _fields("Dune")},
    )
    matches = covermatch.gather_matches(
        "Dune", "Frank Herbert", isbn="9780441013593", page=page, skip_title_if_isbn=True
    )
    # ISBN search empty → title search still runs.
    assert [m.source for m in matches] == ["search"]
