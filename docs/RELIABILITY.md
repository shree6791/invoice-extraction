# Reliability

Failure handling, durability, dashboard read path, warehouse, and on-call for the Invoice Extraction product.

Hub: [`SYSTEM.md`](SYSTEM.md). Sizing: [`CAPACITY.md`](CAPACITY.md). Product / extract: [`PRODUCT.md`](PRODUCT.md) · [`EXTRACTION.md`](EXTRACTION.md).

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
- Historical versions and full document history live in the [Warehouse tier](#warehouse-tier-long-term--audit), not the hot job store

**Dashboard dependency.** Extract+ground is the enrichment step; dashboard KPIs (needs_review rate, IoU pass rate, cost/doc) are computed from its output. Metrics rollups read post-ground state, not raw ingest counts.

---

## Metrics rollups (dashboard read path)

Dashboard KPIs (needs_review rate, cost/doc, IoU pass rate, coverage, lag) are computed from pre-aggregated buckets, never from a live scan of raw job records.

- Aggregation runs per-tenant, per-minute/hour/day as jobs complete: extraction count, needs_review count, mean IoU, cost, latency.
- A dashboard query for "last 2 hours" reads 120 minute-bucket rows; a query for "last 12 months" reads 12 month-bucket rows. Never a full table scan.
- **Storage:** Redis/time-series store for hot rollups (24–48h) — low-latency KV fits the small, high-write-rate key space better than relational joins. Older buckets roll into the warehouse tier's SQL-queryable store, which fits ad-hoc analytical queries better.
- **Sharding:** rollup keys are `(tenant_id, granularity, time_bucket)`, sharded by `tenant_id`, matching the DB shard key (see [`CAPACITY.md` partitioning](CAPACITY.md#partitioning--sharding)) — a dashboard load for one tenant never crosses shards.
- Backs the "Grounding dashboards" roadmap item in [`PRODUCT.md`](PRODUCT.md#roadmap-product).

---

## Warehouse tier (long-term / audit)

Distinct from the &lt; 48h hot Postgres job store. Serves queries the hot store is not designed for — for example, all invoices a tenant processed in a given quarter.

- **Storage: S3, partitioned by `date` / `tenant_id`, queried via Athena** — chosen over a managed warehouse (Redshift/BigQuery/Snowflake) since the query pattern is low-frequency and already colocated with the existing PDF/result-JSON blobs. Revisit if query frequency or join complexity outgrows partition-pruned Athena scans.
- **Tiered lifecycle:** hot (S3 Standard) to cold (Glacier) past a retention window, matching the PDF storage lifecycle already in place.
- **Batch pre-computation:** monthly/quarterly aggregates (tenant-level volume and accuracy trends) are pre-computed on a batch schedule (Spark or DBT over the partitioned S3 data) rather than computed ad hoc per query.
- **Caching:** known/repeated queries (a tenant's monthly summary) are served from a query-result cache in front of Athena rather than re-scanning partitions on every request.
- **Query routing:** requests scoped to the last 48h read the hot rollup store; anything older routes to the warehouse. The routing rule is time-based and sits in the API layer in front of both stores.
- The S3 partitioning scheme exists from day one, independent of whether the query layer (Athena, caching) is built yet.

---

## Operability (failure path)

Alerts fire on review-rate, lag, cost, grounding miss, and DLQ depth, tagged with tenant, job, routing, model, cluster, and blast radius.

**Log volume.**
- Parse and extract pods generate log output at steady state (46/s), on the order of ~1 GB/hr fleet-wide
- Raw logs are not fed to the on-call agent directly
- An hourly checkpoint compresses this into a ~1 MB digest (error counts, anomaly flags)
- The agent reads the digest first; indexed full-text search over raw logs runs only on demand

Failure path: liveness (workers, GPU) → readiness (S3/PG/LLM) → smoke test (golden PDF) → log digest → allowlisted tools (`requeue`, `force_claude`, `search_sop`, …) → SOP DB → escalation (P1 &lt; 5m … P4 ≤ 5d).

An auto-fix reports the steps taken; otherwise the incident routes to a human channel with recommendations attached.
