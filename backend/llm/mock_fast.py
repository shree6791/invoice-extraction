"""MockFastExtractor — regex-based extraction simulating a self-hosted fine-tuned 7B model.

In the production escalation cascade this slot is filled by a LayoutLMv3 or a fine-tuned
Llama/Qwen model served via vLLM at ~1 s/doc. Here we use regex on the Stage-1 markdown to
demonstrate the same interface and routing behaviour without a real GPU.

Contract:
  - Fast (< 5 ms wall-clock — simulates 1 s GPU inference)
  - Returns an InvoiceDraft; uncertain fields go to needs_review
  - Caller checks needs_review: non-empty → escalate to Claude
  - Tags output with model="mock-fast-7b" for observability

Production swap:
    Replace _regex_extract() with an HTTP call to the vLLM endpoint:
        resp = httpx.post(VLLM_URL, json={"prompt": markdown, ...})
        return InvoiceDraft(**resp.json())
"""

from __future__ import annotations

import re
import time

from backend.models.invoice import InvoiceDraft, LineItemDraft

MODEL_NAME = "mock-fast-7b"

# ---------------------------------------------------------------------------
# Regex patterns (applied to Stage-1 markdown)
# ---------------------------------------------------------------------------

_RE_INVOICE_ID = re.compile(
    r"(?:invoice\s*(?:no\.?|number|#|id)[:\s]*|inv[-\s]?)([\w\-/]+)",
    re.IGNORECASE,
)
_RE_DATE = re.compile(
    r"\b(\d{4}[-/]\d{2}[-/]\d{2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b"
)
_RE_AMOUNT = re.compile(r"[\$€£]?\s*(\d[\d,]*\.?\d{0,2})")
_RE_TOTAL = re.compile(
    r"(?:grand\s+)?total[:\s]+[\$€£]?\s*(\d[\d,]*\.?\d{0,2})",
    re.IGNORECASE,
)
_RE_SUBTOTAL = re.compile(
    r"(?:sub\s*total|net\s+total|amount\s+before\s+tax)[:\s]+[\$€£]?\s*(\d[\d,]*\.?\d{0,2})",
    re.IGNORECASE,
)
_RE_TAX = re.compile(
    r"(?:tax|vat|gst)[:\s]+[\$€£]?\s*(\d[\d,]*\.?\d{0,2})",
    re.IGNORECASE,
)
# Markdown table row: | col | col | ... |
_RE_TABLE_ROW = re.compile(r"^\|(.+)\|$")
_RE_TABLE_SEP  = re.compile(r"^\|[-:\s|]+\|$")


def _first(pattern: re.Pattern, text: str) -> str | None:
    m = pattern.search(text)
    return m.group(1).strip() if m else None


def _seller_name(markdown: str) -> str | None:
    """Heuristic: first short non-numeric line is likely the seller header."""
    for line in markdown.splitlines():
        line = line.strip().lstrip("#").strip()
        if 3 < len(line) < 60 and not line.startswith("|") and not line[0].isdigit():
            return line
    return None


def _parse_table_rows(markdown: str) -> list[LineItemDraft]:
    """Extract line items from the first markdown data table."""
    rows: list[list[str]] = []
    in_table = False
    header_seen = False

    for line in markdown.splitlines():
        if _RE_TABLE_ROW.match(line):
            if _RE_TABLE_SEP.match(line):
                header_seen = True
                in_table = True
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if in_table and header_seen:
                rows.append(cells)
            elif not in_table:
                # This is the header row
                in_table = True
        elif in_table:
            break  # end of table

    items = []
    for row in rows:
        # Map by position: description, quantity, unit_price, line_total
        def _cell(i: int) -> str | None:
            v = row[i].strip() if i < len(row) else None
            return v if v and v != "-" else None

        items.append(
            LineItemDraft(
                description=_cell(0),
                quantity=_cell(1),
                unit_price=_cell(2),
                line_total=_cell(3) if len(row) > 3 else _cell(2),
            )
        )
    return items


def mock_fast_extract(markdown: str) -> tuple[InvoiceDraft, float]:
    """Run regex extraction. Returns (InvoiceDraft, latency_s).

    Any field that could not be extracted is added to needs_review —
    the caller uses this to decide whether to escalate.
    """
    t0 = time.perf_counter()

    invoice_id = _first(_RE_INVOICE_ID, markdown)
    date       = _first(_RE_DATE, markdown)
    total      = _first(_RE_TOTAL, markdown)
    subtotal   = _first(_RE_SUBTOTAL, markdown)
    tax        = _first(_RE_TAX, markdown)
    seller     = _seller_name(markdown)
    line_items = _parse_table_rows(markdown)

    needs_review: list[str] = []
    for field, val in [
        ("invoice_id", invoice_id),
        ("date",       date),
        ("total",      total),
        ("seller_name", seller),
    ]:
        if val is None:
            needs_review.append(field)

    draft = InvoiceDraft(
        invoice_id=invoice_id,
        seller_name=seller,
        date=date,
        subtotal=subtotal,
        tax=tax,
        total=total,
        line_items=line_items,
        needs_review=needs_review,
        notes=[f"Extracted by {MODEL_NAME} (regex mock of self-hosted LLM)"],
    )

    latency = time.perf_counter() - t0
    return draft, latency
