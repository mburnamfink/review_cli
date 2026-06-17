#!/usr/bin/env python3
"""Download remote body images into each review and rewrite to a relative path.

For every `![alt](http(s)://…)` in a review body, the image is downloaded into
that review's directory as `img-N.<ext>` and the markdown is rewritten to the
relative `./img-N.<ext>` (the same convention as `cover.jpg`). The original URL
is preserved as an invisible HTML comment on the next line, e.g.

    ![alt](./img-1.jpg)
    <!-- original-image: https://… -->

so a later broken download can be re-sourced. Downloads that fail are reported
and left untouched (no dead relative links). Changes are logged to
typology_changes.csv.

Dry-run by default. Pass --apply to download + write.

Run from review-cli/:
    uv run python scripts/localize_images.py            # preview
    uv run python scripts/localize_images.py --apply    # download + write
"""
from __future__ import annotations

import mimetypes
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from review.config import Config

from _body import read_body, write_body
from _typology_log import replace_section

CHANGE_TYPE = "image"
REMOTE_IMAGE = re.compile(r"!\[([^\]]*)\]\((https?://[^)\s]+)\)")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 review-cli/localize-images"
EXT_FROM_CT = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif",
               "image/webp": ".webp", "image/avif": ".avif"}


def guess_ext(url: str, content_type: str | None) -> str:
    if content_type:
        ct = content_type.split(";")[0].strip().lower()
        if ct in EXT_FROM_CT:
            return EXT_FROM_CT[ct]
        guessed = mimetypes.guess_extension(ct)
        if guessed:
            return ".jpg" if guessed == ".jpe" else guessed
    suffix = Path(urlparse(url).path).suffix.lower()
    return suffix if suffix in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif"} else ".jpg"


def download(url: str, dest_dir: Path, index: int) -> str | None:
    """Download `url` into dest_dir as img-{index}.<ext>; return the filename or None."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
            ext = guess_ext(url, resp.headers.get("Content-Type"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        print(f"      DOWNLOAD FAILED: {url}  ({e})")
        return None
    if not data:
        print(f"      EMPTY RESPONSE: {url}")
        return None
    name = f"img-{index}{ext}"
    (dest_dir / name).write_bytes(data)
    return name


def main() -> int:
    apply = "--apply" in sys.argv
    content_dir = Config.load().content_dir
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"[{mode}] content_dir = {content_dir}\n")

    log_rows: list[dict] = []
    failures = 0
    for md in sorted(content_dir.rglob("*/index.md")):
        fm, body = read_body(md)
        matches = list(REMOTE_IMAGE.finditer(body))
        if not matches:
            continue
        rtype, slug = md.parent.relative_to(content_dir).parts[:2]
        print(f"  {rtype}/{slug}: {len(matches)} remote image(s)")

        # Build the new body left-to-right, downloading as we go.
        out = []
        last = 0
        counter = 0
        for m in matches:
            alt, url = m.group(1), m.group(2)
            counter += 1
            out.append(body[last:m.start()])
            if apply:
                name = download(url, md.parent, counter)
            else:
                name = f"img-{counter}{guess_ext(url, None)}"
                print(f"      would fetch {url} -> {name}")
            if name is None:
                failures += 1
                out.append(m.group(0))  # leave the original link intact
            else:
                out.append(f"![{alt}](./{name})\n<!-- original-image: {url} -->")
                log_rows.append(
                    {"type": rtype, "slug": slug, "before": url, "after": f"./{name}"}
                )
            last = m.end()
        out.append(body[last:])
        new_body = "".join(out)
        if apply and new_body != body:
            write_body(md, fm, new_body)

    print(f"\n{'Localized' if apply else 'Would localize'} {len(log_rows)} image(s); "
          f"{failures} download failure(s).")
    if apply:
        path = replace_section(CHANGE_TYPE, log_rows)
        print(f"Logged -> {path}")
    else:
        print("Dry-run only. Re-run with --apply to download + write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
