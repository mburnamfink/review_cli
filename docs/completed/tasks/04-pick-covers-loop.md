# Slice 4 — `pick-covers` interactive loop + kitty renderer

> Type: AFK (requires manual visual verification in a kitty terminal)
> Source PRD: `docs/prd/improve-covers.md`

## What to build

The orchestration that ties the feature together: review flagged books one at a
time in a single command, with the current cover and all candidates rendered
inline in a kitty terminal, picking the best with a single keystroke and
applying it immediately.

`review pick-covers [--threshold N] [SLUGS…]` composes detector (Slice 2) →
scraper + ranker (Slice 3) → kitty inline render → keypress → apply (via
`process_cover`, Slice 1). Per-book keys:

- `1`–`N` — pick that candidate and immediately apply it: regenerate cover.jpg +
  og-cover.jpg and update frontmatter (`cover`, `og_cover`, and ISBN if known).
- `r` — reject all candidates; append the slug to a "needs manual resolution"
  list.
- `s` — skip this book for now (revisit on a later pass).
- `q` — quit the loop.

A small JSON pick-state store at `covers/.pick_state.json` records, per book:
candidate hashes already shown, the chosen candidate, and status
(`done` / `rejected` / `skipped` / `needs-manual`). Re-running the command reads
the store and resumes — re-running acts as the "second pass" over rejected /
skipped books and does not re-process finished ones.

Rendering uses kitty's graphics protocol; the target terminal is kitty. The
loop and renderer are validated by manual runs, not unit tests (terminal
graphics + network orchestration). The `blur` default for the og renderer is
tuned live during these runs.

Source note: candidates come from Amazon via the headless browser (see Slice 3);
the loop opens one warmed `browser_session` and reuses it across books.

## Acceptance criteria

- [x] `review pick-covers [--threshold N] [--cap N] [SLUGS…]` walks flagged books one at a time, rendering the current cover + candidates inline in kitty (`kitty.render` → `kitten icat`); falls back to listing paths when kitty is absent.
- [x] `1`–`N` picks a candidate, applies it via `process_cover` (cover.jpg, og-cover.jpg, frontmatter `cover`/`og_cover` all updated), and advances. (`_apply_cover`, unit-tested.)
- [x] `r` records the slug to the needs-manual list and advances.
- [x] `s` skips without resolving; `q` (or Ctrl-C/D) quits the loop.
- [x] State persists to `covers/.pick_state.json` (`PickState`, unit-tested); re-running resumes and does not re-process `done` books.
- [x] Re-running revisits `needs-manual` / `skipped` books (the second pass).
- [ ] **MANUAL (user):** verify end-to-end in a kitty terminal — pick a cover and confirm it appears applied on disk and in frontmatter. (Everything up to the keypress is proven via a non-tty smoke run: detect → browser → gather → stage → contact-sheet render all execute; only `click.getchar()` + inline icat need a real tty.)

## Blocked by

- Slice 1 (og-cover renderer) — apply path uses `process_cover`
- Slice 2 (low-res detector) — to find flagged books
- Slice 3 (candidate sourcing) — to produce candidates
