"""LangGraph pipeline state — shared across orchestrator nodes."""

from __future__ import annotations

from typing import Any, TypedDict


class PipelineState(TypedDict, total=False):
    """Mutable graph state. Add fields here when extending the graph."""

    # --- inputs ---
    doc_id_or_path: str
    for_eval: bool
    model: str | None

    # --- resolve_input ---
    doc_id: str
    pdf_path: str

    # --- parse ---
    parsed: Any  # ParsedDocument
    markdown: str

    # --- extract routing ---
    difficulty: str  # "easy" | "hard"
    fast_latency_s: float

    # --- extract ---
    extraction: Any  # ExtractResult
    invoice: Any  # Invoice
