"""GET /api/samples response shapes."""

from __future__ import annotations

from pydantic import BaseModel


class SampleInfo(BaseModel):
    doc_id: str
    page_count: int | None = None
    cluster_id: int | None = None
    document_type: str | None = None


class SamplesResponse(BaseModel):
    samples: list[SampleInfo]
