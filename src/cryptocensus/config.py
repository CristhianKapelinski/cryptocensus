"""Runtime configuration, read from environment variables so that the same image
runs unchanged as a coordinator, a worker, or an analyzer across many machines.
"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass


def _flag(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    redis_url: str = os.environ.get("CC_REDIS_URL", "redis://localhost:6379/0")
    task_queue: str = os.environ.get("CC_TASK_QUEUE", "cryptocensus:tasks")
    processing_queue: str = os.environ.get("CC_PROCESSING_QUEUE", "cryptocensus:processing")
    result_queue: str = os.environ.get("CC_RESULT_QUEUE", "cryptocensus:results")
    done_set: str = os.environ.get("CC_DONE_SET", "cryptocensus:done")
    retry_hash: str = os.environ.get("CC_RETRY_HASH", "cryptocensus:retries")

    # Where each worker writes the full per-image output bundle (records, CBOM, raw
    # tool outputs, and deduplicated crypto blobs). On a multi-machine run this is a
    # per-host directory; gather the hosts' directories into one before analyzing.
    output_dir: str = os.environ.get("CC_OUTPUT_DIR", "/data")
    # Persist the raw (unparsed) artifacts: full third-party tool outputs and the raw
    # certificate/key bytes. Kept on by default for auditability and reproducibility.
    save_raw: bool = _flag("CC_SAVE_RAW", True)

    # Extractor toggles (every collector can be disabled for ablation/perf studies).
    enable_certs_keys: bool = _flag("CC_ENABLE_CERTS_KEYS", True)
    enable_libraries: bool = _flag("CC_ENABLE_LIBRARIES", True)
    enable_secrets: bool = _flag("CC_ENABLE_SECRETS", True)
    enable_cbom_lens: bool = _flag("CC_ENABLE_CBOM_LENS", True)
    enable_syft: bool = _flag("CC_ENABLE_SYFT", False)

    # Tool binaries (overridable; defaults match the Docker image PATH).
    crane_bin: str = os.environ.get("CC_CRANE_BIN", "crane")
    gitleaks_bin: str = os.environ.get("CC_GITLEAKS_BIN", "gitleaks")
    cbom_lens_bin: str = os.environ.get("CC_CBOM_LENS_BIN", "cbom-lens")
    syft_bin: str = os.environ.get("CC_SYFT_BIN", "syft")

    # Limits and retry policy (everything configurable; no hardcoded constants).
    max_file_bytes: int = int(os.environ.get("CC_MAX_FILE_BYTES", str(2_000_000)))
    max_image_bytes: int = int(os.environ.get("CC_MAX_IMAGE_BYTES", str(2 * 1024 * 1024 * 1024)))
    max_extract_bytes: int = int(os.environ.get("CC_MAX_EXTRACT_BYTES", str(4 * 1024 * 1024 * 1024)))
    pull_timeout_s: int = int(os.environ.get("CC_PULL_TIMEOUT_S", "300"))
    tool_timeout_s: int = int(os.environ.get("CC_TOOL_TIMEOUT_S", "300"))
    pull_retries: int = int(os.environ.get("CC_PULL_RETRIES", "3"))
    max_transient_retries: int = int(os.environ.get("CC_MAX_TRANSIENT_RETRIES", "5"))

    # Serialize pulls per host: workers on the same machine acquire a Redis lock before
    # pulling, so only one image downloads at a time per node. This keeps concurrent
    # requests low enough to stay under the registry's pull-rate limit while extraction
    # still runs in parallel. The lock is scoped to the host so the separate-network
    # machines still pull in parallel with each other.
    pull_mutex_enabled: bool = _flag("CC_PULL_MUTEX", True)
    pull_mutex_key: str = os.environ.get("CC_PULL_MUTEX_KEY", f"cryptocensus:pulllock:{socket.gethostname()}")
    pull_mutex_ttl_s: int = int(os.environ.get("CC_PULL_MUTEX_TTL_S", "600"))
    pull_mutex_wait_s: float = float(os.environ.get("CC_PULL_MUTEX_WAIT_S", "0.25"))
    pull_retry_backoff_s: float = float(os.environ.get("CC_PULL_RETRY_BACKOFF_S", "5"))
    platform: str = os.environ.get("CC_PLATFORM", "linux/amd64")
    registry: str = os.environ.get("CC_REGISTRY", "index.docker.io")
    docker_config: str = os.environ.get("DOCKER_CONFIG", "")
    work_dir: str = os.environ.get("CC_WORK_DIR", "/tmp/cryptocensus")
    claim_block_s: int = int(os.environ.get("CC_CLAIM_BLOCK_S", "5"))


settings = Settings()
