"""Browser-based cover picker — a terminal-agnostic replacement for the kitty loop.

``review pick-covers`` renders an inline contact sheet with ``kitten icat``, which
silently falls back to an external image viewer when the shell isn't genuinely a
kitty terminal. This module serves the same review loop over a tiny localhost
HTTP server instead: every candidate (and the current cover) is rendered through
``cover_crop`` — the **2:3 centre crop the site's grid actually shows** (CSS
``object-fit: cover``), so you judge exactly how the cover reads on the main page,
title/author clipping and all. The page captures one keystroke at a time and POSTs
the decision back:

    1–N   apply that candidate  → cover.jpg + og-cover.jpg (the only site write)
    N+1   keep the current cover as-is (settled, no write)
    s     skip — come back next run
    c     crop — a candidate is good but needs a manual crop (settled)
    r     replace — no usable candidate, source one by hand (settled)
    q     quit

State lives in ``covers/.pick_state.json`` (resumable; settled books aren't
re-offered, skipped ones are). After every keystroke a human- and machine-readable
summary of the Skip/Crop/Replace lists is rewritten beside it.
"""
from __future__ import annotations

import json
import threading
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

import frontmatter
from PIL import Image

from . import staging
from .covers import cover_crop, process_cover
from .pickstate import (
    DONE,
    NEEDS_CROP,
    NEEDS_REPLACE,
    SKIPPED,
    PickState,
)

# Preview render size — 2:3, matching the grid card's aspect-ratio.
CARD_W, CARD_H = 400, 600

SUMMARY_JSON = "pick_summary.json"
SUMMARY_MD = "pick_summary.md"

# Map a single keystroke / action name to the state it records.
ACTION_STATUS = {"skip": SKIPPED, "crop": NEEDS_CROP, "replace": NEEDS_REPLACE}


def card_preview_bytes(path: Path) -> bytes:
    """Render an image as the site's grid shows it — a 2:3 centre crop — as JPEG.

    Matches the main page's ``object-fit: cover`` so the preview is exactly what a
    reader sees, title/author clipping and all. (The applied ``cover.jpg`` keeps
    full aspect; only the on-page display crops.)
    """
    with Image.open(path) as im:
        card = cover_crop(im.convert("RGB"), CARD_W, CARD_H)
    buf = BytesIO()
    card.save(buf, "JPEG", quality=88)
    return buf.getvalue()


def apply_staged(review_path: str, image_path: Path) -> None:
    """Write cover.jpg + og-cover.jpg into a review and update its frontmatter."""
    raw = image_path.read_bytes()
    review_dir = Path(review_path).parent
    cover, og_cover = process_cover(raw, review_dir)
    post = frontmatter.load(review_path)
    post.metadata["cover"] = cover
    post.metadata["og_cover"] = og_cover
    Path(review_path).write_text(frontmatter.dumps(post), encoding="utf-8")


def write_summary(covers_dir: Path, state: PickState) -> None:
    """(Re)write the human + machine readable Skip/Crop/Replace summary."""
    groups = {
        "skip": state.slugs_with_status(SKIPPED),
        "crop": state.slugs_with_status(NEEDS_CROP),
        "replace": state.slugs_with_status(NEEDS_REPLACE),
    }
    (covers_dir / SUMMARY_JSON).write_text(
        json.dumps(groups, indent=2, sort_keys=True), encoding="utf-8"
    )

    titles = {"skip": "Skip — revisit later", "crop": "Crop — manual crop needed",
              "replace": "Replace — source a cover by hand"}
    lines = ["# Cover pick summary", ""]
    for key in ("crop", "replace", "skip"):
        slugs = groups[key]
        lines.append(f"## {titles[key]} ({len(slugs)})")
        lines.extend(f"- {s}" for s in slugs)
        if not slugs:
            lines.append("- _(none)_")
        lines.append("")
    (covers_dir / SUMMARY_MD).write_text("\n".join(lines), encoding="utf-8")


@dataclass
class Controller:
    """Shared, lock-guarded state driving the picker across HTTP requests."""

    covers_dir: Path
    state: PickState
    todo: list[staging.StagedBook]
    index: int = 0
    lock: threading.Lock = None  # set in __post_init__
    done_event: threading.Event = None

    def __post_init__(self) -> None:
        self.lock = threading.Lock()
        self.done_event = threading.Event()

    def current(self) -> staging.StagedBook | None:
        return self.todo[self.index] if self.index < len(self.todo) else None

    def book_payload(self) -> dict:
        """JSON describing the book at the pointer (or {done:true} at the end)."""
        book = self.current()
        if book is None:
            return {"done": True, "total": len(self.todo)}
        cands = [
            {"n": i, "width": c.width, "height": c.height,
             "title": c.title, "source": c.source}
            for i, c in enumerate(book.candidates, 1)
        ]
        cur_w = book.current_width
        cur_h = None
        if book.current:
            try:
                with Image.open(staging.book_dir(self.covers_dir, book.slug) / book.current) as im:
                    cur_w, cur_h = im.width, im.height
            except Exception:
                pass
        return {
            "done": False,
            "index": self.index + 1,
            "total": len(self.todo),
            "slug": book.slug,
            "title": book.title,
            "has_current": bool(book.current),
            "current_width": cur_w,
            "current_height": cur_h,
            "candidates": cands,
        }

    def decide(self, action: str, choice: int | None) -> dict:
        """Record a decision for the current book, advance, return the next payload."""
        with self.lock:
            book = self.current()
            if book is None:
                return self.book_payload()
            n_cands = len(book.candidates)
            if action == "pick" and choice and 1 <= choice <= n_cands:
                bdir = staging.book_dir(self.covers_dir, book.slug)
                apply_staged(book.review_path, bdir / book.candidates[choice - 1].file)
                self.state.record(book.slug, DONE, chosen=choice)
            elif action == "pick" and choice == n_cands + 1 and book.current:
                # Current cover is offered as the last option — already applied, just settle it.
                self.state.record(book.slug, DONE, chosen=0)
            elif action in ACTION_STATUS:
                self.state.record(book.slug, ACTION_STATUS[action])
            else:
                return self.book_payload()  # unknown action: no-op
            write_summary(self.covers_dir, self.state)
            self.index += 1
            return self.book_payload()


def _img_path(controller: Controller, slug: str, which: str) -> Path | None:
    book = staging.load_staging(controller.covers_dir, slug)
    if book is None:
        return None
    bdir = staging.book_dir(controller.covers_dir, slug)
    if which == "current":
        return bdir / book.current if book.current else None
    try:
        n = int(which)
    except ValueError:
        return None
    if 1 <= n <= len(book.candidates):
        return bdir / book.candidates[n - 1].file
    return None


def _handler(controller: Controller):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # silence default request logging
            pass

        def _send(self, code, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj).encode(), "application/json")

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/":
                self._send(200, PAGE.encode(), "text/html; charset=utf-8")
            elif path == "/api/state":
                self._json(controller.book_payload())
            elif path.startswith("/img/"):
                _, _, slug, which = path.split("/", 3)
                which = which.removesuffix(".jpg")
                p = _img_path(controller, slug, which)
                if p is None or not p.exists():
                    self._send(404, b"not found", "text/plain")
                    return
                try:
                    self._send(200, card_preview_bytes(p), "image/jpeg")
                except Exception:
                    self._send(500, b"render error", "text/plain")
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self):
            path = urlparse(self.path).path
            if path == "/api/decide":
                length = int(self.headers.get("Content-Length", 0))
                data = json.loads(self.rfile.read(length) or b"{}")
                if data.get("action") == "quit":
                    self._json({"done": True, "quit": True})
                    controller.done_event.set()
                    return
                self._json(controller.decide(data.get("action"), data.get("choice")))
            else:
                self._send(404, b"not found", "text/plain")

    return Handler


def run(covers_dir: Path, state: PickState, todo: list[staging.StagedBook],
        port: int = 8765, open_browser: bool = True) -> None:
    """Serve the picker on localhost and block until quit / all books decided."""
    controller = Controller(covers_dir=covers_dir, state=state, todo=todo)
    write_summary(covers_dir, state)  # ensure a summary exists even on an empty run

    server = ThreadingHTTPServer(("127.0.0.1", port), _handler(controller))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    url = f"http://127.0.0.1:{port}/"
    if open_browser:
        webbrowser.open(url)

    try:
        controller.done_event.wait()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Pick covers</title>
<style>
  :root { color-scheme: dark; }
  body { margin: 0; font: 15px/1.4 system-ui, sans-serif;
         background: #18181b; color: #ebebeb; }
  header { padding: 12px 20px; border-bottom: 1px solid #333;
           display: flex; gap: 16px; align-items: baseline; }
  header b { font-size: 17px; }
  .muted { color: #999; }
  main { padding: 20px; }
  .row { display: flex; flex-wrap: wrap; gap: 22px; align-items: flex-start; }
  figure { margin: 0; text-align: center; }
  figure img { width: 200px; height: 300px; border-radius: 4px;
               box-shadow: 0 4px 14px rgba(0,0,0,.5); background:#000; display:block; }
  figure.current img { outline: 2px solid #555; }
  figure.best figcaption .tag { color: #78c878; }
  figcaption { margin-top: 8px; font-size: 13px; }
  .key { display:inline-block; min-width: 20px; padding: 1px 7px; margin-right:6px;
         border:1px solid #666; border-radius:4px; font-weight:bold; }
  .legend { margin-top: 26px; color:#bbb; }
  .legend span { margin-right: 18px; }
  #done { font-size: 20px; padding: 40px 0; }
  kbd { background:#333; border-radius:3px; padding:1px 6px; }
</style>
</head>
<body>
<header>
  <b id="title">Loading…</b>
  <span class="muted" id="pos"></span>
  <span class="muted" id="slug"></span>
</header>
<main id="main"></main>

<script>
let state = null;

async function load() {
  state = await (await fetch('/api/state')).json();
  render();
}

function render() {
  const main = document.getElementById('main');
  if (state.done) {
    document.getElementById('title').textContent = state.quit ? 'Quit' : 'All done';
    document.getElementById('pos').textContent = '';
    document.getElementById('slug').textContent = '';
    main.innerHTML = '<div id="done">' +
      (state.quit ? 'Stopped. ' : 'Every staged book has been decided. ') +
      'Summary written to <kbd>covers/pick_summary.md</kbd>. You can close this tab.</div>';
    return;
  }
  document.getElementById('title').textContent = state.title;
  document.getElementById('pos').textContent = `(${state.index}/${state.total})`;
  document.getElementById('slug').textContent = state.slug;

  let html = '<div class="row">';
  const curRes = (state.current_width && state.current_height)
    ? ` · ${state.current_width}×${state.current_height}`
    : (state.current_width ? ` · ${state.current_width}px` : '');
  const curKey = state.candidates.length + 1;
  const cur = state.has_current
    ? `<figure class="current"><img src="/img/${state.slug}/current.jpg?t=${Date.now()}">` +
      `<figcaption><span class="key">${curKey}</span>current` +
      `<br><span class="muted">${curRes.replace(' · ', '')}</span></figcaption></figure>`
    : `<figure class="current"><img src=""><figcaption>no current cover</figcaption></figure>`;
  html += cur;

  state.candidates.forEach(c => {
    const best = c.n === 1 ? ' best' : '';
    html += `<figure class="${best}"><img src="/img/${state.slug}/${c.n}.jpg?t=${Date.now()}">` +
      `<figcaption><span class="key">${c.n}</span>${c.width}×${c.height}` +
      (c.n === 1 ? ' <span class="tag">★ best</span>' : '') +
      `<br><span class="muted">${c.title || c.source}</span></figcaption></figure>`;
  });
  html += '</div>';

  html += `<div class="legend">
    <span><span class="key">1</span>–<span class="key">${state.candidates.length}</span> apply</span>` +
    (state.has_current ? `<span><span class="key">${curKey}</span> keep current</span>` : '') + `
    <span><span class="key">s</span> skip</span>
    <span><span class="key">c</span> crop</span>
    <span><span class="key">r</span> replace</span>
    <span><span class="key">q</span> quit</span>
  </div>`;
  main.innerHTML = html;
}

async function decide(body) {
  state = await (await fetch('/api/decide',
    {method:'POST', headers:{'Content-Type':'application/json'},
     body: JSON.stringify(body)})).json();
  render();
}

document.addEventListener('keydown', e => {
  if (!state || state.done) return;
  const k = e.key;
  if (k >= '1' && k <= '9') {
    const n = parseInt(k, 10);
    const maxPick = state.candidates.length + (state.has_current ? 1 : 0);
    if (n <= maxPick) { e.preventDefault(); decide({action:'pick', choice:n}); }
  } else if (k === 's') { e.preventDefault(); decide({action:'skip'}); }
  else if (k === 'c') { e.preventDefault(); decide({action:'crop'}); }
  else if (k === 'r') { e.preventDefault(); decide({action:'replace'}); }
  else if (k === 'q') { e.preventDefault(); decide({action:'quit'}); }
});

load();
</script>
</body>
</html>"""
