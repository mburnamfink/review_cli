"""Find and deduplicate reads entries with the same year in review files."""
import sys
from pathlib import Path

import frontmatter
import yaml

CONTENT_DIR = Path("../site/content/reviews")


def dedup_reads(reads: list) -> tuple[list, list[dict]]:
    """Return (deduped_reads, list of dropped entries)."""
    by_year: dict[int, list] = {}
    for entry in reads:
        year = entry.get("year")
        by_year.setdefault(year, []).append(entry)

    deduped = []
    dropped = []
    for year, entries in by_year.items():
        if len(entries) == 1:
            deduped.append(entries[0])
        else:
            best = max(entries, key=lambda e: len(e))
            deduped.append(best)
            dropped.extend(e for e in entries if e is not best)

    # preserve original order by sorting on first occurrence index
    order = {id(e): i for i, e in enumerate(reads)}
    deduped.sort(key=lambda e: order[id(e)])
    return deduped, dropped


def main(dry_run: bool = True):
    files_changed = 0

    for md in sorted(CONTENT_DIR.rglob("*/index.md")):
        post = frontmatter.load(md)
        reads = post.get("reads") or []
        if not reads:
            continue

        deduped, dropped = dedup_reads(reads)
        if not dropped:
            continue

        files_changed += 1
        print(f"\n{md}")
        for entry in dropped:
            print(f"  DROP  year={entry.get('year')} {dict(entry)}")
        kept = [e for e in deduped if e not in reads or e not in dropped]
        for entry in deduped:
            if entry not in dropped:
                orig_dupes = [e for e in reads if e.get("year") == entry.get("year")]
                if len(orig_dupes) > 1:
                    print(f"  KEEP  year={entry.get('year')} {dict(entry)}")

        if not dry_run:
            post["reads"] = deduped
            md.write_text(frontmatter.dumps(post), encoding="utf-8")

    if files_changed == 0:
        print("No duplicate reads entries found.")
    elif dry_run:
        print(f"\n--- Dry run: {files_changed} file(s) would be changed. Run with --fix to apply. ---")
    else:
        print(f"\n--- Fixed {files_changed} file(s). ---")


if __name__ == "__main__":
    dry_run = "--fix" not in sys.argv
    main(dry_run)
