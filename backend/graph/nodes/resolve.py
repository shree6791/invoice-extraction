"""resolve_input node."""

from __future__ import annotations

from pathlib import Path

from backend.dataset.loader import pdf_path as docile_pdf_path
from backend.graph.state import PipelineState


def resolve_input(state: PipelineState) -> dict:
    """Resolve DocILE id or local PDF path → concrete pdf + doc_id."""
    raw = state["doc_id_or_path"]
    path = Path(raw)
    if path.suffix.lower() == ".pdf" and path.exists():
        doc_id = path.stem
        pdf = path
    else:
        doc_id = str(raw)
        pdf = docile_pdf_path(doc_id)
        if not pdf.exists():
            raise FileNotFoundError(f"PDF not found for {doc_id}: {pdf}")

    return {
        "doc_id": doc_id,
        "pdf_path": str(pdf),
    }
