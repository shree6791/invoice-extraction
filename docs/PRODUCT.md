# Product

Invoice Extraction as a **document AI product**: one API that turns PDFs into grounded, schema-typed JSON — not a bag of scripts.

Peers in the market (e.g. Landing AI ADE) sell the same verbs. We implement them explicitly so every design choice maps to a customer-visible guarantee.

Pipeline / eval depth: [`EXTRACTION.md`](EXTRACTION.md). Fleet / tenancy: [`SYSTEM.md`](SYSTEM.md).

---

## Surface

| Verb | Contract |
|---|---|
| **Parse** | Structure the page (spans, tables, markdown). Layout is first-class data. |
| **Extract** | Fill a declared schema (header + line items). Zero-shot via LLM today; specialized adapters later. |
| **Ground** | Attach `page + bbox + quote` so a human can click the source. Ambiguity → `needs_review`, never a silent wrong box. |
| **Chat** | Grounded Q&A over the extracted invoice — citations from grounded fields only. |
| **Classify** *(roadmap)* | Doc-type / template cluster → route to the right extractor (LoRA / prompt / vendor). |

Demo tenants under `data/tenants/` are the multi-customer fiction made concrete (5 cos × 5 invoices).

---

## Principles (non-negotiable)

1. **Values and boxes are different contracts.** Extraction quality ≠ grounding quality. Measure both.
2. **The LLM never invents coordinates.** Boxes come from spans we already parsed — deterministic, auditable.
3. **Fail loud on spatial ambiguity.** Repeated amounts without a unique label → review queue, not a coin flip.
4. **Cost is a first-class SLO.** Escalation (cheap → expensive model) is product behavior, not an ops hack.
5. **Interfaces before infra.** Queue / cache / job store / control plane swap without rewriting the pipeline.
6. **One codebase, tiered isolation.** Free → enterprise differ in tenancy, not in extract logic.

---

## Quality bar

| KPI | Role |
|---|---|
| **Value F1** | Right text vs DocILE? Release gate for extract. |
| **IoU pass@0.5** | Of value-correct + boxed fields, % with IoU ≥ 0.5? Release gate for ground. |
| **Grounding coverage** | % of predicted values that have a bbox. |
| **`needs_review` rate** | Trust signal; spike = regression. |
| **Cost / doc · latency · queue lag** | Margin and UX. |

```bash
python -m eval   # → outputs/eval_report.json  (metrics + metrics.grounding)
```

Definitions: [`EXTRACTION.md`](EXTRACTION.md#evaluation).

---

## Competitive frame

| Approach | Grounding | When it wins |
|---|---|---|
| **LayoutLM-family** | Structural — bbox is an *input*; labels zip back onto it | Fixed forms, closed labels, high volume |
| **This product** | Reconstructed — LLM text → fuzzy match → span bbox | Varied invoices fast; no training set required |
| **ADE-class API** | Structural inside their stack; zero-shot schema | Buy speed; you don’t own the model |

**Build vs buy is not “who has higher mean IoU.”**  
Quantify **cost of a grounding miss at our volume** → bake off on the same DocILE set (value F1 + pass@0.5) → compare error reduction to API spend.

---

## Roadmap (product)

| Now (Phase 0) | Next | Later |
|---|---|---|
| Parse → Extract → Ground → Chat | Durable jobs, S3, quotas | Self-hosted LLM |
| In-memory queue / cache / jobs | Real control plane | LayoutLM / LoRA fast path |
| Value F1 + IoU eval (`python -m eval`) | Grounding dashboards | Classify → LoRA per vertical |
| 5 demo tenants | | Tiered isolation + regions |

System phases and fleet math: [`SYSTEM.md`](SYSTEM.md).

---

## Talk track (2 minutes)

Numbers live in SYSTEM — don’t re-derive them here.

1. **Product:** Parse → Extract → Ground → Chat; boxes never from the LLM.  
2. **Why layout models exist:** 1D transformers discard position; LayoutLM fuses word+bbox+image — grounding is free because the box was an input.  
3. **Our bet:** post-hoc grounding for speed-to-ship; escalate easy→hard models for cost.  
4. **Scale lever:** Little’s Law — cut extract latency, cut concurrency; API $ hits a wall → self-host.  
5. **Ops:** enriched alerts → smoke → log digest → allowlisted tools → P1–P4 escalate.  
6. **Buy frame:** miss-cost × volume vs ADE-class API; same labeled set; pass@0.5 + F1.

Trap answers: [`SYSTEM.md`](SYSTEM.md#design-traps) · model depth: [`EXTRACTION.md`](EXTRACTION.md#model-strategy).
