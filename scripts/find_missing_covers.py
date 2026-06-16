#!/usr/bin/env python3
"""List every review missing a cover image, across all types.

Writes scripts/missing_covers.txt with one block per review (type/slug, title,
author, isbn, path). This produces a LIST only — it does not fetch anything;
the automated cover fetch has already been run and exhausted.

Run from review-cli/:
    uv run python scripts/find_missing_covers.py
"""
from __future__ import annotations

from pathlib import Path

import frontmatter

from review.config import Config

OUTPUT_FILE = Path(__file__).parent / "missing_covers.txt"
COVER_STEMS = {"cover", "og-cover", "og_cover"}
COVER_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def has_cover(review_dir: Path, meta: dict) -> bool:
    if meta.get("cover"):
        # Trust the field only if the referenced file is actually present.
        ref = review_dir / Path(str(meta["cover"])).name
        if ref.exists():
            return True
    return any(
        f.suffix.lower() in COVER_EXTENSIONS
        for f in review_dir.iterdir()
        if f.is_file() and f.stem.lower() in COVER_STEMS
    )


def author_display(meta: dict) -> str:
    return ", ".join(
        f"{a.get('first', '')} {a.get('last', '')}".strip()
        for a in (meta.get("authors") or [])
        if a.get("role") == "author"
    )


def main() -> int:
    content_dir = Config.load().content_dir
    missing = []

    for md in sorted(content_dir.rglob("*/index.md")):
        meta = frontmatter.load(str(md)).metadata
        if has_cover(md.parent, meta):
            continue
        rel = md.parent.relative_to(content_dir).as_posix()  # {type}/{slug}
        missing.append(
            {
                "id": rel,
                "title": str(meta.get("title", "(unknown)")),
                "author": author_display(meta),
                "isbn": str(meta.get("isbn", "") or ""),
                "path": str(md),
            }
        )

    missing.sort(key=lambda r: (r["id"].split("/")[0], r["title"].lower()))

    lines = [f"Reviews missing cover images ({len(missing)} total)", "=" * 60]
    for r in missing:
        lines += [
            f"\n{r['id']}",
            f"  Title:   {r['title']}",
            f"  Author:  {r['author']}",
            f"  ISBN:    {r['isbn'] or '—'}",
            f"  Path:    {r['path']}",
        ]

    OUTPUT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Found {len(missing)} reviews missing covers -> {OUTPUT_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
