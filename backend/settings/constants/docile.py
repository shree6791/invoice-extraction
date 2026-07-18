"""DocILE annotation fieldtype mapping (ground truth)."""

from __future__ import annotations

HEADER_MAP = {
    "invoice_id": "document_id",
    "seller_name": "vendor_name",
    "date": "date_issue",
    "subtotal": "amount_total_net",
    "tax": "amount_total_tax",
    "total": "amount_total_gross",
}

LI_DESC = "line_item_description"
LI_QTY = "line_item_quantity"
LI_UNIT_NET = "line_item_unit_price_net"
LI_UNIT_GROSS = "line_item_unit_price_gross"
LI_AMT_NET = "line_item_amount_net"
LI_AMT_GROSS = "line_item_amount_gross"
