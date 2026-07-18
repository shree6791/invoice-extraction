# System

Scale, tenancy, and infrastructure for the Invoice Extraction product.

Product surface: [`PRODUCT.md`](PRODUCT.md). Extract / ground / eval: [`EXTRACTION.md`](EXTRACTION.md).

**Design point:** ~**34M docs/day** steady-state (~394/s; 3× peak). ×30 ≈ 1B/day narrative.  
**Load-bearing decision:** self-hosted LLM — API cost (~$95K/day order) and rate limits are a hard ceiling.

---

## Goals

| Goal | Bar |
|---|---|
| Latency | Enqueue &lt; 50 ms; result &lt; 15 s P99 |
| Throughput | Design to 34M/day; path to 1B/day |
| Correctness | Grounded fields; no silent spatial guesses |
| Operability | Job lifecycle visible; backends swappable |
| Cost | Extract path dominates — every tier decision prices the LLM |

---

## Capacity

```
concurrency = arrival_rate × service_time
```

| Backend | ~Service time | In-flight @ 394/s | @ 3× peak |
|---|---|---|---|
| Claude API | ~10 s | ~4K | ~12K |
| Self-hosted LLM | ~1 s | ~400 | ~1.2K |
| LayoutLM fast path | ~50–200 ms | ~20–80 | ~60–240 |

**Latency is fleet size.** Cut extract time 10× → cut concurrency 10×.

**Per-event (order of magnitude):** ~100 KB PDF · ~4 KB markdown · ~$0.003 / ~4 s (Haiku eval) · ~25 KB grounded JSON.

**Storage:** 34M × 100 KB ≈ 3.4 TB/day PDF → S3 + lifecycle. Jobs: partition by time; keep &lt; 48 h hot in Postgres.

**GPU sketch @ 1 s/doc, batch 8:** ~50 GPUs → ~7×8-GPU nodes (sketch, not a PO).

Demand segments (Fortune / mid / SMB / freelance) sum to the 34M design point — same math as before; don’t re-litigate in reviews.

---

## Phase 0 (now)

One FastAPI process; in-memory queue / cache / job store; single `asyncio.to_thread` worker. Proves **contracts**, not scale.

| Limit | Cause |
|---|---|
| ~3K–8K jobs/day | One worker |
| No durability | Process memory |
| No multi-node | Local dicts |
| No backpressure | Unbounded queue |

`POST /api/extract` = sync demo. Production ingress = `POST /api/jobs` only.

---

## Target topology

```
CDN / edge     API key → {tenant, region, shard, quota}; token bucket → 429
     │
Regional API   Redis dedup (ETag) → Kafka (per-tenant fairness)
     │
Parse pods (CPU) ──parse-complete──► Extract pods (GPU / vLLM)
     │
Shard          Postgres (jobs) · S3 (PDF + result JSON)
```

**Backpressure:** lag over threshold → HTTP 429. Unbounded queues hide failure.

**Split parse/extract:** independent HPA; bad PDFs don’t kill GPU pods.

---

## Component choices

| Concern | Phase 0 | Production | Why |
|---|---|---|---|
| Queue | `asyncio.Queue` (`InMemoryQueue`) | Kafka | Replay + throughput |
| Dedup | In-process (`InMemoryCache`) | Redis Cluster (ETag) | Idempotency, not hit-rate |
| Jobs | Dict (`InMemoryJobStore`) | Postgres + PgBouncer | Durable status |
| Blobs | Local DocILE / tenant PDFs | S3 presigned | Remove API from upload path |
| LLM | Anthropic SDK | vLLM OpenAI-compat | Cost + residency |
| Workers | 1 thread | K8s parse / extract tiers | Isolate CPU vs GPU |
| Control plane | `InMemoryControlPlane` + `TenantMiddleware` | Postgres + Redis edge cache | Tenant lookup / quotas |

**Swap seams:** queue / cache / job store wired in `app.py` lifespan; control plane via `TenantMiddleware`. Pipeline code does not change.

---

## Tenancy

Tenant = one customer of the extraction API. **Same extract code**; isolation differs by tier.

| Tier | Isolation |
|---|---|
| Free / Business | Shared schema + `tenant_id` + RLS |
| Professional | Schema-per-tenant |
| Enterprise | DB-per-tenant (silo) |

**Axes (do not conflate):**  
- **Region** — residency (immutable at signup)  
- **Shard** — load (explicit lookup table, not consistent hashing)

Noisy neighbors: edge token bucket → Kafka partition fairness → per-tenant concurrency semaphore.

Demo data: `data/tenants/`. Auth: `X-API-Key` → `request.state.tenant`.

CDN earns its keep on TLS/DDoS, static UI, and **cached tenant lookup** — not on caching `GET /jobs/{id}`.

---

## Rollout

| Phase | Ships | Unlocks |
|---|---|---|
| 0 | In-memory mocks | Interface proof |
| 1 | Kafka + Redis + Postgres | Durability, multi-node |
| 2 | S3 + gateway + HPA | Stateless API, quotas |
| 3 | Self-hosted LLM | Escape API $ / RPM wall |
| 4 | Split parse/extract | Independent scale |
| 5 | LayoutLM / LoRA cascade | Cost dial on escalation rate |
| 6 | Tiered tenancy + regions | Enterprise compliance |
| 7 | Webhooks / SDK | Distribution |

---

## Operability (failure path)

Alert on review-rate / lag / cost / grounding miss — **with** tenant, job, routing, model, cluster, blast radius.

Then: liveness (workers, GPU) → readiness (S3/PG/LLM) → smoke golden PDF → **log digest** (not raw GB) → allowlisted tools (`requeue`, `force_claude`, `search_sop`, …) → SOP DB → P1 (&lt;5m) … P4 (≤5d).

Auto-fix → report steps taken. Else → human channel with recommendations.

---

## Design traps

| Question | Answer |
|---|---|
| Go for 2.5k goroutines? | Wrong lever. LLM latency/cost dominates; scale with pods + Kafka. Go optional later for thin enqueue only. |
| Bboxes in the LLM prompt? | Non-deterministic; breaks audit. Ground from spans. |
| F1 only KPI? | No — F1 + IoU pass@0.5 + coverage + review rate + $/doc + lag. |
| ADE vs build? | Miss-cost × volume vs API $; same DocILE bake-off. |
