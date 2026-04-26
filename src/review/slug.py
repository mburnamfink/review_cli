from __future__ import annotations

import re
import unicodedata


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


def make_slug(title: str, authors: list[dict], review_type: str) -> str:
    title_slug = slugify(title)

    if review_type == "audiobook":
        author = next((a for a in authors if a.get("role") == "author"), None)
        narrator = next((a for a in authors if a.get("role") == "narrator"), None)
        parts = [title_slug]
        if author:
            parts.append(slugify(author["last"]))
        if narrator:
            parts.append(slugify(narrator["last"]))
        return "-".join(parts)

    primary = [a for a in authors if a.get("role") in ("author", "editor")]
    parts = [title_slug] + [slugify(a["last"]) for a in primary[:2]]
    return "-".join(parts)
