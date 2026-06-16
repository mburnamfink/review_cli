"""Candidate cover ranker (Slice 3, pure).

Takes a set of decoded candidate images and returns an ordered, de-duplicated
list: near-duplicate art is collapsed (perceptual hash), the survivors are
sorted by actual resolution descending, and the result is capped to a handful so
the choice stays manageable.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from PIL import Image

DEFAULT_CAP = 8
DEFAULT_HAMMING_THRESHOLD = 5


@dataclass
class Candidate:
    image: Image.Image
    source_url: str = ""
    data: bytes | None = field(default=None, repr=False)
    title: str = ""        # product title, for distinguishing editions in the picker

    @property
    def resolution(self) -> int:
        return self.image.width * self.image.height


def average_hash(img: Image.Image, hash_size: int = 8) -> int:
    """A 64-bit perceptual (average) hash, robust to rescaling and re-encoding."""
    small = img.convert("L").resize((hash_size, hash_size), Image.LANCZOS)
    pixels = small.tobytes()  # one byte per pixel in mode "L"
    avg = sum(pixels) / len(pixels)
    bits = 0
    for i, p in enumerate(pixels):
        if p >= avg:
            bits |= 1 << i
    return bits


def hamming_distance(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def rank_candidates(
    candidates: list[Candidate],
    cap: int = DEFAULT_CAP,
    hamming_threshold: int = DEFAULT_HAMMING_THRESHOLD,
) -> list[Candidate]:
    """Dedup near-duplicates, sort by resolution descending, cap to ``cap``.

    Candidates are considered first in resolution order, so when a near-duplicate
    group is collapsed the highest-resolution member survives.
    """
    ordered = sorted(candidates, key=lambda c: c.resolution, reverse=True)
    kept: list[Candidate] = []
    kept_hashes: list[int] = []

    for cand in ordered:
        h = average_hash(cand.image)
        if any(hamming_distance(h, k) <= hamming_threshold for k in kept_hashes):
            continue
        kept.append(cand)
        kept_hashes.append(h)
        if len(kept) >= cap:
            break

    return kept
