"""Compare books read in a given year between Goodreads tags and review content dir."""
import csv
import sys
from pathlib import Path

import frontmatter

GOODREADS_CSV = Path(__file__).parent / "import/goodreads_library_export (1).csv"
CONTENT_DIR = Path("../site/content/reviews")


def goodreads_by_tag(year: int):
    with open(GOODREADS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            shelves = [s.strip() for s in row.get("Bookshelves", "").split(",")]
            if str(year) in shelves:
                yield row["Title"].strip()


def load_all_reviews() -> dict[str, Path]:
    """Return normalised_title -> Path for every review file."""
    result = {}
    for md in CONTENT_DIR.rglob("*/index.md"):
        post = frontmatter.load(md)
        title = post.get("title", md.parent.name).strip()
        result[normalise(title)] = md
    return result


def review_books(year: int, all_reviews: dict[str, Path]):
    for key, md in all_reviews.items():
        post = frontmatter.load(md)
        reads = post.get("reads") or []
        if any(r.get("year") == year for r in reads):
            yield post.get("title", md.parent.name).strip()


def normalise(title: str) -> str:
    t = title.lower()
    if " (" in t:
        t = t[: t.index(" (")]
    return t.strip()


def add_year_interactive(only_gt: list[str], year: int, all_reviews: dict[str, Path]):
    print(f"\n--- Stepping through {len(only_gt)} Goodreads-only books ---")
    for gr_title in only_gt:
        key = normalise(gr_title)
        md = all_reviews.get(key)
        if md is None:
            print(f"\n  {gr_title}\n  [no review file found — skipping]")
            continue

        print(f"\n  {gr_title}\n  {md}")
        while True:
            choice = input("  [y]es add year / [s]kip / [q]uit: ").strip().lower()
            if choice in ("y", "s", "q"):
                break

        if choice == "q":
            print("Stopped.")
            break
        if choice == "s":
            continue

        post = frontmatter.load(md)
        reads = list(post.get("reads") or [])
        reads.append({"year": year})
        post["reads"] = reads
        md.write_text(frontmatter.dumps(post), encoding="utf-8")
        print(f"  Added year {year}.")


def main(year: int, add: bool = False):
    all_reviews = load_all_reviews()
    gt_titles = list(goodreads_by_tag(year))
    rv_titles = list(review_books(year, all_reviews))

    gt_norm = {normalise(t): t for t in gt_titles}
    rv_norm = {normalise(t): t for t in rv_titles}

    all_keys = set(gt_norm) | set(rv_norm)
    only_gt = sorted(gt_norm[k] for k in set(gt_norm) - set(rv_norm))
    only_rv = sorted(rv_norm[k] for k in set(rv_norm) - set(gt_norm))

    print(f"\n{'='*60}")
    print(f"Year: {year}  |  GR tag: {len(gt_titles)}  |  Reviews: {len(rv_titles)}")
    print(f"Matched: {len(all_keys) - len(only_gt) - len(only_rv)}  |  Only GR: {len(only_gt)}  |  Only reviews: {len(only_rv)}")

    if only_gt:
        print(f"\n--- Only in Goodreads ({len(only_gt)}) ---")
        for t in only_gt:
            print(f"  {t}")

    if only_rv:
        print(f"\n--- Only in reviews ({len(only_rv)}) ---")
        for t in only_rv:
            print(f"  {t}")

    print(f"\n{'='*60}")

    if add and only_gt:
        add_year_interactive(only_gt, year, all_reviews)


if __name__ == "__main__":
    args = sys.argv[1:]
    add = "--add" in args
    args = [a for a in args if a != "--add"]
    if len(args) != 1 or not args[0].isdigit():
        print(f"Usage: python {Path(__file__).name} <year> [--add]")
        sys.exit(1)
    main(int(args[0]), add=add)
