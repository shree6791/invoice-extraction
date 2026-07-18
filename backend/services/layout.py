"""PyMuPDF layout parsing with heuristic block segmentation."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

import fitz  # PyMuPDF

from backend.settings.constants.layout import LAYOUT_BLOCK_ORDER, TOTAL_KEYWORDS
from backend.models.layout import (
    LayoutBlock,
    ParsedDocument,
    ParsedPage,
    Span,
    is_genuine_data_table,
    to_markdown,
)


def _extract_native_spans(page: fitz.Page, page_idx: int) -> list[Span]:
    w, h = page.rect.width, page.rect.height
    spans: list[Span] = []
    for wobj in page.get_text("words"):
        x0, y0, x1, y1, text, *_ = wobj
        if not text or not str(text).strip():
            continue
        spans.append(
            Span(
                text=str(text),
                page=page_idx,
                bbox=[x0 / w, y0 / h, x1 / w, y1 / h],
                font_size=abs(y1 - y0),
                abs_bbox=[x0, y0, x1, y1],
            )
        )
    try:
        d = page.get_text("dict")
        size_by_y: list[tuple[float, float, float]] = []
        for block in d.get("blocks", []):
            for line in block.get("lines", []):
                for sp in line.get("spans", []):
                    size_by_y.append(
                        (sp["bbox"][1] / h, sp["bbox"][3] / h, float(sp.get("size", 0)))
                    )
        for s in spans:
            cy = (s.bbox[1] + s.bbox[3]) / 2
            best = None
            for y0, y1, sz in size_by_y:
                if y0 - 0.01 <= cy <= y1 + 0.01:
                    best = sz
                    break
            if best:
                s.font_size = best
    except Exception:
        pass
    return spans


def _extract_ocr_spans(page: fitz.Page, page_idx: int) -> list[Span]:
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return []

    pix = page.get_pixmap(dpi=200)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    try:
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
    except Exception:
        return []

    w, h = pix.width, pix.height
    spans: list[Span] = []
    n = len(data["text"])
    for i in range(n):
        text = (data["text"][i] or "").strip()
        if not text:
            continue
        x, y, bw, bh = (
            data["left"][i],
            data["top"][i],
            data["width"][i],
            data["height"][i],
        )
        spans.append(
            Span(
                text=text,
                page=page_idx,
                bbox=[x / w, y / h, (x + bw) / w, (y + bh) / h],
                font_size=float(bh),
                abs_bbox=[
                    x * page.rect.width / w,
                    y * page.rect.height / h,
                    (x + bw) * page.rect.width / w,
                    (y + bh) * page.rect.height / h,
                ],
            )
        )
    return spans


def _union_bbox(spans: list[Span]) -> list[float]:
    return [
        min(s.bbox[0] for s in spans),
        min(s.bbox[1] for s in spans),
        max(s.bbox[2] for s in spans),
        max(s.bbox[3] for s in spans),
    ]


def _pick_table_spans(spans: list[Span]) -> list[Span]:
    if len(spans) < 4:
        return spans
    from backend.models.layout import cluster_rows

    rows = cluster_rows(spans, y_tol=0.01)
    dense_rows = [r for r in rows if len(r) >= 2]
    if len(dense_rows) < 2:
        return spans
    dense_idx = {id(s) for r in dense_rows for s in r}
    return [s for s in spans if id(s) in dense_idx]


def _segment_page(spans: list[Span], page_idx: int) -> list[LayoutBlock]:
    if not spans:
        return []

    header_spans = [s for s in spans if s.bbox[3] < 0.28]
    totals_spans = [
        s for s in spans if s.bbox[1] > 0.62 or TOTAL_KEYWORDS.search(s.text)
    ]
    mid = [s for s in spans if 0.25 <= s.bbox[1] <= 0.75]
    table_spans = _pick_table_spans(mid)

    used: set[int] = set()

    def take(cands: list[Span]) -> list[Span]:
        out = []
        for s in cands:
            key = id(s)
            if key in used:
                continue
            used.add(key)
            out.append(s)
        return out

    blocks: list[LayoutBlock] = []
    ts = take(table_spans)
    if ts:
        role = "data_table" if is_genuine_data_table(ts) else "layout_panel"
        kind = "line_item_table" if role == "data_table" else "other"
        blocks.append(
            LayoutBlock(
                kind=kind,
                page=page_idx,
                bbox=_union_bbox(ts),
                spans=ts,
                role=role,
            )
        )
    tot = take(totals_spans)
    if tot:
        blocks.append(
            LayoutBlock(
                kind="totals",
                page=page_idx,
                bbox=_union_bbox(tot),
                spans=tot,
                role="totals",
            )
        )
    hs = take(header_spans)
    if hs:
        blocks.append(
            LayoutBlock(
                kind="header",
                page=page_idx,
                bbox=_union_bbox(hs),
                spans=hs,
                role="layout_panel",
            )
        )
    leftover = [s for s in spans if id(s) not in used]
    if leftover:
        blocks.append(
            LayoutBlock(
                kind="other",
                page=page_idx,
                bbox=_union_bbox(leftover),
                spans=leftover,
                role="layout_panel"
                if not is_genuine_data_table(leftover, min_rows=2)
                else "data_table",
            )
        )
    blocks.sort(key=lambda b: LAYOUT_BLOCK_ORDER.get(b.kind, 9))
    return blocks


def _mark_multipage_tables(pages: list[ParsedPage]) -> None:
    """Flag data tables that continue across consecutive pages (page chunks)."""
    for i in range(len(pages) - 1):
        cur_tables = [b for b in pages[i].blocks if b.role == "data_table"]
        nxt_tables = [b for b in pages[i + 1].blocks if b.role == "data_table"]
        if cur_tables and nxt_tables:
            # Heuristic: table near bottom of page + table near top of next
            for b in cur_tables:
                if b.bbox[3] > 0.55:
                    b.continues = True
            for b in nxt_tables:
                if b.bbox[1] < 0.45:
                    b.continued_from = True


def _parse_page_at(path: str, page_idx: int) -> ParsedPage:
    """Parse a single page. Opens its own Document — safe for thread pools.

    PyMuPDF Document objects must not be shared across threads.
    """
    doc = fitz.open(path)
    try:
        page = doc[page_idx]
        spans = _extract_native_spans(page, page_idx)
        source: Literal["native", "ocr"] = "native"
        if len(spans) < 8:
            ocr_spans = _extract_ocr_spans(page, page_idx)
            if len(ocr_spans) > len(spans):
                spans = ocr_spans
                source = "ocr"
        blocks = _segment_page(spans, page_idx)
        return ParsedPage(
            page=page_idx,
            width=page.rect.width,
            height=page.rect.height,
            spans=spans,
            source=source,
            blocks=blocks,
        )
    finally:
        doc.close()


def parse_pdf(path: str | Path, doc_id: str | None = None) -> ParsedDocument:
    """Parse all pages (in parallel when n_pages > 1), then build markdown."""
    path = Path(path)
    doc_id = doc_id or path.stem
    path_str = str(path)

    probe = fitz.open(path_str)
    try:
        n_pages = probe.page_count
    finally:
        probe.close()

    if n_pages <= 1:
        pages = [_parse_page_at(path_str, 0)] if n_pages == 1 else []
    else:
        workers = min(n_pages, os.cpu_count() or 4, 8)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            pages = list(
                pool.map(lambda i: _parse_page_at(path_str, i), range(n_pages))
            )

    _mark_multipage_tables(pages)
    parsed = ParsedDocument(doc_id=doc_id, path=path_str, pages=pages)
    parsed.markdown = to_markdown(parsed)
    return parsed


def render_page_png(path: str | Path, page_idx: int = 0, dpi: int = 150) -> bytes:
    doc = fitz.open(path)
    try:
        page = doc[page_idx]
        pix = page.get_pixmap(dpi=dpi)
        return pix.tobytes("png")
    finally:
        doc.close()


def layout_for_api(parsed: ParsedDocument) -> dict:
    """Compact layout subset for POST /api/extract responses."""
    return {
        "pages": [
            {
                "page": page.page,
                "width": page.width,
                "height": page.height,
                "source": page.source,
                "blocks": [
                    {
                        "kind": b.kind,
                        "role": b.role,
                        "bbox": b.bbox,
                        "continues": b.continues,
                        "continued_from": b.continued_from,
                        "page": b.page,
                    }
                    for b in page.blocks
                ],
            }
            for page in parsed.pages
        ]
    }
