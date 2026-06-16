"""Tests for the candidate ranker (Slice 3)."""
from __future__ import annotations

from PIL import Image, ImageDraw

from review.ranking import Candidate, average_hash, rank_candidates


def _patterned(w: int, h: int, seed: int) -> Image.Image:
    """A distinct image per seed (so hashes differ), reproducible across sizes.

    The same seed produces visually-equivalent art at any size — a white block
    whose grid position is determined by the seed — so two sizes of one seed are
    perceptual near-duplicates, while different seeds are not.
    """
    img = Image.new("RGB", (w, h), (0, 0, 0))
    d = ImageDraw.Draw(img)
    col, row = seed % 3, (seed // 3) % 3
    x0, y0 = col * w / 3, row * h / 3
    d.rectangle([x0, y0, x0 + w / 3, y0 + h / 3], fill=(255, 255, 255))
    return img


def _cand(w: int, h: int, seed: int) -> Candidate:
    return Candidate(image=_patterned(w, h, seed), source_url=f"seed{seed}-{w}x{h}")


def test_sorted_by_resolution_descending():
    cands = [_cand(100, 150, 0), _cand(400, 600, 1), _cand(200, 300, 2)]
    ranked = rank_candidates(cands)
    sizes = [c.resolution for c in ranked]
    assert sizes == sorted(sizes, reverse=True)
    assert ranked[0].resolution == 400 * 600


def test_near_duplicates_collapsed_keeping_largest():
    # same art (seed 0) at three sizes + one distinct cover (seed 5)
    cands = [_cand(100, 150, 0), _cand(400, 600, 0), _cand(200, 300, 0), _cand(300, 450, 5)]
    ranked = rank_candidates(cands)
    assert len(ranked) == 2  # one survivor of the seed-0 group, plus seed-5
    seed0 = [c for c in ranked if c.source_url.startswith("seed0")]
    assert len(seed0) == 1
    assert seed0[0].resolution == 400 * 600  # the largest of the group survived


def test_result_is_capped():
    cands = [_cand(100 + i, 150 + i, i) for i in range(20)]
    ranked = rank_candidates(cands, cap=8)
    assert len(ranked) == 8


def test_average_hash_stable_across_rescale():
    big = _patterned(400, 600, 7)
    small = _patterned(80, 120, 7)
    from review.ranking import hamming_distance

    assert hamming_distance(average_hash(big), average_hash(small)) <= 5
