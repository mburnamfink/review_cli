from __future__ import annotations

import tomllib
import tomli_w
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_PATH = Path.home() / ".review" / "config.toml"
CACHE_DIR = Path.home() / ".review" / "cache"


@dataclass
class Config:
    content_dir: Path = field(default_factory=lambda: Path.home() / "content" / "reviews")
    canonical_tags: list[str] = field(default_factory=list)

    @classmethod
    def load(cls) -> "Config":
        if not CONFIG_PATH.exists():
            return cls()
        with open(CONFIG_PATH, "rb") as f:
            data = tomllib.load(f)
        content_dir = Path(data.get("content_dir", str(Path.home() / "content" / "reviews")))
        canonical_tags = data.get("tags", {}).get("canonical", [])
        return cls(content_dir=content_dir, canonical_tags=canonical_tags)

    def save(self) -> None:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        data: dict = {
            "content_dir": str(self.content_dir),
            "tags": {"canonical": sorted(self.canonical_tags)},
        }
        with open(CONFIG_PATH, "wb") as f:
            tomli_w.dump(data, f)
