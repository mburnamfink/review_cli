"""Tests for the cover staging layer (review.staging)."""
from __future__ import annotations

from PIL import Image

from review.ranking import Candidate
from review import staging


def _cand(w, h, url, title):
    return Candidate(image=Image.new("RGB", (w, h), (20, 20, 20)), source_url=url, title=title)


def _review(tmp_path):
    rdir = tmp_path / "site" / "book" / "dune-herbert"
    rdir.mkdir(parents=True)
    index = rdir / "index.md"
    index.write_text("---\ntitle: Dune\n---\n", encoding="utf-8")
    cover = rdir / "cover.jpg"
    Image.new("RGB", (300, 450), (1, 2, 3)).save(cover, "JPEG")
    return index, cover


def test_write_and_load_roundtrip(tmp_path):
    covers = tmp_path / "covers"
    index, cover = _review(tmp_path)
    ranked = [_cand(1400, 2100, "u1", "Dune A"), _cand(900, 1200, "u2", "Dune B")]

    book = staging.write_staging(
        covers, slug="dune-herbert", title="Dune", review_type="book",
        review_path=index, current_cover=cover, ranked=ranked,
    )

    bdir = covers / "dune-herbert"
    assert (bdir / "current.jpg").exists()
    assert (bdir / "01.jpg").exists() and (bdir / "02.jpg").exists()
    assert (bdir / "manifest.json").exists()
    # best (highest-res) is first
    assert book.candidates[0].file == "01.jpg"
    assert (book.candidates[0].width, book.candidates[0].height) == (1400, 2100)
    assert book.current_width == 300

    loaded = staging.load_staging(covers, "dune-herbert")
    assert loaded == book
    assert staging.staged_slugs(covers) == ["dune-herbert"]


def test_manual_is_staged_first(tmp_path):
    covers = tmp_path / "covers"
    index, cover = _review(tmp_path)
    manual = _cand(700, 1000, "manual-url", "Manual pick")
    ranked = [_cand(1400, 2100, "u1", "Dune A")]

    book = staging.write_staging(
        covers, slug="dune-herbert", title="Dune", review_type="book",
        review_path=index, current_cover=cover, ranked=ranked, manual=manual,
    )
    assert book.candidates[0].source == "manual"
    assert book.candidates[0].file == "01.jpg"
    assert book.candidates[1].source == "amazon"


def test_no_current_cover_is_handled(tmp_path):
    covers = tmp_path / "covers"
    index, _ = _review(tmp_path)
    book = staging.write_staging(
        covers, slug="dune-herbert", title="Dune", review_type="book",
        review_path=index, current_cover=None, ranked=[_cand(800, 1200, "u", "t")],
    )
    assert book.current is None and book.current_width is None
    assert not (covers / "dune-herbert" / "current.jpg").exists()


def test_load_missing_returns_none(tmp_path):
    assert staging.load_staging(tmp_path / "covers", "nope") is None
    assert staging.staged_slugs(tmp_path / "covers") == []
