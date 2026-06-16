from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageFilter
import io

# Default blur radius applied to the synthesized edge-extension bars. Tuned live
# during real cover runs: higher values wash out streaks on busy/photographic
# edges, lower values keep solid edges crisp.
DEFAULT_OG_BLUR = 24


def process_cover(raw_bytes: bytes, dest_dir: Path) -> tuple[str, str]:
    """
    Given raw image bytes, write cover.jpg and og-cover.jpg into dest_dir.
    Returns (cover_path, og_cover_path) as relative strings.
    """
    img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")

    # cover.jpg — max 800px wide, aspect preserved
    cover = img.copy()
    cover.thumbnail((800, 10000), Image.LANCZOS)
    cover_path = dest_dir / "cover.jpg"
    cover.save(cover_path, "JPEG", quality=88)

    # og-cover.jpg — exactly 400×600, whole cover fit inside (never cropped),
    # bars filled by extending the cover's edge colour outward.
    og = make_og_cover(img, 400, 600)
    og_path = dest_dir / "og-cover.jpg"
    og.save(og_path, "JPEG", quality=88)

    return "./cover.jpg", "./og-cover.jpg"


def regenerate_og_cover(cover_path: Path) -> Path:
    """Rebuild og-cover.jpg from an existing cover.jpg (e.g. after cropping).

    Reads the cover in place and writes og-cover.jpg beside it, leaving the
    cover file itself untouched. Returns the og-cover path.
    """
    with Image.open(cover_path) as img:
        og = make_og_cover(img.convert("RGB"), 400, 600)
    og_path = cover_path.parent / "og-cover.jpg"
    og.save(og_path, "JPEG", quality=88)
    return og_path


def cover_crop(
    img: Image.Image,
    width: int = 400,
    height: int = 600,
) -> Image.Image:
    """Center-crop the source to a width×height (2:3) frame, like CSS object-fit:cover.

    This is exactly how the site's grid/list views display ``cover.jpg``: the image
    is scaled to *cover* the 2:3 box (shortest side fills) and the overflow is
    cropped off evenly from the centre. Use this — not ``make_og_cover`` — to
    preview how a candidate will look on the main page.
    """
    img = img.convert("RGB")
    scale = max(width / img.width, height / img.height)
    new_w = max(width, round(img.width * scale))
    new_h = max(height, round(img.height * scale))
    resized = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - width) // 2
    top = (new_h - height) // 2
    return resized.crop((left, top, left + width, top + height))


def make_og_cover(
    img: Image.Image,
    width: int = 400,
    height: int = 600,
    blur: int = DEFAULT_OG_BLUR,
) -> Image.Image:
    """Fit the whole source image inside a width×height frame without cropping.

    The source is scaled to fit (aspect preserved) and centred. The residual
    bars are filled by sampling a one-pixel strip of the nearest source edge and
    stretching it outward, then blurring the whole background by ``blur`` so the
    extension reads as seamless padding rather than a hard streak.

    No source pixels are discarded — the entire scaled cover is visible inside
    the returned image. ``blur=0`` yields a hard (un-blurred) edge extension.
    """
    img = img.convert("RGB")
    target_ratio = width / height
    src_ratio = img.width / img.height

    # Scale the whole source to fit inside the target box (aspect preserved).
    if src_ratio > target_ratio:
        # wider than target — full width, bars on top/bottom
        new_w = width
        new_h = max(1, round(width / src_ratio))
    else:
        # taller/narrower than target — full height, bars on left/right
        new_h = height
        new_w = max(1, round(height * src_ratio))

    scaled = img.resize((new_w, new_h), Image.LANCZOS)
    offset_x = (width - new_w) // 2
    offset_y = (height - new_h) // 2

    background = _edge_extend(scaled, width, height, offset_x, offset_y)
    if blur > 0:
        background = background.filter(ImageFilter.GaussianBlur(blur))

    background.paste(scaled, (offset_x, offset_y))
    return background


def _edge_extend(
    scaled: Image.Image,
    width: int,
    height: int,
    offset_x: int,
    offset_y: int,
) -> Image.Image:
    """Build a width×height background by stretching the scaled image's edges.

    The scaled image always fills one target dimension exactly (it was fit to
    the box), so bars only ever appear on a single axis:

    - ``offset_x > 0`` → side bars, fed by stretching the left/right edge columns.
    - ``offset_y > 0`` → top/bottom bars, fed by stretching the top/bottom rows.
    """
    sw, sh = scaled.size
    bg = Image.new("RGB", (width, height))

    if offset_x > 0:
        # bars on left/right — scaled spans full height (sh == height, offset_y == 0)
        left_col = scaled.crop((0, 0, 1, sh)).resize((offset_x, sh), Image.LANCZOS)
        right_x = offset_x + sw
        right_col = scaled.crop((sw - 1, 0, sw, sh)).resize((width - right_x, sh), Image.LANCZOS)
        bg.paste(left_col, (0, 0))
        bg.paste(right_col, (right_x, 0))
    elif offset_y > 0:
        # bars on top/bottom — scaled spans full width (sw == width, offset_x == 0)
        top_row = scaled.crop((0, 0, sw, 1)).resize((sw, offset_y), Image.LANCZOS)
        bottom_y = offset_y + sh
        bottom_row = scaled.crop((0, sh - 1, sw, sh)).resize((sw, height - bottom_y), Image.LANCZOS)
        bg.paste(top_row, (0, 0))
        bg.paste(bottom_row, (0, bottom_y))

    return bg
