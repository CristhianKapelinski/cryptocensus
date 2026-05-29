"""Optional crypto-library inventory via Syft (SBOM).

Syft catalogs packages, including statically and dynamically linked crypto libraries
that the dpkg/apk databases may miss (e.g. vendored OpenSSL in a Go binary). Disabled
by default; enable with CC_ENABLE_SYFT=1. Complements, and is cross-checked against,
the package-database inventory in `libraries.py`.
"""

from __future__ import annotations

import json
import subprocess

from ..classify import library_pqc_capable
from ..schema import LibraryRecord

_CRYPTO_KEYWORDS = ("openssl", "libssl", "libcrypto", "gnutls", "gcrypt", "wolfssl",
                    "mbedtls", "boringssl", "nss", "nettle", "oqs")


def extract(root: str, syft_bin: str = "syft", timeout_s: int = 300) -> tuple[list[LibraryRecord], str | None]:
    cmd = [syft_bin, f"dir:{root}", "-o", "syft-json", "-q"]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout_s, check=False)
    except FileNotFoundError:
        return [], "syft binary not found"
    except subprocess.TimeoutExpired:
        return [], "syft timed out"
    try:
        doc = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return [], "syft produced no JSON"
    records: list[LibraryRecord] = []
    for artifact in doc.get("artifacts", []):
        name = (artifact.get("name") or "").lower()
        if any(keyword in name for keyword in _CRYPTO_KEYWORDS):
            version = artifact.get("version") or ""
            records.append(LibraryRecord(name, version, "syft", library_pqc_capable(name, version)))
    return records, None
