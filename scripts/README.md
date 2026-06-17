# scripts/

One-off, problem-specific scripts — **not** part of the supported `review` CLI.

Unlike the `review` commands (which are meant to be bulletproof across
environments), these are tuned to a specific library and a specific cleanup at a
specific time. They assume an operator who can read the source and adjust it —
ideally with a coding agent on hand. Treat each as a starting point to edit, not
a stable interface. Expect to tweak paths, columns, and assumptions before
running.

Run them from the `review-cli/` directory, e.g.:

```bash
uv run python scripts/build_series_sheet.py
```

| Script | What it does |
|--------|--------------|
| `build_series_sheet.py` | Emit a CSV of reviews for filling in series / number by hand. |
| `apply_series.py` | Write series / series_number back into reviews from that CSV. |
| `apply_audiobook_meta.py` | Bulk-apply narrator / runtime / abridged metadata. |
| `reclassify.py` | One-time book ⇄ audiobook reclassification (moves dirs, rewrites `type:`). |
| `find_missing_covers.py` | List reviews with no cover image. |
| `cover_contact_sheet.py` | Build an HTML contact sheet of every cover for visual audit. |
| `lint_typos.py` | Assistive typo / grammar queue for review bodies (codespell + optional LLM pass). |

Generated CSV/JSON/YAML working files in this directory are gitignored.
