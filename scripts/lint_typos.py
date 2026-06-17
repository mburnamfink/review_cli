#!/usr/bin/env python3
"""Assistive typo / grammar linter for review bodies (Task 3, sub-task 1).

Two passes, both *assistive* — nothing is auto-applied. The output is a queue of
`{type}/{slug}/index.md:line: suggestion` lines you accept or reject by hand.

  1. codespell — cheap misspelling / homonym first pass over each review body.
                 Always runs (via `uvx codespell`, no install needed).
  2. LLM pass  — per-file grammar / dropped-word / missing-preposition pass that
                 codespell can't catch. Opt-in via --llm; needs the `anthropic`
                 extra and an ANTHROPIC_API_KEY.

Front matter is excluded from both passes — only the prose body is checked, so
author names, tags, and titles never show up as false positives.

Run from review-cli/:
    uv run python scripts/lint_typos.py                    # codespell only
    uv run python scripts/lint_typos.py --limit 50         # first 50 reviews
    uv run --extra llm python scripts/lint_typos.py --llm  # + LLM grammar pass

Writes scripts/typo_report.txt (gitignored working queue).
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import frontmatter

from review.config import Config

REPORT_OUT = Path(__file__).parent / "typo_report.txt"

# codespell over-eagerly "corrects" words that are correct in book reviews.
# Add lowercase words here (comma-joined into --ignore-words-list).
CODESPELL_IGNORE = [
    "ans",  # common in fantasy/SF names; codespell -> "and"/"answer"
    "ambien",  # the drug; codespell -> "ambient"
    "protestors",  # valid variant of "protesters"
    # Real English words codespell flags as "possible typos":
    "covert", "empress", "rouge", "somme",
    # Author / character / place names recurring across reviews:
    "shepard", "shapin", "brin", "vor", "sade", "leary", "bui",
]

# Model for the optional LLM grammar pass. See the claude-api skill: default to
# the latest Opus and let structured outputs guarantee parseable findings.
LLM_MODEL = "claude-opus-4-8"

LLM_SYSTEM = """\
You are a meticulous copy-editor for short book-review prose. Find only \
*objective* errors a spell-checker misses: dropped words, missing prepositions \
or articles, subject/verb disagreement, wrong-word homonyms (their/there, \
its/it's, lead/led), and dropped -s/-ed endings.

Do NOT report style, tone, word choice, Oxford commas, or anything subjective. \
When the prose is clean, return an empty list. For each error, quote the exact \
span from the text verbatim (long enough to locate it) and give the corrected \
span."""


@dataclass
class Finding:
    rel: str  # {type}/{slug}/index.md
    line: int  # 1-based line in the original file
    message: str  # human-readable suggestion
    source: str  # "codespell" | "llm"


def body_start_line(raw: str) -> int:
    """1-based line number of the first body line (after the YAML front matter)."""
    lines = raw.splitlines()
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                return i + 2  # line after the closing ---
    return 1


def iter_reviews(content_dir: Path, limit: int | None):
    mds = sorted(content_dir.rglob("*/index.md"))
    if limit is not None:
        mds = mds[:limit]
    for md in mds:
        yield md, md.parent.relative_to(content_dir).as_posix()


# --------------------------------------------------------------------------- #
# Pass 1 — codespell
# --------------------------------------------------------------------------- #
def codespell_pass(files: list[Path], body_starts: dict[Path, int]) -> list[Finding]:
    cmd = ["uvx", "codespell", "--disable-colors"]
    if CODESPELL_IGNORE:
        cmd += ["--ignore-words-list", ",".join(CODESPELL_IGNORE)]
    cmd += [str(f) for f in files]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        print("  ! uvx not found — skipping codespell pass.", file=sys.stderr)
        return []

    content_dir = Config.load().content_dir
    # codespell line: "path:line: word ==> correction"
    pat = re.compile(r"^(?P<path>.+?):(?P<line>\d+): (?P<body>.+ ==> .+)$")
    findings: list[Finding] = []
    for raw_line in proc.stdout.splitlines():
        m = pat.match(raw_line)
        if not m:
            continue
        path = Path(m.group("path"))
        line = int(m.group("line"))
        if line < body_starts.get(path, 1):
            continue  # hit landed in the front matter — ignore
        rel = path.parent.relative_to(content_dir).as_posix()
        findings.append(Finding(rel, line, m.group("body").strip(), "codespell"))
    return findings


# --------------------------------------------------------------------------- #
# Pass 2 — LLM grammar (opt-in)
# --------------------------------------------------------------------------- #
def llm_pass(reviews: list[tuple[Path, str]]) -> list[Finding]:
    try:
        import anthropic
    except ImportError:
        print(
            "  ! --llm needs the anthropic SDK. Re-run with:\n"
            "      uv run --extra llm python scripts/lint_typos.py --llm",
            file=sys.stderr,
        )
        return []

    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        print(
            "  ! --llm needs ANTHROPIC_API_KEY (or ANTHROPIC_AUTH_TOKEN) set — "
            "skipping LLM pass.",
            file=sys.stderr,
        )
        return []

    from pydantic import BaseModel

    class Issue(BaseModel):
        quote: str
        correction: str
        kind: str

    class Result(BaseModel):
        findings: list[Issue]

    client = anthropic.Anthropic()
    content_dir = Config.load().content_dir
    findings: list[Finding] = []

    for n, (md, post) in enumerate(reviews, 1):
        body = post  # already the body text
        if not body.strip():
            continue
        rel = md.parent.relative_to(content_dir).as_posix()
        print(f"  llm {n}/{len(reviews)}: {rel}", file=sys.stderr)
        try:
            resp = client.messages.parse(
                model=LLM_MODEL,
                max_tokens=4096,
                system=LLM_SYSTEM,
                output_config={"effort": "low"},
                messages=[{"role": "user", "content": body}],
                output_format=Result,
            )
        except anthropic.AuthenticationError:
            print(
                "  ! No valid ANTHROPIC_API_KEY — stopping LLM pass.", file=sys.stderr
            )
            break
        except anthropic.APIError as e:
            print(f"  ! API error on {rel}: {e} — skipping.", file=sys.stderr)
            continue

        result = resp.parsed_output
        if result is None:
            continue
        body_lines = body.splitlines()
        start = body_start_line_from_post(md)
        for issue in result.findings:
            line = locate_quote(issue.quote, body_lines, start)
            msg = f'{issue.quote!r} ==> {issue.correction!r} ({issue.kind})'
            findings.append(Finding(rel, line, msg, "llm"))
    return findings


def body_start_line_from_post(md: Path) -> int:
    return body_start_line(md.read_text(encoding="utf-8"))


def locate_quote(quote: str, body_lines: list[str], start: int) -> int:
    """Best-effort map a quoted span back to its 1-based line in the file."""
    needle = quote.strip().splitlines()[0].strip() if quote.strip() else ""
    if needle:
        for i, line in enumerate(body_lines):
            if needle in line:
                return start + i
    return start  # fall back to the first body line


# --------------------------------------------------------------------------- #
def write_report(findings: list[Finding]) -> None:
    findings.sort(key=lambda f: (f.rel, f.line, f.source))
    with open(REPORT_OUT, "w", encoding="utf-8") as out:
        out.write("# Typo / grammar review queue (assistive — accept/reject by hand)\n")
        out.write(f"# {len(findings)} suggestion(s). Format: path:line: suggestion [source]\n\n")
        current = None
        for f in findings:
            if f.rel != current:
                current = f.rel
                out.write(f"\n{f.rel}/index.md\n")
            out.write(f"  :{f.line}: {f.message}  [{f.source}]\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=None, help="only the first N reviews")
    ap.add_argument("--llm", action="store_true", help="also run the LLM grammar pass")
    args = ap.parse_args()

    content_dir = Config.load().content_dir
    reviews = list(iter_reviews(content_dir, args.limit))
    files = [md for md, _ in reviews]
    body_starts = {md: body_start_line(md.read_text(encoding="utf-8")) for md in files}
    print(f"Linting {len(files)} review(s)…")

    print("Pass 1: codespell")
    findings = codespell_pass(files, body_starts)
    print(f"  {len(findings)} codespell hit(s).")

    if args.llm:
        print("Pass 2: LLM grammar")
        bodies = [(md, frontmatter.load(str(md)).content) for md in files]
        llm_findings = llm_pass(bodies)
        print(f"  {len(llm_findings)} LLM finding(s).")
        findings += llm_findings

    write_report(findings)
    print(f"\nWrote {len(findings)} suggestion(s) -> {REPORT_OUT}")
    print("Review the queue and apply accepted fixes by hand.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
