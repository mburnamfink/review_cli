from __future__ import annotations

import csv
import io
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .config import Config
from .covers import process_cover
from .openlibrary import fetch_cover_bytes
from .slug import make_slug

_UA = "review-cli/0.1 (book review importer; contact via GitHub)"


# ---------------------------------------------------------------------------
# Log
# ---------------------------------------------------------------------------

@dataclass
class ImportLog:
    imported: list[str] = field(default_factory=list)
    skipped_not_read: int = 0
    # (slug, csv_line_of_existing_or_-1_if_on_disk, csv_line_of_skipped)
    skipped_duplicate: list[tuple[str, int, int]] = field(
        default_factory=list
    )
    image_failures: list[tuple[str, str]] = field(default_factory=list)
    goodreads_links: list[tuple[str, str, str]] = field(default_factory=list)
    multi_read_stubs: list[tuple[str, int]] = field(default_factory=list)
    no_date_read: list[str] = field(default_factory=list)
    no_cover: list[str] = field(default_factory=list)

    def write(self, path: Path) -> None:
        lines: list[str] = []
        lines.append("=== Goodreads Import Log ===")
        lines.append(
            f"Generated: {datetime.now().isoformat(timespec='seconds')}"
        )
        lines.append("")
        lines.append(f"Imported:           {len(self.imported)}")
        lines.append(f"Skipped (not read): {self.skipped_not_read}")
        lines.append(f"Skipped (duplicate):{len(self.skipped_duplicate):>4}")
        lines.append(f"Image failures:     {len(self.image_failures)}")
        lines.append(f"Goodreads links:    {len(self.goodreads_links)}")
        lines.append(f"Multi-read stubs:   {len(self.multi_read_stubs)}")
        lines.append(f"No date_read:       {len(self.no_date_read)}")
        lines.append(f"No cover found:     {len(self.no_cover)}")

        if self.skipped_duplicate:
            lines.append("")
            lines.append("--- Duplicates skipped ---")
            for slug, existing_line, new_line in self.skipped_duplicate:
                if existing_line == -1:
                    lines.append(
                        f"  [{slug}] CSV line {new_line}"
                        " — already exists on disk"
                    )
                else:
                    lines.append(
                        f"  [{slug}] CSV line {new_line}"
                        f" duplicates line {existing_line}"
                    )

        if self.image_failures:
            lines.append("")
            lines.append(
                "--- Image download failures (manual review needed) ---"
            )
            for title, url in self.image_failures:
                lines.append(f"  {title}")
                lines.append(f"    {url}")

        if self.goodreads_links:
            lines.append("")
            lines.append("--- Goodreads links to remap to local files ---")
            for title, slug, link in self.goodreads_links:
                lines.append(f"  [{slug}] {title}")
                lines.append(f"    {link}")

        if self.multi_read_stubs:
            lines.append("")
            lines.append(
                "--- Multi-read stubs (earlier reads have no dates) ---"
            )
            for title, count in self.multi_read_stubs:
                lines.append(f"  {title}  ({count}x)")

        if self.no_date_read:
            lines.append("")
            lines.append(
                "--- No Date Read (year estimated from shelves/date added) ---"
            )
            for title in self.no_date_read:
                lines.append(f"  {title}")

        if self.no_cover:
            lines.append("")
            lines.append(
                "--- No cover found"
                " (Open Library + Google Books both failed) ---"
            )
            for title in self.no_cover:
                lines.append(f"  {title}")

        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# CSV parsing utilities
# ---------------------------------------------------------------------------

_SERIES_RE = re.compile(r"\s*\([^)]*,?\s*#\d+\)\s*$")
_ISBN_WRAPPER = re.compile(r'^="(.*)"$')
_YEAR_RE = re.compile(r"^(19|20)\d{2}$")
AUDIO_BINDINGS = {
    "Audiobook", "Audible Audio", "Audio Cassette", "MP3 CD", "Audio CD"
}


def _parse_isbn(raw: str) -> str | None:
    raw = raw.strip()
    if not raw:
        return None
    m = _ISBN_WRAPPER.match(raw)
    val = m.group(1) if m else raw
    return val if val else None


def _strip_series(title: str) -> str:
    return _SERIES_RE.sub("", title).strip()


def _parse_author_lf(name: str) -> dict | None:
    name = name.strip()
    if not name:
        return None
    if "," in name:
        last, _, first = name.partition(",")
        return {"first": first.strip(), "last": last.strip(), "role": "author"}
    return {"first": "", "last": name, "role": "author"}


def _parse_authors(author_lf: str, additional: str) -> list[dict]:
    authors: list[dict] = []
    a = _parse_author_lf(author_lf)
    if a:
        authors.append(a)
    if additional.strip():
        for name in additional.split(","):
            a2 = _parse_author_lf(name)
            if a2:
                authors.append(a2)
    return authors


def _parse_date(s: str) -> date | None:
    if not s:
        return None
    try:
        y, m, d = s.split("/")
        return date(int(y), int(m), int(d))
    except Exception:
        return None


def _detect_type(bookshelves: str, binding: str) -> str:
    shelves = {s.strip() for s in bookshelves.split(",")}
    if "rpg" in shelves:
        return "rpg"
    if binding in AUDIO_BINDINGS:
        return "audiobook"
    return "book"


def _year_shelves(bookshelves: str) -> list[int]:
    return sorted(
        int(s.strip())
        for s in bookshelves.split(",")
        if _YEAR_RE.match(s.strip())
    )


def _extract_tags(bookshelves: str) -> list[str]:
    return [
        s.strip()
        for s in bookshelves.split(",")
        if s.strip() and not _YEAR_RE.match(s.strip())
    ]


def _build_reads(
    date_read_str: str,
    date_added_str: str,
    read_count: int,
    year_shelves: list[int],
) -> tuple[list[dict], bool]:
    """Return (reads_list, needs_manual_review)."""
    finished = _parse_date(date_read_str)
    added = _parse_date(date_added_str)

    if finished:
        final_year = finished.year
    elif year_shelves:
        final_year = max(year_shelves)
    elif added:
        final_year = added.year
    else:
        final_year = date.today().year

    if read_count <= 1:
        rec: dict = {"year": final_year}
        if finished:
            rec["date_finished"] = finished
        return [rec], False

    # Multiple reads: distribute earlier year shelves across stub records;
    # the last read gets the actual date.
    earlier_years = sorted(y for y in year_shelves if y < final_year)
    reads: list[dict] = []
    for i in range(read_count - 1):
        year = earlier_years[i] if i < len(earlier_years) else final_year
        reads.append({"year": year})
    final_rec: dict = {"year": final_year}
    if finished:
        final_rec["date_finished"] = finished
    reads.append(final_rec)
    return reads, True  # always flag multi-reads for manual review


# ---------------------------------------------------------------------------
# HTML → Markdown converter
# ---------------------------------------------------------------------------

class _HtmlConverter(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._out: list[str] = []
        self._italic = 0
        self._bold = 0
        self._pending_nl = 0
        self._in_link = False
        self._link_href = ""
        self._link_buf: list[str] = []
        self.image_urls: list[str] = []
        self.goodreads_links: list[tuple[str, str]] = []  # (text, href)

    def handle_starttag(self, tag: str, attrs: list) -> None:
        tag = tag.lower()
        ad = dict(attrs)
        if tag == "br":
            self._pending_nl = max(self._pending_nl, 2)
        elif tag == "p":
            self._pending_nl = max(self._pending_nl, 2)
        elif tag in ("i", "em"):
            self._flush_nl()
            self._italic += 1
            self._raw("*")
        elif tag in ("b", "strong"):
            self._flush_nl()
            self._bold += 1
            self._raw("**")
        elif tag == "a":
            self._flush_nl()
            self._in_link = True
            self._link_href = ad.get("href", "")
            self._link_buf = []
        elif tag == "img":
            src = ad.get("src", "")
            if src:
                self._flush_nl()
                self.image_urls.append(src)
                self._raw(f"__IMG_{len(self.image_urls) - 1}__")

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        """Self-closing tags and malformed <i/> used as a closing tag."""
        tag = tag.lower()
        ad = dict(attrs)
        if tag == "br":
            self._pending_nl = max(self._pending_nl, 2)
        elif tag in ("i", "em"):
            # Treat <i/> as </i> when inside an italic span
            if self._italic > 0:
                self._italic -= 1
                self._raw("*")
        elif tag in ("b", "strong"):
            if self._bold > 0:
                self._bold -= 1
                self._raw("**")
        elif tag == "img":
            src = ad.get("src", "")
            if src:
                self._flush_nl()
                self.image_urls.append(src)
                self._raw(f"__IMG_{len(self.image_urls) - 1}__")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in ("i", "em"):
            if self._italic > 0:
                self._italic -= 1
                self._raw("*")
        elif tag in ("b", "strong"):
            if self._bold > 0:
                self._bold -= 1
                self._raw("**")
        elif tag == "a":
            if self._in_link:
                text = "".join(self._link_buf).strip()
                href = self._link_href
                if "goodreads.com" in href:
                    self.goodreads_links.append((text, href))
                self._raw(f"[{text}]({href})")
                self._in_link = False
        elif tag == "p":
            self._pending_nl = max(self._pending_nl, 2)

    def handle_data(self, data: str) -> None:
        self._flush_nl()
        if self._in_link:
            self._link_buf.append(data)
        else:
            self._raw(data)

    def _raw(self, s: str) -> None:
        self._out.append(s)

    def _flush_nl(self) -> None:
        if self._pending_nl:
            self._out.append("\n" * self._pending_nl)
            self._pending_nl = 0

    def result(self) -> str:
        self._flush_nl()
        text = "".join(self._out)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


# ---------------------------------------------------------------------------
# Inline image downloader
# ---------------------------------------------------------------------------

def _download_image(url: str, dest_dir: Path, index: int) -> str | None:
    """Download URL to dest_dir/img-{index}.{ext}. Returns relative path or None."""  # noqa: E501
    try:
        resp = httpx.get(
            url,
            timeout=20,
            follow_redirects=True,
            headers={"User-Agent": _UA},
        )
        resp.raise_for_status()
        content = resp.content
        if len(content) < 200:
            return None

        ct = resp.headers.get("content-type", "")
        url_path = urlparse(url).path.split("?")[0]
        path_ext = Path(url_path).suffix.lower()

        if path_ext in (".jpg", ".jpeg"):
            ext = ".jpg"
        elif path_ext == ".gif":
            ext = ".gif"
        elif path_ext == ".png":
            ext = ".png"
        elif path_ext == ".webp":
            ext = ".jpg"  # will convert below
        elif "gif" in ct:
            ext = ".gif"
        elif "png" in ct:
            ext = ".png"
        elif "webp" in ct:
            ext = ".jpg"  # will convert below
        else:
            ext = ".jpg"

        if path_ext == ".webp" or "webp" in ct:
            from PIL import Image
            img = Image.open(io.BytesIO(content)).convert("RGB")
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=88)
            content = buf.getvalue()

        filename = f"img-{index}{ext}"
        (dest_dir / filename).write_bytes(content)
        return f"./{filename}"
    except Exception:
        return None


# ---------------------------------------------------------------------------
# HTML conversion entry point
# ---------------------------------------------------------------------------

def _convert_html(
    html_str: str,
    review_dir: Path | None,
    title: str,
    slug: str,
    log: ImportLog,
    download: bool = True,
) -> str:
    parser = _HtmlConverter()
    parser.feed(html_str)
    text = parser.result()

    for i, url in enumerate(parser.image_urls):
        placeholder = f"__IMG_{i}__"
        local: str | None = None
        if download and review_dir is not None:
            local = _download_image(url, review_dir, i + 1)
        if local:
            text = text.replace(placeholder, f"![]({local})")
        else:
            if download:
                log.image_failures.append((title, url))
            text = text.replace(placeholder, f"<!-- img: {url} -->")

    for link_text, href in parser.goodreads_links:
        log.goodreads_links.append((title, slug, f"[{link_text}]({href})"))

    return text


# ---------------------------------------------------------------------------
# Main import function
# ---------------------------------------------------------------------------

def import_goodreads(
    csv_path: Path,
    config: Config,
    *,
    dry_run: bool = False,
    fetch_covers: bool = True,
    cover_delay: float = 1.0,
    skip_titles: tuple[str, ...] = (),
    on_progress: object = None,  # callable() called after each row processed
) -> ImportLog:
    import frontmatter as fm_lib

    log = ImportLog()
    seen_slugs: dict[str, int] = {}  # slug -> csv line number

    with open(csv_path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    for csv_line, row in enumerate(rows, start=2):  # line 1 is header
        if on_progress is not None:
            on_progress()

        if row["Exclusive Shelf"] != "read":
            log.skipped_not_read += 1
            continue

        raw_title = row["Title"]
        if skip_titles and any(
            s.lower() in raw_title.lower() for s in skip_titles
        ):
            log.skipped_not_read += 1  # reuse counter; noted in summary
            continue

        title = _strip_series(raw_title)
        authors = _parse_authors(
            row["Author l-f"], row["Additional Authors"]
        )
        if not authors:
            authors = [{
                "first": "",
                "last": row["Author"].strip(),
                "role": "author",
            }]

        review_type = _detect_type(row["Bookshelves"], row["Binding"])
        slug = make_slug(title, authors, review_type)

        if slug in seen_slugs:
            log.skipped_duplicate.append((slug, seen_slugs[slug], csv_line))
            continue
        seen_slugs[slug] = csv_line

        review_dir = config.content_dir / review_type / slug
        if review_dir.exists():
            log.skipped_duplicate.append((slug, -1, csv_line))
            continue

        isbn = _parse_isbn(row["ISBN13"]) or _parse_isbn(row["ISBN"])
        year_shelves = _year_shelves(row["Bookshelves"])

        try:
            read_count = int(row["Read Count"] or 1)
        except ValueError:
            read_count = 1

        reads, needs_review = _build_reads(
            row["Date Read"], row["Date Added"], read_count, year_shelves
        )

        if not row["Date Read"]:
            log.no_date_read.append(title)
        if needs_review:
            log.multi_read_stubs.append((title, read_count))

        tags = _extract_tags(row["Bookshelves"])
        rating_str = row["My Rating"]
        rating: float | None = (
            float(rating_str) if rating_str and rating_str != "0" else None
        )
        date_reviewed = _parse_date(row["Date Added"]) or date.today()

        pub_year: int | None = None
        try:
            pub_year = (
                int(row["Year Published"]) if row["Year Published"] else None
            )
        except ValueError:
            pass

        publisher = row["Publisher"].strip() or None

        extra: dict = {}
        if review_type == "book":
            try:
                if row["Number of Pages"]:
                    extra["page_count"] = int(row["Number of Pages"])
            except ValueError:
                pass
        elif review_type == "audiobook":
            extra["abridged"] = False

        if dry_run:
            if row["My Review"]:
                _convert_html(
                    row["My Review"], None, title, slug, log, download=False
                )
            log.imported.append(f"{title} → {review_type}/{slug}")
            continue

        review_dir.mkdir(parents=True, exist_ok=True)

        body = ""
        if row["My Review"]:
            body = _convert_html(
                row["My Review"], review_dir, title, slug, log, download=True
            )

        cover: str | None = None
        og_cover: str | None = None
        if fetch_covers and isbn:
            raw = fetch_cover_bytes(isbn)
            if raw:
                cover, og_cover = process_cover(raw, review_dir)
            else:
                log.no_cover.append(title)
            time.sleep(cover_delay)

        fm: dict = {
            "title": title,
            "authors": authors,
            "type": review_type,
        }
        if isbn:
            fm["isbn"] = isbn
        if pub_year:
            fm["publication_year"] = pub_year
        if publisher:
            fm["publisher"] = publisher
        fm["rating"] = rating
        fm["date_reviewed"] = date_reviewed
        fm["reads"] = reads
        fm["tags"] = tags
        if cover:
            fm["cover"] = cover
        if og_cover:
            fm["og_cover"] = og_cover
        fm.update(extra)

        post = fm_lib.Post(body, **fm)
        (review_dir / "index.md").write_text(
            fm_lib.dumps(post), encoding="utf-8"
        )
        log.imported.append(f"{title} → {review_type}/{slug}")

    return log
