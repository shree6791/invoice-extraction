"""Thin API over the LangGraph orchestrator."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.graph.graph import get_pipeline_graph
from backend.models.invoice import Invoice
from backend.models.layout import ParsedDocument
from backend.services.extract import ExtractResult, extract_metrics_dict
from backend.services.layout import layout_for_api


@dataclass
class PipelineResult:
    doc_id: str
    parsed: ParsedDocument
    extraction: ExtractResult

    @property
    def invoice(self) -> Invoice:
        return self.extraction.invoice

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "invoice": self.invoice.model_dump(),
            "values": self.invoice.values_only(),
            "markdown": self.parsed.markdown,
            "needs_review": self.invoice.needs_review,
            "unmapped_content": self.invoice.unmapped_content,
            "notes": self.invoice.notes,
            "layout": layout_for_api(self.parsed),
            "metrics": extract_metrics_dict(self.extraction),
        }


def run_pipeline(
    doc_id_or_path: str | Path,
    *,
    for_eval: bool = False,
    model: str | None = None,
) -> PipelineResult:
    """Invoke LangGraph: resolve_input → parse → extract."""
    graph = get_pipeline_graph()
    final = graph.invoke(
        {
            "doc_id_or_path": str(doc_id_or_path),
            "for_eval": for_eval,
            "model": model,
        }
    )
    return PipelineResult(
        doc_id=final["doc_id"],
        parsed=final["parsed"],
        extraction=final["extraction"],
    )
