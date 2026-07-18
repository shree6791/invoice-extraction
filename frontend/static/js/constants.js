/** Field highlight colors + tenant tier colors. */

export const FIELD_COLORS = {
  invoice_id: "#3d9cf0",
  seller_name: "#5ec48a",
  date: "#e0b15a",
  subtotal: "#e07a5f",
  tax: "#e07a5f",
  total: "#ff6b6b",
  description: "#9b7bde",
  quantity: "#9b7bde",
  unit_price: "#9b7bde",
  line_total: "#9b7bde",
};

export const HEADER_FIELDS = [
  "invoice_id",
  "seller_name",
  "date",
  "subtotal",
  "tax",
  "total",
];

export const LINE_ITEM_FIELDS = [
  "description",
  "quantity",
  "unit_price",
  "line_total",
];

export const TIER_COLORS = {
  free: "#888",
  professional: "#3d9cf0",
  enterprise: "#5ec48a",
};
