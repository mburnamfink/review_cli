"""Tests for the Amazon cover sourcing module (Slice 3)."""
from __future__ import annotations

import pytest

from review.amazon import (
    asin_of,
    image_id,
    is_single_volume,
    main_cover_url,
    parse_search_product_paths,
    pick_largest_dynamic_image,
    title_matches,
    upgrade_resolution,
)

BASE = "https://images-na.ssl-images-amazon.com/images/S/compressed.photo.goodreads.com/books/1546275/12345"
ITEM = "https://m.media-amazon.com/images/I/A1hfQCkkhLL"


@pytest.mark.parametrize(
    "url,expected",
    [
        (f"{BASE}._SX318_.jpg", f"{BASE}.jpg"),
        (f"{BASE}._SY475_.jpg", f"{BASE}.jpg"),
        (f"{BASE}._SX98_SY160_.jpg", f"{BASE}.jpg"),
        (f"{BASE}._SX50_QL70_ML2_.jpg", f"{BASE}.jpg"),
        (f"{ITEM}._SY466_.jpg", f"{ITEM}.jpg"),                       # product-page master
        (f"{ITEM}._AC_UF1000,1000_QL80_.jpg", f"{ITEM}.jpg"),        # AC modifier w/ comma
        (f"{BASE}._sx318_.JPG", f"{BASE}.JPG"),  # case-insensitive
        (f"{BASE}.jpg", f"{BASE}.jpg"),          # no suffix → unchanged
        ("https://example.com/cover.png", "https://example.com/cover.png"),
    ],
)
def test_upgrade_resolution_table(url, expected):
    assert upgrade_resolution(url) == expected


def test_upgrade_resolution_idempotent():
    once = upgrade_resolution(f"{BASE}._SX318_.jpg")
    assert upgrade_resolution(once) == once


def test_parse_search_product_paths_dedups_by_asin_in_order():
    html = """
    <a href="/Drop-Corruption/dp/0593723821/ref=sr_1_1?dib=x">first</a>
    <a href="/Drop-Corruption/dp/0593723821/ref=sr_1_1_other">dup ASIN, different params</a>
    <a href="/Some-Other-Book/dp/1984820702/ref=sr_1_2">second</a>
    <a href="/account/dp/notanasin">junk</a>
    """
    paths = parse_search_product_paths(html)
    assert [p.split("/dp/")[1][:10] for p in paths] == ["0593723821", "1984820702"]


def test_asin_of():
    assert asin_of("/Dune-Frank-Herbert-ebook/dp/B00B7NPRY8/ref=sr_1_1") == "B00B7NPRY8"
    assert asin_of("/Dune-Chronicles-Book-1/dp/0441013597") == "0441013597"
    assert asin_of("/no-asin/here") == "/no-asin/here"


@pytest.mark.parametrize(
    "path",
    [
        "/Dune-Frank-Herbert-ebook/dp/B00B7NPRY8/ref=sr_1_1",   # single ebook
        "/Dune-Chronicles-Book-1/dp/0441013597",                # "Book-1" is not "1-book"
        "/Dune-Penguin-Galaxy-Frank-Herbert/dp/0143111582",     # single hardcover
        "/Dune-Book-One-Chronicles-audio-cd/dp/1427201439",     # "Book-One" has no digit
        # Single volumes whose slug carries a *series name* containing "trilogy".
        # These were wrongly dropped by the old bare-"trilogy" rule; the title
        # gate is the backstop if an actual omnibus ever rides along.
        "/Annihilation-Southern-Reach-Trilogy-VanderMeer/dp/0374104093",
        "/Blue-Mars-Trilogy-Kim-Stanley-Robinson/dp/0553573357",
        "/Great-Dune-Trilogy/dp/0575070706",                    # bare "Trilogy" alone
    ],
)
def test_is_single_volume_keeps_single_editions(path):
    assert is_single_volume(path) is True


@pytest.mark.parametrize(
    "path",
    [
        "/Frank-Herberts-Dune-3-Book-Boxed/dp/0593201892",      # 3-Book + Boxed
        "/Frank-Herberts-Dune-Saga-Collection-ebook/dp/B08PQCZX4Z",  # Saga + Collection
        "/Mars-Trilogy-Boxed-Set-Robinson/dp/B000XYZ123",       # Trilogy + Boxed Set
        "/Dune-Saga-6-Book-Boxed-Set/dp/0593201868",            # boxed set
        "/Dune-Complete-Collection/dp/XXXXXXXXXX",              # complete- / collection
    ],
)
def test_is_single_volume_drops_bundles(path):
    assert is_single_volume(path) is False


def test_is_single_volume_ignores_asin_chars():
    # An ASIN that happens to contain "set"-like chars must not trip the filter,
    # because only the slug (before /dp/) is examined.
    assert is_single_volume("/Plain-Single-Book/dp/B0SET12345") is True


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://m.media-amazon.com/images/I/71m91l0treL._SL1500_.jpg", "71m91l0treL"),
        ("https://m.media-amazon.com/images/I/818wSuWyOgL.jpg", "818wSuWyOgL"),
        ("https://example.com/cover.png", None),
        ("", None),
    ],
)
def test_image_id(url, expected):
    assert image_id(url) == expected


@pytest.mark.parametrize(
    "want,got",
    [
        ("Dune", "Dune (Dune Chronicles, Book 1)"),
        ("The Left Hand of Darkness", "The Left Hand of Darkness (Hainish Cycle)"),
        ("Dune", ""),  # no product title → don't over-filter
        ("Children of Time", "Children of Time: Children of Time, Book 1"),
        # Our stored titles carry "(Series, #1-3)" tags; the plain Amazon edition
        # must still match once the parenthetical is stripped.
        ("Cyteen (Cyteen, #1-3)", "Cyteen"),
        (
            "A Knight of the Seven Kingdoms (The Tales of Dunk and Egg, #1-3)",
            "A Knight of the Seven Kingdoms",
        ),
    ],
)
def test_title_matches_accepts_same_book(want, got):
    assert title_matches(want, got) is True


@pytest.mark.parametrize(
    "want,got",
    [
        ("Dune", "Summary of Dune by Frank Herbert"),
        ("Dune", "Study Guide for Frank Herbert's Dune"),
        ("Dune", "Workbook: Dune"),
        ("Dune", "The Hobbit"),  # wrong book, no token overlap
        ("The Left Hand of Darkness", "A Wizard of Earthsea"),
    ],
)
def test_title_matches_rejects_wrong_or_derivative(want, got):
    assert title_matches(want, got) is False


def test_pick_largest_dynamic_image_chooses_max_area():
    blob = (
        '{"https://m.media-amazon.com/images/I/x._SX342_.jpg":[342,500],'
        '"https://m.media-amazon.com/images/I/x._SX522_.jpg":[522,766]}'
    )
    assert pick_largest_dynamic_image(blob) == "https://m.media-amazon.com/images/I/x._SX522_.jpg"
    # &quot;-encoded JSON (as it appears inline in HTML) is handled
    assert pick_largest_dynamic_image(blob.replace('"', "&quot;")) == (
        "https://m.media-amazon.com/images/I/x._SX522_.jpg"
    )


@pytest.mark.parametrize("bad", [None, "", "{}", "not json"])
def test_pick_largest_dynamic_image_handles_bad_input(bad):
    assert pick_largest_dynamic_image(bad) is None


def test_main_cover_url_prefers_old_hires():
    attrs = {
        "data-old-hires": f"{ITEM}._SL1500_.jpg",
        "data-a-dynamic-image": '{"%s._SX522_.jpg":[522,766]}' % ITEM,
        "src": f"{ITEM}._SX342_.jpg",
    }
    assert main_cover_url(attrs) == f"{ITEM}._SL1500_.jpg"


def test_main_cover_url_falls_back_to_dynamic_then_src():
    assert main_cover_url(
        {"data-old-hires": "", "data-a-dynamic-image": '{"%s._SX522_.jpg":[522,766]}' % ITEM}
    ) == f"{ITEM}._SX522_.jpg"
    assert main_cover_url({"src": f"{ITEM}._SX342_.jpg"}) == f"{ITEM}._SX342_.jpg"
    assert main_cover_url(None) is None
    assert main_cover_url({}) is None
