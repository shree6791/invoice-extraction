"""Grounded Q&A over final extracted invoice JSON."""

from __future__ import annotations

import json
import re
from typing import Any

from backend.llm import CHAT_SYSTEM_PROMPT, complete, get_client, parse_json_loose
from backend.schemas.chat import ChatCitation, ChatResponse
from backend.settings.config import MODEL_DEMO
from backend.settings.constants.fields import SOURCE_CONFIDENCE_THRESHOLD

_FIELD_PATH = re.compile(r"^([a-z_]+)(?:\[(\d+)\])?(?:\.([a-z_]+))?$")


def _resolve_field(invoice: dict[str, Any], field_path: str) -> dict[str, Any] | None:
    m = _FIELD_PATH.match(field_path.strip())
    if not m:
        return None
    head, idx, leaf = m.group(1), m.group(2), m.group(3)

    if idx is None and leaf is None:
        node = invoice.get(head)
        return node if isinstance(node, dict) and "value" in node else None

    if idx is not None and leaf is not None:
        items = invoice.get(head)
        if not isinstance(items, list):
            return None
        i = int(idx)
        if i < 0 or i >= len(items):
            return None
        row = items[i]
        if not isinstance(row, dict):
            return None
        node = row.get(leaf)
        return node if isinstance(node, dict) and "value" in node else None

    return None


def _grounded_citation(
    invoice: dict[str, Any], field_path: str
) -> ChatCitation | None:
    node = _resolve_field(invoice, field_path)
    if not node:
        return None
    source = node.get("source") or {}
    if not isinstance(source, dict):
        return None
    conf = source.get("confidence")
    page = source.get("page")
    quote = source.get("quote")
    if conf is None or float(conf) < SOURCE_CONFIDENCE_THRESHOLD:
        return None
    if page is None or not quote:
        return None
    return ChatCitation(
        field=field_path,
        page=int(page),
        quote=str(quote),
        confidence=round(float(conf), 3),
    )


def _validate_response(
    invoice: dict[str, Any], parsed: dict[str, Any]
) -> ChatResponse:
    answer = str(parsed.get("answer") or "").strip()
    uncertain = {str(f) for f in (parsed.get("uncertain_fields") or []) if f}

    citations: list[ChatCitation] = []
    seen: set[str] = set()
    for raw in parsed.get("citations") or []:
        if not isinstance(raw, dict):
            continue
        field_path = str(raw.get("field") or "").strip()
        if not field_path or field_path in seen:
            continue
        seen.add(field_path)
        cite = _grounded_citation(invoice, field_path)
        if cite:
            citations.append(cite)
        else:
            uncertain.add(field_path)

    uncertain_list = sorted(uncertain)
    if uncertain_list and "cannot confidently ground" not in answer.lower():
        answer += (
            "\n\nNote: could not confidently ground: "
            + ", ".join(uncertain_list)
            + "."
        )

    return ChatResponse(
        answer=answer or "No answer generated.",
        citations=citations,
        uncertain_fields=uncertain_list,
    )


def ask_invoice(question: str, invoice: dict[str, Any]) -> ChatResponse:
    question = (question or "").strip()
    if not question:
        return ChatResponse(answer="Question is empty.", citations=[], uncertain_fields=[])
    if not invoice:
        return ChatResponse(
            answer="No extracted invoice JSON provided.",
            citations=[],
            uncertain_fields=[],
        )

    client = get_client()
    user_msg = (
        "FINAL extracted invoice JSON:\n"
        f"{json.dumps(invoice, ensure_ascii=False)}\n\n"
        f"User question:\n{question}\n\n"
        "Answer using ONLY the JSON above. Cite field paths only."
    )

    completion = complete(
        client,
        model=MODEL_DEMO,
        system=CHAT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
        max_tokens=800,
    )

    try:
        parsed = parse_json_loose(completion.text)
        if isinstance(parsed, dict):
            return _validate_response(invoice, parsed)
    except Exception:
        pass

    return ChatResponse(
        answer=completion.text.strip() or "Could not parse a grounded answer.",
        citations=[],
        uncertain_fields=[],
    )
