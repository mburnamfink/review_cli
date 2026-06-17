"""Front-matter–preserving body editing for the Task 3 passes.

These passes only touch the markdown *body*. Re-serialising via the
`frontmatter` library would rewrite the YAML block and produce noisy diffs
across ~1800 files, so we split the raw bytes and leave the front matter
verbatim.
"""
from __future__ import annotations

import re
from pathlib import Path

# Closing front-matter fence: a line that is exactly `---`, whether followed by
# a body (`\n`) or sitting at end-of-file (no trailing newline, e.g. empty-body
# reviews). Missing the EOF case silently mis-splits those files.
_CLOSE_FENCE = re.compile(r"\n---[ \t]*(?:\n|\Z)")


def split_frontmatter(text: str) -> tuple[str, str]:
    """Return (front_matter_block, body). The block includes both `---` fences.

    If the file has no front matter, the block is "" and body is the whole text.
    """
    if text.startswith("---\n"):
        m = _CLOSE_FENCE.search(text, 3)
        if m:
            return text[: m.end()], text[m.end() :]
    return "", text


def read_body(md: Path) -> tuple[str, str]:
    """Return (front_matter_block, body) for a review file."""
    return split_frontmatter(md.read_text(encoding="utf-8"))


def write_body(md: Path, fm: str, body: str) -> None:
    md.write_text(fm + body, encoding="utf-8")
