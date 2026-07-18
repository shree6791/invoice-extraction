"""Evaluation metrics against DocILE ground truth (values + bbox IoU)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any, Sequence

from backend.dataset.ground_truth import GoldField
from backend.models.common import FieldValue
from backend.models.invoice import Invoice
from backend.settings.constants.fields import HEADER_FIELDS, LINE_ITEM_FIELDS

# Pass-rate thresholds commonly used in detection-style reporting.
IOU_THRESHOLDS = (0.5, 0.7)

BBox = Sequence[float]  # [x0, y0, x1, y1]


def box_iou(a: BBox | None, b: BBox | None) -> float:
    """Intersection-over-union for axis-aligned boxes. 0 if either missing."""
    if not a or not b or len(a) < 4 or len(b) < 4:
        return 0.0
    ax0, ay0, ax1, ay1 = (float(a[0]), float(a[1]), float(a[2]), float(a[3]))
    bx0, by0, bx1, by1 = (float(b[0]), float(b[1]), float(b[2]), float(b[3]))
    if ax1 <= ax0 or ay1 <= ay0 or bx1 <= bx0 or by1 <= by0:
        return 0.0

    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = (ax1 - ax0) * (ay1 - ay0)
    area_b = (bx1 - bx0) * (by1 - by0)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def best_iou_against_gold(
    pred_bbox: BBox | None,
    pred_page: int | None,
    gold_boxes: list[tuple[int | None, BBox | None]],
) -> float:
    """Max IoU vs gold candidates. Prefer same-page matches when page is known."""
    if not pred_bbox or not gold_boxes:
        return 0.0
    same_page = [
        (p, b) for p, b in gold_boxes if pred_page is not None and p == pred_page
    ]
    pool = same_page or gold_boxes
    return max((box_iou(pred_bbox, b) for _, b in pool), default=0.0)


def normalize_text(s: str | None) -> str:
    if s is None:
        return ""
    t = str(s).casefold().strip()
    t = t.replace("$", "").replace("€", "").replace("£", "")
    t = re.sub(r"[, ]", "", t) if _looks_numeric(t) else re.sub(r"[^\w./-]", "", t)
    return t


def _looks_numeric(s: str) -> bool:
    return bool(re.search(r"\d", s)) and bool(
        re.fullmatch(r"[\d$€£.,\s-]+", s.strip())
    )


def normalize_date(s: str | None) -> str:
    if not s:
        return ""
    raw = str(s).strip()
    for fmt in (
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
    ):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return normalize_text(raw)


def values_equal(field: str, pred: str | None, gold: str | None) -> bool:
    if not gold and not pred:
        return True
    if not gold or not pred:
        return False
    if field == "date":
        return normalize_date(pred) == normalize_date(gold) and bool(normalize_date(gold))
    np, ng = normalize_text(pred), normalize_text(gold)
    if np == ng:
        return True
    if field in ("seller_name", "description"):
        return SequenceMatcher(None, np, ng).ratio() >= 0.85
    if field in ("subtotal", "tax", "total", "unit_price", "line_total", "quantity"):
        try:
            return abs(float(np) - float(ng)) < 0.02
        except ValueError:
            return np == ng
    return np == ng


def description_score(gold_desc: str | None, pred_desc: str | None) -> float:
    """Row-pair score from descriptions.

    Softens DocILE's short labels vs long LLM strings via containment:
    `(Product Test)` inside a longer pred description counts as a match.
    """
    g = normalize_text(gold_desc)
    p = normalize_text(pred_desc)
    if not g and not p:
        return 0.5
    if not g or not p:
        return 0.0
    ratio = SequenceMatcher(None, g, p).ratio()
    if g in p or p in g:
        ratio = max(ratio, 0.85)
    return ratio


DESC_MATCH_THRESHOLD = 0.5


def match_line_rows(
    gold_items: list[dict[str, str | None]],
    pred_rows: list[dict[str, Any]],
) -> list[tuple[int, int]]:
    """Greedy gold→pred row alignment.

    1) Description (fuzzy + containment) ≥ 0.5
    2) Fallback: unused preds with equal line_total (then unit_price / qty tie-break)
    """
    used_pred: set[int] = set()
    matches: list[tuple[int, int]] = []

    # Pass 1 — description
    for gi, g_row in enumerate(gold_items):
        best_j, best_score = -1, 0.0
        for j, p_row in enumerate(pred_rows):
            if j in used_pred:
                continue
            score = description_score(g_row.get("description"), p_row.get("description"))
            if score > best_score:
                best_score = score
                best_j = j
        if best_j >= 0 and best_score >= DESC_MATCH_THRESHOLD:
            used_pred.add(best_j)
            matches.append((gi, best_j))

    matched_gold = {gi for gi, _ in matches}

    # Pass 2 — amount fallback for unmatched gold rows
    for gi, g_row in enumerate(gold_items):
        if gi in matched_gold:
            continue
        g_total = g_row.get("line_total")
        if not g_total:
            continue
        candidates: list[tuple[float, int]] = []
        for j, p_row in enumerate(pred_rows):
            if j in used_pred:
                continue
            if not values_equal("line_total", p_row.get("line_total"), g_total):
                continue
            # Prefer preds that also agree on unit/qty when present
            tie = 0.0
            if g_row.get("unit_price") and values_equal(
                "unit_price", p_row.get("unit_price"), g_row.get("unit_price")
            ):
                tie += 2.0
            if g_row.get("quantity") and values_equal(
                "quantity", p_row.get("quantity"), g_row.get("quantity")
            ):
                tie += 1.0
            candidates.append((tie, j))
        if not candidates:
            continue
        candidates.sort(key=lambda t: (-t[0], t[1]))
        best_j = candidates[0][1]
        used_pred.add(best_j)
        matches.append((gi, best_j))
        matched_gold.add(gi)

    matches.sort(key=lambda t: t[0])
    return matches


@dataclass
class FieldStats:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 0.0

    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 0.0

    def f1(self) -> float:
        p, r = self.precision(), self.recall()
        return 2 * p * r / (p + r) if (p + r) else 0.0

    def as_dict(self) -> dict[str, float | int]:
        return {
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "precision": round(self.precision(), 4),
            "recall": round(self.recall(), 4),
            "f1": round(self.f1(), 4),
        }


@dataclass
class GroundingStats:
    """Spatial quality — orthogonal to value F1.

    IoU is scored only when the predicted *value* matches gold (a wrong box
    on a wrong value is not a grounding win).
    """

    n_value_correct: int = 0
    n_pred_grounded: int = 0
    n_pred_ungrounded: int = 0
    iou_sum: float = 0.0
    pass_at: dict[float, int] = field(
        default_factory=lambda: {t: 0 for t in IOU_THRESHOLDS}
    )
    n_pred_values: int = 0
    n_pred_with_bbox: int = 0

    def record_coverage(self, fv: FieldValue) -> None:
        if fv.value is None or not str(fv.value).strip():
            return
        self.n_pred_values += 1
        if fv.bbox is not None:
            self.n_pred_with_bbox += 1

    def record_value_correct(
        self,
        fv: FieldValue,
        gold_boxes: list[tuple[int | None, list[float] | None]],
    ) -> float | None:
        if not gold_boxes:
            return None

        self.n_value_correct += 1
        if fv.bbox is None:
            self.n_pred_ungrounded += 1
            return None

        self.n_pred_grounded += 1
        iou = best_iou_against_gold(fv.bbox, fv.page, gold_boxes)
        self.iou_sum += iou
        for t in IOU_THRESHOLDS:
            if iou >= t:
                self.pass_at[t] += 1
        return iou

    def as_dict(self) -> dict[str, Any]:
        grounded = self.n_pred_grounded
        mean_iou = self.iou_sum / grounded if grounded else None
        pass_rates = {
            f"pass_at_{t}": round(self.pass_at[t] / grounded, 4) if grounded else None
            for t in IOU_THRESHOLDS
        }
        return {
            "pred_value_coverage": round(
                self.n_pred_with_bbox / self.n_pred_values, 4
            )
            if self.n_pred_values
            else None,
            "n_pred_values": self.n_pred_values,
            "n_pred_with_bbox": self.n_pred_with_bbox,
            "n_value_correct_with_gold_box": self.n_value_correct,
            "n_grounded": grounded,
            "n_ungrounded_despite_correct_value": self.n_pred_ungrounded,
            "mean_iou": round(mean_iou, 4) if mean_iou is not None else None,
            **pass_rates,
            "note": (
                "IoU only when value matches gold AND both have a bbox. "
                "pass_at_0.5 = fraction of those with IoU≥0.5. "
                "DocILE + our boxes are both normalized 0–1."
            ),
        }


@dataclass
class EvalAccumulator:
    header: dict[str, FieldStats] = field(
        default_factory=lambda: {f: FieldStats() for f in HEADER_FIELDS}
    )
    line_cols: dict[str, FieldStats] = field(
        default_factory=lambda: {f: FieldStats() for f in LINE_ITEM_FIELDS}
    )
    grounding: GroundingStats = field(default_factory=GroundingStats)
    rows_pred: int = 0
    rows_gold: int = 0
    rows_matched: int = 0
    doc_errors: list[dict[str, Any]] = field(default_factory=list)

    def update(
        self,
        doc_id: str,
        pred: Invoice,
        gold_header: dict[str, str | None],
        gold_items: list[dict[str, str | None]],
        meta: dict[str, Any] | None = None,
        *,
        gold_header_boxes: dict[str, list[tuple[int | None, list[float] | None]]]
        | None = None,
        gold_items_rich: list[dict[str, GoldField]] | None = None,
    ) -> dict[str, Any]:
        field_misses: list[str] = []
        halluc: list[str] = []
        iou_details: dict[str, float] = {}
        gold_header_boxes = gold_header_boxes or {}

        for f in HEADER_FIELDS:
            fv: FieldValue = getattr(pred, f)
            self.grounding.record_coverage(fv)
            p = fv.value
            g = gold_header.get(f)
            if g and values_equal(f, p, g):
                self.header[f].tp += 1
                iou = self.grounding.record_value_correct(
                    fv, gold_header_boxes.get(f, [])
                )
                if iou is not None:
                    iou_details[f] = round(iou, 4)
            elif g and not p:
                self.header[f].fn += 1
                field_misses.append(f)
            elif g and p and not values_equal(f, p, g):
                self.header[f].fp += 1
                self.header[f].fn += 1
                field_misses.append(f)
                if normalize_text(p) not in normalize_text(str(g)):
                    halluc.append(f)
            elif not g and p:
                self.header[f].fp += 1
                halluc.append(f)

        pred_rows = [
            {
                "description": li.description.value,
                "quantity": li.quantity.value,
                "unit_price": li.unit_price.value,
                "line_total": li.line_total.value,
                "_fv": {
                    "description": li.description,
                    "quantity": li.quantity,
                    "unit_price": li.unit_price,
                    "line_total": li.line_total,
                },
            }
            for li in pred.line_items
        ]
        self.rows_pred += len(pred_rows)
        self.rows_gold += len(gold_items)

        for li in pred.line_items:
            for col in LINE_ITEM_FIELDS:
                self.grounding.record_coverage(getattr(li, col))

        used_pred: set[int] = set()
        matches = match_line_rows(gold_items, pred_rows)
        self.rows_matched += len(matches)

        for gi, best_j in matches:
            used_pred.add(best_j)
            rich = (
                gold_items_rich[gi]
                if gold_items_rich and gi < len(gold_items_rich)
                else None
            )
            g_row = gold_items[gi]
            for col in LINE_ITEM_FIELDS:
                pv = pred_rows[best_j].get(col)
                gv = g_row.get(col)
                fv = pred_rows[best_j]["_fv"][col]
                if values_equal(col, pv, gv):
                    if gv or pv:
                        if gv:
                            self.line_cols[col].tp += 1
                        if rich and rich.get(col):
                            gf: GoldField = rich[col]
                            boxes = [(gf.page, gf.bbox)] if gf.bbox else []
                            iou = self.grounding.record_value_correct(fv, boxes)
                            if iou is not None:
                                iou_details[f"line_items[{gi}].{col}"] = round(
                                    iou, 4
                                )
                else:
                    if gv:
                        self.line_cols[col].fn += 1
                    if pv:
                        self.line_cols[col].fp += 1

        matched_gold = {gi for gi, _ in matches}
        for gi, g_row in enumerate(gold_items):
            if gi in matched_gold:
                continue
            for col in LINE_ITEM_FIELDS:
                if g_row.get(col):
                    self.line_cols[col].fn += 1
            field_misses.append(f"line_item[{gi}]")

        for j, p_row in enumerate(pred_rows):
            if j not in used_pred:
                for col in LINE_ITEM_FIELDS:
                    if p_row.get(col):
                        self.line_cols[col].fp += 1

        doc_result = {
            "doc_id": doc_id,
            "header_misses": field_misses,
            "hallucination_fields": halluc,
            "n_pred_rows": len(pred_rows),
            "n_gold_rows": len(gold_items),
            "n_matched_rows": len(matches),
            "iou_by_field": iou_details,
            "meta": meta or {},
        }
        self.doc_errors.append(doc_result)
        return doc_result

    def summary(self) -> dict[str, Any]:
        header = {f: self.header[f].as_dict() for f in HEADER_FIELDS}
        line_cols = {f: self.line_cols[f].as_dict() for f in LINE_ITEM_FIELDS}
        h_tp = sum(self.header[f].tp for f in HEADER_FIELDS)
        h_fp = sum(self.header[f].fp for f in HEADER_FIELDS)
        h_fn = sum(self.header[f].fn for f in HEADER_FIELDS)
        header_micro = FieldStats(tp=h_tp, fp=h_fp, fn=h_fn).as_dict()

        l_tp = sum(self.line_cols[f].tp for f in LINE_ITEM_FIELDS)
        l_fp = sum(self.line_cols[f].fp for f in LINE_ITEM_FIELDS)
        l_fn = sum(self.line_cols[f].fn for f in LINE_ITEM_FIELDS)
        line_micro = FieldStats(tp=l_tp, fp=l_fp, fn=l_fn).as_dict()

        row_det = self.rows_matched / self.rows_gold if self.rows_gold else 0.0
        return {
            "header_per_field": header,
            "header_micro_f1": header_micro["f1"],
            "header_micro": header_micro,
            "line_item_per_column": line_cols,
            "line_item_micro_f1": line_micro["f1"],
            "line_item_micro": line_micro,
            "row_detection_recall": round(row_det, 4),
            "rows_pred": self.rows_pred,
            "rows_gold": self.rows_gold,
            "rows_matched": self.rows_matched,
            "n_docs": len(self.doc_errors),
            "grounding": self.grounding.as_dict(),
        }
