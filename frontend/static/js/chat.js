/** Grounded Q&A panel. */

import { askChat } from "./api.js";
import { escapeHtml } from "./util.js";

export function createChat({ questionEl, btn, answerEl, citationsEl, setStatus }) {
  let invoice = null;

  function setEnabled(on) {
    btn.disabled = !on;
    btn.title = on ? "" : "Extract a document first";
    questionEl.disabled = !on;
  }

  function reset(message = "Extract a document first, then ask grounded questions.") {
    invoice = null;
    setEnabled(false);
    answerEl.textContent = message;
    citationsEl.textContent = "";
  }

  function ready(nextInvoice) {
    invoice = nextInvoice;
    setEnabled(true);
    answerEl.textContent = "Ask a question about this invoice.";
    citationsEl.textContent = "";
  }

  function renderCitations(data) {
    const citations = data.citations || [];
    if (!citations.length) {
      citationsEl.textContent =
        (data.uncertain_fields || []).length
          ? "No confident citations for this answer."
          : "";
      return;
    }
    citationsEl.innerHTML = citations
      .map((c) => {
        const field = escapeHtml(c.field || "");
        const page = c.page ?? "?";
        const quote = c.quote ? escapeHtml(c.quote) : "";
        const conf = c.confidence != null ? ` (${c.confidence})` : "";
        return `<div class="cite"><code>${field}</code> p${page}${conf}: ${quote}</div>`;
      })
      .join("");
  }

  async function ask() {
    const q = (questionEl.value || "").trim();
    if (!q) {
      setStatus("Enter a question");
      return;
    }
    if (!invoice) {
      answerEl.textContent = "Extract a document first.";
      return;
    }

    btn.disabled = true;
    setStatus("Asking…");
    try {
      const data = await askChat(q, invoice);
      answerEl.textContent = data.answer || "";
      renderCitations(data);
    } catch (err) {
      answerEl.textContent = String(err);
      citationsEl.textContent = "";
    } finally {
      setStatus("Ready");
      setEnabled(!!invoice);
    }
  }

  btn.addEventListener("click", ask);

  return {
    reset,
    ready,
    get invoice() {
      return invoice;
    },
  };
}
