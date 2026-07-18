"""Span matching + FieldValue grounding (page / bbox / quote).

Hardening vs naive fuzzy:
  - field-typed normalization (money / date / id / text)
  - length-ratio guard against substring traps ("12" ⊂ "112.50")
  - multi-span joins scored to completion (no early break on partial)
  - money-field disambiguation via nearby label tokens
  - near-tie without a clear label winner → leave ungrounded (needs_review)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime

from rapidfuzz import fuzz

from backend.models.common import FieldValue, SourceNote
from backend.models.invoice import Invoice, InvoiceDraft, LineItem
from backend.models.layout import ParsedDocument, Span
from backend.settings.constants.fields import (
    HEADER_FIELDS,
    LINE_ITEM_FIELDS,
    SOURCE_CONFIDENCE_THRESHOLD,
)

log = logging.getLogger(__name__)

# Join up to this many same-row word spans for multi-word values.
_MAX_JOIN = 8
# Same-row y tolerance (normalized page coords).
_Y_TOL = 0.02
# Reject matches where shorter/longer normalized length ratio is below this.
_MIN_LEN_RATIO = 0.5
# Scores within this of the best are "near ties" for disambiguation.
_TIE_EPS = 0.05

_MONEY_FIELDS = frozenset(
    {"subtotal", "tax", "total", "unit_price", "line_total", "quantity"}
)
_DATE_FIELDS = frozenset({"date"})
_ID_FIELDS = frozenset({"invoice_id"})

# Label tokens (normalized) expected near money amounts.
_LABEL_HINTS: dict[str, tuple[str, ...]] = {
    "total": ("total", "amountdue", "balancedue", "grandtotal", "amountdue"),
    "subtotal": ("subtotal", "sub-total", "net", "nett", "netamount"),
    "tax": ("tax", "vat", "gst", "salestax", "pst", "hst"),
    "line_total": ("amount", "total", "ext", "extended"),
    "unit_price": ("rate", "price", "unit", "each"),
    "quantity": ("qty", "quantity", "hours", "hrs"),
}


def _field_base(field_name: str) -> str:
    """line_items[3].total → total; seller_name → seller_name."""
    if "." in field_name:
        return field_name.rsplit(".", 1)[-1]
    return field_name


def normalize_for_field(s: str, field_name: str = "") -> str:
    """Field-typed normalization for matching (not for display)."""
    if s is None:
        return ""
    raw = str(s).strip()
    base = _field_base(field_name)

    if base in _MONEY_FIELDS:
        t = raw.casefold()
        t = t.replace("$", "").replace("€", "").replace("£", "")
        t = t.replace(",", "").replace(" ", "")
        t = re.sub(r"[^\d.\-]", "", t)
        return t

    if base in _DATE_FIELDS:
        # Keep display-form tokens for fuzzy match against spans.
        # ISO equality is handled separately in _score_pair.
        t = raw.casefold().strip()
        t = re.sub(r"[^\w]", "", t)
        return t

    if base in _ID_FIELDS:
        t = raw.casefold().strip()
        t = re.sub(r"\s+", "", t)
        t = re.sub(r"[^\w./\-]", "", t)
        return t

    # seller_name / description / default text
    t = raw.casefold().strip()
    t = re.sub(r"[^\w.\s]", "", t)  # drop & , etc. but keep letters
    t = re.sub(r"\s+", "", t)
    return t


def _length_ratio_ok(a: str, b: str) -> bool:
    if not a or not b:
        return False
    lo, hi = (a, b) if len(a) <= len(b) else (b, a)
    if len(hi) == 0:
        return False
    return (len(lo) / len(hi)) >= _MIN_LEN_RATIO


_DATE_FMTS = (
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%d/%m/%Y",
    "%d/%m/%y",
    "%d-%m-%Y",
    "%Y/%m/%d",
    "%b %d, %Y",
    "%B %d, %Y",
    "%d %b %Y",
    "%d %B %Y",
)


def _parse_date_iso(s: str) -> str | None:
    raw = str(s).strip()
    for fmt in _DATE_FMTS:
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _score_pair(
    value_raw: str,
    span_raw: str,
    *,
    field_name: str,
) -> float:
    """0–1 similarity between raw value and span text."""
    a = normalize_for_field(value_raw, field_name)
    b = normalize_for_field(span_raw, field_name)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    base = _field_base(field_name)
    if base in _DATE_FIELDS:
        da, db = _parse_date_iso(value_raw), _parse_date_iso(span_raw)
        if da and db and da == db:
            return 1.0
    return fuzz.ratio(a, b) / 100.0


@dataclass
class _Candidate:
    span: Span
    score: float
    start: int
    end: int  # inclusive


def _union_span(spans: list[Span], i: int, j: int) -> Span:
    chunk = spans[i : j + 1]
    return Span(
        text=" ".join(s.text for s in chunk),
        page=spans[i].page,
        bbox=[
            min(s.bbox[0] for s in chunk),
            min(s.bbox[1] for s in chunk),
            max(s.bbox[2] for s in chunk),
            max(s.bbox[3] for s in chunk),
        ],
        font_size=spans[i].font_size,
        abs_bbox=[
            min(s.abs_bbox[0] for s in chunk),
            min(s.abs_bbox[1] for s in chunk),
            max(s.abs_bbox[2] for s in chunk),
            max(s.abs_bbox[3] for s in chunk),
        ],
    )


def _same_locus(a: _Candidate, b: _Candidate) -> bool:
    """True if two candidates are overlapping windows of the same on-page amount."""
    if a.span.page != b.span.page:
        return False
    if abs(a.span.bbox[1] - b.span.bbox[1]) > _Y_TOL:
        return False
    # Horizontal overlap (not merely same row elsewhere).
    return not (a.span.bbox[2] < b.span.bbox[0] or b.span.bbox[2] < a.span.bbox[0])


def _collapse_loci(
    cands: list[_Candidate],
    *,
    prefer_short: bool = False,
) -> list[_Candidate]:
    """Keep one candidate per spatial locus.

    prefer_short: for exact money hits, keep the tightest bbox (avoid joins
    that swallowed neighboring labels into the quote).
    """

    def sort_key(x: _Candidate) -> tuple[float, int]:
        length = len(x.span.text)
        return (x.score, -length if prefer_short else length)

    survivors: list[_Candidate] = []
    for c in sorted(cands, key=sort_key, reverse=True):
        if any(_same_locus(c, s) for s in survivors):
            continue
        survivors.append(c)
    return survivors


def _label_boost(field_name: str, spans: list[Span], cand: _Candidate) -> float:
    """Return 0–0.15 boost if a field label sits on the same row to the left."""
    hints = _LABEL_HINTS.get(_field_base(field_name), ())
    if not hints:
        return 0.0
    page = cand.span.page
    y0 = cand.span.bbox[1]
    x0 = cand.span.bbox[0]
    left_texts: list[str] = []
    for k in range(max(0, cand.start - 12), cand.start):
        s = spans[k]
        if s.page != page:
            continue
        if abs(s.bbox[1] - y0) > _Y_TOL:
            continue
        if s.bbox[2] > x0 + 0.02:
            continue
        left_texts.append(normalize_for_field(s.text, "seller_name"))
    joined = "".join(left_texts)
    boost = 0.0
    strong = ("amountdue", "balancedue", "grandtotal", "subtotal", "salestax")
    for h in hints:
        if h in joined:
            boost = max(boost, 0.15 if h in strong else 0.08)
    return boost


def find_span_scored(
    value: str | None,
    spans: list[Span],
    *,
    field_name: str = "",
) -> tuple[Span | None, float]:
    """Best-matching span (or multi-span union) for value_text.

    Returns (None, best_seen_score) when nothing clears the threshold or a
    near-tie cannot be disambiguated — caller should mark needs_review.
    """
    if not value or not str(value).strip():
        return None, 0.0
    value_raw = str(value).strip()
    target = normalize_for_field(value_raw, field_name)
    if not target:
        return None, 0.0

    cands: list[_Candidate] = []
    floor = SOURCE_CONFIDENCE_THRESHOLD * 0.9

    for i, s in enumerate(spans):
        # Single span
        nt = normalize_for_field(s.text, field_name)
        if nt and _length_ratio_ok(target, nt):
            ratio = _score_pair(value_raw, s.text, field_name=field_name)
            if ratio >= floor:
                cands.append(_Candidate(s, ratio, i, i))

        # Multi-span same-row join — score every window, no early break.
        joined = s.text
        for j in range(i + 1, min(i + _MAX_JOIN, len(spans))):
            if spans[j].page != s.page:
                break
            if abs(spans[j].bbox[1] - s.bbox[1]) > _Y_TOL:
                break
            joined = joined + " " + spans[j].text
            nj = normalize_for_field(joined, field_name)
            if not nj or not _length_ratio_ok(target, nj):
                continue
            ratio = _score_pair(value_raw, joined, field_name=field_name)
            if ratio >= floor:
                cands.append(_Candidate(_union_span(spans, i, j), ratio, i, j))

    if not cands:
        log.warning(
            "grounding miss field=%s value=%r (no candidate ≥ threshold)",
            field_name or "?",
            value,
        )
        return None, 0.0

    # Prefer exact normalized hits when present (stops "1.20" fuzzy-matching noise).
    used_exact = False
    exact = [
        c
        for c in cands
        if normalize_for_field(c.span.text, field_name) == target
    ]
    if exact:
        cands = exact
        used_exact = True

    # Money: tightest bbox per locus. Text: longest (more complete phrase).
    base = _field_base(field_name)
    cands = _collapse_loci(
        cands, prefer_short=used_exact and base in _MONEY_FIELDS
    )
    cands.sort(
        key=lambda c: (c.score, -c.span.page, len(c.span.text)),
        reverse=True,
    )

    if base in _MONEY_FIELDS:
        boosted: list[tuple[float, _Candidate]] = [
            (c.score + _label_boost(field_name, spans, c), c) for c in cands
        ]
        # Header money: earlier page is a soft preference when labels tie.
        boosted.sort(
            key=lambda t: (t[0], -t[1].span.page, -len(t[1].span.text)),
            reverse=True,
        )
        best_boost, best = boosted[0]
        close = [b for b in boosted if abs(b[0] - best_boost) <= _TIE_EPS]
        if len(close) > 1:
            # Stronger label wins; else earlier page for header fields.
            close.sort(
                key=lambda t: (
                    _label_boost(field_name, spans, t[1]),
                    -t[1].span.page,
                    -len(t[1].span.text),
                ),
                reverse=True,
            )
            top, second = close[0], close[1]
            top_lab = _label_boost(field_name, spans, top[1])
            sec_lab = _label_boost(field_name, spans, second[1])
            if top_lab > sec_lab or (
                top[1].span.page < second[1].span.page and base in _MONEY_FIELDS
            ):
                best = top[1]
            elif top_lab == sec_lab and top[1].span.page == second[1].span.page:
                log.warning(
                    "grounding ambiguous field=%s value=%r n_ties=%d — leaving ungrounded",
                    field_name or "?",
                    value,
                    len(close),
                )
                return None, best.score
            else:
                best = top[1]
        if best.score < SOURCE_CONFIDENCE_THRESHOLD:
            return None, best.score
        return best.span, best.score

    best = cands[0]
    close = [c for c in cands if abs(c.score - best.score) <= _TIE_EPS]
    if len(close) > 1:
        close.sort(
            key=lambda c: len(normalize_for_field(c.span.text, field_name)),
            reverse=True,
        )
        top_len = len(normalize_for_field(close[0].span.text, field_name))
        second_len = len(normalize_for_field(close[1].span.text, field_name))
        if top_len > second_len:
            best = close[0]

    if best.score < SOURCE_CONFIDENCE_THRESHOLD:
        log.warning(
            "grounding low-score field=%s value=%r score=%.3f quote=%r",
            field_name or "?",
            value,
            best.score,
            best.span.text,
        )
        return None, best.score
    return best.span, best.score


def field_from_value(
    value: str | None,
    spans: list[Span],
    *,
    field_name: str,
    needs_review: list[str],
) -> FieldValue:
    if value is None or not str(value).strip():
        return FieldValue(value=None, page=None, bbox=None, source=None)

    span, score = find_span_scored(value, spans, field_name=field_name)
    if span is None or score < SOURCE_CONFIDENCE_THRESHOLD:
        if field_name not in needs_review:
            needs_review.append(field_name)
        return FieldValue(
            value=value,
            page=None,
            bbox=None,
            source=SourceNote(
                page=None,
                quote=None,
                bbox=None,
                confidence=round(score, 3) if score else 0.0,
            ),
        )

    quote = span.text.strip()
    if len(quote) > 120:
        quote = quote[:117] + "..."
    source = SourceNote(
        page=span.page,
        quote=quote,
        bbox=span.bbox,
        confidence=round(score, 3),
    )
    return FieldValue(value=value, page=span.page, bbox=span.bbox, source=source)


def attach_grounding(draft: InvoiceDraft, parsed: ParsedDocument) -> Invoice:
    spans = parsed.all_spans()
    needs_review = list(draft.needs_review or [])

    header_kwargs = {
        name: field_from_value(
            getattr(draft, name), spans, field_name=name, needs_review=needs_review
        )
        for name in HEADER_FIELDS
    }

    items: list[LineItem] = []
    for idx, li in enumerate(draft.line_items):
        kwargs = {
            f: field_from_value(
                getattr(li, f),
                spans,
                field_name=f"line_items[{idx}].{f}",
                needs_review=needs_review,
            )
            for f in LINE_ITEM_FIELDS
        }
        items.append(LineItem(**kwargs))

    return Invoice(
        **header_kwargs,
        line_items=items,
        needs_review=needs_review,
        unmapped_content=list(draft.unmapped_content or []),
        notes=list(draft.notes or []),
    )
