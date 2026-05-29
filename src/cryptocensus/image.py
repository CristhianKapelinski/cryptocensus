"""Daemonless, digest-pinned image acquisition via crane.

The reference is resolved to an immutable digest and pulled by digest, so the scanned
bytes match the recorded digest exactly (reproducible, no tag TOCTOU). Transient
registry failures are retried; permanent ones (missing tag/repo, auth) are not, so they
are reported as decay rather than masked by retries.
"""

from __future__ import annotations

import os
import subprocess
import tarfile
import time

# Substrings that mark a non-retryable failure (the reference is simply gone/forbidden).
_PERMANENT = ("MANIFEST_UNKNOWN", "NAME_UNKNOWN", "NOT FOUND", "MANIFEST UNKNOWN",
              "UNAUTHORIZED", "DENIED", "NO MATCHING", "NO CHILD WITH PLATFORM")


class ImagePullError(RuntimeError):
    pass


def _permanent(message: str) -> bool:
    upper = message.upper()
    return any(marker in upper for marker in _PERMANENT)


def _crane(args: list[str], timeout_s: int) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout_s, check=False)
    except FileNotFoundError as exc:
        raise ImagePullError("crane binary not found") from exc
    except subprocess.TimeoutExpired:
        return 1, "", "timed out"
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def pin_to_digest(reference: str, digest: str) -> str:
    if "@" in reference:
        return reference
    last_segment = reference.rsplit("/", 1)[-1]
    repo = reference.rsplit(":", 1)[0] if ":" in last_segment else reference
    return f"{repo}@{digest}"


def _safe_extract(tar_path: str, dest: str) -> None:
    root = os.path.realpath(dest)
    with tarfile.open(tar_path, "r:*") as tar:
        for member in tar:
            if not (member.isfile() or member.isdir()):
                continue
            target = os.path.realpath(os.path.join(dest, member.name))
            if target != root and not target.startswith(root + os.sep):
                continue
            try:
                if member.isdir():
                    os.makedirs(target, exist_ok=True)
                    continue
                os.makedirs(os.path.dirname(target), exist_ok=True)
                src = tar.extractfile(member)
                if src is None:
                    continue
                with src, open(target, "wb") as out:
                    out.write(src.read())
            except (OSError, tarfile.TarError):
                continue


def image_digest(reference: str, crane_bin: str = "crane", timeout_s: int = 120,
                 platform: str = "linux/amd64") -> str | None:
    plat = ["--platform", platform] if platform else []
    rc, digest, _ = _crane([crane_bin, "digest", *plat, reference], timeout_s)
    return digest if rc == 0 and digest else None


def export_rootfs(reference: str, dest: str, crane_bin: str = "crane", timeout_s: int = 300,
                  retries: int = 3, backoff_s: float = 5.0, platform: str = "linux/amd64") -> str:
    """Resolve, pull-by-digest, and flatten `reference` into `dest`; return the digest."""
    os.makedirs(dest, exist_ok=True)
    tar_path = dest.rstrip("/") + ".tar"
    plat = ["--platform", platform] if platform else []
    error = ""
    for attempt in range(retries + 1):
        rc, digest, error = _crane([crane_bin, "digest", *plat, reference], min(timeout_s, 120))
        if rc == 0 and digest:
            pinned = pin_to_digest(reference, digest)
            rc, _, error = _crane([crane_bin, "export", *plat, pinned, tar_path], timeout_s)
            if rc == 0 and os.path.exists(tar_path):
                try:
                    _safe_extract(tar_path, dest)
                finally:
                    if os.path.exists(tar_path):
                        os.remove(tar_path)
                return digest
            error = error or "crane export failed"
        else:
            error = error or "could not resolve digest"
        if _permanent(error) or attempt == retries:
            break
        time.sleep(backoff_s * (attempt + 1))
    raise ImagePullError(f"{reference}: {error}")
