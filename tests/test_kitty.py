"""Tests for the kitty contact-sheet builder (Slice 4).

Only the pure image composition is unit-tested; the actual ``kitten icat`` render
is a terminal side effect, validated by manual run.
"""
from __future__ import annotations

from PIL import Image

from review.kitty import LABEL_H, PAD, THUMB_H, build_contact_sheet


def _make(path, size):
    Image.new("RGB", size, (200, 100, 50)).save(path, "JPEG")
    return path


def test_contact_sheet_includes_current_plus_candidates(tmp_path):
    current = _make(tmp_path / "cover.jpg", (400, 600))
    cands = [_make(tmp_path / f"c_{i}.jpg", (400, 600)) for i in range(3)]

    sheet = build_contact_sheet(current, cands)

    # 4 cells (current + 3), each scaled to THUMB_H tall.
    assert sheet.height == LABEL_H + THUMB_H + PAD
    # Each portrait cell is ~ (THUMB_H * 400/600) wide; 4 cells + padding.
    cell_w = round(400 * THUMB_H / 600)
    expected_w = PAD + 4 * (cell_w + PAD)
    assert sheet.width == expected_w


def test_contact_sheet_without_current(tmp_path):
    cands = [_make(tmp_path / "c_1.jpg", (300, 450))]
    sheet = build_contact_sheet(None, cands)
    cell_w = round(300 * THUMB_H / 450)
    assert sheet.width == PAD + (cell_w + PAD)


def test_contact_sheet_empty_is_placeholder():
    sheet = build_contact_sheet(None, [])
    assert sheet.size == (THUMB_H, THUMB_H)


def test_missing_current_path_is_skipped(tmp_path):
    cands = [_make(tmp_path / "c_1.jpg", (400, 600))]
    sheet = build_contact_sheet(tmp_path / "does-not-exist.jpg", cands)
    cell_w = round(400 * THUMB_H / 600)
    assert sheet.width == PAD + (cell_w + PAD)  # only the one candidate
