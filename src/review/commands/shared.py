"""Helpers shared across both command tiers (individual edits and bulk covers)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import frontmatter
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from ..config import Config

console = Console()


def open_editor(path: Path, cfg: Config | None = None) -> None:
    editor = (cfg.editor if cfg else None) or os.environ.get("EDITOR") or os.environ.get("VISUAL")
    if editor:
        # Honor an explicitly configured editor as-is: a terminal editor
        # (vim, nano) needs the foreground tty, so block on it.
        subprocess.run([*editor.split(), str(path)])
    elif sys.platform == "win32":
        os.startfile(str(path))
    else:
        # Default: open the GUI editor and return so the terminal stays free.
        # (Previously "code --wait", which held the shell until the tab closed.)
        subprocess.Popen(["code", str(path)])


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


def _author_str(meta: dict) -> str:
    authors = meta.get("authors", [])
    for a in authors:
        if a.get("role") == "author":
            return f"{a.get('first','')} {a.get('last','')}".strip()
    if authors:
        a = authors[0]
        return f"{a.get('first','')} {a.get('last','')}".strip()
    return ""


def _fmt_authors(authors: list[dict]) -> str:
    return ", ".join(
        f"{a.get('first','')} {a.get('last','')}".strip() for a in authors
    )
