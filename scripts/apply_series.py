#!/usr/bin/env python3
"""Write series / series_number from series_sheet.csv back into reviews.

Reads the CSV produced by build_series_sheet.py (after you fill the `series`
and `number` columns) and writes `series` / `series_number` into each review's
front matter, keyed on (type, slug). Rows with a blank `series` are skipped.
Only reviews whose value actually changes are touched.

Dry-run by default. Pass --apply to write.

Run from review-cli/:
    uv run python scripts/apply_series.py            # preview the diff
    uv run python scripts/apply_series.py --apply    # write
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import frontmatter

from review.config import Config

CSV_IN = Path(__file__).parent / "series_sheet.csv"


def parse_number(raw: str):
    raw = (raw or "").strip()
    if not raw:
        return None
    f = float(raw)
    return int(f) if f.is_integer() else f


def main() -> int:
    apply = "--apply" in sys.argv
    if not CSV_IN.exists():
        print(f"Missing {CSV_IN}. Run build_series_sheet.py first.")
        return 1

    content_dir = Config.load().content_dir
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"[{mode}] content_dir = {content_dir}\n")

    changed = 0
    missing = 0
    with open(CSV_IN, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            series = (row.get("series") or "").strip()
            if not series:
                continue
            number = parse_number(row.get("number", ""))
            rtype = row["type"].strip()
            slug = row["slug"].strip()

            md = content_dir / rtype / slug / "index.md"
            if not md.exists():
                print(f"  MISSING: {rtype}/{slug}")
                missing += 1
                continue

            post = frontmatter.load(str(md))
            cur_series = post.get("series")
            cur_number = post.get("series_number")
            if cur_series == series and cur_number == number:
                continue  # no change

            num_str = "" if number is None else f" #{number}"
            print(f"  {rtype}/{slug}: {cur_series or '—'} -> {series}{num_str}")

            if apply:
                post["series"] = series
                if number is None:
                    post.metadata.pop("series_number", None)
                else:
                    post["series_number"] = number
                md.write_text(frontmatter.dumps(post), encoding="utf-8")
            changed += 1

    print(f"\n{'Wrote' if apply else 'Would write'} {changed} review(s).", end="")
    print(f" ({missing} missing path(s).)" if missing else "")
    if not apply:
        print("Dry-run only. Re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
