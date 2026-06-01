"""Redis-backed reliable, multi-machine task queue and result channel.

The host runs one Redis instance. Workers on any number of machines claim image
references with an atomic BLMOVE from the pending list to a shared processing list (so
a crashed worker's task is recoverable with `requeue_stale`, not lost), and push their
finished result bundles back onto a result list. The host's collector drains that
result list to disk. The only shared service the fleet needs is this Redis; workers are
otherwise stateless and keep nothing locally.
"""

from __future__ import annotations

from typing import Iterable

import redis

from .config import Settings


class TaskQueue:
    def __init__(self, settings: Settings):
        self._s = settings
        self._r = redis.from_url(settings.redis_url, decode_responses=True)

    def ping(self) -> bool:
        return bool(self._r.ping())

    # --- tasks -------------------------------------------------------------
    def enqueue(self, references: Iterable[str], skip_done: bool = True) -> int:
        """Enqueue references, de-duplicated within the batch and (by default) against
        the done set, so re-seeding after a partial or interrupted run is idempotent
        and never piles duplicate work onto the queue."""
        refs = list(dict.fromkeys(r for r in references if r))
        if not refs:
            return 0
        if skip_done:
            pipe = self._r.pipeline()
            for ref in refs:
                pipe.sismember(self._s.done_set, ref)
            already = pipe.execute()
            refs = [ref for ref, done in zip(refs, already) if not done]
            if not refs:
                return 0
        return int(self._r.lpush(self._s.task_queue, *refs))

    def claim(self) -> str | None:
        return self._r.blmove(
            self._s.task_queue, self._s.processing_queue, self._s.claim_block_s, "RIGHT", "LEFT"
        )

    def ack(self, reference: str) -> None:
        pipe = self._r.pipeline()
        pipe.lrem(self._s.processing_queue, 1, reference)
        pipe.sadd(self._s.done_set, reference)
        pipe.execute()

    def requeue_stale(self) -> int:
        moved = 0
        while self._r.lmove(self._s.processing_queue, self._s.task_queue, "RIGHT", "LEFT"):
            moved += 1
        return moved

    def requeue(self, reference: str) -> None:
        """Return one in-flight reference to the pending queue (transient failure): it is
        neither acked nor marked done, so a later attempt or another worker retries it,
        instead of recording a false-negative result."""
        pipe = self._r.pipeline()
        pipe.lrem(self._s.processing_queue, 1, reference)
        pipe.lpush(self._s.task_queue, reference)
        pipe.execute()

    def transient_retry(self, reference: str) -> int:
        """Increment and return how many times this reference has hit a transient error,
        so the worker can stop requeuing after a bounded number of attempts."""
        return int(self._r.hincrby(self._s.retry_hash, reference, 1))

    # --- pull mutex (one download at a time per host) ----------------------
    def acquire_pull_lock(self, token: str) -> bool:
        """Try to take the host-scoped pull lock. The TTL releases it automatically if
        the holder dies, so a crashed worker never deadlocks its peers."""
        return bool(self._r.set(self._s.pull_mutex_key, token, nx=True, ex=self._s.pull_mutex_ttl_s))

    def release_pull_lock(self, token: str) -> None:
        """Release the lock only if we still hold it (compare token), so we never free a
        lock that the TTL already handed to another worker."""
        script = ("if redis.call('get', KEYS[1]) == ARGV[1] then "
                  "return redis.call('del', KEYS[1]) else return 0 end")
        try:
            self._r.eval(script, 1, self._s.pull_mutex_key, token)
        except Exception:
            pass

    # --- results -----------------------------------------------------------
    def push_result(self, payload: str) -> None:
        """`payload` is a base64(gzip(json)) bundle produced by the worker."""
        self._r.lpush(self._s.result_queue, payload)

    def pop_result(self, block_s: int = 2) -> str | None:
        item = self._r.brpop(self._s.result_queue, timeout=block_s)
        return item[1] if item else None

    def results_pending(self) -> int:
        return int(self._r.llen(self._s.result_queue))

    # --- introspection -----------------------------------------------------
    def stats(self) -> dict[str, int]:
        return {
            "pending": int(self._r.llen(self._s.task_queue)),
            "processing": int(self._r.llen(self._s.processing_queue)),
            "results_pending": self.results_pending(),
            "done": int(self._r.scard(self._s.done_set)),
        }
