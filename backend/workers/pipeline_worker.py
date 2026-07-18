"""Background worker — drains InMemoryQueue, runs pipeline in a thread.

asyncio.to_thread() offloads the blocking run_pipeline call so the event loop
stays responsive. In production this becomes a separate process / K8s pod
consuming from Kafka — the interface stays identical.
"""

from __future__ import annotations

import asyncio
import logging

from backend.infra.cache import InMemoryCache
from backend.infra.jobs import InMemoryJobStore
from backend.infra.queue import InMemoryQueue
from backend.services.pipeline import run_pipeline

log = logging.getLogger(__name__)


async def worker_loop(
    queue: InMemoryQueue,
    job_store: InMemoryJobStore,
    cache: InMemoryCache,
) -> None:
    """Runs forever — pull job → process → store result + cache."""
    log.info("Pipeline worker started")
    while True:
        job = await queue.dequeue()
        job_id = job["job_id"]
        doc_id = job["doc_id"]
        model = job.get("model")

        job_store.update(job_id, status="running", started_at=_now())
        log.info("Job %s started (doc_id=%s)", job_id, doc_id)

        try:
            # run_pipeline is fully blocking (PyMuPDF + sync Anthropic SDK).
            # asyncio.to_thread() runs it in a thread-pool thread so the
            # event loop stays free for health checks, status polls, etc.
            result = await asyncio.to_thread(
                run_pipeline, doc_id, for_eval=False, model=model
            )
            api_dict = result.to_api_dict()

            # Store in cache so identical PDFs skip extraction next time.
            cache.set(job["cache_key"], api_dict)

            job_store.update(
                job_id,
                status="done",
                finished_at=_now(),
                result=api_dict,
            )
            log.info("Job %s done", job_id)

        except Exception as exc:  # noqa: BLE001
            log.exception("Job %s failed: %s", job_id, exc)
            job_store.update(
                job_id,
                status="failed",
                finished_at=_now(),
                error=str(exc),
            )

        finally:
            queue.task_done()


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
