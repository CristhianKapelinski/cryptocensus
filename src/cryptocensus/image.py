"""Daemonless image acquisition.

`crane export` pulls an image directly from a registry and streams the *flattened*
root filesystem as a tar archive, without a Docker daemon and without executing the
image. We extract it safely (rejecting absolute paths and path traversal, skipping
device/special files), which is both secure against hostile images and reproducible.
"""

from __future__ import annotations

import os
import subprocess
import tarfile


class ImagePullError(RuntimeError):
    pass


def image_digest(reference: str, crane_bin: str = "crane", timeout_s: int = 120) -> str | None:
    try:
        proc = subprocess.run(
            [crane_bin, "digest", reference],
            capture_output=True, text=True, timeout=timeout_s, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    digest = proc.stdout.strip()
    return digest or None


def _safe_extract(tar_path: str, dest: str) -> None:
    """Extract a rootfs tarball into `dest`, ignoring unsafe and non-regular entries."""
    dest_abs = os.path.realpath(dest)
    with tarfile.open(tar_path, mode="r:*") as tar:
        for member in tar:
            if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
                continue  # skip device nodes, fifos, sockets
            target = os.path.realpath(os.path.join(dest, member.name))
            if not (target == dest_abs or target.startswith(dest_abs + os.sep)):
                continue  # path traversal attempt
            try:
                if member.isdir():
                    os.makedirs(target, exist_ok=True)
                elif member.isfile():
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    with tar.extractfile(member) as src:
                        if src is None:
                            continue
                        with open(target, "wb") as out:
                            out.write(src.read())
                # Symlinks/hardlinks are intentionally not recreated: extractors read
                # regular files only, and links are a traversal risk.
            except (OSError, tarfile.TarError):
                continue


def pin_to_digest(reference: str, digest: str) -> str:
    """Rewrite a tag reference (``repo:tag``) to a digest reference (``repo@sha256:...``).
    A reference that is already digest-pinned is returned unchanged."""
    if "@" in reference:
        return reference
    last_segment = reference.rsplit("/", 1)[-1]
    repo = reference.rsplit(":", 1)[0] if ":" in last_segment else reference
    return f"{repo}@{digest}"


def export_rootfs(
    reference: str,
    dest: str,
    crane_bin: str = "crane",
    timeout_s: int = 300,
) -> str:
    """Resolve `reference` to an immutable digest, then pull and flatten *that digest*
    into `dest`. Returns the digest. Raises ImagePullError if the reference cannot be
    resolved or pulled.

    Resolving the digest first and exporting by digest makes the census 100%
    reproducible: the recorded digest is exactly the bytes that were scanned (no
    time-of-check/time-of-use gap with the mutable tag), and the image can be
    re-pulled later by digest even after the tag moves or is deleted."""
    os.makedirs(dest, exist_ok=True)
    digest = image_digest(reference, crane_bin=crane_bin, timeout_s=min(timeout_s, 120))
    if not digest:
        raise ImagePullError(f"could not resolve digest for {reference}")
    pinned = pin_to_digest(reference, digest)

    tar_path = dest.rstrip("/") + ".tar"
    try:
        proc = subprocess.run(
            [crane_bin, "export", pinned, tar_path],
            capture_output=True, text=True, timeout=timeout_s, check=False,
        )
    except FileNotFoundError as exc:
        raise ImagePullError("crane binary not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise ImagePullError(f"crane export timed out after {timeout_s}s") from exc
    if proc.returncode != 0 or not os.path.exists(tar_path):
        raise ImagePullError(proc.stderr.strip() or "crane export failed")
    try:
        _safe_extract(tar_path, dest)
    finally:
        try:
            os.remove(tar_path)
        except OSError:
            pass
    return digest
