"""Shared extraction model primitives."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SourceNote(BaseModel):
    """Grounding: where on the document the value came from."""

    page: int | None = None  # 0-indexed
    quote: str | None = None
    bbox: list[float] | None = None
    confidence: float | None = None


class FieldValue(BaseModel):
    value: str | None = None
    page: int | None = None
    bbox: list[float] | None = Field(
        default=None,
        description="Normalized [x0,y0,x1,y1] in 0-1 page coordinates",
    )
    source: SourceNote | None = None
