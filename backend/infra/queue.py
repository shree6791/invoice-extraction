"""Async job queue — in-memory mock of Kafka.

Swap InMemoryQueue for a KafkaQueue (confluent-kafka or aiokafka) when ready.
Limitation: jobs are lost on process restart; single-process only.
"""

from __future__ import annotations

import asyncio


class InMemoryQueue:
    """asyncio.Queue stand-in for Kafka topic.

    Production swap:
        class KafkaQueue:
            async def enqueue(self, job: dict) -> None:
                await self._producer.send(TOPIC, value=job)
            async def dequeue(self) -> dict:
                msg = await self._consumer.__anext__()
                return msg.value
    """

    def __init__(self) -> None:
        self._q: asyncio.Queue[dict] = asyncio.Queue()

    async def enqueue(self, job: dict) -> None:
        await self._q.put(job)

    async def dequeue(self) -> dict:
        return await self._q.get()

    def task_done(self) -> None:
        self._q.task_done()

    def qsize(self) -> int:
        return self._q.qsize()
