"""DocILE schema field names."""

from __future__ import annotations

HEADER_FIELDS = (
    "invoice_id",
    "seller_name",
    "date",
    "subtotal",
    "tax",
    "total",
)

LINE_ITEM_FIELDS = ("description", "quantity", "unit_price", "line_total")

# Span-match confidence below this → needs_review
SOURCE_CONFIDENCE_THRESHOLD = 0.55
