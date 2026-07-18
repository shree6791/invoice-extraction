"""Stage 2 extract helpers — MockFast / Claude + grounding.

Orchestration (easy vs hard, escalate) lives in the LangGraph conditional
edges — see ``backend/graph/graph.py``. These functions are the node bodies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.llm import (
    EXTRACT_SYSTEM_PROMPT,
    EXTRACT_USER_TEMPLATE,
    JSON_REPAIR_USER,
    complete,
    estimate_cost,
    get_client,
    parse_json_loose,
)
from backend.llm.mock_fast import MODEL_NAME as FAST_MODEL_NAME
from backend.llm.mock_fast import mock_fast_extract
from backend.models.invoice import Invoice, InvoiceDraft
from backend.models.layout import ParsedDocument
from backend.services.extract.grounding import attach_grounding
from backend.settings.config import MODEL_DEMO, MODEL_EVAL


@dataclass
class ExtractResult:
    invoice: Invoice
    model: str
    latency_s: float
    input_tokens: int
    output_tokens: int
    cost_usd: float
    raw_draft: dict[str, Any]
    markdown: str = ""
    routing: str = "claude-direct"  # mock-fast | mock-fast→claude | claude-direct
    escalated: bool = False


def extract_metrics_dict(extraction: ExtractResult) -> dict[str, Any]:
    return {
        "model": extraction.model,
        "routing": extraction.routing,
        "escalated": extraction.escalated,
        "latency_s": round(extraction.latency_s, 3),
        "input_tokens": extraction.input_tokens,
        "output_tokens": extraction.output_tokens,
        "cost_usd": round(extraction.cost_usd, 6),
    }


def resolve_extract_model(*, for_eval: bool = False, model: str | None = None) -> str:
    return model or (MODEL_EVAL if for_eval else MODEL_DEMO)


def run_mock_fast(parsed: ParsedDocument) -> ExtractResult:
    """Fast-path extract (MockFast stand-in for LayoutLM / small GPU)."""
    layout = parsed.markdown or ""
    if not layout:
        raise RuntimeError("Stage 1 markdown missing — parse step did not run")
    draft, fast_latency = mock_fast_extract(layout)
    invoice = attach_grounding(draft, parsed)
    return ExtractResult(
        invoice=invoice,
        model=FAST_MODEL_NAME,
        latency_s=fast_latency,
        input_tokens=0,
        output_tokens=0,
        cost_usd=0.0,
        raw_draft=draft.model_dump(),
        markdown=layout,
        routing="mock-fast",
        escalated=False,
    )


def run_claude(
    parsed: ParsedDocument,
    *,
    model: str,
    escalated_from: str | None = None,
    prior_latency_s: float = 0.0,
) -> ExtractResult:
    """Claude extract. Set escalated_from when coming from the fast path."""
    layout = parsed.markdown or ""
    if not layout:
        raise RuntimeError("Stage 1 markdown missing — parse step did not run")

    client = get_client()
    user_msg = EXTRACT_USER_TEMPLATE.format(layout=layout)
    messages = [{"role": "user", "content": user_msg}]

    first = complete(
        client, model=model, system=EXTRACT_SYSTEM_PROMPT, messages=messages
    )
    latency = first.latency_s
    in_tok = first.input_tokens
    out_tok = first.output_tokens
    raw_text = first.text

    try:
        data = parse_json_loose(raw_text)
    except Exception:
        repair = complete(
            client,
            model=model,
            system=EXTRACT_SYSTEM_PROMPT,
            messages=[
                *messages,
                {"role": "assistant", "content": raw_text},
                {"role": "user", "content": JSON_REPAIR_USER},
            ],
        )
        latency += repair.latency_s
        in_tok += repair.input_tokens
        out_tok += repair.output_tokens
        raw_text = repair.text
        data = parse_json_loose(raw_text)

    draft = InvoiceDraft.model_validate(data)
    invoice = attach_grounding(draft, parsed)
    routing = f"{escalated_from}→claude" if escalated_from else "claude-direct"

    return ExtractResult(
        invoice=invoice,
        model=model,
        latency_s=latency + prior_latency_s,
        input_tokens=in_tok,
        output_tokens=out_tok,
        cost_usd=estimate_cost(model, in_tok, out_tok),
        raw_draft=draft.model_dump(),
        markdown=layout,
        routing=routing,
        escalated=escalated_from is not None,
    )


def extract_invoice(
    parsed: ParsedDocument,
    *,
    model: str | None = None,
    for_eval: bool = False,
) -> ExtractResult:
    """Imperative cascade (tests / one-offs). Prefer the LangGraph path in prod."""
    from backend.services.extract.escalation import classify_difficulty

    model = resolve_extract_model(for_eval=for_eval, model=model)
    difficulty = classify_difficulty(parsed)
    if difficulty == "easy":
        fast = run_mock_fast(parsed)
        if not fast.invoice.needs_review:
            return fast
        return run_claude(
            parsed,
            model=model,
            escalated_from=FAST_MODEL_NAME,
            prior_latency_s=fast.latency_s,
        )
    return run_claude(parsed, model=model, escalated_from=None)
