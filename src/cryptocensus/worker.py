"""Worker: claim an image reference, pull and flatten it, run every enabled
extractor, and emit a result. Stateless and idempotent — any number of workers on
any number of machines can run concurrently against the same queue.
"""

from __future__ import annotations

import logging
import os
import re
import shutil

from .cbom import build_cbom
from .config import Settings, settings as default_settings
from .extractors import cbom_lens, certs_keys, libraries, sbom, secrets
from .image import ImagePullError, export_rootfs
from .queue import TaskQueue
from .schema import ImageResult, ToolObservation

log = logging.getLogger("cryptocensus.worker")


def _safe_name(reference: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", reference)


def process_image(reference: str, s: Settings) -> ImageResult:
    """Pull, flatten, and analyze a single image. Never raises for expected
    failures (pull/parse); those are returned as a non-ok ImageResult."""
    work = os.path.join(s.work_dir, _safe_name(reference))
    shutil.rmtree(work, ignore_errors=True)
    try:
        digest = export_rootfs(reference, work, s.crane_bin, s.pull_timeout_s)
    except ImagePullError as exc:
        return ImageResult(reference=reference, digest=None, ok=False, error=f"pull: {exc}")

    try:
        result = ImageResult(reference=reference, digest=digest, ok=True)
        if s.enable_certs_keys:
            certs, keys, weak_configs, files_scanned = certs_keys.extract(work, s.max_file_bytes)
            result.certs = certs
            result.keys = keys
            result.weak_configs = weak_configs
            result.files_scanned = files_scanned
            result.tool_observations.append(
                ToolObservation("builtin", len(certs), len(keys), 0)
            )
        if s.enable_libraries:
            result.libraries.extend(libraries.extract(work))
        if s.enable_syft:
            syft_records, err = sbom.extract(work, s.syft_bin, s.tool_timeout_s)
            result.libraries.extend(syft_records)
            if err:
                log.warning("syft on %s: %s", reference, err)
        if s.enable_secrets:
            findings, err = secrets.extract(work, s.gitleaks_bin, s.tool_timeout_s)
            result.tool_observations.append(ToolObservation("gitleaks", 0, len(findings), 0, error=err))
        if s.enable_cbom_lens:
            result.tool_observations.append(
                cbom_lens.observe(work, s.cbom_lens_bin, s.tool_timeout_s)
            )
        return result
    finally:
        shutil.rmtree(work, ignore_errors=True)


def run_worker(s: Settings | None = None, idle_exit: int = 0) -> None:
    """Main loop. `idle_exit` > 0 makes the worker exit after that many consecutive
    empty claims (used by the minimal test and batch jobs); 0 means run forever."""
    s = s or default_settings
    queue = TaskQueue(s)
    idle = 0
    log.info("worker started; redis=%s", s.redis_url)
    while True:
        reference = queue.claim()
        if reference is None:
            idle += 1
            if idle_exit and idle >= idle_exit and queue.stats()["processing"] == 0:
                log.info("worker idle; exiting")
                return
            continue
        idle = 0
        log.info("processing %s", reference)
        try:
            result = process_image(reference, s)
        except Exception as exc:  # defensive: a worker must never die on one image
            log.exception("unexpected error on %s", reference)
            result = ImageResult(reference=reference, digest=None, ok=False, error=f"unexpected: {exc}")
        payload = result.to_json()
        payload["cbom"] = build_cbom(result) if result.ok else None
        queue.push_result(payload)
        queue.ack(reference)
