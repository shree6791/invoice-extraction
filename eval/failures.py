"""Bucket extraction errors by likely cause for interview narrative."""

from __future__ import annotations

from collections import Counter
from typing import Any


def classify_doc_failure(doc_result: dict[str, Any], parsed_sources: list[str]) -> str | None:
    """Return a failure bucket or None if doc looks mostly ok."""
    misses = doc_result.get("header_misses") or []
    halluc = doc_result.get("hallucination_fields") or []
    meta = doc_result.get("meta") or {}
    n_gold = doc_result.get("n_gold_rows", 0)
    n_matched = doc_result.get("n_matched_rows", 0)

    ok_headers = not misses and not halluc
    ok_rows = n_gold == 0 or (n_matched / max(n_gold, 1) >= 0.7)
    if ok_headers and ok_rows:
        return None

    page_count = int(meta.get("page_count", 1))
    if page_count > 1 and (n_matched < n_gold * 0.7):
        return "multi_page_table"

    if "ocr" in parsed_sources:
        return "low_quality_scan"

    if halluc and not misses:
        return "hallucination"

    # Unusual template: many header misses
    if len(misses) >= 3:
        return "unusual_template"

    if any(m.startswith("line_item") for m in misses) and len(misses) <= 2:
        return "layout_miss"

    if misses:
        return "ambiguous_field"

    return "layout_miss"


def summarize_buckets(doc_results: list[dict[str, Any]]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    labeled = 0
    for d in doc_results:
        bucket = d.get("failure_bucket")
        if bucket:
            counts[bucket] += 1
            labeled += 1
    total = len(doc_results) or 1
    failed = labeled or 1
    pct = {k: round(100.0 * v / failed, 1) for k, v in counts.items()}
    return {
        "n_docs": len(doc_results),
        "n_failed": labeled,
        "n_ok": len(doc_results) - labeled,
        "counts": dict(counts),
        "pct_of_failures": pct,
        "pct_of_docs": {k: round(100.0 * v / total, 1) for k, v in counts.items()},
    }
