from __future__ import annotations

import os
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Optional

import click
import frontmatter
import yaml
from pydantic import ValidationError
from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table

from .config import Config
from .covers import process_cover
from .models import REVIEW_MODELS, parse_review
from .openlibrary import fetch_cover_bytes, search
from .slug import make_slug
from .tags import validate_tags

console = Console()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def open_editor(path: Path, cfg: Config | None = None) -> None:
    editor = (cfg.editor if cfg else None) or os.environ.get("EDITOR") or os.environ.get("VISUAL")
    if editor:
        subprocess.run([*editor.split(), str(path)])
    elif sys.platform == "win32":
        os.startfile(str(path))
    else:
        subprocess.run(["code", "--wait", str(path)])


def _iter_reviews(content_dir: Path):
    """Yield (path, frontmatter_metadata) for all review index.md files."""
    for md in sorted(content_dir.rglob("*/index.md")):
        try:
            post = frontmatter.load(str(md))
        except Exception as e:
            raise RuntimeError(f"Failed to parse {md}") from e
        yield md, post.metadata


def _fuzzy_find(query: str, content_dir: Path) -> list[tuple[Path, dict]]:
    """Return reviews whose title or author matches query (case-insensitive)."""
    q = query.lower()
    matches = []
    for path, meta in _iter_reviews(content_dir):
        title = meta.get("title", "").lower()
        authors = " ".join(
            f"{a.get('first','')} {a.get('last','')}".strip()
            for a in meta.get("authors", [])
        ).lower()
        if q in title or q in authors:
            matches.append((path, meta))
    return matches


def _pick_match(matches: list[tuple[Path, dict]]) -> tuple[Path, dict] | None:
    if not matches:
        console.print("[red]No matching reviews found.[/]")
        return None
    if len(matches) == 1:
        return matches[0]

    table = Table(show_header=True, header_style="bold")
    table.add_column("#", width=3)
    table.add_column("Title")
    table.add_column("Author(s)")
    table.add_column("Type")

    for i, (_, meta) in enumerate(matches, 1):
        authors = ", ".join(
            f"{a.get('first','')} {a.get('last','')}".strip()
            for a in meta.get("authors", [])
            if a.get("role") == "author"
        )
        table.add_row(str(i), meta.get("title", ""), authors, meta.get("type", ""))

    console.print(table)
    choice = Prompt.ask("Pick a number", default="1")
    try:
        idx = int(choice) - 1
        return matches[idx]
    except (ValueError, IndexError):
        console.print("[red]Invalid choice.[/]")
        return None


def _prompt_authors() -> list[dict]:
    authors = []
    while True:
        first = Prompt.ask("  Author first name")
        last = Prompt.ask("  Author last name")
        role = Prompt.ask("  Role", choices=["author", "editor", "contributor"], default="author")
        authors.append({"first": first, "last": last, "role": role})
        if not Confirm.ask("  Add another author?", default=False):
            break
    return authors


def _prompt_rating() -> float | None:
    while True:
        raw = Prompt.ask("Rating (1–5 in 0.5 steps, or blank for DNF)", default="")
        if raw == "":
            return None
        try:
            v = float(raw)
            if 1.0 <= v <= 5.0 and (v * 2) == int(v * 2):
                return v
        except ValueError:
            pass
        console.print("[yellow]Enter a value like 3.5, 4, 5 — or leave blank for DNF.[/]")


def _prompt_tags(config: Config) -> list[str]:
    raw = Prompt.ask("Tags (comma-separated)", default="")
    raw_tags = [t.strip() for t in raw.split(",") if t.strip()]
    return validate_tags(raw_tags, config)


def _prompt_read_record() -> dict:
    today = date.today()
    year_str = Prompt.ask("Year read", default=str(today.year))
    year = int(year_str)

    started = Prompt.ask("Date started (YYYY-MM-DD, or blank)", default="")
    finished = Prompt.ask("Date finished (YYYY-MM-DD, or blank)", default="")
    dnf = Confirm.ask("Did not finish (DNF)?", default=False)

    record: dict = {"year": year}
    if started:
        record["date_started"] = started
    if finished:
        record["date_finished"] = finished
    if dnf:
        record["dnf"] = True
    return record


def _build_frontmatter(
    title: str,
    authors: list[dict],
    review_type: str,
    isbn: str | None,
    publication_year: int | None,
    publisher: str | None,
    rating: float | None,
    tags: list[str],
    read_record: dict,
    extra: dict,
    cover: str | None,
    og_cover: str | None,
) -> dict:
    fm: dict = {
        "title": title,
        "authors": authors,
        "type": review_type,
    }
    if isbn:
        fm["isbn"] = isbn
    if publication_year:
        fm["publication_year"] = publication_year
    if publisher:
        fm["publisher"] = publisher
    fm["rating"] = rating
    fm["date_reviewed"] = date.today().isoformat()
    fm["reads"] = [read_record]
    fm["tags"] = tags
    if cover:
        fm["cover"] = cover
    if og_cover:
        fm["og_cover"] = og_cover
    fm.update(extra)
    return fm


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.group(context_settings={"max_content_width": 120, "terminal_width": 120})
def cli():
    """Book review manager."""


# ---------------------------------------------------------------------------
# review new
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("query", nargs=-1)
@click.option("--manual", is_flag=True, help="Skip Open Library search.")
@click.option(
    "--type", "review_type",
    type=click.Choice(["book", "audiobook", "rpg", "other"]),
    default=None,
)
def new(query: tuple[str, ...], manual: bool, review_type: str | None):
    """Create a new review. Optionally provide a search QUERY."""
    config = Config.load()
    config.content_dir.mkdir(parents=True, exist_ok=True)

    ol_result: dict | None = None
    query_str = " ".join(query)

    if not manual and query_str:
        console.print(f"\n[bold]Searching Open Library for:[/] {query_str}\n")
        results = search(query_str)
        if results:
            _display_ol_results(results)
            pick = Prompt.ask(
                "Pick a result (1–6), [m]anual entry, or [s]kip",
                default="1",
            )
            if pick.lower() == "s":
                return
            if pick.lower() != "m":
                try:
                    ol_result = results[int(pick) - 1]
                except (ValueError, IndexError):
                    console.print("[yellow]Invalid choice, falling back to manual.[/]")
        else:
            console.print("[yellow]No results found. Falling back to manual entry.[/]")

    # --- Gather data ---
    console.print()

    ol_page_count: int | None = None
    if ol_result:
        title = Prompt.ask("Title", default=ol_result["title"])
        console.print(f"  Authors from Open Library: {_fmt_authors(ol_result['authors'])}")
        use_ol_authors = Confirm.ask("  Use these authors?", default=True)
        if use_ol_authors:
            authors = ol_result["authors"]
        else:
            authors = _prompt_authors()
        isbn = Prompt.ask("ISBN", default=ol_result.get("isbn") or "").strip() or None
        year_default = str(ol_result["year"]) if ol_result.get("year") else ""
        year_str = Prompt.ask("Publication year", default=year_default).strip()
        publication_year = int(year_str) if year_str else None
        ol_page_count = ol_result.get("page_count")
    else:
        title = Prompt.ask("Title")
        authors = _prompt_authors()
        isbn = Prompt.ask("ISBN (optional)", default="").strip() or None
        year_str = Prompt.ask("Publication year (optional)", default="").strip()
        publication_year = int(year_str) if year_str else None

    publisher = Prompt.ask("Publisher (optional)", default="").strip() or None

    if not review_type:
        review_type = Prompt.ask(
            "Type", choices=["book", "audiobook", "rpg", "other"], default="book"
        )

    extra: dict = {}
    if review_type == "book":
        page_default = str(ol_page_count) if ol_page_count else ""
        pages_str = Prompt.ask("Page count (optional)", default=page_default).strip()
        if pages_str:
            extra["page_count"] = int(pages_str)
    elif review_type == "audiobook":
        console.print("\n[bold]Narrator:[/]")
        narrator_first = Prompt.ask("  First name")
        narrator_last = Prompt.ask("  Last name")
        extra["narrator"] = {"first": narrator_first, "last": narrator_last, "role": "narrator"}
        runtime = Prompt.ask("  Runtime (HH:MM or decimal hours, optional)", default="").strip()
        if runtime:
            if ':' in runtime:
                h, m = runtime.split(':', 1)
                extra["runtime_hours"] = int(h) + int(m) / 60
            else:
                extra["runtime_hours"] = float(runtime)
        extra["abridged"] = Confirm.ask("  Abridged?", default=False)
        # narrator goes into authors list for slug generation; copy to avoid
        # yaml anchor/alias generation from shared object references
        authors = authors + [dict(extra["narrator"])]
    elif review_type == "rpg":
        extra["system"] = Prompt.ask("System (optional)", default="").strip() or None
    elif review_type == "other":
        extra["medium"] = Prompt.ask("Medium (optional)", default="").strip() or None

    rating = _prompt_rating()
    tags = _prompt_tags(config)
    read_record = _prompt_read_record()

    # --- Cover art ---
    cover: str | None = None
    og_cover: str | None = None
    slug = make_slug(title, authors, review_type)
    review_dir = config.content_dir / review_type / slug
    review_dir.mkdir(parents=True, exist_ok=True)

    if isbn:
        console.print("\n[dim]Downloading cover art…[/]")
        cover_i = ol_result.get("cover_i") if ol_result else None
        raw = fetch_cover_bytes(isbn, cover_i=cover_i)
        if raw:
            cover, og_cover = process_cover(raw, review_dir)
            console.print("[green]Cover saved.[/]")
        else:
            console.print("[yellow]No cover found.[/]")

    # --- Write index.md ---
    fm = _build_frontmatter(
        title=title,
        authors=authors,
        review_type=review_type,
        isbn=isbn,
        publication_year=publication_year,
        publisher=publisher,
        rating=rating,
        tags=tags,
        read_record=read_record,
        extra=extra,
        cover=cover,
        og_cover=og_cover,
    )

    md_path = review_dir / "index.md"
    post = frontmatter.Post("", **fm)
    md_path.write_text(frontmatter.dumps(post), encoding="utf-8")

    console.print(f"\n[green]Created:[/] {md_path}")
    console.print("[dim]Opening editor…[/]")
    open_editor(md_path, config)


def _display_ol_results(results: list[dict]) -> None:
    table = Table(show_header=True, header_style="bold")
    table.add_column("#", width=3)
    table.add_column("Title")
    table.add_column("Author(s)")
    table.add_column("Year", width=6)
    table.add_column("ISBN", width=14)

    for i, r in enumerate(results, 1):
        authors = _fmt_authors(r["authors"])
        table.add_row(
            str(i),
            r["title"],
            authors,
            str(r["year"] or ""),
            r.get("isbn") or "",
        )

    console.print(table)


def _fmt_authors(authors: list[dict]) -> str:
    return ", ".join(
        f"{a.get('first','')} {a.get('last','')}".strip() for a in authors
    )


# ---------------------------------------------------------------------------
# review validate
# ---------------------------------------------------------------------------


@cli.command()
def validate():
    """Validate all review files against the schema."""
    config = Config.load()
    errors: list[tuple[Path, str]] = []
    ok = 0

    for path, meta in _iter_reviews(config.content_dir):
        try:
            parse_review(meta)
            ok += 1
        except ValidationError as e:
            errors.append((path, str(e)))
        except Exception as e:
            errors.append((path, f"Parse error: {e}"))

    if errors:
        for path, msg in errors:
            console.print(f"[red]FAIL[/] {path}\n  {msg}\n")
        console.print(f"[red]{len(errors)} error(s)[/], {ok} ok")
    else:
        console.print(f"[green]All {ok} reviews valid.[/]")


# ---------------------------------------------------------------------------
# review list
# ---------------------------------------------------------------------------


@cli.command("list")
@click.option("--type", "review_type", default=None, help="Filter by type.")
@click.option("--tag", default=None, help="Filter by tag.")
@click.option("--page", default=1, show_default=True, help="Page number.")
@click.option("--per-page", default=40, show_default=True)
def list_reviews(review_type: str | None, tag: str | None, page: int, per_page: int):
    """List reviews as a table."""
    config = Config.load()

    rows = []
    for _, meta in _iter_reviews(config.content_dir):
        if review_type and meta.get("type") != review_type:
            continue
        if tag and tag not in meta.get("tags", []):
            continue
        rows.append(meta)

    # Sort by most-recent read year descending, then title
    def sort_key(m: dict):
        reads = m.get("reads") or []
        max_year = max((r.get("year", 0) for r in reads), default=0)
        return (-max_year, m.get("title", "").lower())

    rows.sort(key=sort_key)

    total = len(rows)
    start = (page - 1) * per_page
    page_rows = rows[start : start + per_page]

    table = Table(show_header=True, header_style="bold", title=f"Reviews (page {page})")
    table.add_column("Title")
    table.add_column("Author(s)")
    table.add_column("Type", width=10)
    table.add_column("Rating", width=7)
    table.add_column("Year read", width=10)
    table.add_column("Tags")

    for meta in page_rows:
        author_names = [
            f"{a.get('last','')}".strip()
            for a in meta.get("authors", [])
            if a.get("role") == "author"
        ]
        if len(author_names) > 3:
            authors = ", ".join(author_names[:3]) + " et al."
        else:
            authors = ", ".join(author_names)
        reads = meta.get("reads") or []
        years = sorted({str(r.get("year", "")) for r in reads if r.get("year")}, reverse=True)
        rating = meta.get("rating")
        rating_str = _stars(rating) if rating else "DNF"
        table.add_row(
            meta.get("title", ""),
            authors,
            meta.get("type", ""),
            rating_str,
            ", ".join(years),
            ", ".join(meta.get("tags", [])[:3]),
        )

    console.print(table)
    console.print(
        f"[dim]Showing {start+1}–{min(start+per_page, total)} of {total}. "
        f"Use --page to paginate.[/]"
    )


def _stars(rating: float) -> str:
    full = int(rating)
    half = rating - full >= 0.5
    return "★" * full + ("½" if half else "")


# ---------------------------------------------------------------------------
# review edit
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("query")
def edit(query: str):
    """Fuzzy-find an existing review and open it in $EDITOR."""
    config = Config.load()
    matches = _fuzzy_find(query, config.content_dir)
    result = _pick_match(matches)
    if result:
        path, _ = result
        open_editor(path, config)


# ---------------------------------------------------------------------------
# review link
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("query")
def link(query: str):
    """Fuzzy-find a review and print a markdown link for it."""
    config = Config.load()
    matches = _fuzzy_find(query, config.content_dir)
    result = _pick_match(matches)
    if result:
        path, meta = result
        # path is .../content_dir/<type>/<slug>/index.md
        slug = path.parent.name
        review_type = path.parent.parent.name
        title = meta.get("title", slug)
        url = f"/{review_type}/{slug}"
        console.print(f"[*{title}*]({url})")


# ---------------------------------------------------------------------------
# review bsky
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("query")
@click.argument("url")
def bsky(query: str, url: str):
    """Set the Bluesky post URL on a review (enables discussion thread on the site)."""
    config = Config.load()
    matches = _fuzzy_find(query, config.content_dir)
    result = _pick_match(matches)
    if not result:
        return

    path, meta = result
    post = frontmatter.load(str(path))
    post.metadata["bsky_post"] = url
    path.write_text(frontmatter.dumps(post), encoding="utf-8")
    console.print(f"[green]Updated:[/] {meta.get('title', path.parent.name)}")
    console.print(f"[dim]{url}[/]")


# ---------------------------------------------------------------------------
# review add-read
# ---------------------------------------------------------------------------


@cli.command("add-read")
@click.argument("query")
def add_read(query: str):
    """Append a new read record to an existing review (for re-reads)."""
    config = Config.load()
    matches = _fuzzy_find(query, config.content_dir)
    result = _pick_match(matches)
    if not result:
        return

    path, meta = result
    console.print(f"\n[bold]Adding read record to:[/] {meta.get('title', '')}")

    record = _prompt_read_record()

    post = frontmatter.load(str(path))
    reads = post.metadata.get("reads", []) or []
    reads.append(record)
    post.metadata["reads"] = reads

    path.write_text(frontmatter.dumps(post), encoding="utf-8")
    console.print(f"[green]Updated:[/] {path}")


# ---------------------------------------------------------------------------
# review fetch-cover
# ---------------------------------------------------------------------------


@cli.command("fetch-cover")
@click.argument("query")
@click.option("--isbn", default=None, help="ISBN to use (skips prompt).")
def fetch_cover(query: str, isbn: str | None):
    """Fetch and save cover art for an existing review."""
    config = Config.load()
    matches = _fuzzy_find(query, config.content_dir)
    result = _pick_match(matches)
    if not result:
        return

    path, meta = result
    console.print(f"\n[bold]Fetching cover for:[/] {meta.get('title', '')}")

    if not isbn:
        isbn = Prompt.ask("ISBN", default=meta.get("isbn") or "").strip() or None

    if not isbn:
        console.print("[red]No ISBN provided.[/]")
        return

    console.print("[dim]Downloading cover art…[/]")
    raw = fetch_cover_bytes(isbn)
    if not raw:
        console.print("[yellow]No cover found for that ISBN.[/]")
        return

    review_dir = path.parent
    cover, og_cover = process_cover(raw, review_dir)
    console.print("[green]Cover saved.[/]")

    post = frontmatter.load(str(path))
    post.metadata["isbn"] = isbn
    post.metadata["cover"] = cover
    post.metadata["og_cover"] = og_cover
    path.write_text(frontmatter.dumps(post), encoding="utf-8")
    console.print(f"[green]Updated:[/] {path}")


# ---------------------------------------------------------------------------
# review process-cover
# ---------------------------------------------------------------------------


@cli.command("process-cover")
@click.argument("query")
@click.argument("image", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def process_cover_cmd(query: str, image: Path):
    """Process a local image file as the cover for an existing review.

    Resizes it to cover.jpg and generates og-cover.jpg, then updates the frontmatter.
    """
    config = Config.load()
    matches = _fuzzy_find(query, config.content_dir)
    result = _pick_match(matches)
    if not result:
        return

    path, meta = result
    console.print(f"\n[bold]Processing cover for:[/] {meta.get('title', '')}")
    console.print(f"[dim]Source: {image}[/]")

    raw = image.read_bytes()
    review_dir = path.parent
    cover, og_cover = process_cover(raw, review_dir)

    post = frontmatter.load(str(path))
    post.metadata["cover"] = cover
    post.metadata["og_cover"] = og_cover
    path.write_text(frontmatter.dumps(post), encoding="utf-8")

    console.print("[green]cover.jpg and og-cover.jpg saved.[/]")
    console.print(f"[green]Updated:[/] {path}")


# ---------------------------------------------------------------------------
# review init
# ---------------------------------------------------------------------------


@cli.command("init")
def init():
    """Set up review for the first time (creates ~/.review/config.toml)."""
    from .config import CONFIG_PATH

    existing = Config.load()
    console.print("\n[bold]review init[/] — first-time setup\n")

    default_dir = str(existing.content_dir)
    raw = Prompt.ask("Where should review files be stored?", default=default_dir).strip()
    content_dir = Path(raw).expanduser().resolve()

    content_dir.mkdir(parents=True, exist_ok=True)
    console.print(f"  [green]✓[/] Content directory: {content_dir}")

    config = Config(content_dir=content_dir, canonical_tags=existing.canonical_tags)
    config.save()
    console.print(f"  [green]✓[/] Config written to: {CONFIG_PATH}")
    console.print("\nRun [bold]review new[/] to create your first review.")
