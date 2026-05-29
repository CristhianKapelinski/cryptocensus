"""Collector: drain results from Redis into a local dataset directory.

Running on the coordinator machine, the collector pops each worker result and writes
two artifacts per image: the structured record (``records/<ref>.json``) and the
CycloneDX 1.7 CBOM (``cbom/<ref>.cbom.json``). This is the only component that needs
a local filesystem; workers themselves are stateless.
"""

from __future__ import annotations

import json
import logging
import os
import re

from .config import Settings, settings as default_settings
from .queue import TaskQueue

log = logging.getLogger("cryptocensus.collector")


def _safe_name(reference: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", reference)


def collect(dataset_dir: str, s: Settings | None = None, max_results: int | None = None) -> int:
    s = s or default_settings
    queue = TaskQueue(s)
    records_dir = os.path.join(dataset_dir, "records")
    cbom_dir = os.path.join(dataset_dir, "cbom")
    os.makedirs(records_dir, exist_ok=True)
    os.makedirs(cbom_dir, exist_ok=True)

    written = 0
    while True:
        result = queue.pop_result(block_s=2)
        if result is None:
            stats = queue.stats()
            if stats["pending"] == 0 and stats["processing"] == 0 and stats["results_buffered"] == 0:
                break
            continue
        name = _safe_name(result["reference"])
        cbom = result.pop("cbom", None)
        with open(os.path.join(records_dir, f"{name}.json"), "w") as handle:
            json.dump(result, handle, indent=2)
        if cbom is not None:
            with open(os.path.join(cbom_dir, f"{name}.cbom.json"), "w") as handle:
                json.dump(cbom, handle, indent=2)
        written += 1
        log.info("collected %s (%d)", result["reference"], written)
        if max_results and written >= max_results:
            break
    return written
