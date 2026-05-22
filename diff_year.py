"""Compare books read in a given year between Goodreads export and review content dir."""
import csv
import sys
from pathlib import Path

import frontmatter

GOODREADS_CSV = Path(__file__).parent / "import/goodreads_library_export (1).csv"
CONTENT_DIR = Path("../site/content/reviews")


def goodreads_by_date(year: int):
    with open(GOODREADS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("Date Read", "").strip().startswith(str(year)):
                yield row["Title"].strip()


def goodreads_by_tag(year: int):
    with open(GOODREADS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            shelves = [s.strip() for s in row.get("Bookshelves", "").split(",")]
            if str(year) in shelves:
                yield row["Title"].strip()


def review_books(year: int):
    for md in CONTENT_DIR.rglob("*/index.md"):
        post = frontmatter.load(md)
        reads = post.get("reads") or []
        if any(r.get("year") == year for r in reads):
            yield post.get("title", md.parent.name).strip()


def normalise(title: str) -> str:
    t = title.lower()
    if " (" in t:
        t = t[: t.index(" (")]
    return t.strip()


def main(year: int):
    gd_titles = list(goodreads_by_date(year))
    gt_titles = list(goodreads_by_tag(year))
    rv_titles = list(review_books(year))

    gd_norm = {normalise(t): t for t in gd_titles}
    gt_norm = {normalise(t): t for t in gt_titles}
    rv_norm = {normalise(t): t for t in rv_titles}

    all_keys = set(gd_norm) | set(gt_norm) | set(rv_norm)

    print(f"\n{'='*72}")
    print(f"Year: {year}  |  GR date: {len(gd_titles)}  |  GR tag: {len(gt_titles)}  |  Reviews: {len(rv_titles)}")
    print(f"\n{'Title':<45} {'GR date':>7} {'GR tag':>7} {'Review':>7}")
    print("-" * 72)

    for key in sorted(all_keys):
        title = rv_norm.get(key) or gt_norm.get(key) or gd_norm.get(key)
        cols = [
            "  X  " if key in gd_norm else "  -  ",
            "  X  " if key in gt_norm else "  -  ",
            "  X  " if key in rv_norm else "  -  ",
        ]
        if not (key in gd_norm and key in gt_norm and key in rv_norm):
            print(f"{title[:44]:<45} {cols[0]:>7} {cols[1]:>7} {cols[2]:>7}")

    print(f"\n{'='*72}")
    print("(Rows where all three agree are hidden)")


if __name__ == "__main__":
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        print(f"Usage: python {Path(__file__).name} <year>")
        sys.exit(1)
    main(int(sys.argv[1]))
