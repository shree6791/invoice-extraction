"""DocILE invoice models + LLM drafts."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from backend.models.common import FieldValue


class LineItem(BaseModel):
    description: FieldValue = Field(default_factory=FieldValue)
    quantity: FieldValue = Field(default_factory=FieldValue)
    unit_price: FieldValue = Field(default_factory=FieldValue)
    line_total: FieldValue = Field(default_factory=FieldValue)


class Invoice(BaseModel):
    invoice_id: FieldValue = Field(default_factory=FieldValue)
    seller_name: FieldValue = Field(default_factory=FieldValue)
    date: FieldValue = Field(default_factory=FieldValue)
    subtotal: FieldValue = Field(default_factory=FieldValue)
    tax: FieldValue = Field(default_factory=FieldValue)
    total: FieldValue = Field(default_factory=FieldValue)

    line_items: list[LineItem] = Field(default_factory=list)
    needs_review: list[str] = Field(default_factory=list)
    unmapped_content: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    def values_only(self) -> dict[str, Any]:
        return {
            "invoice_id": self.invoice_id.value,
            "seller_name": self.seller_name.value,
            "date": self.date.value,
            "subtotal": self.subtotal.value,
            "tax": self.tax.value,
            "total": self.total.value,
            "line_items": [
                {
                    "description": li.description.value,
                    "quantity": li.quantity.value,
                    "unit_price": li.unit_price.value,
                    "line_total": li.line_total.value,
                }
                for li in self.line_items
            ],
            "needs_review": self.needs_review,
            "unmapped_content": self.unmapped_content,
            "notes": self.notes,
        }


class LineItemDraft(BaseModel):
    description: str | None = None
    quantity: str | None = None
    unit_price: str | None = None
    line_total: str | None = None


class InvoiceDraft(BaseModel):
    invoice_id: str | None = None
    seller_name: str | None = None
    date: str | None = None
    subtotal: str | None = None
    tax: str | None = None
    total: str | None = None
    line_items: list[LineItemDraft] = Field(default_factory=list)
    needs_review: list[str] = Field(default_factory=list)
    unmapped_content: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
