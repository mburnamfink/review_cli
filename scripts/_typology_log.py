"""Shared change log for the Task 3 typology passes.

The three automated passes (italicize_titles, fix_internal_links,
localize_images) each record every edit they make to a single combined
`typology_changes.csv` so the author can audit them in one place.

Columns: change_type, type, slug, before, after

`replace_section()` is idempotent per change_type: re-running a pass overwrites
only that pass's rows, leaving the other passes' rows intact.
"""
from __future__ import annotations

import csv
from pathlib import Path

LOG_PATH = Path(__file__).parent / "typology_changes.csv"
FIELDS = ["change_type", "type", "slug", "before", "after"]


def replace_section(change_type: str, rows: list[dict]) -> Path:
    """Replace all rows tagged `change_type` in the combined log with `rows`."""
    kept: list[dict] = []
    if LOG_PATH.exists():
        with open(LOG_PATH, newline="", encoding="utf-8") as f:
            kept = [r for r in csv.DictReader(f) if r.get("change_type") != change_type]

    tagged = [{**r, "change_type": change_type} for r in rows]
    with open(LOG_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in kept + tagged:
            w.writerow({k: r.get(k, "") for k in FIELDS})
    return LOG_PATH
