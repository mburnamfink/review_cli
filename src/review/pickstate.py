"""Persistent state for the ``pick-covers`` loop (Slice 4).

A small JSON manifest at ``covers/.pick_state.json`` records, per review slug, the
outcome of a pick session so the loop is resumable: re-running skips books
already marked ``done`` and revisits everything else (the "second pass" over
``skipped`` / ``needs-manual`` books). Pure file I/O + dict bookkeeping, so it's
unit-tested independently of the terminal/network parts of the command.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

# Per-book status values.
DONE = "done"            # a candidate was picked and applied — never revisit
SKIPPED = "skipped"      # deferred for now — revisit next pass
NEEDS_MANUAL = "needs-manual"  # all candidates rejected — handle by hand, but still offered next pass
NEEDS_CROP = "needs-crop"      # one candidate is good but must be cropped by hand — settled, not re-offered
NEEDS_REPLACE = "needs-replace"  # no usable candidate — source a cover manually — settled, not re-offered

# Statuses that are settled: re-running the picker does not offer them again.
# SKIPPED is deliberately absent — "come back later" means revisit next pass.
SETTLED = frozenset({DONE, NEEDS_CROP, NEEDS_REPLACE})


@dataclass
class PickState:
    path: Path
    books: dict[str, dict] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "PickState":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            books = data.get("books", {}) if isinstance(data, dict) else {}
        except (FileNotFoundError, ValueError):
            books = {}
        return cls(path=path, books=books)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"books": self.books}, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def status(self, slug: str) -> str | None:
        rec = self.books.get(slug)
        return rec.get("status") if rec else None

    def is_done(self, slug: str) -> bool:
        """A finished book is never re-processed; everything else is fair game."""
        return self.status(slug) == DONE

    def is_settled(self, slug: str) -> bool:
        """Settled = applied, crop, or replace — never re-offered (skip is not settled)."""
        return self.status(slug) in SETTLED

    def slugs_with_status(self, status: str) -> list[str]:
        """All slugs currently recorded with the given status, sorted."""
        return sorted(s for s, r in self.books.items() if r.get("status") == status)

    def record(
        self,
        slug: str,
        status: str,
        chosen: int | None = None,
        hashes: list[int] | None = None,
    ) -> None:
        """Set a book's outcome and persist immediately (interrupt-safe)."""
        rec = self.books.setdefault(slug, {})
        rec["status"] = status
        if chosen is not None:
            rec["chosen"] = chosen
        if hashes is not None:
            rec["hashes"] = hashes
        self.save()

    def needs_manual(self) -> list[str]:
        """Slugs whose candidates were all rejected — the manual-resolution list."""
        return sorted(s for s, r in self.books.items() if r.get("status") == NEEDS_MANUAL)
