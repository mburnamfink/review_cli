"""Apply-path test for pick-covers (offline).

Exercises the non-interactive core — turning a staged image into cover.jpg +
og-cover.jpg and updating frontmatter — without the terminal parts. The keypress
loop and kitty render are validated by manual run.
"""
from __future__ import annotations

import io

import frontmatter
from PIL import Image

from review.cli import _apply_staged


def _jpeg_bytes(size) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (10, 120, 90)).save(buf, "JPEG")
    return buf.getvalue()


def test_apply_staged_writes_images_and_frontmatter(tmp_path):
    review_dir = tmp_path / "book" / "dune-herbert"
    review_dir.mkdir(parents=True)
    index = review_dir / "index.md"
    index.write_text("---\ntitle: Dune\n---\n\nbody\n", encoding="utf-8")

    staged = tmp_path / "covers" / "dune-herbert" / "01.jpg"
    staged.parent.mkdir(parents=True)
    staged.write_bytes(_jpeg_bytes((1400, 2100)))

    _apply_staged(str(index), staged)

    cover = review_dir / "cover.jpg"
    og = review_dir / "og-cover.jpg"
    assert cover.exists() and og.exists()
    assert Image.open(cover).width <= 800           # process_cover caps cover width
    assert Image.open(og).size == (400, 600)        # og is fixed 400×600

    meta = frontmatter.load(str(index)).metadata
    assert meta["cover"] == "./cover.jpg"
    assert meta["og_cover"] == "./og-cover.jpg"
    assert meta["title"] == "Dune"                  # untouched
