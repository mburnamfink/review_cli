"""Tests for the low-resolution cover detector (Slice 2)."""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from review.lowres import find_low_res, is_low_res


@pytest.mark.parametrize(
    "width,expected",
    [
        (699, True),
        (700, False),
        (701, False),
        (800, False),
        (320, True),
    ],
)
def test_is_low_res_boundaries(width, expected):
    assert is_low_res(width) is expected


def test_is_low_res_custom_threshold():
    assert is_low_res(750, threshold=800) is True
    assert is_low_res(800, threshold=800) is False


def _make_review(content_dir: Path, review_type: str, slug: str, cover_width: int | None) -> None:
    d = content_dir / review_type / slug
    d.mkdir(parents=True)
    (d / "index.md").write_text(f"---\ntitle: {slug.title()}\n---\n", encoding="utf-8")
    if cover_width is not None:
        Image.new("RGB", (cover_width, int(cover_width * 1.5)), (123, 123, 123)).save(
            d / "cover.jpg", "JPEG"
        )


@pytest.fixture
def content_tree(tmp_path: Path) -> Path:
    root = tmp_path / "reviews"
    _make_review(root, "book", "sharp", 800)        # ok
    _make_review(root, "book", "exact", 700)        # ok (boundary)
    _make_review(root, "book", "thumb", 320)        # low-res
    _make_review(root, "audiobook", "fuzzy", 480)   # low-res
    _make_review(root, "book", "nocover", None)     # missing cover
    return root


def test_find_low_res_flags_thumbnails_and_missing(content_tree: Path):
    flagged = {r.slug for r in find_low_res(content_tree)}
    assert flagged == {"thumb", "fuzzy", "nocover"}


def test_find_low_res_reports_widths(content_tree: Path):
    by_slug = {r.slug: r for r in find_low_res(content_tree)}
    assert by_slug["thumb"].width == 320
    assert by_slug["nocover"].width is None
    assert by_slug["fuzzy"].review_type == "audiobook"


def test_threshold_override(content_tree: Path):
    # raising the threshold catches the otherwise-ok covers too
    flagged = {r.slug for r in find_low_res(content_tree, threshold=900)}
    assert flagged == {"sharp", "exact", "thumb", "fuzzy", "nocover"}


def test_explicit_slugs_override_width(content_tree: Path):
    # a sharp cover is normally not flagged, but an explicit slug forces it in
    flagged = find_low_res(content_tree, slugs=["sharp"])
    assert [r.slug for r in flagged] == ["sharp"]
    assert flagged[0].width == 800
