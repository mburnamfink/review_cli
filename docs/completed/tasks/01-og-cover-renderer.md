# Slice 1 — Edge-extend og-cover renderer

> Type: AFK
> Source PRD: `docs/prd/improve-covers.md`

## What to build

Replace the og-preview's centre-crop with a fit + edge-extend renderer so the
title, author, and art are never clipped. A new pure function fits the whole
source cover inside the 400×600 og frame (never cropping), then fills the
leftover bars by sampling a thin averaged strip of the corresponding edge and
extending it outward, blurred by a `blur` parameter.

This is wired into `process_cover`'s og branch only — the `cover.jpg` path
(max-800 width, aspect preserved) is unchanged. Because all three cover paths
(`new`, `fetch-cover`, `process-cover`) go through `process_cover`, they all
inherit the new behavior for free.

This slice also establishes the `pytest` suite under `review_cli/tests/`
(greenfield — no existing tests). Add `pytest` as a dev dependency. Tests assert
external behavior only (inputs → outputs / observable invariants), never
internal call structure, and construct small `PIL.Image`s in-test rather than
committing binary fixtures.

## Acceptance criteria

- [ ] New pure renderer `make_og_cover(img, width=400, height=600, blur=<default>) -> Image` exists.
- [ ] Output is exactly 400×600 for any input aspect ratio.
- [ ] No source pixels are discarded: the full source is visible scaled inside the frame; only the bars are synthesized.
- [ ] Narrower-than-2:3 sources get side bars; wider/square sources get top/bottom bars.
- [ ] The `blur` parameter is honored (e.g. `blur=0` yields a hard edge extension).
- [ ] `process_cover` uses `make_og_cover` for og-cover.jpg; `cover.jpg` output is unchanged.
- [ ] `pytest` runs from `review_cli/` and the renderer tests pass.
- [ ] The existing cover contact sheet tool still runs without modification.

## Blocked by

- None - can start immediately
