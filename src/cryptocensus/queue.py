"""Redis-backed reliable, multi-machine task queue.

Workers on any number of machines connect to a single Redis instance. A task (an
image reference) is claimed with an atomic BLMOVE from the pending list to a
per-fleet processing list, so a crashed worker's task can be recovered with
`requeue_stale` rather than lost. Results are pushed onto a separate list and drained
by the collector, which means the only cross-machine dependency is reachable Redis.
"""

from __future__ import annotations

import json
from typing import Iterable

import redis

from .config import Settings


class TaskQueue:
    def __init__(self, settings: Settings):
        self._s = settings
        self._r = redis.from_url(settings.redis_url, decode_responses=True)

    def ping(self) -> bool:
        return bool(self._r.ping())

    # --- producing ---------------------------------------------------------
    def enqueue(self, references: Iterable[str]) -> int:
        refs = [r for r in references if r]
        if not refs:
            return 0
        return int(self._r.lpush(self._s.task_queue, *refs))

    # --- consuming ---------------------------------------------------------
    def claim(self) -> str | None:
        """Atomically move one task from pending to processing and return it, or None
        if nothing arrived within the configured block window."""
        return self._r.blmove(
            self._s.task_queue, self._s.processing_queue, self._s.claim_block_s, "RIGHT", "LEFT"
        )

    def ack(self, reference: str) -> None:
        pipe = self._r.pipeline()
        pipe.lrem(self._s.processing_queue, 1, reference)
        pipe.sadd(self._s.done_set, reference)
        pipe.execute()

    def requeue_stale(self) -> int:
        """Move everything still in the processing list back to pending (run after a
        worker crash). Returns the number of tasks recovered."""
        moved = 0
        while self._r.lmove(self._s.processing_queue, self._s.task_queue, "RIGHT", "LEFT"):
            moved += 1
        return moved

    # --- results -----------------------------------------------------------
    def push_result(self, result: dict) -> None:
        self._r.lpush(self._s.result_queue, json.dumps(result))

    def pop_result(self, block_s: int = 1) -> dict | None:
        item = self._r.brpop(self._s.result_queue, timeout=block_s)
        if item is None:
            return None
        return json.loads(item[1])

    # --- introspection -----------------------------------------------------
    def stats(self) -> dict[str, int]:
        return {
            "pending": int(self._r.llen(self._s.task_queue)),
            "processing": int(self._r.llen(self._s.processing_queue)),
            "done": int(self._r.scard(self._s.done_set)),
            "results_buffered": int(self._r.llen(self._s.result_queue)),
        }
