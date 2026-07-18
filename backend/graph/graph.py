"""LangGraph orchestrator — parse → classify → (mock-fast | claude) → finalize.

::

    resolve_input → parse → classify_extract
                              │
              easy ───────────┼─────────── hard
              ▼                           ▼
        extract_mock_fast           extract_claude
              │                           │
              ├─ needs_review ─► extract_claude
              │                           │
              └─ clean ───────────────────┴─► finalize_extract → END
"""

from __future__ import annotations

from functools import lru_cache

from langgraph.graph import END, START, StateGraph

from backend.graph.nodes.extract import (
    classify_extract,
    extract_claude,
    extract_mock_fast,
    finalize_extract,
    route_after_classify,
    route_after_mock_fast,
)
from backend.graph.nodes.parse import parse_document
from backend.graph.nodes.resolve import resolve_input
from backend.graph.state import PipelineState


def build_pipeline_graph():
    builder = StateGraph(PipelineState)

    builder.add_node("resolve_input", resolve_input)
    builder.add_node("parse", parse_document)
    builder.add_node("classify_extract", classify_extract)
    builder.add_node("extract_mock_fast", extract_mock_fast)
    builder.add_node("extract_claude", extract_claude)
    builder.add_node("finalize_extract", finalize_extract)

    builder.add_edge(START, "resolve_input")
    builder.add_edge("resolve_input", "parse")
    builder.add_edge("parse", "classify_extract")
    builder.add_conditional_edges(
        "classify_extract",
        route_after_classify,
        {
            "extract_mock_fast": "extract_mock_fast",
            "extract_claude": "extract_claude",
        },
    )
    builder.add_conditional_edges(
        "extract_mock_fast",
        route_after_mock_fast,
        {
            "extract_claude": "extract_claude",
            "finalize_extract": "finalize_extract",
        },
    )
    builder.add_edge("extract_claude", "finalize_extract")
    builder.add_edge("finalize_extract", END)

    return builder.compile()


@lru_cache(maxsize=1)
def get_pipeline_graph():
    return build_pipeline_graph()
