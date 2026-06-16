# Slice 2 — Low-res detector + `find-low-res` command

> Type: AFK
> Source PRD: `docs/prd/improve-covers.md`

## What to build

Automatically find every review whose `cover.jpg` is below a width threshold, so
the user never hand-maintains a list of low-resolution covers. Rationale for
width-only: `process_cover` caps width at 800 and never upscales, so a
properly-sourced cover is ~800px wide; anything well under is a thumbnail.

A pure core plus a filesystem wrapper, exposed as a new CLI command:

- `is_low_res(width, threshold=700) -> bool` (pure).
- `find_low_res(content_dir, threshold=700) -> list[review]` walks reviews and
  applies `is_low_res` to each `cover.jpg`'s width.
- `review find-low-res [--threshold N] [SLUGS…]` lists the flagged reviews
  (title / slug / cover width). The threshold defaults to 700 and is
  overridable by flag. If explicit slugs are passed, restrict to those reviews
  even if they are high-resolution (so a disliked-but-sharp cover can be
  targeted).

## Acceptance criteria

- [ ] `is_low_res` boundary behavior: 699 → true, 700 → false, 800 → false.
- [ ] `find_low_res` walks a content tree and returns only reviews whose `cover.jpg` width is below threshold.
- [ ] Reviews with no `cover.jpg` are handled gracefully (treated as needing attention or skipped — pick one and test it).
- [ ] `review find-low-res` prints the flagged reviews; `--threshold` overrides the default.
- [ ] Passing explicit slugs restricts output to those reviews regardless of width.
- [ ] Unit tests cover `is_low_res` boundaries and `find_low_res` against a small fixture tree of review dirs with known cover widths (generated in-test).

## Blocked by

- None - can start immediately
