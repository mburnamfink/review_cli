from __future__ import annotations

from pathlib import Path

from PIL import Image
import io


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

    # og-cover.jpg — exactly 400×600, centre-cropped
    og = _centre_crop(img, 400, 600)
    og_path = dest_dir / "og-cover.jpg"
    og.save(og_path, "JPEG", quality=88)

    return "./cover.jpg", "./og-cover.jpg"


def _centre_crop(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    target_ratio = target_w / target_h
    src_ratio = img.width / img.height

    if src_ratio > target_ratio:
        # image is wider than target — crop sides
        new_w = int(img.height * target_ratio)
        left = (img.width - new_w) // 2
        img = img.crop((left, 0, left + new_w, img.height))
    else:
        # image is taller than target — crop top/bottom
        new_h = int(img.width / target_ratio)
        top = (img.height - new_h) // 2
        img = img.crop((0, top, img.width, top + new_h))

    return img.resize((target_w, target_h), Image.LANCZOS)
