"""Worker: claim an image reference, pull and flatten it by digest, run every enabled
extractor, and write the complete per-image bundle (structured record, CBOM, raw tool
outputs, raw crypto blobs, and a log) to the output directory.

Stateless and idempotent: any number of workers on any number of machines run
concurrently against the same Redis queue and write into their own output directory,
which are merged for analysis. Raw artifacts are compressed as they are written.
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
from .transport import encode_bundle

log = logging.getLogger("cryptocensus.worker")


def _safe_name(reference: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", reference)


def _force_rmtree(path: str) -> None:
    """Reliably remove a flattened rootfs. Extracted container trees often contain
    directories with restrictive modes that defeat a plain rmtree, so make every
    directory traversable/writable first. Leaking scratch fills small disks and was
    the dominant cause of ENOSPC pull failures."""
    if not os.path.exists(path):
        return
    for root, dirs, _files in os.walk(path):
        for d in dirs:
            try:
                os.chmod(os.path.join(root, d), 0o700)
            except OSError:
                pass
    shutil.rmtree(path, ignore_errors=True)


_TRANSIENT_MARKERS = (
    "no space left", "errno 28", "register layer", "write /", "timed out", "timeout",
    "deadline exceeded", "too many requests", "toomanyrequests", "429",
    "connection reset", "i/o timeout", "temporary failure", "unexpected eof",
)


def _is_transient(error: str | None) -> bool:
    """A disk/network/rate-limit failure that must be retried, not recorded as a (false)
    terminal result. Distinct from permanent decay (missing tag/repo) and from too-large."""
    if not error:
        return False
    low = error.lower()
    return any(marker in low for marker in _TRANSIENT_MARKERS)


def process_image(reference: str, s: Settings) -> tuple[ImageResult, dict]:
    """Pull (by resolved digest), flatten, and analyze a single image. Returns the
    structured result and a `raw` bundle (blobs, full tool outputs, log). Expected
    failures (pull/parse) are returned as a non-ok result, never raised."""
    events: list[str] = []
    raw: dict = {"blobs": {}, "builtin_cbom": None, "cbom_lens": None,
                 "gitleaks": None, "syft": None, "log": ""}

    work = os.path.join(s.work_dir, _safe_name(reference))
    _force_rmtree(work)
    try:
        digest = export_rootfs(reference, work, crane_bin=s.crane_bin, timeout_s=s.pull_timeout_s,
                               retries=s.pull_retries, backoff_s=s.pull_retry_backoff_s,
                               platform=s.platform, max_bytes=s.max_image_bytes,
                               max_extract_bytes=s.max_extract_bytes)
        events.append(f"pull ok: {reference} -> {digest}")
    except ImagePullError as exc:
        events.append(f"pull failed: {exc}")
        raw["log"] = "\n".join(events)
        return ImageResult(reference=reference, digest=None, ok=False, error=f"pull: {exc}"), raw

    try:
        result = ImageResult(reference=reference, digest=digest, ok=True)
        if s.enable_certs_keys:
            certs, keys, weak_configs, files_scanned, blobs = certs_keys.extract(work, s.max_file_bytes)
            result.certs, result.keys = certs, keys
            result.weak_configs, result.files_scanned = weak_configs, files_scanned
            result.tool_observations.append(ToolObservation("builtin", len(certs), len(keys), 0))
            raw["blobs"] = blobs
            events.append(f"builtin: certs={len(certs)} keys={len(keys)} blobs={len(blobs)}")
        if s.enable_libraries:
            libs = libraries.extract(work)
            result.libraries.extend(libs)
            events.append(f"libraries: {len(libs)}")
        if s.enable_syft:
            syft_records, syft_doc, err = sbom.extract(work, s.syft_bin, s.tool_timeout_s)
            result.libraries.extend(syft_records)
            raw["syft"] = syft_doc
            events.append(f"syft: {len(syft_records)} crypto libs" + (f" (error: {err})" if err else ""))
        if s.enable_secrets:
            findings, err = secrets.extract(work, s.gitleaks_bin, s.tool_timeout_s)
            raw["gitleaks"] = findings
            result.tool_observations.append(ToolObservation("gitleaks", 0, len(findings), 0, error=err))
            events.append(f"gitleaks: {len(findings)} key findings" + (f" (error: {err})" if err else ""))
        if s.enable_cbom_lens:
            observation, raw_cbom = cbom_lens.scan(work, s.cbom_lens_bin, s.tool_timeout_s)
            result.tool_observations.append(observation)
            raw["cbom_lens"] = raw_cbom
            events.append(f"cbom-lens: certs={observation.certificates}"
                          + (f" (error: {observation.error})" if observation.error else ""))

        raw["builtin_cbom"] = build_cbom(result)
        raw["log"] = "\n".join(events)
        return result, raw
    finally:
        _force_rmtree(work)


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
            result, raw = process_image(reference, s)
        except Exception as exc:  # defensive: a worker must never die on one image
            log.exception("unexpected error on %s", reference)
            result = ImageResult(reference=reference, digest=None, ok=False, error=f"unexpected: {exc}")
            raw = {"log": f"unexpected: {exc}"}
        if (not result.ok and _is_transient(result.error)
                and queue.transient_retry(reference) <= s.max_transient_retries):
            # Disk/network/rate-limit failure: return the task for a later attempt or a
            # healthier worker instead of poisoning the dataset with a false unavailable.
            log.warning("transient failure on %s (%s); requeuing", reference, result.error)
            queue.requeue(reference)
            continue
        try:
            queue.push_result(encode_bundle(result, raw))
        except Exception:
            log.exception("failed to push result for %s", reference)
        finally:
            queue.ack(reference)
