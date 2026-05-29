"""Crypto-library inventory from the image package databases.

Reading the dpkg/apk databases on the flattened filesystem is deterministic and
cheap, and yields the installed cryptographic libraries and their versions. Each
library is tagged with a version-based post-quantum capability flag (the QED-Lite
fingerprinting idea, IACR ePrint 2026/660): a deployed library can negotiate PQC
only if its version is recent enough. This measures *capability*, not *usage*.
"""

from __future__ import annotations

import os
import re

from ..classify import library_pqc_capable
from ..schema import LibraryRecord

_CRYPTO_LIB_RE = re.compile(
    r"(openssl|libssl|libcrypto|gnutls|libgcrypt|wolfssl|mbedtls|boringssl|nss3?|nettle|oqs)",
    re.IGNORECASE,
)


def _parse_dpkg(status_path: str) -> list[LibraryRecord]:
    records: list[LibraryRecord] = []
    current = None
    try:
        with open(status_path, "r", errors="ignore") as handle:
            for line in handle:
                if line.startswith("Package:"):
                    current = line.split(":", 1)[1].strip()
                elif line.startswith("Version:") and current and _CRYPTO_LIB_RE.search(current):
                    version = line.split(":", 1)[1].strip()
                    records.append(
                        LibraryRecord(current, version, "dpkg", library_pqc_capable(current, version))
                    )
    except OSError:
        pass
    return records


def _parse_apk(installed_path: str) -> list[LibraryRecord]:
    records: list[LibraryRecord] = []
    package = None
    try:
        with open(installed_path, "r", errors="ignore") as handle:
            for line in handle:
                if line.startswith("P:"):
                    package = line[2:].strip()
                elif line.startswith("V:") and package and _CRYPTO_LIB_RE.search(package):
                    version = line[2:].strip()
                    records.append(
                        LibraryRecord(package, version, "apk", library_pqc_capable(package, version))
                    )
    except OSError:
        pass
    return records


def extract(root: str) -> list[LibraryRecord]:
    records: list[LibraryRecord] = []
    dpkg_status = os.path.join(root, "var/lib/dpkg/status")
    if os.path.exists(dpkg_status):
        records.extend(_parse_dpkg(dpkg_status))
    apk_installed = os.path.join(root, "lib/apk/db/installed")
    if os.path.exists(apk_installed):
        records.extend(_parse_apk(apk_installed))
    return records
