/** Thin fetch wrappers for the demo API. */

async function json(res) {
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export function fetchTenants() {
  return fetch("/api/tenants").then(json);
}

export function fetchSamples(company) {
  const url = company
    ? `/api/samples?company=${encodeURIComponent(company)}`
    : "/api/samples";
  return fetch(url).then(json);
}

export function extractInvoice(docId) {
  return fetch("/api/extract", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ doc_id: docId }),
  }).then(json);
}

export function askChat(question, invoice) {
  return fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, invoice }),
  }).then(json);
}

export function pageImageUrl(docId, page = 0) {
  return `/api/page-image/${encodeURIComponent(docId)}?page=${page}&t=${Date.now()}`;
}
