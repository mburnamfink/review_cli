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

## First-time setup

```bash
review init
```

This asks where you want to store review files and writes `~/.review/config.toml`.
The default is `~/content/reviews/` — change it to wherever makes sense for your setup
(e.g. inside a git repo you control).

## Commands

```
review new [QUERY]       Search Open Library and create a new review
review new --manual      Skip search, enter everything by hand
review new --type TYPE   Pre-select type: book | audiobook | rpg | other

review edit QUERY        Fuzzy-find a review and open it in $EDITOR
review add-read QUERY    Append a new read record (for re-reads)
review fetch-cover QUERY Download cover art for an existing review

review list              Show all reviews as a table
review list --type book  Filter by type
review list --tag war    Filter by tag

review validate          Check all reviews against the schema
review init              First-time setup / change content directory
```

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
content_dir = "/Users/you/dev/book-review-site/content/reviews"

[tags]
canonical = ["fantasy", "science-fiction", "horror"]
```

Run `review init` to set `content_dir` interactively, or edit the file directly.

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

## License

MIT — see [LICENSE](LICENSE). The review content this tool manages is copyright Michael Burnam-Fink, all rights reserved.
