# review-cli

A command-line tool for writing and managing book reviews as Markdown files with YAML front matter.

Reviews are stored as plain files on your machine — no database, no service dependency.
The schema is designed to feed an [Astro](https://astro.build) static site.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

## Install

```bash
# With uv (recommended)
git clone https://github.com/YOUR_USERNAME/review-cli
cd review-cli
uv tool install .

# Or with pip
pip install .
```

### Developing on the CLI

A plain `uv tool install .` builds a **frozen copy** of the source into an
isolated environment, so your edits under `src/` don't take effect until you
rerun the install. To avoid reinstalling after every change, install the tool
**editable** so the `review` command imports your working tree directly:

```bash
uv tool install --force --editable .
```

After that, `src/` edits apply live with no reinstall — only rerun the command
when `pyproject.toml` changes (entry points or dependencies). If you add the
browser extra, include it: `uv tool install --force --editable '.[browser]'`.

## First-time setup

```bash
review init
```

This asks where you want to store review files and writes `~/.review/config.toml`.
The default is `{repo}/site/content/reviews/` (relative to the review-cli checkout) — change it if your layout differs.

## Commands

```
review new [QUERY]       Search Open Library and create a new review
review new --manual      Skip search, enter everything by hand
review new --type TYPE   Pre-select type: book | audiobook | rpg | other

review edit QUERY        Fuzzy-find a review and open it in your configured editor
review add-read QUERY    Append a new read record (for re-reads)
review fetch-cover QUERY Download cover art for an existing review

review list              Show all reviews as a table
review list --type book  Filter by type
review list --tag war    Filter by tag

review validate          Check all reviews against the schema
review init              First-time setup / change content directory
```

## Cover sources

`review new` and `review fetch-cover` get a cover through a cascade. The source is
set by `cover_source` in `~/.review/config.toml` (or per-run with `--source`):

| `cover_source` | Behaviour |
|----------------|-----------|
| `openlibrary` (default) | httpx-only: OpenLibrary → WorldCat. Works everywhere, no extra setup, but ~500px re-compressed images. |
| `amazon` | Full-resolution Amazon master first, then falls back to OpenLibrary/WorldCat. Needs the browser extra. |
| `auto` | Like `amazon` when a browser is installed, otherwise `openlibrary`. Recommended once the browser extra is set up. |

The Amazon path produces much higher-resolution covers (the same source the bulk
`stage-covers` repair pipeline uses), so preferring it at creation time avoids
generating low-res covers that later need fixing. It requires Playwright + Chrome:

```bash
uv pip install 'review[browser]'   # then optionally: playwright install chromium
```

`amazon`/`auto` always degrade gracefully — a missing or broken browser falls back
to the httpx path, so creating a review is never blocked.

```toml
# ~/.review/config.toml
cover_source = "auto"
```

## Browser cover sourcing (the `browser` extra)

The `amazon` and `auto` sources fetch the genuine full-resolution Amazon cover
master (~2560px) instead of OpenLibrary's re-compressed ~500px image. That path
drives a headless browser, which isn't in the default dependencies — install the
`browser` extra to enable it:

```bash
# As the installed tool (editable dev install):
uv tool install --force --editable '.[browser]'

# Or into a working environment:
uv pip install 'review[browser]'
```

The browser uses your **system Google Chrome** by default (`channel="chrome"`, no
150 MB browser download). If Chrome isn't present, install Chromium for
Playwright instead:

```bash
playwright install chromium
```

Once installed, set `cover_source = "auto"` (Amazon when a browser is available,
else httpx) or `"amazon"` (Amazon first, always). Both **degrade gracefully**: a
missing browser, captcha, timeout, or no-match silently falls back to the
OpenLibrary → WorldCat httpx path, so creating a review is never blocked. To try
it ad hoc without changing the install, run with `uv`:

```bash
uv run --with playwright review fetch-cover "QUERY" --source amazon
```

The bulk `find-covers` / `stage-covers` repair pipeline relies on this same
browser path — see [Bulk cover repair](#bulk-cover-repair).

## Bulk cover repair

The bulk pipeline (`stage-covers` → `pick-covers` / `pick-covers-web`, plus
`find-low-res` and `find-covers`) repairs existing low-resolution covers in batch.
It is tuned to a specific library and leans on a headless browser; see those
commands' `--help`. One-off maintenance scripts live in `scripts/` (unsupported;
read before running).

## Typo & grammar linting

`scripts/lint_typos.py` finds and (with `--apply`) fixes spelling and grammar
errors in review bodies. Front matter is excluded from both passes, so author
names, titles, and tags never show up as false positives.

It runs two passes:

1. **codespell** — a cheap misspelling / homonym sweep over each body. Always
   runs via `uvx codespell` (no install needed). An ignore-list suppresses words
   that are correct in book reviews but codespell over-eagerly "fixes".
2. **LLM pass** — an Opus (`claude-opus-4-8`) grammar / dropped-word /
   missing-preposition check that codespell can't catch. Synchronous on a
   `--limit` sample; the full corpus goes through the **Batch API** (~50% cheaper,
   async). Needs the `llm` extra (`anthropic` SDK) and `ANTHROPIC_API_KEY`.

### Apply policy

The script edits files in the working tree but **never touches git** — you own
branch / commit / merge. `--apply` is opt-in; the default is report-only
(`scripts/typo_report.txt`, no files touched). The policy biases toward applying,
with `git diff` as your review surface and undo:

| Finding | Action |
|---|---|
| codespell, lowercase single suggestion | apply |
| codespell, multiple suggestions | apply the first suggestion |
| codespell, **Capitalized / ALL-CAPS** | → residual report (lone guardrail: reliably proper nouns / acronyms) |
| LLM, quote located in body | apply (exact, else whitespace-normalized) |
| LLM, quote not locatable | → residual report |

Findings that can't be applied cleanly go to `scripts/residual_report.txt` for a
short hand-pass. Both reports and the batch state file are gitignored.

### Workflow

Run from `review-cli/`, on a dedicated branch:

```bash
git switch -c typo-fixes

# Validate on a sample first (synchronous, fast, ~pennies):
uv run --extra llm python scripts/lint_typos.py --llm --limit 50 --apply
git diff --word-diff          # eyeball; git restore . to discard

# Full corpus via the Batch API (two phase):
uv run --extra llm python scripts/lint_typos.py --submit   # phase 1: submit, returns at once
#   ...wait ~20–60 min (runs on Anthropic's side; safe to close the terminal).
#   Don't edit review bodies in between, or quoted spans may stop matching.
uv run --extra llm python scripts/lint_typos.py --apply    # phase 2: polls, then writes fixes

git diff --word-diff                       # review; git restore -p <file> to revert a hunk
cat scripts/residual_report.txt            # small hand-queue
git commit -am "Proofreading pass" && git switch main && git merge typo-fixes
```

Other invocations:

```bash
uv run python scripts/lint_typos.py                 # codespell-only dry-run report
uv run --extra llm python scripts/lint_typos.py --llm --limit 50   # sample report, no edits
```

`--apply` re-runs idempotently against the working tree: to redo a run, `git
restore .` (or reset the branch to `main`) and run again.

## Review file format

Each review lives at `{content_dir}/{type}/{slug}/index.md`.
Cover images (`cover.jpg`, `og-cover.jpg`) sit alongside it in the same directory.

Example front matter:

```yaml
---
title: "Piranesi"
authors:
  - first: "Susanna"
    last: "Clarke"
    role: author
type: book
isbn: "9781635575637"
publication_year: 2020
page_count: 272
rating: 4.5
date_reviewed: 2026-04-24
reads:
  - year: 2026
    date_started: 2026-03-15
    date_finished: 2026-04-02
tags:
  - fantasy
  - literary-fiction
cover: ./cover.jpg
og_cover: ./og-cover.jpg
---

Your review text goes here.
```

### Type-specific fields

| Type | Extra fields |
|------|-------------|
| audiobook | `narrator`, `runtime_hours`, `abridged` |
| rpg | `system`, `format` |
| other | `medium` |

## Configuration

`~/.review/config.toml`:

```toml
content_dir = "/home/you/dev/book-review-site/site/content/reviews"
editor = "code --wait"

[tags]
canonical = ["fantasy", "sci-fi", "horror"]
```

Run `review init` to set `content_dir` interactively, or edit the file directly.

`editor` overrides `$EDITOR`/`$VISUAL`. Use `code --wait` for VS Code so the CLI waits while you write.

## Tag management

When you enter a tag that isn't in the canonical list, the CLI prompts:

```
Unknown tag: sci-fi
  Similar canonical tags: science-fiction
  Add to canonical / Use once / Replace / Skip [a/u/r/s] (u):
```

Choosing **A** adds it to `config.toml` permanently.
`difflib` fuzzy-matching catches near-duplicates like `sci-fi` vs `science-fiction`.

## Cover art

`review new` automatically downloads cover art from Open Library (by ISBN),
falling back to Google Books. Two sizes are generated via Pillow:

- `cover.jpg` — max 800px wide, aspect ratio preserved
- `og-cover.jpg` — 400×600px centre-crop for Open Graph

Use `review fetch-cover QUERY` to add cover art to an existing review.

Cover art download fails frequently. Use `review process-cover {SLUG} image_file.jpg` to fix covers from local files.

## Utilities

### `diff_year.py`

Compares Goodreads and StoryGraph CSV exports against review files to surface gaps for a given year.

Place your exports in the `import/` directory. The script auto-discovers any file with `goodreads` or `storygraph` in the name and prints which files it found on startup.

```bash
# Show diff for a given year
uv run python diff_year.py 2025

# Step through books with missing years and patch their reads list
uv run python diff_year.py 2025 --add
```

Year detection uses shelf/tag labels first (e.g. a `2025` shelf on Goodreads), falling back to Date Read, then Date Added.

Output has three sections:

- **Missing year in reads** — review file exists but the year isn't in its `reads` list
- **Not reviewed** — no review file found at all
- **Only in reviews** — review has the year but the book isn't in any CSV

Each line is tagged with its source: `[GR]`, `[SG]`, or `[GR+SG]` if it appears in both.

Matching normalises titles (lowercase, series suffix like `(The Expanse, #3)` stripped, `: ` and ` - ` treated as equivalent subtitle separators).

With `--add`, the script steps through each **Missing year** book and prompts:

```text
  [GR+SG] Piranesi
  ../site/content/reviews/book/piranesi-clarke/index.md
  [y]es add year / [s]kip / [q]uit:
```

Choosing `y` appends `- year: 2025` to the `reads` list. **Not reviewed** books are skipped — use `review new` for those.

## License

MIT — see [LICENSE](LICENSE). The review content this tool manages is copyright Michael Burnam-Fink, all rights reserved.
