"""On-disk staging for cover candidates, so scraping and picking are separate.

The slow, network-bound work (scrape Amazon, download masters) runs once in an
unattended pass and writes everything here — never into the site. Each book gets
its own directory under the staging root::

    covers/<slug>/
        current.jpg     # a copy of the review's existing cover (if any)
        01.jpg 02.jpg…  # candidates, best (highest-resolution) first
        manifest.json   # what each file is + where to apply the winner

The pick step then reads these directories with no network at all, compares the
current cover against the candidates, and only on selection writes the chosen
image back into the review. Nothing here mutates ``site/content``.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image

from .ranking import Candidate

MANIFEST = "manifest.json"
CURRENT = "current.jpg"


@dataclass
class StagedCandidate:
    file: str
    url: str
    width: int
    height: int
    title: str
    source: str


@dataclass
class StagedBook:
    slug: str
    title: str
    review_type: str
    review_path: str          # absolute path to the review's index.md
    current: str | None       # filename of the copied current cover, or None
    current_width: int | None
    candidates: list[StagedCandidate]

    @property
    def is_empty(self) -> bool:
        return not self.candidates


def book_dir(covers_dir: Path, slug: str) -> Path:
    return covers_dir / slug


def write_staging(
    covers_dir: Path,
    *,
    slug: str,
    title: str,
    review_type: str,
    review_path: Path,
    current_cover: Path | None,
    ranked: list[Candidate],
    manual: Candidate | None = None,
) -> StagedBook:
    """Stage a book's current cover + candidate images and a manifest.

    ``ranked`` is best-first (highest resolution); a ``manual`` override, if
    given, is staged as candidate ``01`` ahead of them. Re-staging a book
    replaces its directory.
    """
    bdir = book_dir(covers_dir, slug)
    if bdir.exists():
        shutil.rmtree(bdir)
    bdir.mkdir(parents=True, exist_ok=True)

    current_name: str | None = None
    current_width: int | None = None
    if current_cover and current_cover.exists():
        shutil.copyfile(current_cover, bdir / CURRENT)
        current_name = CURRENT
        try:
            with Image.open(bdir / CURRENT) as im:
                current_width = im.width
        except Exception:
            current_width = None

    ordered: list[tuple[Candidate, str]] = []
    if manual is not None:
        ordered.append((manual, "manual"))
    ordered.extend((c, "amazon") for c in ranked)

    staged: list[StagedCandidate] = []
    for i, (cand, source) in enumerate(ordered, 1):
        fname = f"{i:02d}.jpg"
        cand.image.save(bdir / fname, "JPEG", quality=95)
        staged.append(
            StagedCandidate(
                file=fname,
                url=cand.source_url,
                width=cand.image.width,
                height=cand.image.height,
                title=cand.title,
                source=source,
            )
        )

    book = StagedBook(
        slug=slug,
        title=title,
        review_type=review_type,
        review_path=str(review_path),
        current=current_name,
        current_width=current_width,
        candidates=staged,
    )
    (bdir / MANIFEST).write_text(
        json.dumps(
            {**asdict(book), "candidates": [asdict(c) for c in staged]},
            indent=2,
        ),
        encoding="utf-8",
    )
    return book


def load_staging(covers_dir: Path, slug: str) -> StagedBook | None:
    """Read a staged book's manifest, or ``None`` if it isn't staged."""
    path = book_dir(covers_dir, slug) / MANIFEST
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        cands = [StagedCandidate(**c) for c in data.pop("candidates", [])]
        return StagedBook(candidates=cands, **data)
    except (ValueError, TypeError):
        return None


def staged_slugs(covers_dir: Path) -> list[str]:
    """Slugs that have a staging directory with a manifest, sorted."""
    if not covers_dir.exists():
        return []
    return sorted(
        d.name for d in covers_dir.iterdir() if d.is_dir() and (d / MANIFEST).exists()
    )
