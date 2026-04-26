from __future__ import annotations

import difflib

from rich.console import Console
from rich.prompt import Prompt

from .config import Config

console = Console()


def validate_tags(raw_tags: list[str], config: Config) -> list[str]:
    """
    Interactively validate each tag against the canonical list.
    Returns the final list of tags to use.
    """
    result: list[str] = []
    for tag in raw_tags:
        final = _validate_one(tag, config)
        if final:
            result.append(final)
    return result


def _validate_one(tag: str, config: Config) -> str | None:
    if tag in config.canonical_tags:
        return tag

    close = difflib.get_close_matches(tag, config.canonical_tags, n=3, cutoff=0.6)
    if close:
        console.print(f"\n[yellow]Unknown tag:[/] [bold]{tag}[/bold]")
        console.print(f"  Similar canonical tags: {', '.join(close)}")
    else:
        console.print(f"\n[yellow]Unknown tag:[/] [bold]{tag}[/bold]")

    choice = Prompt.ask(
        "  [bold magenta]A[/]dd to canonical / [bold magenta]U[/]se once / [bold magenta]R[/]eplace / [bold magenta]S[/]kip",
        choices=["a", "u", "r", "s"],
        default="u",
    )

    if choice == "a":
        config.canonical_tags.append(tag)
        config.save()
        console.print(f"  [green]Added[/] '{tag}' to canonical list.")
        return tag
    elif choice == "u":
        return tag
    elif choice == "r":
        replacement = Prompt.ask("  Enter replacement tag")
        return _validate_one(replacement, config)
    else:
        return None
