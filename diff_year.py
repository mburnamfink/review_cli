"""Compare books read in a given year between import CSVs and review content dir."""
import csv
import re
import sys
from pathlib import Path

import frontmatter

IMPORT_DIR = Path(__file__).parent / "import"
CONTENT_DIR = Path(__file__).parent / "../site/content/reviews"


def find_import_files() -> tuple[Path | None, Path | None]:
    all_csvs = list(IMPORT_DIR.glob("*.csv"))
    gr = next((p for p in all_csvs if "goodreads" in p.name.lower()), None)
    sg = next((p for p in all_csvs if "storygraph" in p.name.lower()), None)
    return gr, sg


def year_from_tags(tags_str: str, year: int) -> bool:
    """Return True if `year` appears as a bare 4-digit tag or 'YYYY (#N)' form."""
    for part in tags_str.split(","):
        part = part.strip()
        m = re.match(r"^(\d{4})(?:\s*\(|$)", part)
        if m and int(m.group(1)) == year:
            return True
    return False


def year_from_date(date_str: str) -> int | None:
    if date_str:
        m = re.match(r"^(\d{4})", date_str.strip())
        if m:
            return int(m.group(1))
    return None


def titles_for_year_goodreads(path: Path, year: int) -> list[str]:
    result = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            shelves = row.get("Bookshelves", "") or ""
            date_read = row.get("Date Read", "") or ""
            date_added = row.get("Date Added", "") or ""
            if (
                year_from_tags(shelves, year)
                or year_from_date(date_read) == year
                or year_from_date(date_added) == year
            ):
                result.append(row["Title"].strip())
    return result


def titles_for_year_storygraph(path: Path, year: int) -> list[str]:
    result = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            tags = row.get("Tags", "") or ""
            dates_read = row.get("Dates Read", "") or ""
            last_date_read = row.get("Last Date Read", "") or ""
            date_added = row.get("Date Added", "") or ""
            if year_from_tags(tags, year):
                result.append(row["Title"].strip())
            elif any(year_from_date(d.strip()) == year for d in dates_read.split(",") if d.strip()):
                result.append(row["Title"].strip())
            elif year_from_date(last_date_read) == year:
                result.append(row["Title"].strip())
            elif year_from_date(date_added) == year:
                result.append(row["Title"].strip())
    return result


def normalise(title: str) -> str:
    t = title.lower()
    if " (" in t:
        t = t[: t.index(" (")]
    # Collapse subtitle separators so "Foo: Bar" and "Foo - Bar" match
    t = t.replace(": ", " ").replace(" - ", " ")
    return t.strip()


def load_all_reviews() -> dict[str, dict]:
    """Return norm_title -> {title, path, years} for every review file."""
    result = {}
    for md in CONTENT_DIR.rglob("*/index.md"):
        post = frontmatter.load(md)
        title = post.get("title", md.parent.name).strip()
        reads = post.get("reads") or []
        years = {r.get("year") for r in reads if r.get("year")}
        result[normalise(title)] = {"title": title, "path": md, "years": years}
    return result


def add_year_interactive(missing_year: list[tuple[str, str, Path]], year: int):
    print(f"\n--- Stepping through {len(missing_year)} books with missing year ---")
    for title, source, md in missing_year:
        print(f"\n  [{source}] {title}\n  {md}")
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
    gr_path, sg_path = find_import_files()

    if not gr_path and not sg_path:
        print(f"No import files found in {IMPORT_DIR}.")
        print("Add a Goodreads or StoryGraph CSV export to that directory.")
        sys.exit(1)

    print(f"\nImport sources:")
    print(f"  Goodreads:   {gr_path.name if gr_path else '(not found)'}")
    print(f"  StoryGraph:  {sg_path.name if sg_path else '(not found)'}")

    csv_books: dict[str, dict] = {}

    def add_csv(titles: list[str], source: str) -> None:
        for t in titles:
            key = normalise(t)
            if key not in csv_books:
                csv_books[key] = {"title": t, "sources": set()}
            csv_books[key]["sources"].add(source)

    if gr_path:
        add_csv(titles_for_year_goodreads(gr_path, year), "GR")
    if sg_path:
        add_csv(titles_for_year_storygraph(sg_path, year), "SG")

    all_reviews = load_all_reviews()
    reviewed_this_year = {k for k, v in all_reviews.items() if year in v["years"]}

    missing_year_list: list[tuple[str, str, Path]] = []
    not_reviewed_list: list[tuple[str, str]] = []

    for key, info in csv_books.items():
        if key in reviewed_this_year:
            continue
        source_str = "+".join(sorted(info["sources"]))
        if key in all_reviews:
            missing_year_list.append((info["title"], source_str, all_reviews[key]["path"]))
        else:
            not_reviewed_list.append((info["title"], source_str))

    missing_year_list.sort(key=lambda x: x[0].lower())
    not_reviewed_list.sort(key=lambda x: x[0].lower())

    only_reviews = sorted(
        all_reviews[k]["title"]
        for k in reviewed_this_year
        if k not in csv_books
    )

    matched = sum(1 for k in csv_books if k in reviewed_this_year)

    print(f"\n{'='*60}")
    print(f"Year: {year}  |  CSV total: {len(csv_books)}  |  Reviews with year: {len(reviewed_this_year)}")
    print(
        f"Matched: {matched}  |  Missing year: {len(missing_year_list)}"
        f"  |  Not reviewed: {len(not_reviewed_list)}  |  Only in reviews: {len(only_reviews)}"
    )

    if missing_year_list:
        print(f"\n--- Missing year in reads ({len(missing_year_list)}) ---")
        for title, source, _ in missing_year_list:
            print(f"  [{source}] {title}")

    if not_reviewed_list:
        print(f"\n--- Not reviewed ({len(not_reviewed_list)}) ---")
        for title, source in not_reviewed_list:
            print(f"  [{source}] {title}")

    if only_reviews:
        print(f"\n--- Only in reviews ({len(only_reviews)}) ---")
        for t in only_reviews:
            print(f"  {t}")

    print(f"\n{'='*60}")

    if add and missing_year_list:
        add_year_interactive(missing_year_list, year)


if __name__ == "__main__":
    args = sys.argv[1:]
    add = "--add" in args
    args = [a for a in args if a != "--add"]
    if len(args) != 1 or not args[0].isdigit():
        print(f"Usage: python {Path(__file__).name} <year> [--add]")
        sys.exit(1)
    main(int(args[0]), add=add)
