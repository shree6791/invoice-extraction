# System

Architecture hub for the Invoice Extraction product: what we run today, target topology, component swaps, tenancy, and design traps.

| Doc | Contents |
|---|---|
| **This file** | Phase 0 vs design, topology, component choices, tenancy, traps |
| [`CAPACITY.md`](CAPACITY.md) | Demand, Little’s Law, latency, ingestion/HPA, sharding, adapter serving |
| [`RELIABILITY.md`](RELIABILITY.md) | Retry/DLQ, rollups, warehouse, operability |
| [`DIAGRAMS.md`](DIAGRAMS.md) | Mermaid architecture sketches |

Product surface: [`PRODUCT.md`](PRODUCT.md). Extract / ground / eval: [`EXTRACTION.md`](EXTRACTION.md). Diagrams: [`DIAGRAMS.md`](DIAGRAMS.md).

**Design point:** 100M req/day ceiling; **4M docs/day** operating point ([`CAPACITY.md`](CAPACITY.md#demand-derivation)).  
**Load-bearing decision:** self-hosted LLM — API cost (~$95K/day order) and rate limits are a hard ceiling at this volume.

**Phase 0 (now):** one FastAPI process; in-memory queue / cache / job store; single worker. Proves **contracts**, not scale. Rows in [Component choices](#component-choices) under **Now** are what ships today; **At scale** is the design target.

---

## Target topology

Visual: [`DIAGRAMS.md` target fleet](DIAGRAMS.md#target-fleet-topology) · [Phase 0](DIAGRAMS.md#phase-0-now).

```
CDN / edge     API key -> {tenant, region, shard, quota}; token bucket -> 429
     |
Regional API   Redis dedup (ETag) -> Kafka (tenant_id-partitioned, per-tenant fairness)
     |
Parse pods (CPU) --parse-complete--> Extract pods (GPU / vLLM) --> retry/DLQ
     |
Shard          Postgres (jobs, <48h hot) . S3 (PDF + result JSON, + warehouse tier)
     |
Rollups        Metrics aggregator (per-tenant, per-minute/hour/day) -> dashboard read path
```

Parse and extract scale independently (separate HPA). Retry/DLQ and warehouse detail: [`RELIABILITY.md`](RELIABILITY.md). Sizing: [`CAPACITY.md`](CAPACITY.md).

---

## Component choices

Each row is a build-now vs. build-later trade-off. Build later when the "now" column stops holding at the target design point.

| Concern | Now | At scale | Trade-off |
|---|---|---|---|
| Queue | `asyncio.Queue` (`InMemoryQueue`) | Kafka (tenant_id-partitioned) | In-memory: zero ops cost, no replay, dies with the process. Kafka: replay + per-tenant fairness, adds a cluster to run. |
| Dedup | In-process (`InMemoryCache`) | Redis Cluster (ETag) | In-process: free, lost on restart. Redis: idempotent across restarts and multi-node, adds a dependency. |
| Jobs | Dict (`InMemoryJobStore`) | Postgres + PgBouncer | Dict: instant, no durability. Postgres: durable status survives restarts, adds write latency. |
| Retry/DLQ | None | Dead-letter topic + retry queue | None: simplest, a down LLM backend silently drops jobs. DLQ: bounds retry cost, adds a queue to monitor. |
| Blobs | Local DocILE / tenant PDFs | S3 presigned | Local: no setup. S3: removes API from the upload path, adds presign/auth plumbing. |
| Warehouse | None | S3 partitioned (date/tenant) + Athena | None: no audit-query support. Athena: cheap for low-frequency partition-scoped queries, wrong choice if query patterns get complex or frequent. |
| Rollups | None | Redis / time-series store | None: dashboards would scan raw jobs. Rollup store: fast reads, another store to keep in sync. |
| LLM | Anthropic SDK | vLLM OpenAI-compat | API: no infra, costs scale linearly with volume and hits rate limits (~$95K/day order at design point). Self-hosted: fixed infra cost, requires GPU capacity. Cheapest once parse/extract are already split, since GPU sizing then doesn't compete with parse's CPU footprint. |
| Workers | 1 thread | K8s parse / extract tiers | 1 thread: nothing to operate. Split tiers: isolates CPU-bound parse from GPU-bound extract, requires K8s. |
| Control plane | `InMemoryControlPlane` + `TenantMiddleware` | Postgres + Redis edge cache | In-memory: single-process only. Postgres+Redis: multi-node tenant lookup, adds a cache-invalidation surface. |

Queue, cache, and job store are wired in `app.py` lifespan; control plane runs through `TenantMiddleware`. Swapping any row does not change pipeline code.

---

## Tenancy

A tenant is one customer of the extraction API. Extraction code is identical across tiers; isolation differs by tier.

| Tier | Isolation |
|---|---|
| Free / Business | Shared schema + `tenant_id` + RLS |
| Professional | Schema-per-tenant |
| Enterprise | DB-per-tenant (silo) |

Region and shard are separate axes and are not conflated: region is a residency boundary, fixed at signup; shard is a load-balancing boundary, assigned via an explicit lookup table (see [`CAPACITY.md` partitioning](CAPACITY.md#partitioning--sharding)).

Noisy-neighbor protection layers: edge token bucket, then Kafka partition fairness (`tenant_id` key), then a per-tenant concurrency semaphore.

Demo data: `data/tenants/`. Auth: `X-API-Key` resolves to `request.state.tenant`.

The CDN's value is TLS/DDoS termination, static UI, and cached tenant lookup — not caching `GET /jobs/{id}`, which is per-tenant and mutates frequently.

---

## Design traps

| Question | Answer |
|---|---|
| Go for 2.5k goroutines? | Wrong lever — LLM latency and cost dominate; scale with pods and Kafka. Go is optional later, for thin enqueue only. |
| Bboxes in the LLM prompt? | Non-deterministic; breaks audit. Ground from parsed spans instead. |
| F1 only KPI? | No — F1, IoU pass@0.5, coverage, review rate, cost/doc, lag, and DLQ depth together. |
| ADE vs. build? | Compare miss-cost × volume against API spend, on the same DocILE bake-off. |
| Does DAU math justify our scale? | Order-of-magnitude ceiling only — 10M DAU, not 100M. Load is tenant-concentrated, not user-concentrated. DAU math applied directly would mis-shape sharding and fairness design (see [`CAPACITY.md` demand](CAPACITY.md#demand-derivation)). |
| What if the LLM backend is down mid-extraction? | Bounded retry, then DLQ, then alert — not unbounded retry (amplifies the outage) or silent drop (loses the job). See [`RELIABILITY.md` pipeline](RELIABILITY.md#extraction-pipeline-failure-durability-and-storage). |
| How do dashboards stay fast at 4M docs/day? | Pre-computed rollups, sharded by tenant; never a live scan of raw job records. See [`RELIABILITY.md` rollups](RELIABILITY.md#metrics-rollups-dashboard-read-path). |
| Why S3+Athena for the warehouse, not Redshift/Snowflake? | Query pattern is low-frequency and partition-scoped; a managed warehouse adds ETL and cost without a matching latency requirement at this stage. See [`RELIABILITY.md` warehouse](RELIABILITY.md#warehouse-tier-long-term--audit). |
| Why no phase-numbered rollout plan? | [Component choices](#component-choices) states, per component, what changes and why. A separate phase table would re-sequence the same trade-offs without adding information. |
| How does serving cost scale with more industry verticals? | Sub-linearly — new verticals add small LoRA adapters on the shared base model, not new model deployments (see [`CAPACITY.md` adapters](CAPACITY.md#model-serving--adapter-scaling)). |

---

## Notes

- "Tenant" = one customer account of the API (a company, or a freelancer), isolated from every other tenant's data. Used instead of "customer" because it specifically means isolation, not just billing.
