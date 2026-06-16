"""Tests for the og-cover renderer (Slice 1).

Tests assert external behavior only — output size, that the whole source is
visible (nothing cropped), which axis the bars land on, and that the blur
parameter is honored. Sources are constructed in-test as PIL images.
"""
from __future__ import annotations

from PIL import Image

from review.covers import make_og_cover


def _gradient(w: int, h: int) -> Image.Image:
    """A non-uniform source so pixel comparisons are meaningful."""
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = (x % 256, y % 256, (x + y) % 256)
    return img


def _solid_with_edges(w: int, h: int, fill, edge, *, vertical: bool, band: int = 25) -> Image.Image:
    """Solid `fill` with the given edges painted `edge`.

    vertical=True paints the left/right columns; vertical=False the top/bottom rows.
    The painted edge is a `band`-px strip so it survives downscaling before the
    renderer samples its 1px edge.
    """
    img = Image.new("RGB", (w, h), fill)
    px = img.load()
    if vertical:
        for y in range(h):
            for b in range(band):
                px[b, y] = edge
                px[w - 1 - b, y] = edge
    else:
        for x in range(w):
            for b in range(band):
                px[x, b] = edge
                px[x, h - 1 - b] = edge
    return img


def test_output_is_always_400x600():
    for w, h in [(300, 450), (200, 600), (600, 300), (500, 500), (1000, 100)]:
        og = make_og_cover(_gradient(w, h))
        assert og.size == (400, 600)


def test_full_source_visible_no_crop():
    # Narrow source → side bars, but the whole cover must be visible inside.
    src = _gradient(200, 600)  # ratio 0.333 → fits to 200×600, centred at x=100
    og = make_og_cover(src, blur=0)
    region = og.crop((100, 0, 300, 600))
    assert region.tobytes() == src.tobytes()


def test_narrow_source_gets_side_bars():
    # ratio < 2:3 → bars on the left/right, image spans full height
    src = _solid_with_edges(200, 600, fill=(255, 255, 255), edge=(255, 0, 0), vertical=True)
    og = make_og_cover(src, blur=0)
    assert og.getpixel((10, 300)) == (255, 0, 0)      # left bar, from red edge column
    assert og.getpixel((200, 300)) == (255, 255, 255)  # image interior
    assert og.getpixel((200, 10)) == (255, 255, 255)   # image spans full height — no top bar


def test_wide_source_gets_top_bottom_bars():
    # ratio > 2:3 → bars on top/bottom, image spans full width
    src = _solid_with_edges(600, 300, fill=(255, 255, 255), edge=(255, 0, 0), vertical=False)
    og = make_og_cover(src, blur=0)
    assert og.getpixel((200, 10)) == (255, 0, 0)       # top bar, from red edge row
    assert og.getpixel((200, 300)) == (255, 255, 255)  # image interior (image at y∈[200,400))
    assert og.getpixel((10, 300)) == (255, 255, 255)   # image spans full width — no side bar


def test_blur_is_honored():
    src = _solid_with_edges(200, 600, fill=(255, 255, 255), edge=(255, 0, 0), vertical=True)
    sharp = make_og_cover(src, blur=0)
    blurred = make_og_cover(src, blur=20)
    probe = (95, 300)  # in the left bar, near the image boundary
    assert sharp.getpixel(probe) == (255, 0, 0)        # blur=0 → hard edge extension
    assert blurred.getpixel(probe) != (255, 0, 0)      # blur smears the bar near the boundary


def test_cover_crop_is_2_3_and_centred():
    # A square source must lose its left/right edges to become 2:3, keeping the centre.
    from review.covers import cover_crop
    src = Image.new("RGB", (600, 600), (255, 255, 255))
    for x in range(60):                                  # red bands on far left/right
        for y in range(600):
            src.putpixel((x, y), (255, 0, 0))
            src.putpixel((599 - x, y), (255, 0, 0))
    out = cover_crop(src, 400, 600)
    assert out.size == (400, 600)                        # exact 2:3
    assert out.getpixel((200, 300)) == (255, 255, 255)   # centre preserved
    assert out.getpixel((5, 300)) == (255, 255, 255)     # red side bands cropped away
