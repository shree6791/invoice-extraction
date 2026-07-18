"""Run extraction eval against DocILE ground truth.

Doc source: data/tenants/ — all 5 companies, 5 docs each (25 total).
Each tenant folder contains the PDF + annotation JSON side-by-side,
making the eval set self-contained and aligned with the multi-tenant demo.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from backend.settings.config import MODEL_EVAL, OUTPUTS_DIR, ROOT
from backend.dataset.ground_truth import (
    gt_header_fields,
    gt_header_gold_boxes,
    gt_line_items,
    gt_line_items_gold,
)
from backend.dataset.loader import load_annotation, load_doc_meta
from backend.services.pipeline import run_pipeline
from eval.failures import classify_doc_failure, summarize_buckets
from eval.metrics import EvalAccumulator

TENANTS_DIR = ROOT / "data" / "tenants"


def _tenant_doc_ids() -> list[tuple[str, str]]:
    """Return [(doc_id, company_slug), ...] from all tenant manifests."""
    pairs: list[tuple[str, str]] = []
    for folder in sorted(TENANTS_DIR.iterdir()):
        manifest = folder / "manifest.json"
        if folder.is_dir() and manifest.exists():
            data = json.loads(manifest.read_text())
            slug = data["slug"]
            for doc_id in data.get("doc_ids", []):
                pairs.append((doc_id, slug))
    return pairs


def run_eval(
    *,
    limit: int | None = None,
    model: str | None = None,
    out: Path | None = None,
    verbose: bool = True,
) -> dict[str, Any]:
    out   = out   or OUTPUTS_DIR / "eval_report.json"
    model = model or MODEL_EVAL

    doc_pairs = _tenant_doc_ids()
    if limit:
        doc_pairs = doc_pairs[:limit]

    acc = EvalAccumulator()
    latencies: list[float] = []
    costs: list[float] = []
    per_doc: list[dict[str, Any]] = []

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    t_all = time.perf_counter()

    for i, (doc_id, company) in enumerate(doc_pairs, 1):
        if verbose:
            print(f"[{i}/{len(doc_pairs)}] {company}/{doc_id} ...", flush=True)
        try:
            result = run_pipeline(doc_id, for_eval=True, model=model)
            ann = load_annotation(doc_id)
            meta_obj = load_doc_meta(doc_id)
            meta = {
                "page_count": meta_obj.page_count if meta_obj else 1,
                "cluster_id": meta_obj.cluster_id if meta_obj else -1,
                "company": company,
            }
            doc_res = acc.update(
                doc_id,
                result.invoice,
                gt_header_fields(ann),
                gt_line_items(ann),
                meta=meta,
                gold_header_boxes=gt_header_gold_boxes(ann),
                gold_items_rich=gt_line_items_gold(ann),
            )
            sources = [p.source for p in result.parsed.pages]
            bucket = classify_doc_failure(doc_res, sources)
            doc_res["failure_bucket"] = bucket
            doc_res["company"] = company
            doc_res["routing"] = result.extraction.routing
            doc_res["escalated"] = result.extraction.escalated
            doc_res["latency_s"] = result.extraction.latency_s
            doc_res["cost_usd"]  = result.extraction.cost_usd
            latencies.append(result.extraction.latency_s)
            costs.append(result.extraction.cost_usd)
            per_doc.append(doc_res)
            if verbose:
                print(
                    f"  ok routing={result.extraction.routing} "
                    f"latency={result.extraction.latency_s:.2f}s "
                    f"cost=${result.extraction.cost_usd:.4f} bucket={bucket}",
                    flush=True,
                )
        except Exception as e:
            if verbose:
                print(f"  ERROR: {e}", flush=True)
            per_doc.append(
                {
                    "doc_id": doc_id,
                    "company": company,
                    "error": str(e),
                    "failure_bucket": "pipeline_error",
                    "header_misses": [],
                    "hallucination_fields": [],
                    "n_pred_rows": 0,
                    "n_gold_rows": 0,
                    "n_matched_rows": 0,
                    "meta": {},
                }
            )

    summary = acc.summary()
    buckets = summarize_buckets(per_doc)

    # Escalation stats — how often did the fast model handle it vs. Claude?
    routing_counts: dict[str, int] = {}
    for d in per_doc:
        r = d.get("routing", "unknown")
        routing_counts[r] = routing_counts.get(r, 0) + 1

    report: dict[str, Any] = {
        "doc_source": "data/tenants/ (5 companies × 5 docs)",
        "model": model,
        "n_docs": len(doc_pairs),
        "wall_time_s": round(time.perf_counter() - t_all, 2),
        "latency": {
            "mean_s":  round(sum(latencies) / len(latencies), 3) if latencies else None,
            "p50_s":   round(sorted(latencies)[len(latencies) // 2], 3) if latencies else None,
            "total_s": round(sum(latencies), 2),
        },
        "cost": {
            "total_usd": round(sum(costs), 4),
            "mean_usd":  round(sum(costs) / len(costs), 5) if costs else None,
        },
        "escalation": routing_counts,
        "metrics": summary,
        "failure_buckets": buckets,
        "per_doc": per_doc,
        "notes": {
            "protocol": "Value-centric P/R/F1 + bbox IoU grounding metrics. "
                        "F1 is not DocILE official word-overlap AP. "
                        "IoU uses normalized 0–1 boxes; pass_at_0.5 is the primary "
                        "grounding KPI (not raw mean IoU alone).",
            "escalation": "routing=mock-fast means self-hosted model handled it (no LLM cost). "
                          "routing=mock-fast→claude means escalated. "
                          "routing=claude-direct means multi-page/complex doc.",
        },
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")
    return report


def print_report_summary(report: dict[str, Any], out: Path) -> None:
    summary = report["metrics"]
    buckets = report["failure_buckets"]

    print("\n=== Escalation routing ===")
    for route, count in report.get("escalation", {}).items():
        print(f"  {route}: {count}")

    print("\n=== Header per-field F1 ===")
    for f, st in summary["header_per_field"].items():
        print(f"  {f:12s}  P={st['precision']:.3f} R={st['recall']:.3f} F1={st['f1']:.3f}")
    print(f"  {'MICRO':12s}  F1={summary['header_micro_f1']:.3f}")

    print("\n=== Line-item per-column F1 ===")
    for f, st in summary["line_item_per_column"].items():
        print(f"  {f:12s}  P={st['precision']:.3f} R={st['recall']:.3f} F1={st['f1']:.3f}")
    print(f"  row detection recall={summary['row_detection_recall']:.3f}")
    print(f"  line micro F1={summary['line_item_micro_f1']:.3f}")

    print("\n=== Failure buckets (% of failures) ===")
    for k, v in buckets.get("pct_of_failures", {}).items():
        print(f"  {k}: {v}% ({buckets['counts'][k]})")

    g = summary.get("grounding") or {}
    print("\n=== Grounding / bbox IoU ===")
    print(f"  pred value coverage (has bbox)={g.get('pred_value_coverage')}")
    print(
        f"  value-correct+gold-box={g.get('n_value_correct_with_gold_box')}  "
        f"grounded={g.get('n_grounded')}  ungrounded={g.get('n_ungrounded_despite_correct_value')}"
    )
    print(f"  mean_iou={g.get('mean_iou')}  pass@0.5={g.get('pass_at_0.5')}  pass@0.7={g.get('pass_at_0.7')}")
    print(f"\nWrote {out}")
