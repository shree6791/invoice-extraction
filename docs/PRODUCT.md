# Product

Invoice Extraction as a **document AI product**: one API that turns PDFs into grounded, schema-typed JSON — not a bag of scripts.

Peers in the market (e.g. Landing AI ADE) sell the same verbs. We implement them explicitly so every design choice maps to a customer-visible guarantee.

Pipeline / eval depth: [`EXTRACTION.md`](EXTRACTION.md). Fleet: [`SYSTEM.md`](SYSTEM.md) · [`CAPACITY.md`](CAPACITY.md) · [`RELIABILITY.md`](RELIABILITY.md).

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
5. **No event is silently lost.** A job that fails extraction retries, then dead-letters, then alerts.
6. **Interfaces before infra.** Queue / cache / job store / control plane swap without rewriting the pipeline.
7. **One codebase, tiered isolation.** Free → enterprise differ in tenancy, not in extract logic.

---

## Quality bar

| KPI | Role | Target (directional) |
|---|---|---|
| **Value F1** | Right text vs DocILE? Release gate for extract. | High-80s/90s%, field-dependent — line items trail headers |
| **IoU pass@0.5** | Of value-correct + boxed fields, % with IoU ≥ 0.5? Release gate for ground. | Low-90s% on unambiguous single-instance fields; meaningfully lower on repeated-amount fields — see [`EXTRACTION.md` grounding](EXTRACTION.md#grounding) failure-mode table |
| **Grounding coverage** | % of predicted values that have a bbox. | High — low coverage means values are landing in `needs_review` too often, a review-queue cost, not a silent failure |
| **`needs_review` rate** | Trust signal; spike = regression. | Stable baseline; alert on delta, not absolute |
| **DLQ depth** | Jobs that exhausted retries against a down/degraded LLM backend. | Near-zero at steady state; nonzero sustained = backend health incident, not a product bug |
| **Cost / doc · latency · queue lag** | Margin and UX. | Escalation rate is the cost lever — target ~80% fast-path ([`EXTRACTION.md`](EXTRACTION.md#escalation-cost-control)) |

Directional targets, not measured production SLOs — current build runs against a demo/DocILE set, not live traffic.

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
| **ADE-class API** | Structural inside their stack; zero-shot schema | Buy speed; you don't own the model |

**Build vs. buy — not "who has higher mean IoU."**
- Quantify cost of a grounding miss at our volume.
- Bake off on the same DocILE set (value F1 + pass@0.5).
- Compare error reduction to API spend.
- Single-digit pass-rate gap: closable with grounding tuning already owned ([`EXTRACTION.md` grounding](EXTRACTION.md#grounding)).
- Large gap concentrated in the repeated-amount failure mode: signals a structural ceiling on the post-hoc approach — this is the threshold where buy gets reconsidered.

---

## Roadmap (product)

| Now | Next | Later |
|---|---|---|
| Parse → Extract → Ground → Chat | Durable jobs (Kafka/Redis/Postgres) | Self-hosted LLM |
| In-memory queue / cache / jobs | Retry/DLQ + metrics rollups (dashboards) | LayoutLM / LoRA fast path |
| Value F1 + IoU eval (`python -m eval`) | S3 + gateway + HPA, split parse/extract | Classify → LoRA per vertical |
| 5 demo tenants | | Warehouse tier (audit queries), tiered isolation + regions |

Component-level trade-offs: [`SYSTEM.md`](SYSTEM.md#component-choices). Fleet math: [`CAPACITY.md`](CAPACITY.md).

---

## Talk track (2 minutes)

Numbers live in SYSTEM — don't re-derive them here.

1. **Product:** Parse → Extract → Ground → Chat; boxes never from the LLM.
2. **Why layout models exist:** 1D transformers discard position; LayoutLM fuses word+bbox+image — the box is an input, not a generated output.
3. **Our bet:** post-hoc grounding for speed-to-ship; escalate easy→hard models for cost. Every failure mode is named and mitigated ([`EXTRACTION.md` grounding](EXTRACTION.md#grounding)).
4. **Scale lever:** Little's Law — cut extract latency, cut concurrency; API $ hits a wall → self-host.
5. **Durability:** bounded retry → DLQ → alert; dashboards read pre-computed rollups, never raw job records — see [`RELIABILITY.md`](RELIABILITY.md#extraction-pipeline-failure-durability-and-storage).
6. **Ops:** enriched alerts → smoke → log digest → allowlisted tools → P1–P4 escalate ([`RELIABILITY.md` operability](RELIABILITY.md#operability-failure-path)).
7. **Buy frame:** miss-cost × volume vs. ADE-class API; same labeled set; pass@0.5 + F1.

Trap answers: [`SYSTEM.md`](SYSTEM.md#design-traps) · model depth: [`EXTRACTION.md`](EXTRACTION.md#model-strategy).
