#!/usr/bin/env python3
"""Build an HTML contact sheet of every cover, for spotting bad/wrong covers.

Tiles each review's cover with its title, type, and slug so you can scan for
poor photography or mismatched covers. Reviews without a cover show a
placeholder. Open the output file in a browser; flagged covers can then be
replaced with: uv run review process-cover <slug> <image.jpg>

Run from review-cli/:
    uv run python tools/cover_contact_sheet.py
"""
from __future__ import annotations

import html
import os
from pathlib import Path

import frontmatter

from review.config import Config

OUTPUT_FILE = Path(__file__).parent / "cover_contact_sheet.html"
COVER_EXTENSIONS = [".jpg", ".jpeg", ".png", ".webp", ".gif"]

PAGE_HEAD = """<!doctype html>
<meta charset="utf-8">
<title>Cover contact sheet</title>
<style>
  body { font-family: system-ui, sans-serif; margin: 1rem; background: #111; color: #eee; }
  h1 { font-size: 1.1rem; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 1rem; }
  .cell { font-size: .75rem; }
  .cell img, .cell .ph {
    width: 100%; aspect-ratio: 2/3; object-fit: contain;
    background: #222; border: 1px solid #333; display: block;
  }
  .ph { display: flex; align-items: center; justify-content: center; color: #666; text-align: center; padding: .5rem; }
  .title { margin: .25rem 0 0; font-weight: 600; }
  .slug { color: #888; word-break: break-all; }
</style>
"""


def find_cover_file(review_dir: Path) -> Path | None:
    for ext in COVER_EXTENSIONS:
        f = review_dir / f"cover{ext}"
        if f.exists():
            return f
    return None


def main() -> int:
    content_dir = Config.load().content_dir
    out_dir = OUTPUT_FILE.parent

    cells = []
    for md in sorted(content_dir.rglob("*/index.md")):
        meta = frontmatter.load(str(md)).metadata
        rel = md.parent.relative_to(content_dir).as_posix()
        title = html.escape(str(meta.get("title", md.parent.name)))
        cover = find_cover_file(md.parent)
        if cover:
            src = html.escape(os.path.relpath(cover, out_dir))
            img = f'<img loading="lazy" src="{src}" alt="">'
        else:
            img = '<div class="ph">no cover</div>'
        cells.append(
            f'<div class="cell">{img}'
            f'<p class="title">{title}</p>'
            f'<p class="slug">{html.escape(rel)}</p></div>'
        )

    page = (
        PAGE_HEAD
        + f"<h1>{len(cells)} reviews</h1>\n<div class=\"grid\">\n"
        + "\n".join(cells)
        + "\n</div>\n"
    )
    OUTPUT_FILE.write_text(page, encoding="utf-8")
    print(f"Wrote contact sheet ({len(cells)} reviews) -> {OUTPUT_FILE}")
    print("Open it in a browser to scan for bad covers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
