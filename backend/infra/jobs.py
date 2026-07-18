"""Job state store — in-memory mock of PostgreSQL.

Tracks: queued → running → done | failed
Swap InMemoryJobStore for a PostgresJobStore (asyncpg / SQLAlchemy) when ready.
Limitation: state lost on restart; no pagination; no persistence.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from threading import Lock
from typing import Literal

JobStatus = Literal["queued", "running", "done", "failed"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class InMemoryJobStore:
    """Thread-safe dict stand-in for a jobs table in PostgreSQL.

    Production swap:
        class PostgresJobStore:
            async def create(...): await conn.execute(INSERT ...)
            async def update(...): await conn.execute(UPDATE ...)
            async def get(...): return await conn.fetchrow(SELECT ...)
    """

    def __init__(self) -> None:
        self._jobs: dict[str, dict] = {}
        self._lock = Lock()

    # ------------------------------------------------------------------
    def create(self, doc_id: str, pdf_path: str, cache_key: str) -> str:
        job_id = str(uuid.uuid4())
        with self._lock:
            self._jobs[job_id] = {
                "job_id": job_id,
                "doc_id": doc_id,
                "pdf_path": pdf_path,
                "cache_key": cache_key,
                "status": "queued",
                "queued_at": _now(),
                "started_at": None,
                "finished_at": None,
                "result": None,
                "error": None,
            }
        return job_id

    def update(self, job_id: str, **fields) -> None:
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id].update(fields)

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def count(self) -> dict[str, int]:
        with self._lock:
            counts: dict[str, int] = {"queued": 0, "running": 0, "done": 0, "failed": 0}
            for j in self._jobs.values():
                counts[j["status"]] = counts.get(j["status"], 0) + 1
            return counts
