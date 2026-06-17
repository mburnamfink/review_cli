#!/usr/bin/env python3
"""Wrap known book titles in *italics* where they appear unformatted in bodies.

Builds a set of known titles from the local reviews plus the Goodreads /
StoryGraph export `Title` columns (series suffixes stripped). For each review
body, finds whole-word, case-sensitive occurrences of a known title that are
NOT already italic / bold / a heading / inside a link anchor or URL / inside a
code span, and wraps them in `*…*`.

False-positive guards (titles over-match badly on common words):
  * multi-word titles must be >= MIN_CHARS characters;
  * single-word titles must be >= SINGLE_MIN chars AND not a dictionary word
    (so *Pet*, *Breath*, *Drop* are skipped);
  * an explicit DENYLIST for the rest.
Every change is logged to typology_changes.csv for a quick audit.

Dry-run by default. Pass --apply to write.

Run from review-cli/:
    uv run python scripts/italicize_titles.py            # preview
    uv run python scripts/italicize_titles.py --apply    # write
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

import frontmatter

from review.config import Config

from _body import read_body, write_body
from _typology_log import replace_section

CHANGE_TYPE = "italicize"

# Goodreads / StoryGraph exports (StoryGraph may be absent — handled gracefully).
IMPORT_DIR = Path(__file__).parent.parent / "import"
CSV_SOURCES = [IMPORT_DIR / "goodreads_library_export (1).csv", IMPORT_DIR / "storygraph.csv"]

MIN_CHARS = 8       # multi-word titles shorter than this are skipped
SINGLE_MIN = 8      # single-word titles shorter than this are skipped
DICT_PATH = Path("/usr/share/dict/words")

# Titles that survive the length guard but still over-match prose: common-word
# titles, genre phrases, surnames, and historical-event names that also appear
# as ordinary prose.
DENYLIST = {
    "pet", "breath", "crossings", "drop", "everything must go",
    "the road", "small things like these", "science fiction", "summer of love",
    "the party", "pathfinder", "westmoreland", "green zone", "renaissance florence",
}

# Regions of a body that must never be touched.
PROTECT_PATTERNS = [
    re.compile(r"```.*?```", re.DOTALL),          # fenced code
    re.compile(r"`[^`\n]*`"),                       # inline code
    re.compile(r"!?\[[^\]]*\]\([^)]*\)"),          # links / images
    re.compile(r"\*\*[^*]+\*\*"),                   # bold (**)
    re.compile(r"__[^_]+__"),                        # bold (__)
    re.compile(r"\*[^*\n]+\*"),                     # italic (*)
    re.compile(r"(?<!\w)_[^_\n]+_(?!\w)"),         # italic (_)
    re.compile(r"(?m)^#{1,6}[^\n]*$"),             # headings
    re.compile(r"<!--.*?-->", re.DOTALL),          # html comments
    re.compile(r"<[^>]+>"),                         # raw html tags
]


def load_dict_words() -> set[str]:
    if not DICT_PATH.exists():
        return set()
    words = set()
    for line in DICT_PATH.read_text(encoding="utf-8", errors="ignore").splitlines():
        w = line.strip().lower()
        if w and w.isalpha():
            words.add(w)
    return words


def strip_series(title: str) -> str:
    """Drop a trailing ' (Series, #N)' suffix."""
    i = title.find(" (")
    return title[:i] if i != -1 else title


def surface_forms(title: str):
    """Candidate (surface string, is_subtitle_main) pairs for one source title."""
    base = strip_series(title).strip()
    forms = [(base, False)]
    main = base.split(": ", 1)[0].strip()  # drop subtitle
    if main and main != base:
        forms.append((main, True))
    return [(f, is_main) for f, is_main in forms if f]


def qualifies(form: str, is_main: bool, dict_words: set[str]) -> bool:
    if form.lower() in DENYLIST:
        return False
    if not form[:1].isupper():          # must look like Title Case
        return False
    words = form.split()
    if is_main:
        # A subtitle-stripped main title (e.g. "Westmoreland: The General …")
        # is a truncation — require it stay multi-word and long to avoid surname
        # / generic-phrase false positives.
        return len(words) >= 2 and len(form) >= MIN_CHARS
    if len(words) == 1:
        return len(form) >= SINGLE_MIN and form.lower() not in dict_words
    return len(form) >= MIN_CHARS


def build_forms(content_dir: Path, dict_words: set[str]) -> list[str]:
    raw: set[str] = set()
    for md in content_dir.rglob("*/index.md"):
        t = frontmatter.load(str(md)).get("title")
        if t:
            raw.add(str(t))
    for csv_path in CSV_SOURCES:
        if not csv_path.exists():
            continue
        with open(csv_path, newline="", encoding="utf-8", errors="replace") as f:
            for row in csv.DictReader(f):
                t = (row.get("Title") or "").strip()
                if t:
                    raw.add(t)

    forms: set[str] = set()
    for title in raw:
        for form, is_main in surface_forms(title):
            if qualifies(form, is_main, dict_words):
                forms.add(form)
    # Longest first so the alternation prefers the most specific title.
    return sorted(forms, key=len, reverse=True)


def protected_spans(body: str) -> list[tuple[int, int]]:
    spans = []
    for pat in PROTECT_PATTERNS:
        spans.extend((m.start(), m.end()) for m in pat.finditer(body))
    return spans


def in_protected(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    return any(s < end and start < e for s, e in spans)


def italicize_body(body: str, matcher: re.Pattern) -> tuple[str, list[str]]:
    spans = protected_spans(body)
    edits = []  # (start, end, form)
    for m in matcher.finditer(body):
        if not in_protected(m.start(), m.end(), spans):
            edits.append((m.start(), m.end(), m.group(0)))
    if not edits:
        return body, []
    changed = []
    for start, end, form in reversed(edits):  # right-to-left keeps offsets valid
        body = body[:start] + f"*{form}*" + body[end:]
        changed.append(form)
    changed.reverse()
    return body, changed


def main() -> int:
    apply = "--apply" in sys.argv
    content_dir = Config.load().content_dir
    dict_words = load_dict_words()
    forms = build_forms(content_dir, dict_words)
    matcher = re.compile(
        r"(?<![A-Za-z0-9*_])(?:" + "|".join(re.escape(f) for f in forms) + r")(?![A-Za-z0-9*_])"
    )
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"[{mode}] content_dir = {content_dir}")
    print(f"{len(forms)} qualifying title forms in the matcher.\n")

    log_rows: list[dict] = []
    reviews_changed = 0
    for md in sorted(content_dir.rglob("*/index.md")):
        fm, body = read_body(md)
        new_body, changed = italicize_body(body, matcher)
        if not changed:
            continue
        reviews_changed += 1
        rtype, slug = md.parent.relative_to(content_dir).parts[:2]
        for form in changed:
            log_rows.append(
                {"type": rtype, "slug": slug, "before": form, "after": f"*{form}*"}
            )
        print(f"  {rtype}/{slug}: " + ", ".join(sorted(set(changed))))
        if apply:
            write_body(md, fm, new_body)

    print(f"\n{'Italicized' if apply else 'Would italicize'} {len(log_rows)} "
          f"occurrence(s) across {reviews_changed} review(s).")
    if apply:
        path = replace_section(CHANGE_TYPE, log_rows)
        print(f"Logged -> {path}")
    else:
        print("Dry-run only. Re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
