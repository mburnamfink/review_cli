"""Low-resolution cover detector (Slice 2).

`process_cover` caps cover.jpg at 800px wide and never upscales, so a
properly-sourced cover is ~800px wide; anything well under that is a thumbnail.
Detection is therefore pure width: no blur/quality heuristic is needed.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import frontmatter
from PIL import Image

DEFAULT_THRESHOLD = 700


@dataclass
class FlaggedReview:
    path: Path            # the review's index.md
    slug: str
    review_type: str
    title: str
    width: int | None     # cover.jpg width, or None if no cover.jpg exists
    cover_path: Path | None


def is_low_res(width: int, threshold: int = DEFAULT_THRESHOLD) -> bool:
    """True when a cover of the given pixel width counts as low-resolution.

    Boundary: 699 → True, 700 → False, 800 → False.
    """
    return width < threshold


def _cover_width(cover_path: Path) -> int | None:
    try:
        with Image.open(cover_path) as img:
            return img.width
    except Exception:
        return None


def find_low_res(
    content_dir: Path,
    threshold: int = DEFAULT_THRESHOLD,
    slugs: list[str] | None = None,
) -> list[FlaggedReview]:
    """Walk reviews under content_dir and return the ones needing a better cover.

    Without ``slugs``: a review is flagged when its cover.jpg is below the width
    threshold, or when it has no cover.jpg at all (a missing cover always needs
    attention). With ``slugs``: only those reviews are returned, regardless of
    width, so a disliked-but-sharp cover can still be targeted.
    """
    slugset = set(slugs) if slugs else None
    flagged: list[FlaggedReview] = []

    for md in sorted(content_dir.rglob("*/index.md")):
        slug = md.parent.name
        if slugset is not None and slug not in slugset:
            continue

        try:
            meta = frontmatter.load(str(md)).metadata
        except Exception:
            meta = {}

        cover = md.parent / "cover.jpg"
        width = _cover_width(cover) if cover.exists() else None

        if slugset is not None:
            include = True
        else:
            include = width is None or is_low_res(width, threshold)

        if include:
            flagged.append(
                FlaggedReview(
                    path=md,
                    slug=slug,
                    review_type=md.parent.parent.name,
                    title=meta.get("title", slug),
                    width=width,
                    cover_path=cover if cover.exists() else None,
                )
            )

    return flagged
