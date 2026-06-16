#!/usr/bin/env python3
"""Export every review to series_sheet.csv, sorted by author then title.

Columns: slug, type, author, title, series, number
`series` and `number` are left blank for you to fill in by hand (they are
pre-filled from any existing front-matter values, so regenerating the sheet is
idempotent). Sorting by author clusters series together for fast manual entry.
Feed the finished sheet back in with apply_series.py.

Run from review-cli/:
    uv run python scripts/build_series_sheet.py
"""
from __future__ import annotations

import csv
from pathlib import Path

import frontmatter

from review.config import Config

CSV_OUT = Path(__file__).parent / "series_sheet.csv"


def primary_author(meta: dict) -> tuple[str, str]:
    """Return (last, first) of the first author-role contributor, else first contributor."""
    authors = meta.get("authors") or []
    chosen = next((a for a in authors if a.get("role") == "author"), None)
    if chosen is None and authors:
        chosen = authors[0]
    if chosen is None:
        return ("", "")
    return (str(chosen.get("last", "")), str(chosen.get("first", "")))


def fmt_number(n) -> str:
    if n is None:
        return ""
    f = float(n)
    return str(int(f)) if f.is_integer() else f"{f:g}"


def main() -> int:
    content_dir = Config.load().content_dir
    rows = []

    for md in sorted(content_dir.rglob("*/index.md")):
        meta = frontmatter.load(str(md)).metadata
        rel = md.parent.relative_to(content_dir).as_posix()  # {type}/{slug}
        rtype, _, slug = rel.partition("/")
        last, first = primary_author(meta)
        author = f"{first} {last}".strip()
        rows.append(
            {
                "_sort": (last.lower(), first.lower(), str(meta.get("title", "")).lower()),
                "slug": slug,
                "type": rtype,
                "author": author,
                "title": str(meta.get("title", "")),
                "series": str(meta.get("series", "") or ""),
                "number": fmt_number(meta.get("series_number")),
            }
        )

    rows.sort(key=lambda r: r["_sort"])

    with open(CSV_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["slug", "type", "author", "title", "series", "number"])
        w.writeheader()
        for r in rows:
            r.pop("_sort")
            w.writerow(r)

    print(f"Wrote {len(rows)} reviews -> {CSV_OUT}")
    print("Fill in the `series` and `number` columns, then run apply_series.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
