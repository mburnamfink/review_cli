# Slice 3 — Candidate sourcing + `find-covers` command

> Type: AFK
> Source PRD: `docs/prd/improve-covers.md`

## What to build

Given a flagged book, fetch real high-resolution cover candidates and stage them
on disk. End-to-end path: search **Amazon** by title + author, take the main
cover from each of the top editions, recover the full-resolution master behind
each thumbnail, dedup and rank the candidates, download them, and save to the
`covers/` staging directory.

> **Source decision (revised during build).** Goodreads was the original plan but
> proved a dead end: (1) it serves a CloudFront JS/WAF challenge that plain HTTP
> can't clear — *not* a datacenter-IP block; it fails identically from a
> residential IP; and (2) even when reached, Goodreads re-compresses covers to
> ~500px, so there is no high-res master to recover. Open Library and the Amazon
> `/images/P/<ISBN>` endpoint also cap at ~500px. The genuine 1500–2560px masters
> live on Amazon's `m.media-amazon.com/images/I/` item path, embedded only on the
> rendered product page. We reach it with a real headless browser.

Modules plus a command:

- **Headless-browser edge** (`browser.py`): a stealthed Playwright/Chrome session
  that warms up on the site homepage (clearing the WAF token) before navigating.
  Optional, lazily-imported dependency (`[browser]` extra); drives system Chrome
  by default. Exposes `html(url)` and `element_attrs(url, selector, attrs)` — the
  latter reads a *single* DOM element so we stay on the product's own image and
  off the "customers also bought" carousels.
- **Amazon sourcing** (`amazon.py`): pure parsers `parse_search_product_paths`
  (dedup `/dp/<ASIN>` links), `pick_largest_dynamic_image`, `main_cover_url`
  (resolve the `#landingImage` cover from its attributes), plus
  `upgrade_resolution` (strip the `._SX###_` / `._SL1500_` / `._AC_..._` suffix
  to the full-res master; idempotent). Edge: `search_cover_urls(title, author)`.
- **Candidate ranker** (pure): dedup by perceptual (average) hash; sort by
  resolution descending; cap to ~6–8. (Unchanged from original plan.)
- `review find-covers <query>` fuzzy-matches a review (like `review edit`), then
  composes search → main-cover-per-edition → upgrade → filter (portrait,
  non-thumbnail) → rank → download. Saved as `covers/<slug>_N.jpg`.

## Acceptance criteria

- [x] `upgrade_resolution` table-tested across size suffixes (incl. `._SL1500_`, `._AC_UF1000,1000_QL80_`); no-suffix pass-through; idempotent.
- [x] Ranker collapses near-duplicate covers, orders by resolution descending, caps to ~6–8.
- [x] `main_cover_url` / `pick_largest_dynamic_image` resolve the product's own cover and ignore carousel images (verified: contamination bug found and fixed).
- [x] `review find-covers <query>` writes top candidates to `covers/<slug>_N.jpg` and prints them; HTML parsing is pure and unit-tested.
- [x] Validated live against Amazon (residential IP): *A Drop of Corruption* → 1 cover @1678×2560; *Dune* → 4 distinct editions @≥1900px tall, all correct book.

## Blocked by

- None - can start immediately
