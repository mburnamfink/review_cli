#!/usr/bin/env python3
"""Rewrite off-site review links to this site, and repair internal links.

Two passes over each review body:

A. External -> internal. Links to goodreads.com, the StoryGraph
   (storygraph.app / thestorygraph.com) and pagebound use the *book title* as
   their anchor text. If that title matches a local review, the URL is
   rewritten to `/{type}/{slug}/`; otherwise the link is left alone and
   reported as "no local match".

B. Internal-link repair. Every same-site `/{type}/{slug}/…` link is validated
   against the content tree. If a slug moved to a new type (Task 1's
   reclassification), the link is re-pointed; anything still unresolved is
   reported.

Changes are logged to typology_changes.csv; unresolved links are written to
internal_links_report.txt.

Dry-run by default. Pass --apply to write.

Run from review-cli/:
    uv run python scripts/fix_internal_links.py            # preview
    uv run python scripts/fix_internal_links.py --apply    # write
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import frontmatter

from review.config import Config

from _body import read_body, write_body
from _typology_log import replace_section

REPORT_PATH = Path(__file__).parent / "internal_links_report.txt"

OFFSITE_HOSTS = re.compile(r"(goodreads\.com|storygraph\.app|thestorygraph\.com|pagebound)", re.I)
MD_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
INTERNAL_LINK = re.compile(r"\]\((/(?:book|audiobook|rpg)/[^)]+)\)")
TYPES = ("book", "audiobook", "rpg")


def match_key(s: str) -> str:
    """Aggressive normalisation for anchor-text <-> title matching."""
    s = s.lower().strip()
    s = re.sub(r"\s+", " ", s)
    if " (" in s:
        s = s[: s.index(" (")]
    s = s.split(": ", 1)[0]
    s = s.split(" - ", 1)[0]
    return s.strip(" .,:;\"'")


def build_title_index(content_dir: Path) -> dict[str, list[tuple[str, str]]]:
    idx: dict[str, list[tuple[str, str]]] = {}
    for md in content_dir.rglob("*/index.md"):
        rtype, slug = md.parent.relative_to(content_dir).parts[:2]
        key = match_key(str(frontmatter.load(str(md)).get("title", slug)))
        if key:
            idx.setdefault(key, []).append((rtype, slug))
    return idx


def build_slug_types(content_dir: Path) -> dict[str, list[str]]:
    """slug -> the type(s) it currently lives under."""
    out: dict[str, list[str]] = {}
    for t in TYPES:
        d = content_dir / t
        if d.is_dir():
            for sub in d.iterdir():
                if (sub / "index.md").exists():
                    out.setdefault(sub.name, []).append(t)
    return out


def main() -> int:
    apply = "--apply" in sys.argv
    content_dir = Config.load().content_dir
    title_idx = build_title_index(content_dir)
    slug_types = build_slug_types(content_dir)
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"[{mode}] content_dir = {content_dir}\n")

    log_rows: list[dict] = []
    no_match: list[str] = []
    broken: list[str] = []

    for md in sorted(content_dir.rglob("*/index.md")):
        fm, body = read_body(md)
        orig_body = body
        rtype, slug = md.parent.relative_to(content_dir).parts[:2]
        ref = f"{rtype}/{slug}"

        # --- Pass A: offsite -> internal ---
        def repl_external(m: re.Match) -> str:
            anchor, url = m.group(1), m.group(2)
            if not OFFSITE_HOSTS.search(url):
                return m.group(0)
            hits = title_idx.get(match_key(anchor), [])
            if len(hits) == 1:
                t, s = hits[0]
                new_url = f"/{t}/{s}/"
                log_rows.append({"type": rtype, "slug": slug, "before": url, "after": new_url})
                return f"[{anchor}]({new_url})"
            reason = "no local match" if not hits else f"ambiguous ({len(hits)})"
            no_match.append(f"{ref}: [{anchor}]({url})  -- {reason}")
            return m.group(0)

        body = MD_LINK.sub(repl_external, body)

        # --- Pass B: validate / repair internal links ---
        def repl_internal(m: re.Match) -> str:
            path = m.group(1)  # /type/slug[/rest]
            parts = path.strip("/").split("/")
            t, s = parts[0], parts[1]
            rest = "/" + "/".join(parts[2:]) if len(parts) > 2 else ("/" if path.endswith("/") else "")
            if (content_dir / t / s / "index.md").exists() or (content_dir / t / s).is_dir():
                return m.group(0)  # resolves fine
            current = slug_types.get(s, [])
            if len(current) == 1:
                new_path = f"/{current[0]}/{s}{rest}"
                log_rows.append({"type": rtype, "slug": slug, "before": path, "after": new_path})
                return f"]({new_path})"
            broken.append(f"{ref}: {path}  -- {'no such slug' if not current else 'ambiguous'}")
            return m.group(0)

        body = INTERNAL_LINK.sub(repl_internal, body)

        if apply and body != orig_body:
            write_body(md, fm, body)

    print(f"External links rewritten to internal: "
          f"{sum(1 for r in log_rows if r['before'].startswith('http'))}")
    print(f"Internal links repaired: "
          f"{sum(1 for r in log_rows if r['before'].startswith('/'))}")
    print(f"Off-site links with no local match: {len(no_match)}")
    print(f"Broken internal links: {len(broken)}")

    report = ["# Off-site links with no local match\n", *[f"  {x}\n" for x in no_match],
              "\n# Broken internal links\n", *[f"  {x}\n" for x in broken]]
    if apply:
        REPORT_PATH.write_text("".join(report), encoding="utf-8")
        path = replace_section("link", log_rows)
        print(f"\nLogged -> {path}\nReport -> {REPORT_PATH}")
    else:
        print("\n--- would-report (no local match) ---")
        for x in no_match[:30]:
            print(f"  {x}")
        if broken:
            print("--- would-report (broken internal) ---")
            for x in broken:
                print(f"  {x}")
        print("\nDry-run only. Re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
