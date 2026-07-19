# Diagrams

Architecture sketches for the Invoice Extraction product (Mermaid). Narrative lives in the linked docs — these are the visual map.

| Diagram | Read with |
|---|---|
| [Product surface](#1-product-surface) | [`PRODUCT.md`](PRODUCT.md) |
| [Extract pipeline (LangGraph)](#2-extract-pipeline-langgraph) | [`EXTRACTION.md`](EXTRACTION.md#pipeline-today) |
| [Phase 0 (now)](#3-phase-0-now) | [`SYSTEM.md`](SYSTEM.md) |
| [Target fleet topology](#4-target-fleet-topology) | [`SYSTEM.md`](SYSTEM.md#target-topology) · [`CAPACITY.md`](CAPACITY.md) |
| [Failure / retry / DLQ](#5-failure--retry--dlq) | [`RELIABILITY.md`](RELIABILITY.md#extraction-pipeline-failure-durability-and-storage) |
| [Tenant shard & fairness](#6-tenant-shard--fairness) | [`CAPACITY.md`](CAPACITY.md#partitioning--sharding) · [`SYSTEM.md`](SYSTEM.md#tenancy) |
| [Hot path vs warehouse](#7-hot-path-vs-warehouse) | [`RELIABILITY.md`](RELIABILITY.md#metrics-rollups-dashboard-read-path) |

---

## 1. Product surface

Parse → Extract → Ground → Chat. Boxes never come from the LLM.

```mermaid
flowchart LR
  PDF[PDF] --> Parse
  Parse -->|spans + markdown| Extract
  Extract -->|schema values| Ground
  Ground -->|page + bbox + quote| Invoice[Grounded invoice JSON]
  Invoice --> Chat
  Ground -->|ambiguous| Review[needs_review]
```

Details: [`PRODUCT.md` surface](PRODUCT.md#surface) · [`EXTRACTION.md` grounding](EXTRACTION.md#grounding).

---

## 2. Extract pipeline (LangGraph)

Today’s graph inside one process. Grounding runs inside each extract path.

```mermaid
flowchart TD
  Start([doc_id / PDF]) --> Resolve[resolve_input]
  Resolve --> Parse[parse · PyMuPDF parallel pages]
  Parse --> Classify{classify_extract}
  Classify -->|hard| Claude[extract_claude]
  Classify -->|easy| Mock[extract_mock_fast]
  Mock -->|needs_review| Claude
  Mock -->|clean| Final[finalize]
  Claude --> Final
  Final --> Out([Invoice + routing / escalated])
```

Escalation & model roadmap: [`EXTRACTION.md`](EXTRACTION.md#escalation-cost-control).

---

## 3. Phase 0 (now)

Contracts only — in-memory queue / cache / jobs, one worker.

```mermaid
flowchart TB
  subgraph Client
    UI[Demo UI / curl]
  end

  subgraph FastAPI["Single FastAPI process"]
    API[Routes · TenantMiddleware]
    Q[InMemoryQueue]
    Store[InMemoryJobStore]
    Cache[InMemoryCache]
    Worker[1 × asyncio.to_thread worker]
    Graph[LangGraph pipeline]
    API --> Q
    API --> Store
    Worker --> Q
    Worker --> Graph
    Worker --> Store
    Worker --> Cache
  end

  UI -->|POST /api/extract sync| Graph
  UI -->|POST /api/jobs| API
  Graph --> PDF[(data/tenants · data/docile)]
```

Swap map: [`SYSTEM.md` component choices](SYSTEM.md#component-choices).

---

## 4. Target fleet topology

Design point (~4M docs/day). Parse and extract scale independently.

```mermaid
flowchart TB
  Edge[CDN / edge · API key · token bucket] -->|429 if over quota| API[Regional API]
  API --> Redis[(Redis ETag dedup)]
  API --> Kafka[(Kafka · key = tenant_id)]
  Kafka --> Parse[Parse pods · CPU · PyMuPDF]
  Parse -->|parse-complete| ExtractQ[Extract queue]
  ExtractQ --> Extract[Extract pods · GPU / vLLM]
  Extract -->|success| Ground[Ground in-process]
  Extract -->|transient fail| Retry[Retry queue]
  Retry --> Extract
  Extract -->|retries exhausted| DLQ[(DLQ)]
  Ground --> PG[(Postgres jobs &lt;48h)]
  Ground --> S3[(S3 PDF + result JSON)]
  Ground --> Rollups[Metrics aggregator]
  Rollups --> Dash[Dashboard read path]
  S3 --> Warehouse[Warehouse · Athena]
  DLQ --> Alert[Alert / requeue tool]
```

Sizing: [`CAPACITY.md`](CAPACITY.md). Durability: [`RELIABILITY.md`](RELIABILITY.md).

---

## 5. Failure / retry / DLQ

No silent drops when the LLM backend is down.

```mermaid
stateDiagram-v2
  [*] --> Acked: enqueue &lt; 50ms
  Acked --> Parsing: parse stage
  Parsing --> Extracting: parse OK
  Parsing --> FailedParse: bad PDF
  Extracting --> Grounded: extract OK
  Extracting --> Retrying: transient error
  Retrying --> Extracting: backoff ≤ N
  Retrying --> DLQ: budget exhausted
  Grounded --> Complete: write result
  DLQ --> Alerting: page on-call
  Alerting --> Extracting: admin requeue
  Complete --> [*]
  FailedParse --> [*]
```

Narrative: [`RELIABILITY.md` pipeline](RELIABILITY.md#extraction-pipeline-failure-durability-and-storage).

---

## 6. Tenant shard & fairness

`tenant_id` is the partition and shard key — noisy neighbors stay in their lane.

```mermaid
flowchart LR
  subgraph Ingress
    T1[tenant A · high volume]
    T2[tenant B · SMB]
    T3[tenant C · SMB]
  end

  subgraph Kafka
    P7[partition / shard 7 · dedicated]
    P1[partition / shard 1 · shared]
  end

  T1 --> P7
  T2 --> P1
  T3 --> P1
  P7 --> W7[workers on shard 7]
  P1 --> W1[workers on shard 1]
```

Lookup table (not consistent hashing): [`CAPACITY.md` partitioning](CAPACITY.md#partitioning--sharding).

---

## 7. Hot path vs warehouse

Dashboards never scan raw job rows. Audit queries use the warehouse tier.

```mermaid
flowchart TB
  Job[Extract + ground complete] --> Hot[(Postgres &lt;48h hot)]
  Job --> S3[(S3 partitioned date / tenant_id)]
  Job --> Rollup[Per-tenant minute/hour/day buckets]
  Rollup --> Redis[(Redis / TS hot rollups 24–48h)]
  Redis --> API[Dashboard API]
  S3 --> Athena[Athena / batch aggregates]
  Athena --> API
  API -->|last 48h| Redis
  API -->|older / audit| Athena
```

Detail: [`RELIABILITY.md` rollups](RELIABILITY.md#metrics-rollups-dashboard-read-path) · [warehouse](RELIABILITY.md#warehouse-tier-long-term--audit).
