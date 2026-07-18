"""parse node — Stage 1 layout."""

from __future__ import annotations

from backend.graph.state import PipelineState
from backend.services.layout import parse_pdf


def parse_document(state: PipelineState) -> dict:
    """Stage 1 — layout parse → markdown."""
    parsed = parse_pdf(state["pdf_path"], doc_id=state["doc_id"])
    return {
        "parsed": parsed,
        "markdown": parsed.markdown,
    }
