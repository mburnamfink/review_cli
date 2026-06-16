from __future__ import annotations

import tomllib
import tomli_w
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_PATH = Path.home() / ".review" / "config.toml"
CACHE_DIR = Path.home() / ".review" / "cache"

# review-cli lives at <project>/review-cli/; default content is <project>/site/content/reviews/
_DEFAULT_CONTENT_DIR = Path(__file__).parent.parent.parent.parent / "site" / "content" / "reviews"


@dataclass
class Config:
    content_dir: Path = field(default_factory=lambda: _DEFAULT_CONTENT_DIR)
    canonical_tags: list[str] = field(default_factory=list)
    librarything_api_key: str | None = None
    editor: str | None = None
    # Default cover source for `new` / `fetch-cover`:
    #   "openlibrary" — httpx-only, no browser (bulletproof default)
    #   "amazon"      — full-res Amazon master first, then OpenLibrary/WorldCat
    #   "auto"        — like "amazon" when a browser is installed, else "openlibrary"
    cover_source: str = "openlibrary"

    @property
    def covers_dir(self) -> Path:
        """Staging directory for candidate covers (<project>/covers)."""
        # content_dir is <project>/site/content/reviews; covers sits at <project>/covers
        return self.content_dir.parent.parent.parent / "covers"

    @classmethod
    def load(cls) -> "Config":
        if not CONFIG_PATH.exists():
            return cls()
        with open(CONFIG_PATH, "rb") as f:
            data = tomllib.load(f)
        content_dir = Path(data.get("content_dir", str(_DEFAULT_CONTENT_DIR)))
        canonical_tags = data.get("tags", {}).get("canonical", [])
        librarything_api_key = data.get("librarything_api_key") or None
        editor = data.get("editor") or None
        cover_source = data.get("cover_source") or "openlibrary"
        return cls(
            content_dir=content_dir,
            canonical_tags=canonical_tags,
            librarything_api_key=librarything_api_key,
            editor=editor,
            cover_source=cover_source,
        )

    def save(self) -> None:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        data: dict = {
            "content_dir": str(self.content_dir),
            "tags": {"canonical": sorted(self.canonical_tags)},
        }
        if self.librarything_api_key:
            data["librarything_api_key"] = self.librarything_api_key
        if self.editor:
            data["editor"] = self.editor
        if self.cover_source and self.cover_source != "openlibrary":
            data["cover_source"] = self.cover_source
        with open(CONFIG_PATH, "wb") as f:
            tomli_w.dump(data, f)
