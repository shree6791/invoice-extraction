"""Map DocILE annotations onto our invoice schema (values + gold bboxes)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from backend.settings.constants.docile import (
    HEADER_MAP,
    LI_AMT_GROSS,
    LI_AMT_NET,
    LI_DESC,
    LI_QTY,
    LI_UNIT_GROSS,
    LI_UNIT_NET,
)


@dataclass
class GoldField:
    text: str | None = None
    page: int | None = None
    bbox: list[float] | None = None  # DocILE normalized [x0,y0,x1,y1]


def _pick_text(by_type: dict[str, list[dict[str, Any]]], fieldtype: str) -> str | None:
    vals = [e.get("text") or "" for e in by_type.get(fieldtype, []) if e.get("text")]
    return vals[0] if vals else None


def _all_boxes(
    by_type: dict[str, list[dict[str, Any]]], fieldtype: str
) -> list[tuple[int | None, list[float] | None]]:
    out: list[tuple[int | None, list[float] | None]] = []
    for e in by_type.get(fieldtype, []):
        bbox = e.get("bbox")
        if bbox and len(bbox) >= 4:
            out.append((e.get("page"), list(bbox)))
    return out


def _field_extractions_by_type(ann: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for f in ann.get("field_extractions", []):
        by_type[f["fieldtype"]].append(f)
    return by_type


def gt_header_fields(ann: dict[str, Any]) -> dict[str, str | None]:
    by_type = _field_extractions_by_type(ann)
    return {
        our: _pick_text(by_type, theirs) for our, theirs in HEADER_MAP.items()
    }


def gt_header_gold_boxes(
    ann: dict[str, Any],
) -> dict[str, list[tuple[int | None, list[float] | None]]]:
    """All DocILE boxes per our header field (handles multi-page duplicates)."""
    by_type = _field_extractions_by_type(ann)
    return {our: _all_boxes(by_type, theirs) for our, theirs in HEADER_MAP.items()}


def gt_line_items(ann: dict[str, Any]) -> list[dict[str, str | None]]:
    return [
        {k: v.text for k, v in row.items()}
        for row in gt_line_items_gold(ann)
    ]


def gt_line_items_gold(ann: dict[str, Any]) -> list[dict[str, GoldField]]:
    by_li: dict[int, dict[str, dict[str, Any]]] = defaultdict(dict)
    for f in ann.get("line_item_extractions", []):
        li_id = f.get("line_item_id")
        if li_id is None:
            continue
        by_li[int(li_id)][f["fieldtype"]] = f

    items: list[dict[str, GoldField]] = []
    for li_id in sorted(by_li.keys()):
        fields = by_li[li_id]
        unit_e = fields.get(LI_UNIT_NET) or fields.get(LI_UNIT_GROSS)
        total_e = fields.get(LI_AMT_NET) or fields.get(LI_AMT_GROSS)

        def to_gold(e: dict[str, Any] | None) -> GoldField:
            if not e:
                return GoldField()
            bbox = e.get("bbox")
            return GoldField(
                text=e.get("text") or None,
                page=e.get("page"),
                bbox=list(bbox) if bbox and len(bbox) >= 4 else None,
            )

        items.append(
            {
                "description": to_gold(fields.get(LI_DESC)),
                "quantity": to_gold(fields.get(LI_QTY)),
                "unit_price": to_gold(unit_e),
                "line_total": to_gold(total_e),
            }
        )
    return items
