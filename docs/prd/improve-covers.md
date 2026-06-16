# PRD: Cover Improvement Workflow

> Status: ready-for-agent
> Area: `review_cli`
> Source: design grilling session, 2026-06-13

## Problem Statement

Many reviews on the site display a poor cover image. The covers fall into two
buckets:

1. **Low-resolution covers** — the `cover.jpg` was sourced from a thumbnail, so
   it looks soft and pixelated. Because `process_cover` caps width at 800px and
   never upscales, these covers land well below 800px wide.
2. **Awkward og-previews** — the `og-cover.jpg` (the image shown on the site's
   main listing page) is produced by a forced 400×600 centre-crop. On covers
   whose aspect ratio differs from 2:3, this shaves off the top and bottom (or
   sides), frequently clipping the title, author name, or key art.

Today the only fix is fully manual: notice a bad cover by eye, hunt down a
better image somewhere, download it, and run `review process-cover <slug>
<image>` by hand. This does not scale across a library of hundreds of reviews,
and the centre-crop keeps mangling otherwise-good replacements.

## Solution

A semi-automated workflow, driven from the `review` CLI on a kitty terminal,
that:

1. **Finds** every low-resolution cover automatically (pure width threshold), so
   the user never hand-maintains a list of "bad" books.
2. **Scrapes Goodreads** for alternate editions of each flagged book, recovers
   the full-resolution original behind each Amazon-hosted thumbnail, and ranks
   the candidates.
3. **Presents** the current cover and the top candidates **inline in the
   terminal**, so the user picks the best one with a single keystroke and it is
   applied immediately — no filename juggling, no alt-tabbing.
4. **Stops clipping** the og-preview: instead of centre-cropping, it fits the
   whole cover into the 400×600 frame and fills the leftover bars by extending
   the cover's edge colour outward, so the title, author, and art are never lost.

The user keeps full editorial control — nothing is applied without an explicit
pick — while the tedious parts (finding, fetching, resolution-upgrading,
ranking, applying) are automated.

## User Stories

1. As a site owner, I want the tool to automatically find every review whose
   `cover.jpg` is below a width threshold, so that I never have to manually
   maintain a list of low-resolution covers.
2. As a site owner, I want the low-resolution threshold to default to 700px, so
   that thumbnails are caught while properly-sourced ~800px covers are not.
3. As a site owner, I want to override the threshold with a flag, so that I can
   tune sensitivity without editing code.
4. As a site owner, I want to optionally pass an explicit list of slugs, so that
   I can replace a cover I dislike even when it is already high-resolution.
5. As a site owner, I want the tool to scrape Goodreads for alternate editions
   of a flagged book by title and author, so that I have real choices for a
   better cover.
6. As a site owner, I want each candidate's Amazon-hosted image URL upgraded to
   its full-resolution original (by stripping the size suffix), so that I am
   choosing among high-resolution covers rather than more thumbnails.
7. As a site owner, I want duplicate and near-duplicate candidate covers
   collapsed, so that I am not shown the same art repeatedly.
8. As a site owner, I want candidates ranked by resolution (after upgrade), so
   that the best options appear first.
9. As a site owner, I speak English so I care most about US and UK editions. Other site owners may have different priorities.
10. As a site owner, I want only the top handful (~6–8) of candidates downloaded
   and shown per book, so that the choice stays manageable.
11. As a site owner, I want candidate images saved into the `covers/` staging
    directory as `<slug>_N.jpg`, so that they are inspectable and reusable
    outside the loop.
12. As a site owner, I want to review books one at a time in a single command,
    with the current cover and all candidates rendered inline in my kitty
    terminal, so that I can judge them without leaving the terminal.
13. As a site owner, I want to press a digit to pick a candidate and have the
    cover applied immediately (cover.jpg, og-cover.jpg, and frontmatter all
    updated), so that picking and applying are one motion.
14. As a site owner, I want to press `r` to reject all candidates for a book and
    have that book appended to a "needs manual resolution" list, so that I can
    handle hopeless cases by hand later.
15. As a site owner, I want to press `s` to skip a book for now without
    resolving it, so that I can come back to it.
16. As a site owner, I want to press `q` to quit the loop at any time, so that I
    can stop and resume later.
17. As a site owner, I want the loop to persist its state, so that re-running the
    command resumes where I left off and does not re-process books I already
    finished.
18. As a site owner, I want re-running the command to act as the "second pass"
    over the books I rejected or skipped, so that the workflow is iterative.
19. As a site owner, I want the og-preview to fit the entire cover inside 400×600
    rather than cropping it, so that the title, author, and key art are never
    clipped.
20. As a site owner, I want the empty bars filled by extending the cover's edge
    colour outward, so that the padding looks like a seamless part of the cover.
21. As a site owner, I want a blur parameter controlling the edge extension, so
    that I can soften streaks on covers with busy/photographic edges and tune the
    look during real runs.
22. As a site owner, I want the new og-preview logic applied to every code path
    that generates a cover (`pick-covers`, `process-cover`, `fetch-cover`), so
    that all covers benefit consistently.
23. As a site owner, I want the display `cover.jpg` left untouched, so that the
    full-aspect main image is unaffected by the og-preview change.
24. As a site owner, I want the existing cover contact sheet to remain valid, so
    that I can audit the whole library after a run.

## Implementation Decisions

### Source strategy (Goodreads → Amazon full-res)
- Covers are sourced by scraping **Goodreads editions** for a given book, then
  recovering the full-resolution original. Goodreads serves Amazon-hosted images
  carrying a size suffix (e.g. `..._SX318_.jpg`); stripping that suffix yields
  the full-resolution asset. This resolution upgrade is the entire justification
  for using Goodreads — without it, scraping returns more thumbnails.
- Google Books was rejected (failed in a prior run). Amazon-direct was rejected
  as harder than Goodreads. Goodreads bot/Cloudflare blocking is a known,
  accepted implementation risk.

### Modules

- **`goodreads` edition scraper** (new deep module)
  - Interface (shape, not final signature): `search_editions(title, author) ->
    list[Edition]`, where `Edition` carries at least a cover image URL.
  - Network lives at the edge of this module; HTML parsing is a pure function so
    it can be exercised against saved fixtures.

- **Amazon-URL upgrader** (new, pure)
  - `upgrade_resolution(url) -> url` — strips the `_SX###_` / `_SY###_` style
    size suffix to point at the full-resolution original. Idempotent; returns the
    input unchanged when no suffix is present.

- **Low-res detector** (new, pure core + filesystem wrapper)
  - `is_low_res(width, threshold=700) -> bool` (pure).
  - `find_low_res(content_dir, threshold=700) -> list[review]` walks reviews and
    applies `is_low_res` to each `cover.jpg`'s width.
  - Rationale for width-only: `process_cover` caps width at 800 and never
    upscales, so a properly-sourced cover is ~800px wide; anything well under is
    a thumbnail. No blur/quality heuristic needed.

- **Candidate ranker** (new, pure)
  - Input: a set of downloaded candidate images. Output: an ordered, de-duplicated
    list. Dedup by content/perceptual hash; sort by *upgraded* resolution
    descending; cap to ~6–8.

- **og-cover renderer** (new deep module; replaces the og path of
  `process_cover`)
  - `make_og_cover(img, width=400, height=600, blur=<default>) -> Image`.
  - Algorithm: scale the whole source image to *fit* inside the target box
    (never crop); fill the residual bars by sampling a thin averaged strip of the
    corresponding edge (left/right edges feed side bars; top/bottom edges feed
    top/bottom bars) and extending it outward, blurred by `blur`.
  - Replaces `_centre_crop` for the og output only. The `cover.jpg` path
    (max-800 width, aspect preserved) is unchanged.
  - Wired into `covers.process_cover` so every caller (`pick-covers`,
    `process-cover`, `fetch-cover`) inherits it.

- **Pick-state store** (new, small)
  - Load/save a JSON manifest at `covers/.pick_state.json` recording, per book:
    candidate hashes already shown, the chosen candidate, and status
    (`done` / `rejected` / `skipped` / `needs-manual`).

- **`pick-covers` command + kitty inline renderer** (new, thin orchestration)
  - New `review pick-covers` command. Composes detector → scraper → ranker →
    inline render → keypress → apply.
  - Per-book keys: `1`–`N` pick & immediately apply (`process_cover`),
    `r` reject-all → append slug to the needs-manual list, `s` skip,
    `q` quit.
  - Candidates downloaded to `covers/<slug>_N.jpg`. Rendering uses kitty's
    graphics protocol; target terminal is kitty.
  - Re-running the command reads the state store and resumes (the "second pass").

### Scope of change to existing code
- `covers.py` gains the new og renderer and keeps `process_cover`'s public
  signature; the og branch swaps centre-crop for fit + edge-extend.
- The three existing cover paths in `cli.py` (`process-cover`, `fetch-cover`,
  and the bulk path) are unchanged except that they now produce edge-extended
  og-previews for free.
- `cover_contact_sheet.py` is unchanged and remains the post-run audit tool.

## Testing Decisions

This is a greenfield test situation for `review_cli` — there is no existing
suite. Introduce `pytest` under `review_cli/tests/`. Tests assert **external
behavior only** (inputs → outputs and observable invariants), never internal
call structure, so the modules can be refactored freely.

Modules to unit-test (per developer selection):

- **og-cover renderer** — the highest-value test.
  - Output is exactly 400×600 for any input aspect ratio.
  - No source pixels are discarded (the full source is visible inside the frame):
    e.g. for a known source, the scaled cover region matches the source and only
    the bars are synthesized.
  - Bars are drawn on the correct axis: narrower-than-2:3 sources get side bars;
    wider/square sources get top/bottom bars.
  - The `blur` parameter is honored (e.g. blur=0 yields a hard edge extension).

- **Candidate ranker** — feed synthetic candidates with known dimensions and
  known duplicate hashes; assert duplicates are collapsed, ordering is by
  upgraded resolution descending, and the result is capped.

- **Amazon-URL upgrader** — table-driven: URLs with various size suffixes map to
  their stripped form; URLs without a suffix pass through unchanged; idempotent
  on already-upgraded URLs.

- **Low-res detector** — `is_low_res` boundary cases around the threshold
  (699 → true, 700 → false, 800 → false); the filesystem wrapper against a small
  fixture tree of review dirs with known cover widths.

Explicitly **not** unit-tested (integration / manual only):

- **Goodreads parser** — would require saved-HTML fixtures that are brittle to
  Goodreads markup changes; the upkeep cost outweighs the value. Validate by
  manual run instead.
- **`pick-covers` loop and kitty renderer** — terminal-graphics side effects and
  network orchestration; covered by manual runs, not unit tests.

Prior art: none in this repo; follow standard `pytest` conventions and keep image
fixtures small and generated in-test where possible (construct `PIL.Image`s of
known size/colour rather than committing binaries).

## Out of Scope

- Any "smart"/saliency/AI-based crop of the og-preview. The fit + edge-extend
  approach is deterministic and preserves all content; an AI escape hatch is a
  possible future addition, not part of this work.
- Changing the display `cover.jpg` (it already preserves aspect and never crops).
- Distortion/non-uniform scaling to fill the og frame (rejected — warps text and
  faces).
- Solving Goodreads Cloudflare/bot-blocking robustly; basic polite fetching is in
  scope, but hardened anti-bot evasion is not.
- Automating the manual-resolution cases: `r` only records the slug to a list;
  actually finding those covers stays a human task.
- Pagination / fetching deeper batches of editions when all candidates are
  rejected. `r` goes straight to the needs-manual list by design.
- Switching the underlying source away from Goodreads (e.g. back to OpenLibrary)
  as a fallback within the loop.

## Further Notes

- Edge-uniformity sampling on the existing cover library showed roughly half of
  edges are solid (extension is seamless) and half are busy/photographic (a naive
  per-pixel stretch would streak). The `blur` parameter exists precisely to wash
  out streaks on busy edges; its default is to be tuned live during real cover
  runs rather than fixed now.
- og target is 2:3 (0.667); the library's covers run ~0.61–0.73, so for real
  books the bars are thin. Square-ish audiobook covers produce larger bars but
  read as polished padding rather than the ~33% loss a centre-crop would inflict.
- No issue tracker is configured for this project (no `gh`, no triage
  vocabulary), so this PRD is published as a local markdown file. If a tracker is
  set up later (`/setup-matt-pocock-skills`), this can be promoted to an issue
  with the `ready-for-agent` label.
