"""Bulk cover-repair pipeline: find low-res covers, scrape candidates, pick & apply.

This tier is tuned to a specific library's problems and leans on heavier
machinery (a headless browser, a kitty/web picker). It assumes an operator who is
comfortable editing scripts — unlike the bulletproof individual-edit commands.
"""
from __future__ import annotations

import csv
from pathlib import Path

import click
import frontmatter
from rich.table import Table

from .. import covermatch, kitty, staging, webpick
from ..amazon import HOME_URL
from ..browser import BrowserUnavailable, browser_session
from ..config import Config
from ..covers import process_cover
from ..lowres import FlaggedReview, find_low_res
from ..pickstate import DONE, SKIPPED, PickState
from ..ranking import Candidate
from .shared import _author_str, _fuzzy_find, _pick_match, console


# ---------------------------------------------------------------------------
# Candidate sourcing (shared by find-covers and stage-covers)
# ---------------------------------------------------------------------------


def _gather_candidates(
    title: str,
    author: str,
    isbn: str | None = None,
    cap: int = 8,
    page=None,
    refresh: bool = False,
    isbn_only: bool = False,
    settle_ms: int = 2500,
    skip_title_if_isbn: bool = False,
) -> list[Candidate]:
    """Match a book to ranked, downloaded cover candidates (ISBN search first).

    Drives a real browser; may raise :class:`BrowserUnavailable`. Pass ``page`` to
    reuse an open browser session; otherwise a fresh session is opened.
    ``skip_title_if_isbn`` is the fast staging profile (title search only when the
    ISBN search finds nothing). Shared by ``find-covers`` and ``stage-covers``.
    """
    matches = covermatch.gather_matches(
        title, author, isbn, page=page, refresh=refresh, isbn_only=isbn_only,
        settle_ms=settle_ms, skip_title_if_isbn=skip_title_if_isbn,
    )
    return covermatch.download_candidates(matches, cap=cap, refresh=refresh)


def _apply_staged(review_path: str, image_path: Path) -> None:
    """Write cover.jpg + og-cover.jpg into a review from a staged image; update frontmatter."""
    raw = image_path.read_bytes()
    review_dir = Path(review_path).parent
    cover, og_cover = process_cover(raw, review_dir)
    post = frontmatter.load(review_path)
    post.metadata["cover"] = cover
    post.metadata["og_cover"] = og_cover
    Path(review_path).write_text(frontmatter.dumps(post), encoding="utf-8")


# ---------------------------------------------------------------------------
# review find-low-res
# ---------------------------------------------------------------------------


@click.command("find-low-res")
@click.option(
    "--threshold",
    default=700,
    show_default=True,
    help="Flag covers narrower than this many pixels.",
)
@click.argument("slugs", nargs=-1)
def find_low_res_cmd(threshold: int, slugs: tuple[str, ...]):
    """List reviews whose cover.jpg is below the width threshold.

    Pass SLUGS to restrict to specific reviews regardless of width (e.g. to
    replace a cover you dislike even when it is already high-resolution).
    """
    config = Config.load()
    flagged = find_low_res(
        config.content_dir, threshold=threshold, slugs=list(slugs) or None
    )

    if not flagged:
        console.print("[green]No low-resolution covers found.[/]")
        return

    table = Table(show_header=True, header_style="bold", title="Low-resolution covers")
    table.add_column("Title")
    table.add_column("Type", width=10)
    table.add_column("Slug")
    table.add_column("Width", width=7, justify="right")

    for r in flagged:
        width_str = "—" if r.width is None else str(r.width)
        table.add_row(r.title, r.review_type, r.slug, width_str)

    console.print(table)
    console.print(f"[dim]{len(flagged)} review(s) flagged (threshold {threshold}px).[/]")


# ---------------------------------------------------------------------------
# review find-covers
# ---------------------------------------------------------------------------


@click.command("find-covers")
@click.argument("query")
@click.option("--cap", default=8, show_default=True, help="Max candidates to stage.")
@click.option("--refresh", is_flag=True, help="Bypass the scrape cache and re-fetch from Amazon.")
def find_covers_cmd(query: str, cap: int, refresh: bool):
    """Scrape Amazon for alternate covers for one review and stage them (no site writes).

    QUERY is fuzzy-matched against review titles and authors (like `review edit`).
    Candidates (ISBN-13 search + title search, deduped, ranked best-first) and a
    copy of the current cover are written to covers/<slug>/ for `pick-covers` to
    compare. This is `stage-covers` for a single book.
    """
    config = Config.load()
    matches = _fuzzy_find(query, config.content_dir)
    result = _pick_match(matches)
    if not result:
        return

    path, meta = result
    slug = path.parent.name
    title = meta.get("title", slug)
    author = _author_str(meta)
    console.print(f"\n[bold]Finding covers for:[/] {title} — {author or '(unknown author)'}")
    console.print("[dim]Searching Amazon (headless browser)…[/]")

    try:
        ranked = _gather_candidates(title, author, isbn=meta.get("isbn"), cap=cap, refresh=refresh)
    except BrowserUnavailable as e:
        console.print(f"[red]Browser unavailable:[/] {e}")
        return

    if not ranked:
        console.print("[yellow]No candidate covers found.[/]")
        return

    cover = path.parent / "cover.jpg"
    book = staging.write_staging(
        config.covers_dir, slug=slug, title=title, review_type=path.parent.parent.name,
        review_path=path, current_cover=cover if cover.exists() else None, ranked=ranked,
    )

    table = Table(show_header=True, header_style="bold", title=f"Candidates for {slug}")
    table.add_column("#", width=3)
    table.add_column("File")
    table.add_column("Size", width=12)
    table.add_column("Title")
    for i, c in enumerate(book.candidates, 1):
        table.add_row(str(i), c.file, f"{c.width}×{c.height}", c.title)

    console.print(table)
    console.print(
        f"[green]Staged {len(book.candidates)} candidate(s) in[/] "
        f"{staging.book_dir(config.covers_dir, slug)}\n"
        "[dim]Run `review pick-covers` to compare and apply.[/]"
    )


# ---------------------------------------------------------------------------
# review pick-covers
# ---------------------------------------------------------------------------


def _pick_one(
    book: staging.StagedBook,
    idx: int,
    total: int,
    covers_dir: Path,
    state: PickState,
) -> bool:
    """Compare current vs staged candidates for one book; apply a choice. Offline.

    Returns False to quit the loop, True to continue.
    """
    bdir = staging.book_dir(covers_dir, book.slug)
    current_path = bdir / book.current if book.current else None
    cand_paths = [bdir / c.file for c in book.candidates]

    cur = "no cover" if book.current_width is None else f"{book.current_width}px"
    console.print(
        f"\n[bold]({idx}/{total}) {book.title}[/]  "
        f"[dim]{book.slug} · current {cur}[/]"
    )

    if kitty.kitty_available():
        kitty.render(current_path, cand_paths)
    # Legend: candidate 1 is the best (highest-res) pick.
    for i, c in enumerate(book.candidates, 1):
        star = " [green]★[/]" if i == 1 else ""
        console.print(f"  [{i}]{star} {c.width}×{c.height}  [dim]{c.title or c.source}[/]")

    n = len(cand_paths)
    while True:
        console.print(
            f"[bold]1–{n} apply (Enter = 1, the best) · k keep current · s skip · q quit[/] ",
            end="",
        )
        ch = click.getchar()
        console.print(ch if ch.isprintable() else "")
        choice = None
        if ch in ("\r", "\n"):
            choice = 1
        elif ch.isdigit() and 1 <= int(ch) <= n:
            choice = int(ch)
        if choice is not None:
            _apply_staged(book.review_path, cand_paths[choice - 1])
            state.record(book.slug, DONE, chosen=choice)
            c = book.candidates[choice - 1]
            console.print(
                f"[green]Applied candidate {choice}[/] ({c.width}×{c.height}) "
                "→ cover.jpg + og-cover.jpg."
            )
            return True
        if ch == "k":
            state.record(book.slug, DONE, chosen=0)
            console.print("[cyan]Kept the existing cover.[/]")
            return True
        if ch == "s":
            state.record(book.slug, SKIPPED)
            console.print("[cyan]Skipped — offered again next run.[/]")
            return True
        if ch in ("q", "\x03", "\x04"):  # q, Ctrl-C, Ctrl-D
            console.print("[red]Quit.[/]")
            return False
        # any other key: re-prompt


@click.command("pick-covers")
@click.argument("slugs", nargs=-1)
def pick_covers_cmd(slugs: tuple[str, ...]):
    """Compare staged covers against the current one and apply your pick (offline).

    Reads what `stage-covers` (or `find-covers`) left in covers/<slug>/ — no
    network — and walks each book: renders the current cover plus candidates
    inline (kitty), candidate 1 being the highest-resolution pick. Press 1–N or
    Enter to apply, k to keep the current cover, s to skip, q to quit. The chosen
    image is the only thing written into the site. State persists to
    covers/.pick_state.json, so re-running resumes (finished books skipped).
    """
    config = Config.load()
    covers_dir = config.covers_dir
    state = PickState.load(covers_dir / ".pick_state.json")

    want = set(slugs) if slugs else None
    todo: list[staging.StagedBook] = []
    for slug in staging.staged_slugs(covers_dir):
        if want is not None and slug not in want:
            continue
        if state.is_done(slug):
            continue
        book = staging.load_staging(covers_dir, slug)
        if book and not book.is_empty:
            todo.append(book)

    if not todo:
        console.print(
            "[green]Nothing staged to review.[/] "
            "[dim]Run `review stage-covers` first, or all staged books are done "
            f"(delete {covers_dir / '.pick_state.json'} to redo).[/]"
        )
        return

    if not kitty.kitty_available():
        console.print(
            "[yellow]kitty not detected[/] — staged files are listed, not shown inline. "
            f"Open them under {covers_dir}/<slug>/."
        )
    console.print(f"[bold]{len(todo)} staged book(s) to review.[/]")

    for idx, book in enumerate(todo, 1):
        if not _pick_one(book, idx, len(todo), covers_dir, state):
            break

    console.print(f"[dim]State saved to {state.path}[/]")


@click.command("pick-covers-web")
@click.option("--port", default=8765, show_default=True, help="Local server port.")
@click.option("--no-open", is_flag=True, help="Don't auto-open a browser tab.")
@click.argument("slugs", nargs=-1)
def pick_covers_web_cmd(port: int, no_open: bool, slugs: tuple[str, ...]):
    """Pick covers in a browser — terminal-agnostic, one keystroke per book.

    Serves staged covers from covers/<slug>/ on localhost: each candidate and the
    current cover are shown as the site's grid actually renders them — a 2:3 centre
    crop (CSS object-fit:cover) — so you judge how each reads on the main page. In
    the tab press 1–N to apply a candidate, N+1 to keep the current cover, s skip,
    c crop (good but needs a manual crop), r replace (no usable candidate), q quit.
    The chosen image is the only site
    write. State persists to covers/.pick_state.json (resumable: applied/crop/
    replace are settled and not re-offered; skipped books come back). A human +
    machine readable Skip/Crop/Replace summary is rewritten after every keystroke
    to covers/pick_summary.md and pick_summary.json.
    """
    config = Config.load()
    covers_dir = config.covers_dir
    state = PickState.load(covers_dir / ".pick_state.json")

    want = set(slugs) if slugs else None
    todo: list[staging.StagedBook] = []
    for slug in staging.staged_slugs(covers_dir):
        if want is not None and slug not in want:
            continue
        if state.is_settled(slug):
            continue
        book = staging.load_staging(covers_dir, slug)
        if book and not book.is_empty:
            todo.append(book)

    if not todo:
        webpick.write_summary(covers_dir, state)
        console.print(
            "[green]Nothing staged to review.[/] "
            "[dim]Run `review stage-covers` first, or all staged books are settled "
            f"(see {covers_dir / 'pick_summary.md'}).[/]"
        )
        return

    url = f"http://127.0.0.1:{port}/"
    console.print(
        f"[bold]{len(todo)} staged book(s) to review.[/] "
        f"Open [link={url}]{url}[/] — keys: 1–N apply · N+1 keep current · s skip · c crop · r replace · q quit.\n"
        "[dim]Ctrl-C here also stops the server.[/]"
    )
    webpick.run(covers_dir, state, todo, port=port, open_browser=not no_open)
    console.print(
        f"[dim]State → {state.path}; summary → {covers_dir / 'pick_summary.md'}[/]"
    )


# ---------------------------------------------------------------------------
# review stage-covers
# ---------------------------------------------------------------------------


def _load_manual_urls(csv_path: Path) -> dict[str, str]:
    """Map slug → manual_url from the low-res CSV (override column), read-only."""
    overrides: dict[str, str] = {}
    if not csv_path.exists():
        return overrides
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            url = (row.get("manual_url") or "").strip()
            slug = (row.get("slug") or "").strip()
            if url and slug:
                overrides[slug] = url
    return overrides


_STAGE_REPORT_FIELDS = ["slug", "title", "type", "status", "candidates", "best", "message"]


def _stage_one(
    fr: FlaggedReview, page, overrides: dict[str, str], cap: int, covers_dir: Path,
    refresh: bool, settle_ms: int,
) -> dict:
    """Scrape + stage one book's candidates. Writes only to staging. Returns a report row."""
    meta = frontmatter.load(str(fr.path)).metadata
    row = {f: "" for f in _STAGE_REPORT_FIELDS}
    row.update(slug=fr.slug, title=fr.title, type=fr.review_type, candidates="0")

    manual_cand = None
    url = overrides.get(fr.slug)
    if url:
        manual_cand = covermatch.download_candidate(url, refresh=refresh, enforce_cover=False)
        if manual_cand is None:
            row["message"] = f"manual_url failed to download: {url}"

    ranked = _gather_candidates(
        fr.title, _author_str(meta), isbn=meta.get("isbn"),
        cap=cap, page=page, refresh=refresh, isbn_only=False,
        settle_ms=settle_ms, skip_title_if_isbn=True,
    )
    if not ranked and manual_cand is None:
        row.update(status="empty", message="nothing found; leave as-is or set manual_url")
        return row

    book = staging.write_staging(
        covers_dir, slug=fr.slug, title=fr.title, review_type=fr.review_type,
        review_path=fr.path, current_cover=fr.cover_path, ranked=ranked, manual=manual_cand,
    )
    best = book.candidates[0]
    row.update(status="staged", candidates=str(len(book.candidates)),
               best=f"{best.width}×{best.height}")
    return row


@click.command("stage-covers")
@click.option("--threshold", default=700, show_default=True,
              help="Flag covers narrower than this many pixels.")
@click.option("--cap", default=8, show_default=True, help="Max candidates to stage per book.")
@click.option("--limit", default=0, show_default=True, help="Process at most N books (0 = all).")
@click.option("--csv", "csv_path", default="low_res_covers.csv", show_default=True,
              help="CSV read for manual_url overrides (never written).")
@click.option("--report", default="cover_staging_log.csv", show_default=True,
              help="Per-book staging results are written here.")
@click.option("--settle", default=1200, show_default=True,
              help="Per-page settle wait in ms (lower = faster, riskier).")
@click.option("--refresh", is_flag=True, help="Re-stage books already staged; bypass caches.")
@click.argument("slugs", nargs=-1)
def stage_covers_cmd(threshold, cap, limit, csv_path, report, settle, refresh, slugs):
    """Unattended pass: scrape candidate covers for every low-res book into staging.

    Writes NOTHING to the site. For each flagged book it gathers candidates
    (ISBN-13 search + title search, deduped, ranked best-first), downloads the
    masters, and stages them — plus a copy of the current cover — under
    covers/<slug>/ with a manifest. A manual_url from the CSV is staged as the
    first candidate. Then run `review pick-covers` to compare and apply. Already
    staged books are skipped unless --refresh. A per-book log goes to --report.
    """
    config = Config.load()
    flagged = find_low_res(config.content_dir, threshold=threshold, slugs=list(slugs) or None)
    if not flagged:
        console.print("[green]No low-resolution covers found.[/]")
        return

    covers_dir = config.covers_dir
    covers_dir.mkdir(parents=True, exist_ok=True)
    overrides = _load_manual_urls(Path(csv_path))

    if refresh:
        todo = flagged
    else:
        todo = [f for f in flagged if staging.load_staging(covers_dir, f.slug) is None]
    if limit:
        todo = todo[:limit]
    if not todo:
        console.print("[green]Nothing to stage — every flagged book is already staged.[/] "
                      "[dim]Use --refresh to re-stage.[/]")
        return

    console.print(
        f"[bold]Staging {len(todo)} book(s)[/] of {len(flagged)} flagged "
        f"[dim]({len(overrides)} manual override(s))[/]"
    )

    rows: list[dict] = []
    staged = empty = errored = 0
    try:
        with browser_session(warmup_url=HOME_URL) as page:
            for idx, fr in enumerate(todo, 1):
                try:
                    row = _stage_one(fr, page, overrides, cap, covers_dir, refresh, settle)
                except Exception as e:  # one book must never abort the batch
                    row = {f: "" for f in _STAGE_REPORT_FIELDS}
                    row.update(slug=fr.slug, title=fr.title, type=fr.review_type,
                               status="error", candidates="0", message=str(e)[:160])
                rows.append(row)
                _write_report(Path(report), rows, _STAGE_REPORT_FIELDS)  # checkpoint each book
                if row["status"] == "staged":
                    staged += 1
                    tag = f"[green]staged {row['candidates']}[/] best {row['best']}"
                elif row["status"] == "error":
                    errored += 1
                    tag = "[red]error[/]"
                else:
                    empty += 1
                    tag = "[yellow]no candidates[/]"
                console.print(f"  [dim]({idx}/{len(todo)})[/] {fr.slug}: {tag}")
    except BrowserUnavailable as e:
        console.print(f"[red]Browser unavailable:[/] {e}")
        return
    finally:
        _write_report(Path(report), rows, _STAGE_REPORT_FIELDS)

    console.print(
        f"\n[bold]Done.[/] [green]{staged} staged[/], "
        f"[yellow]{empty} no candidates[/], [red]{errored} errors[/]."
    )
    console.print(f"[dim]Log → {report}. Now run `review pick-covers` to compare and apply.[/]")


def _write_report(path: Path, rows: list[dict], fields: list[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
