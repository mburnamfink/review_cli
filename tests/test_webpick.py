"""Tests for the browser cover picker's pure core (review.webpick).

Covers the controller decision/advance logic, the Skip/Crop/Replace summary
writer, and the og-preview renderer — everything except the HTTP/browser shell,
which is exercised by manual run.
"""
from __future__ import annotations

import io
import json

from PIL import Image

from review import staging, webpick
from review.pickstate import DONE, NEEDS_CROP, NEEDS_REPLACE, SKIPPED, PickState
from review.ranking import Candidate


def _cand(w, h, url, title):
    return Candidate(image=Image.new("RGB", (w, h), (20, 80, 140)), source_url=url, title=title)


def _stage(tmp_path, slug="dune-herbert"):
    covers = tmp_path / "covers"
    rdir = tmp_path / "site" / "book" / slug
    rdir.mkdir(parents=True)
    index = rdir / "index.md"
    index.write_text("---\ntitle: Dune\n---\n", encoding="utf-8")
    cover = rdir / "cover.jpg"
    Image.new("RGB", (300, 450), (1, 2, 3)).save(cover, "JPEG")
    book = staging.write_staging(
        covers, slug=slug, title="Dune", review_type="book",
        review_path=index, current_cover=cover,
        ranked=[_cand(1400, 2100, "u1", "Dune A"), _cand(900, 1200, "u2", "Dune B")],
    )
    return covers, index, book


def _controller(tmp_path, books):
    covers = tmp_path / "covers"
    state = PickState.load(covers / ".pick_state.json")
    return webpick.Controller(covers_dir=covers, state=state, todo=books), state, covers


def test_pick_applies_and_advances(tmp_path):
    covers, index, book = _stage(tmp_path)
    ctrl, state, _ = _controller(tmp_path, [book])

    payload = ctrl.book_payload()
    assert payload["title"] == "Dune"
    assert payload["index"] == 1 and payload["total"] == 1
    assert len(payload["candidates"]) == 2

    after = ctrl.decide("pick", 2)
    assert after["done"] is True              # only book, pointer advanced
    assert state.status("dune-herbert") == DONE
    assert state.books["dune-herbert"]["chosen"] == 2
    # the chosen candidate was written into the review
    assert (index.parent / "cover.jpg").exists()
    assert Image.open(index.parent / "og-cover.jpg").size == (400, 600)


def test_keep_current_settles_without_writing(tmp_path):
    covers, index, book = _stage(tmp_path)  # 2 candidates → option 3 = keep current
    before = (index.parent / "cover.jpg").read_bytes()
    ctrl, state, _ = _controller(tmp_path, [book])

    after = ctrl.decide("pick", len(book.candidates) + 1)
    assert after["done"] is True
    assert state.status("dune-herbert") == DONE
    assert state.books["dune-herbert"]["chosen"] == 0   # 0 == kept the existing cover
    # the review's cover was left untouched (no candidate written over it)
    assert (index.parent / "cover.jpg").read_bytes() == before


def test_skip_crop_replace_record_status_and_summary(tmp_path):
    covers = tmp_path / "covers"
    books = [_stage(tmp_path, s)[2] for s in ("a-book", "b-book", "c-book")]
    ctrl, state, _ = _controller(tmp_path, books)

    ctrl.decide("skip", None)
    ctrl.decide("crop", None)
    ctrl.decide("replace", None)

    assert state.status("a-book") == SKIPPED
    assert state.status("b-book") == NEEDS_CROP
    assert state.status("c-book") == NEEDS_REPLACE

    data = json.loads((covers / webpick.SUMMARY_JSON).read_text())
    assert data == {"skip": ["a-book"], "crop": ["b-book"], "replace": ["c-book"]}
    md = (covers / webpick.SUMMARY_MD).read_text()
    assert "a-book" in md and "b-book" in md and "c-book" in md


def test_settled_not_reoffered_but_skip_is(tmp_path):
    _stage(tmp_path, "a-book")
    _stage(tmp_path, "b-book")
    covers = tmp_path / "covers"
    state = PickState.load(covers / ".pick_state.json")
    state.record("a-book", NEEDS_CROP)
    state.record("b-book", SKIPPED)

    assert state.is_settled("a-book") is True      # crop is settled
    assert state.is_settled("b-book") is False     # skip comes back


def test_card_preview_is_jpeg_cropped_to_2_3(tmp_path):
    covers, _, book = _stage(tmp_path)
    p = staging.book_dir(covers, "dune-herbert") / "01.jpg"
    data = webpick.card_preview_bytes(p)
    img = Image.open(io.BytesIO(data))
    assert img.format == "JPEG"
    assert img.size == (400, 600)         # exact 2:3 grid frame
