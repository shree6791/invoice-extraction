# System

Scale, tenancy, and infrastructure for the Invoice Extraction product.

Product surface: [`PRODUCT.md`](PRODUCT.md). Extract / ground / eval: [`EXTRACTION.md`](EXTRACTION.md).

**Design point:** 100M req/day ceiling; 4M docs/day operating point.
**Load-bearing decision:** self-hosted LLM. API cost (~$95K/day order) and rate limits are a hard ceiling at this volume.

---

## Capacity

```
concurrency = arrival_rate x service_time      (Little's Law)
```

### Demand derivation

10M DAU x 10 req/user/day = 100M req/day; / 86,400s/day = ~1.16K req/s avg, x3 peak = ~3.5K req/s — architecture ceiling. Operating design point derived bottom-up from US-only, invoices-only tenant counts and AP-industry volume benchmarks:

| Segment | Tenants | Docs/tenant/day | Docs/day |
|---|---|---|---|
| Enterprise | 2,000 | 500 | 1M |
| Mid-market | 20,000 | 100 | 2M |
| SMB | 100,000 | 10 | 1M |

Design point: **4M docs/day**.

### Per-event size

| Artifact | Derivation | Size |
|---|---|---|
| Invoice PDF | ~2-3 pages x ~30-50KB/page (embedded fonts/images) | ~100 KB |
| Parsed markdown | ~50-80 spans/page x ~50 bytes/span (text + layout markers) | ~4 KB |
| Grounded JSON | ~15 fields x (value + bbox[4 floats] + quote + confidence), ~1.6 KB/field | ~25 KB |

### Service-time capacity

| Backend | Service time | In-flight @ 46/s | @ 3x peak (139/s) |
|---|---|---|---|
| Claude API | ~10 s | ~460 | ~1.4K |
| Self-hosted LLM | ~1 s | ~46 | ~140 |
| LayoutLM fast path | ~50-200 ms | ~2-9 | ~7-28 |

Latency determines fleet size directly: a 10x cut in extract time cuts concurrency 10x.

**Storage:** 4M x 100 KB = 400 GB/day PDF -> S3 with lifecycle policy. Job records: partition by time, keep < 48h hot in Postgres; older records move to the warehouse tier.

**GPU sketch @ 1s/doc, batch 8:** ~6 GPUs, 1 node. Sizing sketch, not a procurement figure.

---

## Ingestion & autoscaling

Ingestion instances are stateless and horizontally autoscaled behind a load balancer. Autoscaling ties to request rate, not CPU — ingestion is I/O-bound (accept, dedup, enqueue), not compute-bound.

**Server-count estimate.**
- ~2K req/s assumed sustained capacity per ingestion instance (accept + dedup + enqueue, no parse/extract work on this tier)
- Ceiling case: ~1.16K req/s avg fits within a single instance; 3x peak (~3.5K req/s) requires ~2
- Operating point (4M/day, ~46 req/s avg, ~139 req/s peak): one instance covers both
- Extract capacity is the bottleneck (see Service-time capacity), not ingestion

**Multi-region / multi-AZ.**
- Deployed per-region (see Target topology)
- Region = residency boundary (see Tenancy) + failure-isolation boundary — a regional outage degrades only that region's tenants
- Within a region: instances, Kafka brokers, and Postgres replicas spread across at least 2 AZs
- A single-AZ failure does not stall ingestion or lose acked jobs

---

## Latency budget

P99 target: 15 s, broken into hops:

| Stage | Type | Time | Notes |
|---|---|---|---|
| Ingress -> Kafka | enqueue | < 50 ms | token bucket + dedup (Redis ETag) |
| Kafka -> Parse pod | queue lag | < 100 ms steady | per-tenant partition fairness |
| Parse (PyMuPDF) | compute | ~200-500 ms | CPU-bound, page-parallel |
| Parse -> Extract queue | hop | < 100 ms | independent HPA per stage |
| Extract (LLM) | compute | ~1-10 s | dominant cost; self-hosting reduces this |
| Ground (fuzzy match) | compute | < 50 ms | in-process, no external call |
| Extract -> Chat (optional) | on-demand | n/a | not on the ingest critical path |

**Backpressure (parse -> extract queue).**
- If queue depth x extract service time exceeds ~2x current in-flight capacity for > 30s, scale extract pods before shedding
- A sustained breach past the HPA ceiling returns 429 upstream rather than let the queue grow unbounded
- Parse is cheap and fast; extract is the bottleneck

---

## Partitioning & sharding

**Kafka partition key: `tenant_id`.**
- Preserves per-tenant ordering and fairness — a noisy tenant fills its own partition(s), not others'
- Document-type keys would create hot partitions for common types
- Time-based keys would serialize all tenants during peak windows

**DB shard key: `tenant_id`, explicit lookup table, not consistent hashing.**
- Tenant load is heavily skewed
- Hashing risks co-locating a high-volume tenant with others, creating an unrebalanceable hot shard
- An explicit table lets ops move one tenant to a dedicated shard without rehashing the rest

```
tenant_id=acme-corp     -> shard=7  (dedicated, high-volume)
tenant_id=freelancer-42 -> shard=1  (shared pool)
```

Every production query (job status, results, invoice lookup) is scoped by `tenant_id` — a single-shard lookup, never scatter-gather.

---

## Extraction pipeline: failure, durability, and storage

Extract+ground runs asynchronously after ack; a job must not be lost if the LLM backend is unavailable.

```
Job acked (enqueue < 50ms)
  -> Parse (independent stage; a bad PDF fails parse, not extract)
  -> Extract attempt
       success           -> Ground -> finalize
       transient failure -> retry queue, exponential backoff, <= N attempts
       exhausted retries -> DLQ (dead-letter topic)
                              -> alert (review-rate/lag dashboard)
                              -> admin tool: requeue (see Operability)
```

Retry budget is bounded — unbounded retries against a down backend amplify the outage. DLQ plus alert is the release valve once budget is exhausted.

**Storage semantics.**
- `FieldValue` result written once, on successful ground — `pending` to `complete` in place (update, not append), one row per job
- A retried extraction overwrites the prior attempt; only the successful result is retained
- Historical versions and full document history live in the Warehouse tier, not the hot job store

**Dashboard dependency.** Extract+ground is the enrichment step; dashboard KPIs (needs_review rate, IoU pass rate, cost/doc) are computed from its output. Metrics rollups read post-ground state, not raw ingest counts.

---

## Model serving & adapter scaling

Model strategy (classify -> LoRA per vertical, DocILE cluster seeding, escalation cascade) is covered in [`EXTRACTION.md`](EXTRACTION.md#model-strategy). This section covers the infra cost of that strategy.

- **Adapter footprint:** the shared base model dominates GPU memory; a LoRA adapter is megabytes, not the multi-GB size of a full model copy. N adapters loaded alongside one base model cost close to base-model GPU sizing, not N x base-model sizing.
- **Routing:** the classify step (see [`EXTRACTION.md`](EXTRACTION.md#model-strategy)) resolves a request to a `cluster_id`; the extract pod loads or already holds the matching adapter and serves the request against base model + adapter.
- **Batching:** requests routed to the same adapter batch together for GPU throughput. Requests spanning different adapters either pay an adapter-switch cost or queue separately per adapter.
- **Cold start:** a new vertical or layout cluster with no trained adapter falls back to the Claude escalation path (see [`EXTRACTION.md` escalation](EXTRACTION.md#escalation-cost-control)) until enough confirmed extractions accumulate to train a patch.
- **Capacity math:** the GPU sketch above ([Capacity](#capacity)) sizes the shared base model at the operating point; adapters run at the LoRA fast-path service time (~50-200 ms), not the Claude/self-hosted-LLM service time.

---

## Target topology

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

Parse and extract scale independently (separate HPA).

---

## Metrics rollups (dashboard read path)

Dashboard KPIs (needs_review rate, cost/doc, IoU pass rate, coverage, lag) are computed from pre-aggregated buckets, never from a live scan of raw job records.

- Aggregation runs per-tenant, per-minute/hour/day as jobs complete: extraction count, needs_review count, mean IoU, cost, latency.
- A dashboard query for "last 2 hours" reads 120 minute-bucket rows; a query for "last 12 months" reads 12 month-bucket rows. Never a full table scan.
- **Storage:** Redis/time-series store for hot rollups (24-48h) — low-latency KV fits the small, high-write-rate key space better than relational joins. Older buckets roll into the warehouse tier's SQL-queryable store, which fits ad-hoc analytical queries better.
- **Sharding:** rollup keys are `(tenant_id, granularity, time_bucket)`, sharded by `tenant_id`, matching the DB shard key (see [Partitioning & sharding](#partitioning--sharding)) — a dashboard load for one tenant never crosses shards.
- Backs the "Grounding dashboards" roadmap item in [`PRODUCT.md`](PRODUCT.md#roadmap-product).

---

## Warehouse tier (long-term / audit)

Distinct from the < 48h hot Postgres job store. Serves queries the hot store is not designed for — for example, all invoices a tenant processed in a given quarter.

- **Storage: S3, partitioned by `date` / `tenant_id`, queried via Athena** — chosen over a managed warehouse (Redshift/BigQuery/Snowflake) since the query pattern is low-frequency and already colocated with the existing PDF/result-JSON blobs. Revisit if query frequency or join complexity outgrows partition-pruned Athena scans.
- **Tiered lifecycle:** hot (S3 Standard) to cold (Glacier) past a retention window, matching the PDF storage lifecycle already in place.
- **Batch pre-computation:** monthly/quarterly aggregates (tenant-level volume and accuracy trends) are pre-computed on a batch schedule (Spark or DBT over the partitioned S3 data) rather than computed ad hoc per query.
- **Caching:** known/repeated queries (a tenant's monthly summary) are served from a query-result cache in front of Athena rather than re-scanning partitions on every request.
- **Query routing:** requests scoped to the last 48h read the hot rollup store; anything older routes to the warehouse. The routing rule is time-based and sits in the API layer in front of both stores.
- The S3 partitioning scheme exists from day one, independent of whether the query layer (Athena, caching) is built yet.

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

Region and shard are separate axes and are not conflated: region is a residency boundary, fixed at signup; shard is a load-balancing boundary, assigned via an explicit lookup table (see [Partitioning & sharding](#partitioning--sharding)).

Noisy-neighbor protection layers: edge token bucket, then Kafka partition fairness (`tenant_id` key), then a per-tenant concurrency semaphore.

Demo data: `data/tenants/`. Auth: `X-API-Key` resolves to `request.state.tenant`.

The CDN's value is TLS/DDoS termination, static UI, and cached tenant lookup — not caching `GET /jobs/{id}`, which is per-tenant and mutates frequently.

---

## Operability (failure path)

Alerts fire on review-rate, lag, cost, grounding miss, and DLQ depth, tagged with tenant, job, routing, model, cluster, and blast radius.

**Log volume.**
- Parse and extract pods generate log output at steady state (46/s), on the order of ~1 GB/hr fleet-wide
- Raw logs are not fed to the on-call agent directly
- An hourly checkpoint compresses this into a ~1 MB digest (error counts, anomaly flags)
- The agent reads the digest first; indexed full-text search over raw logs runs only on demand

Failure path: liveness (workers, GPU) -> readiness (S3/PG/LLM) -> smoke test (golden PDF) -> log digest -> allowlisted tools (`requeue`, `force_claude`, `search_sop`, ...) -> SOP DB -> escalation (P1 < 5m ... P4 <= 5d).

An auto-fix reports the steps taken; otherwise the incident routes to a human channel with recommendations attached.

---

## Design traps

| Question | Answer |
|---|---|
| Go for 2.5k goroutines? | Wrong lever — LLM latency and cost dominate; scale with pods and Kafka. Go is optional later, for thin enqueue only. |
| Bboxes in the LLM prompt? | Non-deterministic; breaks audit. Ground from parsed spans instead. |
| F1 only KPI? | No — F1, IoU pass@0.5, coverage, review rate, cost/doc, lag, and DLQ depth together. |
| ADE vs. build? | Compare miss-cost x volume against API spend, on the same DocILE bake-off. |
| Does DAU math justify our scale? | Order-of-magnitude ceiling only — 10M DAU, not 100M. Load is tenant-concentrated, not user-concentrated. DAU math applied directly would mis-shape sharding and fairness design (see [Demand derivation](#demand-derivation)). |
| What if the LLM backend is down mid-extraction? | Bounded retry, then DLQ, then alert — not unbounded retry (amplifies the outage) or silent drop (loses the job). See [Extraction pipeline](#extraction-pipeline-failure-durability-and-storage). |
| How do dashboards stay fast at 4M docs/day? | Pre-computed rollups, sharded by tenant; never a live scan of raw job records. See [Metrics rollups](#metrics-rollups-dashboard-read-path). |
| Why S3+Athena for the warehouse, not Redshift/Snowflake? | Query pattern is low-frequency and partition-scoped; a managed warehouse adds ETL and cost without a matching latency requirement at this stage. See [Warehouse tier](#warehouse-tier-long-term--audit). |
| Why no phase-numbered rollout plan? | [Component choices](#component-choices) states, per component, what changes and why. A separate phase table would re-sequence the same trade-offs without adding information. |
| How does serving cost scale with more industry verticals? | Sub-linearly — new verticals add small LoRA adapters on the shared base model, not new model deployments (see [Model serving & adapter scaling](#model-serving--adapter-scaling)). |

---

## Notes

- "Tenant" = one customer account of the API (a company, or a freelancer), isolated from every other tenant's data. Used instead of "customer" because it specifically means isolation, not just billing.
