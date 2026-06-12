#!/usr/bin/env python3
"""Write narrator / runtime_hours from reclassify_audiobooks.csv back into reviews.

Reads the CSV produced by reclassify.py (after you fill the `narrator` and
`runtime_hours` columns by hand) and writes those fields into each
audiobook/{slug}/index.md front matter.

- `narrator` is split into first/last on the last space and stored as a
  contributor with role: narrator.
- `runtime_hours` accepts decimal hours ("9.5") or HH:MM ("9:30").
- Rows with both fields blank are skipped.

Dry-run by default. Pass --apply to write.

Run from review-cli/:
    uv run python tools/apply_audiobook_meta.py            # preview
    uv run python tools/apply_audiobook_meta.py --apply    # write
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import frontmatter

from review.config import Config

CSV_IN = Path(__file__).parent / "reclassify_audiobooks.csv"


def parse_runtime(raw: str) -> float | None:
    raw = raw.strip()
    if not raw:
        return None
    if ":" in raw:
        h, m = raw.split(":", 1)
        return int(h) + int(m) / 60
    return float(raw)


def split_narrator(raw: str) -> dict | None:
    raw = raw.strip()
    if not raw:
        return None
    parts = raw.rsplit(" ", 1)
    if len(parts) == 2:
        first, last = parts
    else:
        first, last = "", parts[0]
    return {"first": first, "last": last, "role": "narrator"}


def main() -> int:
    apply = "--apply" in sys.argv
    if not CSV_IN.exists():
        print(f"Missing {CSV_IN}. Run reclassify.py --apply first.")
        return 1

    cfg = Config.load()
    content_dir = cfg.content_dir
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"[{mode}] content_dir = {content_dir}\n")

    changed = 0
    with open(CSV_IN, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            slug = row["slug"].strip()
            narrator = split_narrator(row.get("narrator", ""))
            runtime = parse_runtime(row.get("runtime_hours", ""))
            if narrator is None and runtime is None:
                continue

            md = content_dir / "audiobook" / slug / "index.md"
            if not md.exists():
                print(f"  MISSING: audiobook/{slug}")
                continue

            updates = []
            if narrator is not None:
                updates.append(f"narrator={narrator['first']} {narrator['last']}".strip())
            if runtime is not None:
                updates.append(f"runtime_hours={runtime:g}")
            print(f"  audiobook/{slug}: {', '.join(updates)}")

            if apply:
                post = frontmatter.load(str(md))
                if narrator is not None:
                    post["narrator"] = narrator
                if runtime is not None:
                    post["runtime_hours"] = runtime
                md.write_text(frontmatter.dumps(post), encoding="utf-8")
            changed += 1

    print(f"\n{'Wrote' if apply else 'Would write'} {changed} review(s).")
    if not apply:
        print("Dry-run only. Re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
