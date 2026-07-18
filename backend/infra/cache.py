"""SHA-256 dedup cache — in-memory mock of Redis.

Key = SHA-256 of raw PDF bytes → prevents re-extracting identical documents.
Swap InMemoryCache for a RedisCache (redis-py / aioredis) when ready.
Limitation: cache evicted on restart; no TTL; unbounded memory growth.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from threading import Lock


class InMemoryCache:
    """Dict-backed content cache stand-in for Redis.

    Production swap:
        class RedisCache:
            def pdf_key(self, pdf_path: str) -> str: ...
            def get(self, key: str) -> dict | None:
                raw = self._r.get(key)
                return json.loads(raw) if raw else None
            def set(self, key: str, value: dict, ttl_s: int = 3600) -> None:
                self._r.setex(key, ttl_s, json.dumps(value))
    """

    def __init__(self) -> None:
        self._store: dict[str, dict] = {}
        self._lock = Lock()

    # ------------------------------------------------------------------
    def pdf_key(self, pdf_path: str) -> str:
        """SHA-256 of PDF bytes — same file always maps to same key."""
        data = Path(pdf_path).read_bytes()
        return hashlib.sha256(data).hexdigest()

    def get(self, key: str) -> dict | None:
        with self._lock:
            return self._store.get(key)

    def set(self, key: str, value: dict) -> None:
        with self._lock:
            self._store[key] = value

    def size(self) -> int:
        return len(self._store)
