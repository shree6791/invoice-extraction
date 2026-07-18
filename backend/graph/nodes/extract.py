"""LangGraph extract nodes — MockFast / Claude with conditional escalation."""

from __future__ import annotations

from backend.graph.state import PipelineState
from backend.llm.mock_fast import MODEL_NAME as FAST_MODEL_NAME
from backend.services.extract.escalation import classify_difficulty
from backend.services.extract.service import (
    resolve_extract_model,
    run_claude,
    run_mock_fast,
)


def classify_extract(state: PipelineState) -> dict:
    """Tag difficulty for the conditional edge after parse."""
    return {"difficulty": classify_difficulty(state["parsed"])}


def extract_mock_fast(state: PipelineState) -> dict:
    """Easy path: cheap/fast extractor (MockFast stand-in)."""
    result = run_mock_fast(state["parsed"])
    return {
        "extraction": result,
        "invoice": result.invoice,
        "fast_latency_s": result.latency_s,
    }


def extract_claude(state: PipelineState) -> dict:
    """Claude path — direct (hard) or escalated from MockFast."""
    model = resolve_extract_model(
        for_eval=bool(state.get("for_eval")),
        model=state.get("model"),
    )
    prior = float(state.get("fast_latency_s") or 0.0)
    # Escalation if we already ran mock-fast and still need review.
    escalated_from = None
    prev = state.get("extraction")
    if prev is not None and getattr(prev, "routing", "") == "mock-fast":
        escalated_from = FAST_MODEL_NAME
        prior = float(getattr(prev, "latency_s", 0.0) or prior)

    result = run_claude(
        state["parsed"],
        model=model,
        escalated_from=escalated_from,
        prior_latency_s=prior if escalated_from else 0.0,
    )
    return {"extraction": result, "invoice": result.invoice}


def finalize_extract(state: PipelineState) -> dict:
    """Terminal no-op (keeps graph join after mock-fast / claude)."""
    return {}


def route_after_classify(state: PipelineState) -> str:
    """Conditional: hard → Claude; easy → MockFast."""
    return "extract_claude" if state.get("difficulty") == "hard" else "extract_mock_fast"


def route_after_mock_fast(state: PipelineState) -> str:
    """Conditional: needs_review → escalate Claude; else finalize."""
    invoice = state.get("invoice")
    if invoice is not None and invoice.needs_review:
        return "extract_claude"
    return "finalize_extract"
