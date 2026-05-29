"""Collector: drain worker result bundles from the queue into the host's dataset.

Runs on the host (next to Redis). It pops each gzip-compressed bundle a worker pushed,
decodes it, and writes the per-image files (record, CBOM, raw tool outputs, log, and
deduplicated crypto blobs). It exits when the task queue, the processing list, and the
result list are all empty.
"""

from __future__ import annotations

import logging

from .config import Settings, settings as default_settings
from .queue import TaskQueue
from .storage import write_bundle
from .transport import decode_bundle

log = logging.getLogger("cryptocensus.collector")


def collect(output_dir: str, s: Settings | None = None, max_results: int | None = None) -> int:
    s = s or default_settings
    queue = TaskQueue(s)
    written = 0
    while True:
        payload = queue.pop_result(block_s=2)
        if payload is None:
            stats = queue.stats()
            if stats["pending"] == 0 and stats["processing"] == 0 and stats["results_pending"] == 0:
                break
            continue
        try:
            record, builtin_cbom, raw = decode_bundle(payload)
        except Exception:
            log.exception("failed to decode a result bundle; skipping")
            continue
        write_bundle(output_dir, record, builtin_cbom, raw, save_raw=s.save_raw)
        written += 1
        log.info("collected %s (%d)", record.get("reference"), written)
        if max_results and written >= max_results:
            break
    return written
