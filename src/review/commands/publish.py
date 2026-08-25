"""``review publish`` — commit and push the site's pending review changes.

The site repo is deployed by Cloudflare Pages on every push to ``main``, so
publishing is simply: validate, then ``git add``/``commit``/``push`` the review
files. This lives apart from the content-edit commands because it is a
site/deploy concern, not a per-review edit.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import click
from pydantic import ValidationError

from ..config import Config
from ..models import parse_review
from .shared import _author_str, _iter_reviews, console


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
    )


def _repo_root(start: Path) -> Path:
    """Git top-level containing ``start`` (the reviews content dir)."""
    proc = _git(start, "rev-parse", "--show-toplevel")
    if proc.returncode != 0:
        raise click.ClickException(
            f"{start} is not inside a git repository:\n{proc.stderr.strip()}"
        )
    return Path(proc.stdout.strip())


def _validate_all(content_dir: Path) -> list[tuple[Path, str]]:
    errors: list[tuple[Path, str]] = []
    for path, meta in _iter_reviews(content_dir):
        try:
            parse_review(meta)
        except ValidationError as e:
            errors.append((path, str(e)))
        except Exception as e:  # noqa: BLE001 — surface any parse failure to the user
            errors.append((path, f"Parse error: {e}"))
    return errors


def _changed_review_slugs(porcelain: str, reviews_rel: Path) -> list[str]:
    """``<type>/<slug>`` for each review touched in ``git status`` output."""
    slugs: set[str] = set()
    for line in porcelain.splitlines():
        if not line.strip():
            continue
        # Porcelain: 'XY <path>'; renames use 'XY old -> new'.
        path_part = line[3:].split(" -> ")[-1].strip().strip('"')
        try:
            rel = Path(path_part).relative_to(reviews_rel)
        except ValueError:
            continue
        parts = rel.parts
        if len(parts) >= 2:
            slugs.add(f"{parts[0]}/{parts[1]}")
    return sorted(slugs)


def _commit_message(content_dir: Path, slugs: list[str]) -> str:
    if len(slugs) == 1:
        index = content_dir / slugs[0] / "index.md"
        if index.exists():
            import frontmatter

            meta = frontmatter.load(str(index)).metadata
            title = meta.get("title")
            author = _author_str(meta)
            if title:
                return f"Add review: {title}" + (f" by {author}" if author else "")
        return f"Publish review: {slugs[0]}"
    return f"Publish {len(slugs)} review updates"


@click.command()
@click.option("--yes", "-y", is_flag=True, help="Skip the confirmation prompt.")
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would be committed and pushed, then stop.",
)
def publish(yes: bool, dry_run: bool):
    """Validate, commit, and push all pending review changes.

    Commits every uncommitted file under the reviews content directory and
    pushes to the upstream branch. The push is the deploy: Cloudflare Pages
    rebuilds the live site on every push to ``main``.
    """
    config = Config.load()
    content_dir = config.content_dir
    repo = _repo_root(content_dir)
    reviews_rel = content_dir.relative_to(repo)

    # 1. Validate before touching git — never publish a review that fails schema.
    errors = _validate_all(content_dir)
    if errors:
        for path, msg in errors:
            console.print(f"[red]FAIL[/] {path}\n  {msg}\n")
        raise click.ClickException(
            f"{len(errors)} review(s) failed validation; nothing published."
        )

    # 2. What's pending under the reviews dir?
    status = _git(repo, "status", "--porcelain", "--", str(reviews_rel))
    if status.returncode != 0:
        raise click.ClickException(f"git status failed:\n{status.stderr.strip()}")
    if not status.stdout.strip():
        console.print("[yellow]No pending review changes to publish.[/]")
        return

    slugs = _changed_review_slugs(status.stdout, reviews_rel)
    branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    message = _commit_message(content_dir, slugs)

    console.print("[bold]Changes to publish:[/]")
    for line in status.stdout.splitlines():
        console.print(f"  {line}")
    console.print(f"\n[bold]Commit:[/] {message}")
    console.print(f"[bold]Push:[/]   {branch} → deploys to burrowedbooks.com\n")

    if dry_run:
        console.print("[dim]--dry-run: stopping before commit.[/]")
        return

    if not yes and not click.confirm("Publish these changes?", default=True):
        console.print("[yellow]Aborted; nothing published.[/]")
        return

    # 3. add → commit → push.
    add = _git(repo, "add", "--", str(reviews_rel))
    if add.returncode != 0:
        raise click.ClickException(f"git add failed:\n{add.stderr.strip()}")

    commit = _git(repo, "commit", "-m", message)
    if commit.returncode != 0:
        raise click.ClickException(f"git commit failed:\n{commit.stderr.strip()}")
    console.print(f"[green]Committed[/] {message}")

    push = _git(repo, "push")
    if push.returncode != 0:
        raise click.ClickException(
            "Committed locally, but git push failed:\n"
            f"{(push.stderr or push.stdout).strip()}\n"
            "Fix the issue and run `git push` to deploy."
        )
    console.print("[green]Pushed.[/] Cloudflare Pages will build and deploy shortly.")
