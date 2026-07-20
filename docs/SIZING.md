# Sizing

Worker, core, and GPU sizing for Parse, Ingestion, and Extract. Derived from [`CAPACITY.md`](CAPACITY.md#capacity) demand and service-time figures. Sketches pending load test, not procurement figures.

Hub: [`SYSTEM.md`](SYSTEM.md). Fleet: [`CAPACITY.md`](CAPACITY.md) · [`RELIABILITY.md`](RELIABILITY.md). Product / extract: [`PRODUCT.md`](PRODUCT.md) · [`EXTRACTION.md`](EXTRACTION.md).

---

## Conversion rules

Concurrency (Little's Law: `concurrency = arrival_rate × service_time`) is demand. Converting demand into a resource count depends on the bound type.

| Bound type | In-flight behavior | Conversion | Stage |
|---|---|---|---|
| I/O-bound | Waiting on network/disk | workers ≫ cores | Ingestion |
| CPU-bound | Computing for full duration | workers ≈ cores (1:1) | Parse |
| GPU-batched | Batched forward pass | GPUs = concurrency ÷ batch size | Extract |

---

## Parse (CPU-bound)

Parse service time is assumed at 0.3 s/doc — the midpoint of the 200–500 ms range from [`CAPACITY.md`'s latency budget](CAPACITY.md#latency-budget) — with one core occupied per document for that duration.

| Load | Concurrency | Cores (+30% buffer) |
|---|---|---|
| Avg (46 req/s) | 46 × 0.3 ≈ 14 | **~18** |
| 3× peak (139 req/s) | 139 × 0.3 ≈ 42 | **~55** |

On 8-core pods, that's 2–3 pods at the average load and about 7 at 3× peak.

**Unverified:** whether a single document's page-level parallelism (the PyMuPDF ThreadPool) consumes more than one core internally. If it does, cores should scale by that factor.

---

## Ingestion (I/O-bound)

This tier only accepts, dedups, and enqueues — no parse or extract work runs here.

| Resource | Value |
|---|---|
| Cores/instance | 2–4 |
| Concurrent connections/instance | low thousands (async event loop; memory/FD-bound, not CPU-bound) |
| Instances at operating point (46–139 req/s) | 1 |

Ceiling derivation: [`CAPACITY.md` server-count estimate](CAPACITY.md#ingestion--autoscaling).

---

## Extract (GPU-batched)

Self-hosted extract service time is assumed at 1 s/doc (see [`CAPACITY.md` service-time capacity](CAPACITY.md#service-time-capacity)).

| Load | Concurrency |
|---|---|
| Avg (46 req/s) | 46 |
| 3× peak (139 req/s) | 139 |

### Batch size derivation

GPU count depends on batch size, which in turn depends on how much GPU memory is left over once model weights and overhead are subtracted:

```
usable_memory = GPU_memory − model_weights − overhead
max_batch = usable_memory / memory_per_request
```

**Model weights (fp16):**

| Model | Weights |
|---|---|
| 7B | ~14 GB |
| 13B | ~26 GB |
| 70B | ~140 GB (exceeds one 80GB GPU — needs tensor parallelism) |

**Memory per request (KV cache), Llama-2-7B-class (32 layers, 32 KV heads, head_dim 128, fp16):**

```
memory/token = 2 × 32 × 32 × 128 × 2 bytes ≈ 0.5 MB
```

| Sequence length | Memory/request |
|---|---|
| 2,000 tokens | ~1 GB |
| 4,000 tokens | ~2 GB |
| 8,000 tokens | ~4 GB |

Sequence length reference: [`CAPACITY.md` per-event size](CAPACITY.md#per-event-size) — ~4 KB parsed markdown/doc, ~1,000 tokens/page by English-text heuristic → ~2,000–3,000 tokens for a 2–3 page invoice. Not yet measured against real tokenizer output.

**7B model, 80GB GPU:**

```
usable_memory = 80 − 14 − 6 (overhead) ≈ 60 GB
```

| Memory/request | Batch size |
|---|---|
| 2 GB | ~30 |
| 1 GB | ~60 |
| 0.5 GB | ~120 |

### GPU count by batch size

| Batch size | Avg (46 req/s) | 3× peak (139 req/s) |
|---|---|---|
| 8 (placeholder, likely conservative) | ~6 | ~17 |
| 30 (7B model, 80GB, ~2GB/req) | ~2 | ~5 |

Batch size is the single largest lever on GPU fleet size in this calculation.

**Not accounted for:** continuous batching / paged attention (vLLM) typically raises effective batch size above this flat estimate; actual GPU (A100 vs H100 vs L4), actual model, actual tokenized invoice length.

**Resolution path:** run the target model on the target GPU under vLLM, ramp concurrent requests until memory or p99 latency breaks, read off the batch ceiling. Same for Parse's per-doc core assumption and Ingestion's per-instance throughput assumption.

---

## Adapter serving

No separate sizing math — adapters run at the LayoutLM fast-path service time already covered above, not a GPU-batched service time of their own. Full explanation: [`CAPACITY.md` model serving](CAPACITY.md#model-serving--adapter-scaling).