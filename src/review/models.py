from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class Contributor(BaseModel):
    first: str
    last: str
    role: Literal["author", "editor", "contributor", "narrator"] = "author"


class ReadRecord(BaseModel):
    year: int
    date_started: Optional[date] = None
    date_finished: Optional[date] = None
    dnf: bool = False


class ReviewBase(BaseModel):
    title: str
    authors: list[Contributor]
    type: Literal["book", "audiobook", "rpg", "other"]
    isbn: Optional[str] = None
    publication_year: Optional[int] = None
    publisher: Optional[str] = None
    rating: Optional[float] = Field(None, ge=1.0, le=5.0)
    date_reviewed: date
    reads: list[ReadRecord]
    tags: list[str] = Field(default_factory=list)
    cover: Optional[str] = None
    og_cover: Optional[str] = None
    bsky_post: Optional[str] = None

    @field_validator("rating")
    @classmethod
    def rating_half_steps(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return v
        if (v * 2) != int(v * 2):
            raise ValueError("rating must be in 0.5 steps")
        return v

    @field_validator("reads")
    @classmethod
    def reads_not_empty(cls, v: list[ReadRecord]) -> list[ReadRecord]:
        if not v:
            raise ValueError("reads must have at least one entry")
        return v


class BookReview(ReviewBase):
    type: Literal["book"] = "book"
    page_count: Optional[int] = None


class AudiobookReview(ReviewBase):
    type: Literal["audiobook"] = "audiobook"
    narrator: Optional[Contributor] = None
    runtime_hours: Optional[float] = None
    abridged: bool = False


class RpgReview(ReviewBase):
    type: Literal["rpg"] = "rpg"
    system: Optional[str] = None


class OtherReview(ReviewBase):
    type: Literal["other"] = "other"
    medium: Optional[str] = None


REVIEW_MODELS = {
    "book": BookReview,
    "audiobook": AudiobookReview,
    "rpg": RpgReview,
    "other": OtherReview,
}


def parse_review(data: dict) -> ReviewBase:
    review_type = data.get("type", "book")
    model = REVIEW_MODELS.get(review_type, BookReview)
    return model.model_validate(data)
