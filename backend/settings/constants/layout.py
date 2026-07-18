"""Layout-parse heuristics and debug overlay colors."""

from __future__ import annotations

import re

TOTAL_KEYWORDS = re.compile(
    r"\b(total|subtotal|sub-total|tax|vat|amount\s*due|balance|grand\s*total)\b",
    re.I,
)

LAYOUT_BLOCK_ORDER = {"header": 0, "line_item_table": 1, "totals": 2, "other": 3}

LAYOUT_DEBUG_COLORS = {
    "header": (0, 0.55, 0.8),
    "line_item_table": (0.15, 0.65, 0.25),
    "totals": (0.85, 0.45, 0.1),
    "other": (0.5, 0.5, 0.5),
}
