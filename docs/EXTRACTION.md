# Extraction

How **Parse → Extract → Ground → Chat** works, how we score it, and how the model stack evolves.

Product framing: [`PRODUCT.md`](PRODUCT.md). Fleet: [`SYSTEM.md`](SYSTEM.md) · [`CAPACITY.md`](CAPACITY.md) · [`RELIABILITY.md`](RELIABILITY.md). Diagrams: [`DIAGRAMS.md`](DIAGRAMS.md).

---

## Pipeline (today)

Visual: [`DIAGRAMS.md` LangGraph](DIAGRAMS.md#extract-pipeline-langgraph).

```
PDF
  → Parse     PyMuPDF per page in parallel (ThreadPool; one Document per worker)
              → spans + blocks → join → markdown
  → LangGraph classify_extract
        hard  → extract_claude
        easy  → extract_mock_fast
                  ├─ needs_review empty → finalize
                  └─ needs_review set   → extract_claude (escalate)
  → Ground    inside each extract path (`grounding.py`)
              value → span match → FieldValue{value, page, bbox, quote}
  → Chat      optional; POST /api/chat over grounded invoice JSON
```

- **Parse** always uses PyMuPDF (OCR fallback when native text is thin). Parallelism is page-level; markdown is built after all pages finish.
- **MockFast** is not PDF parsing — it's a cheap *extract* stand-in (regex today → LayoutLM/GPU later) that only sees markdown.
- **Conditional edges** in LangGraph own easy/hard and escalate-vs-done.
- **Failure handling** (bounded retry → DLQ → alert on exhausted retries) lives at the fleet level — see [`RELIABILITY.md`](RELIABILITY.md#extraction-pipeline-failure-durability-and-storage).

Orchestration: `backend/graph/graph.py`.
Helpers: `layout.py`, `extract/service.py` (`run_mock_fast` / `run_claude`), `grounding.py`, `chat.py`.

**Invariant:** the LLM emits text only. Coordinates are reconstructed from parse spans — never generated, never asked for.

`value` = model's field answer · `quote` = exact page span used as evidence (may differ under OCR cleanup).

---

## Schema (scope)

We score a **subset** of DocILE — not every annotated fieldtype. Unmapped labels (addresses, `amount_due`, `order_id`, …) are ignored by eval.

| Our field | DocILE `fieldtype` |
|---|---|
| `invoice_id` | `document_id` |
| `seller_name` | `vendor_name` |
| `date` | `date_issue` |
| `subtotal` | `amount_total_net` *(sparse in demo set)* |
| `tax` | `amount_total_tax` *(sparse)* |
| `total` | `amount_total_gross` |
| line: `description`, `quantity`, `unit_price`, `line_total` | `line_item_*` (net preferred, else gross) |

Map: `backend/settings/constants/docile.py`.

---

## Grounding

`find_span_scored` (`grounding.py`):

- Field-typed normalize (money / date / id / text)
- rapidfuzz on single spans + same-row joins (≤ 8)
- Length-ratio guard (blocks `12` ⊂ `112.50`)
- Money: label proximity (`TOTAL`, `SUBTOTAL`, …) + tightest exact bbox
- Near-tie without a clear winner → ungrounded + `needs_review`

| Failure mode | Frequency (rough, unmitigated) | Mitigation | Residual risk after mitigation |
|---|---|---|---|
| Repeated `$` amounts (ambiguous match) | Largest single source of grounding error on multi-line-item invoices | Label boost (proximity to `TOTAL`/`SUBTOTAL`) | Top residual risk — label boost helps but doesn't fully disambiguate three similar totals on one page |
| Normalization mismatch (`$450.00` vs `450.00`; date formats) | Common, but systematic | Field-typed normalize — money/date get aggressive stripping, IDs keep hyphens/slashes | Near-zero once field-typed |
| Substring trap (`12` ⊂ `112.50`) | Occasional | Length-ratio guard | Low — edge case is near-equal-length false positives |
| OCR junk (`ARNOLD`→`ABNOLD`) | Only on scanned/OCR'd docs, not native-text PDFs | Fuzzy threshold ~0.55 | Depends on OCR quality; native PyMuPDF text avoids this entirely |
| Split multi-word values (vendor names, addresses) | Common — PyMuPDF word-level spans rarely equal one value | Same-row joins (≤ 8 spans, y-tolerance) | Low once joined; fails only if a value spans more than 8 tokens or crosses rows |

---

## Chat

After extract+ground, `POST /api/chat` answers from the invoice JSON only. Citations resolve to field paths with `page` / `quote` / confidence; low-confidence or missing grounding → listed as uncertain. UI: Ask panel in `frontend/static/` (enabled only after a successful extract).

---

## Evaluation

```bash
python -m eval   # → outputs/eval_report.json
```

Two orthogonal gates:

| Gate | Measures | Definition |
|---|---|---|
| **Value F1** | Extract text | TP/FP/FN vs DocILE after field mapping. Line rows: description fuzzy **or containment** ≥ 0.5, else **`line_total` fallback** |
| **IoU pass@0.5** | Ground quality | Among *value-correct* fields with pred+gold boxes (0–1 coords): fraction with IoU ≥ 0.5 |

Also: coverage (% values with a bbox), mean IoU, pass@0.7.

**IoU numbers.**
- Percentage-point pass rates (0–100 scale), not raw average overlap — "82% pass@0.5" means 82% of value-correct, boxed fields have ≥50% overlap with the gold box.
- 5–10 point pass-rate gap vs. a vendor benchmark: closable with grounding tuning (see failure-mode table above).
- 15+ point gap, especially concentrated in the repeated-amount failure mode: signals a structural limit of post-hoc fuzzy matching, not a tuning gap — see [`PRODUCT.md`](PRODUCT.md#competitive-frame) for how that distinction drives build-vs-buy.

**Gating:** IoU only runs after the value matches gold (and, for lines, after the row is paired). Wrong text or unmatched rows never enter IoU stats.

**Both gates required:** perfect boxes on wrong totals don't help the AP clerk; correct totals with missing boxes still pass F1 but fail audit UI. Improving `grounding.py` moves IoU, not F1.

Internal release protocol — not DocILE's official word-overlap AP. Code: `eval/metrics.py`, `gt_header_gold_boxes`, `gt_line_items_gold`.

---

## Model strategy

### Why layout-aware models exist

1D BERT/GPT discard *where* a token sits. Document models fuse **word + 2D bbox + image patch** per token before attention.

| Family | Examples | Grounding |
|---|---|---|
| OCR-then-encode | LayoutLM, LiLT, BROS | Bbox is an **input**; labels zip onto those boxes |
| OCR-free | Donut, Pix2Struct | Pixels → text; no inherent word boxes |

LayoutLM (compressed): BIO token classifier; at infer, argmax labels zip to input boxes. Bbox was already an input feature, never something the model generates. Best for fixed layouts + closed label sets; poor fit for our varied invoice templates without per-template fine-tuning.

### Where we sit

| | This product (now) | LayoutLM fast path (target) | ADE-class API |
|---|---|---|---|
| Grounding | Post-hoc fuzzy | Structural | Structural (vendor) |
| Training | None | Fine-tune / LoRA | None (their weights) |
| Varied layouts | Strong | Needs clusters | Strong |
| Failure mode owned by us | Yes — every row in the grounding table above is ours to fix | N/A once trained | No — opaque, only observable via IoU delta |

### Escalation (cost control)

```
Classify (roadmap) → Parse
  → fast path: LayoutLM / MockFast   ~50ms–1s
  → mid:       fine-tuned LLM
  → edge:      Claude
```

Today: `escalation.py` + `MockFastExtractor`. Production dial = escalation **rate** — target ~80% on the fast path.

**80%, not higher:**
- Fast path only owns documents where MockFast's regex/pattern match returns empty `needs_review` — layouts it's confident about.
- Pushing past ~80% means accepting fast-path answers on ambiguous documents — trading cost savings for exactly the errors the failure-mode table above exists to catch.
- The rate is a dial against risk, not a pure cost-minimization target.

### Multi-vertical + flywheel

One shared base + **classify → LoRA** per industry/doc-type. DocILE `cluster_id` seeds layout clustering. Confirmed extractions → per-cluster training → LoRA patches. At tens of M docs/day even a small confirm rate dominates cold-start corpora. Infra cost of serving many adapters: [`CAPACITY.md`](CAPACITY.md#model-serving--adapter-scaling).

---

## Out of scope here

Capacity, Kafka, tenancy, component trade-offs → [`SYSTEM.md`](SYSTEM.md). Sizing math → [`CAPACITY.md`](CAPACITY.md). Failure/retry, rollups → [`RELIABILITY.md`](RELIABILITY.md).
