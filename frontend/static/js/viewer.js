/** Page image + grounded bbox overlay. */

import {
  FIELD_COLORS,
  HEADER_FIELDS,
  LINE_ITEM_FIELDS,
} from "./constants.js";
import { pageImageUrl } from "./api.js";

export function createViewer({ pageImg, overlay, legend }) {
  const ctx = overlay.getContext("2d");
  let boxes = [];

  function resize() {
    overlay.width = pageImg.clientWidth;
    overlay.height = pageImg.clientHeight;
    overlay.style.width = `${pageImg.clientWidth}px`;
    overlay.style.height = `${pageImg.clientHeight}px`;
    draw();
  }

  function clear() {
    boxes = [];
    ctx.clearRect(0, 0, overlay.width, overlay.height);
    legend.innerHTML = "";
  }

  function collect(invoice) {
    const out = [];
    for (const k of HEADER_FIELDS) {
      const f = invoice[k];
      if (f?.bbox && f.page === 0) {
        out.push({ key: k, label: k, ...f, color: FIELD_COLORS[k] });
      }
    }
    (invoice.line_items || []).forEach((li, i) => {
      for (const k of LINE_ITEM_FIELDS) {
        const f = li[k];
        if (f?.bbox && f.page === 0) {
          out.push({
            key: `li${i}.${k}`,
            label: `line[${i}].${k}`,
            ...f,
            color: FIELD_COLORS[k],
          });
        }
      }
    });
    return out;
  }

  function draw() {
    ctx.clearRect(0, 0, overlay.width, overlay.height);
    const w = overlay.width;
    const h = overlay.height;
    for (const b of boxes) {
      const [x0, y0, x1, y1] = b.bbox;
      ctx.strokeStyle = b.color;
      ctx.lineWidth = 1.5;
      ctx.globalAlpha = 0.85;
      ctx.strokeRect(x0 * w, y0 * h, (x1 - x0) * w, (y1 - y0) * h);
    }
    ctx.globalAlpha = 1;
  }

  function renderLegend() {
    const seen = new Map();
    for (const b of boxes) {
      const base = b.label.split(".")[0].startsWith("line")
        ? "line_item"
        : b.label;
      if (!seen.has(base)) seen.set(base, b.color);
    }
    legend.innerHTML = "";
    for (const [name, color] of seen) {
      const span = document.createElement("span");
      span.textContent = name;
      const dot = document.createElement("i");
      dot.style.cssText =
        `display:inline-block;width:10px;height:10px;background:${color};` +
        "border-radius:2px;margin-right:4px;vertical-align:-1px;";
      span.prepend(dot);
      legend.appendChild(span);
    }
  }

  async function showPage(docId) {
    pageImg.src = pageImageUrl(docId);
    await pageImg.decode().catch(() => {});
    resize();
    clear();
  }

  function showInvoice(invoice) {
    boxes = collect(invoice);
    renderLegend();
    draw();
  }

  pageImg.addEventListener("load", resize);
  window.addEventListener("resize", resize);

  return { showPage, showInvoice, clear, resize };
}
