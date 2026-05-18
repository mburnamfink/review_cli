#!/usr/bin/env python3
"""Bulk fetch cover images for reviews that are missing them."""

import argparse
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent / "review_cli" / "src"))

from review.covers import process_cover
from review.openlibrary import fetch_cover_by_ol_id, fetch_cover_bytes, search

CONTENT_DIR = Path(__file__).parent / "book-review-content" / "reviews"
COVER_STEMS = {"cover", "og-cover", "og_cover"}
COVER_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
DELAY = 0.5  # seconds between OL API calls


# ---------------------------------------------------------------------------
# Frontmatter helpers
# ---------------------------------------------------------------------------

def _parse(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    return yaml.safe_load(parts[1]) or {}, parts[2]


def _write(path: Path, meta: dict, body: str) -> None:
    path.write_text(
        "---\n" + yaml.dump(meta, allow_unicode=True, default_flow_style=False) + "---" + body,
        encoding="utf-8",
    )


def _has_cover(review_dir: Path, meta: dict) -> bool:
    if meta.get("cover"):
        return True
    return any(
        f.suffix.lower() in COVER_EXTENSIONS
        for f in review_dir.iterdir()
        if f.stem.lower() in COVER_STEMS
    )


def _fmt_authors(meta: dict) -> str:
    return " ".join(
        a.get("last", "") for a in (meta.get("authors") or []) if a.get("role") == "author"
    ).strip()


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def find_missing(review_type: str | None) -> list[tuple[Path, dict, str]]:
    rows = []
    for md in sorted(CONTENT_DIR.rglob("*/index.md")):
        meta, body = _parse(md)
        if review_type and meta.get("type") != review_type:
            continue
        if not _has_cover(md.parent, meta):
            rows.append((md, meta, body))
    return rows


def attempt(
    md: Path,
    meta: dict,
    body: str,
    no_isbn_only: bool,
    dry_run: bool,
) -> str:
    """Try to fetch and save a cover. Returns a status string."""
    isbn = meta.get("isbn") or None
    title = meta.get("title", "?")
    author = _fmt_authors(meta)

    # --- Pass 1: ISBN-based ---
    if isbn:
        results = search(f"{title} {author}")
        time.sleep(DELAY)
        cover_i = next((r["cover_i"] for r in results if r.get("cover_i")), None)
        raw = fetch_cover_bytes(isbn, cover_i=cover_i)
        if raw:
            if not dry_run:
                cov, og = process_cover(raw, md.parent)
                meta["cover"] = cov
                meta["og_cover"] = og
                _write(md, meta, body)
            return "cover_i" if cover_i else "isbn"

    # --- Pass 2: title search, no ISBN ---
    if not isbn and not no_isbn_only:
        query = f"{title} {author}".strip()
        results = search(query)
        time.sleep(DELAY)
        cover_i = next((r["cover_i"] for r in results if r.get("cover_i")), None)
        if cover_i:
            raw = fetch_cover_by_ol_id(cover_i)
            if raw:
                if not dry_run:
                    cov, og = process_cover(raw, md.parent)
                    meta["cover"] = cov
                    meta["og_cover"] = og
                    _write(md, meta, body)
                return "verify"  # title match — needs human spot-check

    return "not_found"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--type", dest="review_type", default=None,
                        choices=["book", "audiobook", "rpg", "other"],
                        help="Limit to one content type.")
    parser.add_argument("--no-isbn-only", action="store_true",
                        help="Skip pass 2 (only process books with ISBNs).")
    parser.add_argument("--limit", type=int, default=None, metavar="N",
                        help="Stop after processing N books.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be fetched without saving anything.")
    args = parser.parse_args()

    if args.dry_run:
        print("DRY RUN — nothing will be saved.\n")

    missing = find_missing(args.review_type)
    total = len(missing)
    batch = missing[:args.limit] if args.limit else missing
    width = len(str(len(batch)))

    counts: dict[str, int] = {"isbn": 0, "cover_i": 0, "verify": 0, "not_found": 0}
    needs_verify: list[str] = []

    for i, (md, meta, body) in enumerate(batch, 1):
        title = meta.get("title", "?")[:45].ljust(45)
        status = attempt(md, meta, body, args.no_isbn_only, args.dry_run)
        counts[status] += 1

        if status == "isbn":
            marker = "✓ isbn   "
        elif status == "cover_i":
            marker = "✓ cover_i"
        elif status == "verify":
            marker = "? verify "
            needs_verify.append(f"  {meta.get('title', '?')} — {md}")
        else:
            marker = "✗        "

        print(f"[{i:{width}}/{len(batch)}] {title} {marker}")

    print(f"\n{'(dry run) ' if args.dry_run else ''}Done: "
          f"{counts['isbn'] + counts['cover_i']} saved  "
          f"({counts['isbn']} by isbn, {counts['cover_i']} by cover_i)  |  "
          f"{counts['verify']} needs verification  |  "
          f"{counts['not_found']} not found  |  "
          f"{total - len(batch)} skipped by --limit")

    if needs_verify:
        print("\nNeeds verification (title-matched, no ISBN):")
        print("\n".join(needs_verify))


if __name__ == "__main__":
    main()
