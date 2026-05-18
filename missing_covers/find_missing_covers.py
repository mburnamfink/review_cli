#!/usr/bin/env python3
"""Find reviews missing a cover image and write a report to missing_covers.txt."""

from pathlib import Path
import yaml

CONTENT_DIR = Path(__file__).parent / "book-review-content" / "reviews"
OUTPUT_FILE = Path(__file__).parent / "missing_covers.txt"
COVER_STEMS = {"cover", "og-cover", "og_cover"}
COVER_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def parse_frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    return yaml.safe_load(parts[1]) or {}


def has_cover(review_dir: Path, meta: dict) -> bool:
    if meta.get("cover"):
        return True
    return any(
        f.suffix.lower() in COVER_EXTENSIONS
        for f in review_dir.iterdir()
        if f.stem.lower() in COVER_STEMS
    )


def main():
    missing = []

    for md in sorted(CONTENT_DIR.rglob("*/index.md")):
        meta = parse_frontmatter(md)
        if not has_cover(md.parent, meta):
            title = meta.get("title", "(unknown)")
            authors = ", ".join(
                f"{a.get('first', '')} {a.get('last', '')}".strip()
                for a in (meta.get("authors") or [])
                if a.get("role") == "author"
            )
            isbn = meta.get("isbn", "")
            rtype = meta.get("type", "")
            missing.append((title, authors, rtype, isbn, md))

    missing.sort(key=lambda r: r[0].lower())

    lines = [f"Reviews missing cover images ({len(missing)} total)", "=" * 60]
    for title, authors, rtype, isbn, path in missing:
        lines.append(f"\nTitle:   {title}")
        lines.append(f"Authors: {authors}")
        lines.append(f"Type:    {rtype}")
        lines.append(f"ISBN:    {isbn or '—'}")
        lines.append(f"Path:    {path}")

    OUTPUT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Found {len(missing)} reviews missing covers → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
