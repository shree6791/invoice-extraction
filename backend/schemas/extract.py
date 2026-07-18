"""POST /api/extract request body."""

from __future__ import annotations

from pydantic import BaseModel


class ExtractRequest(BaseModel):
    doc_id: str
    model: str | None = None
