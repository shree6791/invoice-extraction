"""POST /api/chat — grounded Q&A over extracted invoice JSON."""

from __future__ import annotations

from fastapi import APIRouter

from backend.schemas.chat import ChatRequest, ChatResponse
from backend.services.chat import ask_invoice

router = APIRouter(tags=["chat"])


@router.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    return ask_invoice(req.question, req.invoice)
