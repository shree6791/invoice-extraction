"""Async job endpoints — POST /api/jobs, GET /api/jobs/{job_id}

Demonstrates the async-queue + dedup pattern:
  POST /api/jobs  → hash PDF → cache hit? return immediately
                             → cache miss? enqueue, return job_id
  GET  /api/jobs/{id} → poll job status (queued | running | done | failed)
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request

from backend.dataset.loader import pdf_path as docile_pdf_path
from backend.schemas.extract import ExtractRequest

router = APIRouter(tags=["jobs"])


def _infra(request: Request):
    """Pull shared infra singletons from app state."""
    return (
        request.app.state.job_queue,
        request.app.state.job_store,
        request.app.state.cache,
    )


@router.post("/api/jobs", status_code=202)
async def enqueue_job(req: ExtractRequest, request: Request):
    """Submit an extraction job.

    Returns immediately with a job_id. If the same PDF was already extracted
    (cache hit) returns status='done' with the result inline — no LLM call.
    """
    queue, job_store, cache = _infra(request)

    # Resolve PDF path so we can hash the actual bytes.
    try:
        pdf = docile_pdf_path(req.doc_id)
        if not pdf.exists():
            raise FileNotFoundError(f"PDF not found: {pdf}")
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e

    # --- SHA-256 dedup (mock Redis) ---
    # read_bytes() + sha256 are blocking I/O — offload to thread pool so the
    # event loop stays free. At scale: hash from S3 ETag, never read bytes here.
    cache_key = await asyncio.to_thread(cache.pdf_key, str(pdf))
    cached = cache.get(cache_key)
    if cached is not None:
        return {
            "job_id": cache_key[:8],  # stable short id for cached results
            "status": "done",
            "cache_hit": True,
            "result": cached,
        }

    # --- Enqueue (mock Kafka) ---
    job_id = job_store.create(req.doc_id, str(pdf), cache_key)
    await queue.enqueue(
        {"job_id": job_id, "doc_id": req.doc_id, "cache_key": cache_key, "model": req.model}
    )

    return {
        "job_id": job_id,
        "status": "queued",
        "cache_hit": False,
        "queue_depth": queue.qsize(),
    }


@router.get("/api/jobs/{job_id}")
def get_job(job_id: str, request: Request):
    """Poll job status.

    Status transitions: queued → running → done | failed
    Poll until status is 'done' or 'failed', then read 'result' or 'error'.
    """
    _, job_store, _ = _infra(request)
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(404, f"Job {job_id!r} not found")

    # Drop internal fields from response.
    return {
        "job_id": job["job_id"],
        "doc_id": job["doc_id"],
        "status": job["status"],
        "queued_at": job["queued_at"],
        "started_at": job["started_at"],
        "finished_at": job["finished_at"],
        "result": job["result"] if job["status"] == "done" else None,
        "error": job["error"] if job["status"] == "failed" else None,
    }


@router.get("/api/jobs")
def list_jobs(request: Request):
    """Job counts by status — quick health snapshot."""
    _, job_store, cache = _infra(request)
    return {
        "counts": job_store.count(),
        "cache_size": cache.size(),
    }
