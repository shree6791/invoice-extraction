/** Demo UI bootstrap: tenants → samples → extract → viewer + chat. */

import { extractInvoice, fetchSamples, fetchTenants } from "./api.js";
import { TIER_COLORS } from "./constants.js";
import { createChat } from "./chat.js";
import { $ } from "./util.js";
import { createViewer } from "./viewer.js";

const companySelect = $("companySelect");
const tenantBadge = $("tenantBadge");
const sampleSelect = $("sampleSelect");
const extractBtn = $("extractBtn");
const statusEl = $("status");
const reviewBadge = $("reviewBadge");

const setStatus = (msg) => {
  statusEl.textContent = msg;
};

const viewer = createViewer({
  pageImg: $("pageImg"),
  overlay: $("overlay"),
  legend: $("legend"),
});

const chat = createChat({
  questionEl: $("chatQuestion"),
  btn: $("chatBtn"),
  answerEl: $("chatAnswer"),
  citationsEl: $("chatCitations"),
  setStatus,
});

function updateTenantBadge(tenant) {
  const color = TIER_COLORS[tenant.tier] || "#888";
  tenantBadge.innerHTML =
    `<span style="color:${color};font-weight:600;">${tenant.tier}</span>` +
    `<span style="color:#aaa;margin-left:6px;">· ${tenant.region}</span>`;
}

function resetForNewDoc() {
  chat.reset();
  reviewBadge.textContent = "";
  viewer.clear();
}

async function loadCompanies() {
  const data = await fetchTenants();
  companySelect.innerHTML = "";
  for (const t of data.tenants || []) {
    const opt = document.createElement("option");
    opt.value = t.slug;
    opt.dataset.tier = t.tier;
    opt.dataset.region = t.region;
    opt.textContent = t.slug;
    companySelect.appendChild(opt);
  }
  if (data.tenants?.length) {
    updateTenantBadge(data.tenants[0]);
    await loadSamples(data.tenants[0].slug);
  }
}

async function loadSamples(company) {
  const data = await fetchSamples(company);
  sampleSelect.innerHTML = "";
  for (const s of data.samples || []) {
    const opt = document.createElement("option");
    opt.value = s.doc_id;
    opt.textContent = `${s.doc_id.slice(0, 10)}… (c${s.cluster_id ?? "?"}, ${s.page_count ?? "?"}p)`;
    sampleSelect.appendChild(opt);
  }
  resetForNewDoc();
  if (data.samples?.length) {
    await viewer.showPage(data.samples[0].doc_id);
  }
}

async function extractDoc(docId) {
  setStatus("Extracting…");
  extractBtn.disabled = true;
  try {
    await viewer.showPage(docId);
    const data = await extractInvoice(docId);
    viewer.showInvoice(data.invoice);
    chat.ready(data.invoice);

    const nReview = (data.needs_review || []).length;
    reviewBadge.textContent = nReview
      ? `${nReview} field(s) need review`
      : "All grounded fields passed confidence threshold";

    const m = data.metrics || {};
    setStatus(`Done in ${m.latency_s}s · $${m.cost_usd}`);
  } catch (err) {
    setStatus("Error");
    chat.reset();
    reviewBadge.textContent = String(err);
  } finally {
    extractBtn.disabled = false;
  }
}

extractBtn.addEventListener("click", () => {
  if (sampleSelect.value) extractDoc(sampleSelect.value);
});

companySelect.addEventListener("change", () => {
  const opt = companySelect.selectedOptions[0];
  updateTenantBadge({ tier: opt.dataset.tier, region: opt.dataset.region });
  loadSamples(companySelect.value);
});

sampleSelect.addEventListener("change", () => {
  resetForNewDoc();
  viewer.showPage(sampleSelect.value);
});

chat.reset();
loadCompanies();
