"""Layout domain dataclasses produced by the layout service."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

BlockKind = Literal["header", "line_item_table", "totals", "other"]
BlockRole = Literal["data_table", "layout_panel", "totals", "other"]


@dataclass
class Span:
    text: str
    page: int
    bbox: list[float]  # normalized [x0,y0,x1,y1] in 0-1
    font_size: float
    abs_bbox: list[float]  # absolute PDF points


@dataclass
class LayoutBlock:
    kind: BlockKind
    page: int
    bbox: list[float]
    spans: list[Span] = field(default_factory=list)
    role: BlockRole = "other"
    continues: bool = False  # table continues onto a later page
    continued_from: bool = False  # continuation of a prior page's table

    def text(self) -> str:
        ordered = sorted(
            self.spans,
            key=lambda s: (round(s.bbox[1], 3), round(s.bbox[0], 3)),
        )
        return " ".join(s.text for s in ordered if s.text.strip())


@dataclass
class ParsedPage:
    page: int
    width: float
    height: float
    spans: list[Span]
    source: Literal["native", "ocr"]
    blocks: list[LayoutBlock] = field(default_factory=list)


@dataclass
class ParsedDocument:
    doc_id: str
    path: str
    pages: list[ParsedPage]
    markdown: str = ""

    def all_spans(self) -> list[Span]:
        out: list[Span] = []
        for p in self.pages:
            out.extend(p.spans)
        return out


def cluster_rows(spans: list[Span], y_tol: float = 0.008) -> list[list[Span]]:
    if not spans:
        return []
    ordered = sorted(spans, key=lambda s: (s.bbox[1], s.bbox[0]))
    rows: list[list[Span]] = []
    current: list[Span] = [ordered[0]]
    current_y = ordered[0].bbox[1]
    for s in ordered[1:]:
        if abs(s.bbox[1] - current_y) <= y_tol:
            current.append(s)
        else:
            rows.append(sorted(current, key=lambda x: x.bbox[0]))
            current = [s]
            current_y = s.bbox[1]
    rows.append(sorted(current, key=lambda x: x.bbox[0]))
    return rows


def is_genuine_data_table(spans: list[Span], min_rows: int = 3) -> bool:
    """True if rows look like repeating columns (line-item schedule), not a boxed panel."""
    rows = cluster_rows(spans, y_tol=0.01)
    dense = [r for r in rows if len(r) >= 2]
    if len(dense) < min_rows:
        return False
    # Column-count consistency across dense rows
    widths = [len(r) for r in dense]
    median = sorted(widths)[len(widths) // 2]
    consistent = sum(1 for w in widths if abs(w - median) <= 1) / len(widths)
    if consistent < 0.6:
        return False
    # Horizontal spread: real tables usually span much of the page width
    x0 = min(s.bbox[0] for s in spans)
    x1 = max(s.bbox[2] for s in spans)
    if (x1 - x0) < 0.35:
        return False
    return True


def to_markdown(doc: "ParsedDocument", max_rows: int = 400) -> str:
    """Stage-1 ADE-style markdown: page chunks, data tables vs layout panels."""
    lines: list[str] = [
        f"# Document `{doc.doc_id}`",
        "",
        "Stage 1 PARSE — structure only. Data tables are markdown tables; "
        "address/header panels are bullet lists (not table rows).",
        "",
    ]
    row_budget = max_rows
    n_pages = len(doc.pages)

    for page in doc.pages:
        lines.append(f"## Page {page.page + 1} of {n_pages} (source={page.source})")
        lines.append("")
        for block in page.blocks:
            if row_budget <= 0:
                lines.append("_…truncated…_")
                return "\n".join(lines)

            title = {
                "data_table": "Data table (line items)",
                "layout_panel": "Layout panel (not a data table)",
                "totals": "Totals / amounts",
                "other": "Other content",
            }.get(block.role, block.role)

            header = f"### {title}"
            if block.continued_from:
                header += " — *continuation from previous page*"
            if block.continues:
                header += " — *continues on next page*"
            lines.append(header)
            lines.append("")

            rows = cluster_rows(block.spans)
            if block.role == "data_table" and rows:
                for i, row in enumerate(rows):
                    cells = [s.text.strip() for s in row if s.text.strip()]
                    if not cells:
                        continue
                    if i == 0:
                        lines.append("| " + " | ".join(cells) + " |")
                        lines.append("| " + " | ".join("---" for _ in cells) + " |")
                    else:
                        lines.append("| " + " | ".join(cells) + " |")
                    row_budget -= 1
                    if row_budget <= 0:
                        break
                if block.continues:
                    lines.append("")
                    lines.append(
                        f"> Table chunk ends on page {page.page + 1}; "
                        "more rows on the next page."
                    )
            else:
                for row in rows:
                    text = " ".join(s.text for s in row if s.text.strip()).strip()
                    if text:
                        lines.append(f"- {text}")
                        row_budget -= 1
                        if row_budget <= 0:
                            break
            lines.append("")

    return "\n".join(lines)
