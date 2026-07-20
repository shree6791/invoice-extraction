# Invoice Extraction

**Parse → Extract → Ground → Chat.** Messy PDFs become schema-typed, grounded fields — then ask questions that cite those fields. Same product shape as document AI platforms (ADE-class), Phase-0 prototype on [DocILE](https://github.com/rossumai/docile).

| Stage | Guarantees |
|---|---|
| **Parse** | PDF → word spans + layout markdown (PyMuPDF; OCR fallback) |
| **Extract** | Schema fields via LLM / fast path; values must come from layout text |
| **Ground** | Each value → `page + bbox + quote` (deterministic post-hoc match; never LLM-emitted boxes) |
| **Chat** | Q&A over the grounded invoice; citations only from grounded fields |

Failed grounding → `needs_review` (value kept, bbox cleared). Responses expose `routing` / `escalated`.

**Docs (one concern each)**

| Doc | Read when |
|---|---|
| [`docs/PRODUCT.md`](docs/PRODUCT.md) | Principles, KPIs, competitive frame, talk track |
| [`docs/EXTRACTION.md`](docs/EXTRACTION.md) | Pipeline, schema, grounding, chat, eval, model roadmap |
| [`docs/SYSTEM.md`](docs/SYSTEM.md) | Architecture hub — topology, swaps, tenancy, traps |
| [`docs/CAPACITY.md`](docs/CAPACITY.md) | Demand, latency, ingestion, sharding, adapters |
| [`docs/RELIABILITY.md`](docs/RELIABILITY.md) | Retry/DLQ, rollups, warehouse, operability |
| [`docs/SIZING.md`](docs/SIZING.md) | Worker/core/GPU sizing math (Little's Law → cores/GPUs) |

## Setup

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# .env: ANTHROPIC_API_KEY=
```

`data/docile/` — local DocILE root (symlink OK). Gitignored; do not commit or move it.  
`data/tenants/` — demo set (5 companies × 5 docs); committed.

## Run

```bash
uvicorn backend.app:app --reload --port 8000   # http://127.0.0.1:8000
python -m eval                                 # value F1 + IoU pass@0.5
```

Eval writes `outputs/eval_report.json` (gitignored via `outputs/`).

## API

```bash
curl -X POST localhost:8000/api/extract -H 'Content-Type: application/json' -d '{"doc_id":"<id>"}'
curl -X POST localhost:8000/api/jobs    -H 'Content-Type: application/json' -d '{"doc_id":"<id>"}'
curl localhost:8000/api/jobs/<job_id>
curl localhost:8000/api/tenants
curl 'localhost:8000/api/samples?company=acme-corp'
```

OpenAPI: `http://localhost:8000/docs`

## Layout

```
backend/       FastAPI · LangGraph pipeline · infra swaps · tenants
eval/          Value F1 + bbox IoU (`python -m eval`)
frontend/      Static demo UI (`js/` modules)
docs/          PRODUCT · EXTRACTION · SYSTEM · CAPACITY · RELIABILITY · SIZING
data/tenants/  Demo invoices (5 × 5)
data/docile/   Full DocILE (local only)
```

## Env

| Variable | Default |
|---|---|
| `ANTHROPIC_API_KEY` | required |
| `ANTHROPIC_MODEL_DEMO` | `claude-sonnet-4-5-20250929` |
| `ANTHROPIC_MODEL_EVAL` | `claude-haiku-4-5-20251001` |
