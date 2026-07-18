"""HTTP chat request/response schemas (grounded over extracted invoice JSON)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatCitation(BaseModel):
    field: str = Field(..., description="Invoice field key (e.g. 'total').")
    page: int | None = None
    quote: str | None = None
    confidence: float | None = None


class ChatResponse(BaseModel):
    answer: str
    citations: list[ChatCitation] = []
    uncertain_fields: list[str] = []


class ChatRequest(BaseModel):
    question: str
    invoice: dict[str, Any]
