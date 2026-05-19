#!/usr/bin/env python3
"""Bulk fetch cover images for reviews that are missing them."""

import argparse
import logging
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from review.covers import process_cover
from review.openlibrary import fetch_cover_by_ol_id, fetch_cover_bytes, search

CONTENT_DIR = Path(__file__).parent.parent.parent / "content" / "reviews"
ARCHIVE_DIR = Path(__file__).parent.parent.parent / "content" / "00_missing_covers"
LOG_DIR = Path(__file__).parent
COVER_STEMS = {"cover", "og-cover", "og_cover"}
COVER_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
DELAY = 1.0  # seconds between OL API calls


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


def _archive_cover(review_dir: Path, slug: str) -> None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    src = review_dir / "cover.jpg"
    if src.exists():
        dest = ARCHIVE_DIR / f"{slug}.jpg"
        shutil.copy2(src, dest)
        logging.info("archived cover → %s", dest)


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def find_missing(review_type: str | None, slug: str | None = None) -> list[tuple[Path, dict, str]]:
    rows = []
    for md in sorted(CONTENT_DIR.rglob("*/index.md")):
        meta, body = _parse(md)
        if review_type and meta.get("type") != review_type:
            continue
        if slug and md.parent.name != slug:
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

    logging.info("processing: %s (isbn=%s)", title, isbn or "none")

    # --- Pass 1: ISBN-based ---
    if isbn:
        logging.debug("pass 1 — searching OL for '%s %s'", title, author)
        results = search(f"{title} {author}")
        time.sleep(DELAY)
        cover_i = next((r["cover_i"] for r in results if r.get("cover_i")), None)
        logging.debug("pass 1 — cover_i=%s", cover_i)
        raw = fetch_cover_bytes(isbn, cover_i=cover_i)
        time.sleep(DELAY)
        if raw:
            logging.info("pass 1 — fetched %d bytes via %s", len(raw), "cover_i" if cover_i else "isbn")
            if not dry_run:
                cov, og = process_cover(raw, md.parent)
                meta["cover"] = cov
                meta["og_cover"] = og
                _write(md, meta, body)
                logging.info("saved cover + og-cover to %s", md.parent)
                _archive_cover(md.parent, md.parent.name)
            return "cover_i" if cover_i else "isbn"
        else:
            logging.warning("pass 1 — no image returned for '%s' (isbn=%s)", title, isbn)

    # --- Pass 2: title search, no ISBN ---
    if not isbn and not no_isbn_only:
        query = f"{title} {author}".strip()
        logging.debug("pass 2 — searching OL for '%s'", query)
        results = search(query)
        time.sleep(DELAY)
        cover_i = next((r["cover_i"] for r in results if r.get("cover_i")), None)
        logging.debug("pass 2 — cover_i=%s", cover_i)
        if cover_i:
            raw = fetch_cover_by_ol_id(cover_i)
            time.sleep(DELAY)
            if raw:
                logging.info("pass 2 — fetched %d bytes via title search (needs verify)", len(raw))
                if not dry_run:
                    cov, og = process_cover(raw, md.parent)
                    meta["cover"] = cov
                    meta["og_cover"] = og
                    _write(md, meta, body)
                    logging.info("saved cover + og-cover to %s", md.parent)
                    _archive_cover(md.parent, md.parent.name)
                return "verify"  # title match — needs human spot-check
            else:
                logging.warning("pass 2 — no image returned for cover_i=%s", cover_i)
        else:
            logging.warning("pass 2 — no cover_i found for '%s'", query)

    logging.info("not found: %s", title)
    return "not_found"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--type", dest="review_type", default=None,
                        choices=["book", "audiobook", "rpg", "other"],
                        help="Limit to one content type.")
    parser.add_argument("--slug", default=None, metavar="SLUG",
                        help="Target a single review by its directory slug (e.g. rejection-tulathimutte).")
    parser.add_argument("--no-isbn-only", action="store_true",
                        help="Skip pass 2 (only process books with ISBNs).")
    parser.add_argument("--limit", type=int, default=None, metavar="N",
                        help="Stop after processing N books.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be fetched without saving anything.")
    args = parser.parse_args()

    log_path = LOG_DIR / f"fetch_covers_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)-8s %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    logging.getLogger().handlers[1].setLevel(logging.WARNING)  # console: warnings+ only
    logging.info("run started — log: %s", log_path)

    if args.dry_run:
        print("DRY RUN — nothing will be saved.\n")
        logging.info("dry run mode")

    missing = find_missing(args.review_type, args.slug)
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

    summary = (
        f"{'(dry run) ' if args.dry_run else ''}Done: "
        f"{counts['isbn'] + counts['cover_i']} saved  "
        f"({counts['isbn']} by isbn, {counts['cover_i']} by cover_i)  |  "
        f"{counts['verify']} needs verification  |  "
        f"{counts['not_found']} not found  |  "
        f"{total - len(batch)} skipped by --limit"
    )
    print(f"\n{summary}")
    logging.info(summary)

    if needs_verify:
        print("\nNeeds verification (title-matched, no ISBN):")
        print("\n".join(needs_verify))


if __name__ == "__main__":
    main()
