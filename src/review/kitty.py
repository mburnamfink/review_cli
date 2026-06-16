"""Inline cover rendering for the ``pick-covers`` loop (kitty terminal, Slice 4).

Builds a single contact sheet — the current cover plus numbered candidates — and
displays it inline using kitty's graphics protocol via ``kitten icat``. One
composite image means one render call and one stable layout; the numeric labels
are burned into the image so they stay aligned with the art. If kitty isn't
available the caller can fall back to printing file paths.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

THUMB_H = 340          # thumbnail height in px
PAD = 14               # gap between cells / margin
LABEL_H = 30           # label strip height above each thumbnail
BG = (24, 24, 27)      # near-black backdrop
FG = (235, 235, 235)
ACCENT = (120, 200, 120)


def kitty_available() -> bool:
    return shutil.which("kitten") is not None or shutil.which("kitty") is not None


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _thumb(path: Path) -> Image.Image:
    img = Image.open(path).convert("RGB")
    w = max(1, round(img.width * THUMB_H / img.height))
    return img.resize((w, THUMB_H), Image.LANCZOS)


def build_contact_sheet(
    current: Path | None,
    candidates: list[Path],
) -> Image.Image:
    """Compose ``[current] [1] [2] …`` into one labelled horizontal strip."""
    cells: list[tuple[str, Image.Image]] = []
    if current is not None and current.exists():
        cells.append(("current", _thumb(current)))
    for i, c in enumerate(candidates, 1):
        cells.append((str(i), _thumb(c)))

    if not cells:
        return Image.new("RGB", (THUMB_H, THUMB_H), BG)

    cell_h = LABEL_H + THUMB_H
    total_w = PAD + sum(t.width + PAD for _, t in cells)
    sheet = Image.new("RGB", (total_w, cell_h + PAD), BG)
    draw = ImageDraw.Draw(sheet)
    font = _font(20)

    x = PAD
    for label, thumb in cells:
        colour = FG if label == "current" else ACCENT
        text = label if label == "current" else f"[{label}]"
        draw.text((x, PAD // 2), text, fill=colour, font=font)
        sheet.paste(thumb, (x, LABEL_H))
        x += thumb.width + PAD

    return sheet


def show(image: Image.Image) -> None:
    """Render an image inline at the cursor via ``kitten icat``."""
    cmd = (
        ["kitten", "icat", "--align", "left"]
        if shutil.which("kitten")
        else ["kitty", "+kitten", "icat", "--align", "left"]
    )
    with tempfile.NamedTemporaryFile(suffix=".png", delete=True) as tmp:
        image.save(tmp.name, "PNG")
        subprocess.run([*cmd, tmp.name], check=False)


def render(current: Path | None, candidates: list[Path]) -> None:
    show(build_contact_sheet(current, candidates))
