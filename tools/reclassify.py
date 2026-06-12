#!/usr/bin/env python3
"""One-time reclassification of misclassified reviews (book <-> audiobook).

Phase A: move each review's directory to the correct {type}/ folder and rewrite
         its `type:` front-matter field.
Phase B: emit reclassify_audiobooks.csv listing the newly-reclassified audiobooks
         with blank `narrator` / `runtime_hours` columns for manual entry
         (fed back in by apply_audiobook_meta.py).

Dry-run by default. Pass --apply to actually move files and write the CSV.

Run from review-cli/:
    uv run python tools/reclassify.py            # preview
    uv run python tools/reclassify.py --apply    # execute
"""
from __future__ import annotations

import csv
import shutil
import sys
from pathlib import Path

import frontmatter

from review.config import Config

# --- The two lists from site/todo.md -------------------------------------

# "actually a book": currently under audiobook/, given as explicit slugs.
AUDIOBOOK_TO_BOOK_SLUGS = [
    "the-bridge-at-dong-ha-miller",
    "second-variety-dick",
    "hell-divers-smith",
    "children-of-ruin-tchaikovsky",
]

# "Actually Audiobooks": currently under book/, given by title only.
# Resolved to a review dir by normalised-title match below.
BOOK_TO_AUDIOBOOK_TITLES = [
    "The Achilles Trap",
    "Small Things Like These",
    "A Drop of Corruption",
    "No More Mr. Nice Guy",
    "Traitor to His Class",
    "Planet of Exile",
    "City of Illusions",
    "Crossings",
    "The Ionian Mission",
    "Pet",
    "Breath",
    "How Rome Fell",
    "The Golden Road",
    "The Left Hand of Darkness",
    "Everything Must Go",
    "The Surgeon's Mate",
    "A Stitch in Time",
    "The Fortune of War",
    "The Splendid and the Vile",
    "Desolation Island",
    "The Mauritius Command",
    "Mastery - George Leonard",
    "NurtureShock",
    "The Daughter's War",
]

# Titles whose review exists under a slug that normalised-matching can't reach
# (review title differs from the todo entry). Maps todo title -> book/ slug.
OVERRIDE_SLUGS = {
    "Mastery - George Leonard": "mastery-the-keys-to-success-and-long-term-fulfillment-leonard",
    "The Daughter's War": "the-daughters-war-buehlman",
}

CSV_OUT = Path(__file__).parent / "reclassify_audiobooks.csv"


def normalise(title: str) -> str:
    """Match diff_year.normalise: lowercase, drop series/paren suffix, fold separators."""
    t = title.lower()
    if " (" in t:
        t = t[: t.index(" (")]
    t = t.replace(": ", " ").replace(" - ", " ")
    return t.strip()


def author_display(meta: dict) -> str:
    parts = [
        f"{a.get('first', '')} {a.get('last', '')}".strip()
        for a in (meta.get("authors") or [])
        if a.get("role") == "author"
    ]
    return ", ".join(parts)


def index_by_norm_title(content_dir: Path, review_type: str) -> dict[str, list[Path]]:
    idx: dict[str, list[Path]] = {}
    for md in sorted((content_dir / review_type).rglob("*/index.md")):
        post = frontmatter.load(str(md))
        key = normalise(str(post.get("title", md.parent.name)))
        idx.setdefault(key, []).append(md)
    return idx


def retype_and_move(md: Path, content_dir: Path, new_type: str, apply: bool) -> Path | None:
    """Rewrite type: in front matter and move the dir to {new_type}/{slug}. Returns new dir."""
    slug = md.parent.name
    dst_dir = content_dir / new_type / slug
    if dst_dir.exists():
        print(f"  !! destination already exists, skipping: {dst_dir}")
        return None
    if apply:
        post = frontmatter.load(str(md))
        post["type"] = new_type
        md.write_text(frontmatter.dumps(post), encoding="utf-8")
        shutil.move(str(md.parent), str(dst_dir))
    return dst_dir


def main() -> int:
    apply = "--apply" in sys.argv
    cfg = Config.load()
    content_dir = cfg.content_dir
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"[{mode}] content_dir = {content_dir}\n")

    # --- Phase A.1: audiobook -> book (explicit slugs) ---
    print("=== audiobook -> book ===")
    for slug in AUDIOBOOK_TO_BOOK_SLUGS:
        src = content_dir / "audiobook" / slug / "index.md"
        if not src.exists():
            print(f"  MISSING: audiobook/{slug}")
            continue
        dst = retype_and_move(src, content_dir, "book", apply)
        if dst:
            print(f"  audiobook/{slug}  ->  book/{slug}")

    # --- Phase A.2: book -> audiobook (resolve titles to slugs) ---
    print("\n=== book -> audiobook ===")
    book_idx = index_by_norm_title(content_dir, "book")
    moved_audiobooks: list[tuple[str, str, dict]] = []  # (slug, type-path, meta)
    unresolved: list[str] = []

    audiobook_idx = index_by_norm_title(content_dir, "audiobook")

    for title in BOOK_TO_AUDIOBOOK_TITLES:
        override = OVERRIDE_SLUGS.get(title)
        if override:
            candidates = [content_dir / "book" / override / "index.md"]
            if not candidates[0].exists():
                print(f"  OVERRIDE MISSING: {title!r} -> book/{override}")
                unresolved.append(title)
                continue
        else:
            key = normalise(title)
            candidates = book_idx.get(key, [])
            if not candidates:
                # fall back: target may carry an author suffix the review title lacks,
                # matched only on a whole-word boundary to avoid "Ho" == "How Rome Fell"
                candidates = [
                    mds[0]
                    for bk, mds in book_idx.items()
                    if key == bk or key.startswith(bk + " ") or bk.startswith(key + " ")
                ]
        if len(candidates) != 1:
            if not candidates:
                # Already an audiobook, or simply not reviewed yet.
                if normalise(title) in audiobook_idx:
                    reason = "already an audiobook — nothing to do"
                else:
                    reason = "no review found — not reviewed yet?"
                print(f"  SKIP: {title!r} ({reason})")
            else:
                print(f"  AMBIGUOUS ({len(candidates)}): {title!r}")
                for c in candidates:
                    print(f"      candidate: book/{c.parent.name}")
            unresolved.append(title)
            continue

        md = candidates[0]
        slug = md.parent.name
        meta = frontmatter.load(str(md)).metadata
        dst = retype_and_move(md, content_dir, "audiobook", apply)
        if dst:
            print(f"  {title!r}  ->  audiobook/{slug}")
            moved_audiobooks.append((slug, author_display(meta), str(meta.get("title", title))))

    # --- Phase B: emit the narrator/runtime CSV for the moved audiobooks ---
    print(f"\n=== Phase B: {CSV_OUT.name} ===")
    if apply:
        with open(CSV_OUT, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["slug", "author", "title", "narrator", "runtime_hours"])
            for slug, author, title in sorted(moved_audiobooks):
                w.writerow([slug, author, title, "", ""])
        print(f"  wrote {len(moved_audiobooks)} rows -> {CSV_OUT}")
    else:
        print(f"  would write {len(moved_audiobooks)} rows (run with --apply)")

    if unresolved:
        print(f"\n!! {len(unresolved)} title(s) unresolved — handle manually:")
        for t in unresolved:
            print(f"   - {t}")

    if not apply:
        print("\nDry-run only. Re-run with --apply to move files and write the CSV.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
