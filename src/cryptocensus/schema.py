"""Typed records exchanged between extractors, the worker, and the analyzer.

Records are plain dataclasses serialized to JSON. Every cryptographic asset carries
its provenance (image reference, in-image path, and whether it belongs to the system
trust store) so that aggregation can separate the CA trust bundle shipped by the base
OS from cryptographic material the image author actually introduced.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class CertRecord:
    path: str
    in_trust_store: bool
    signature_hash: str
    weak_signature: bool
    key_type: str
    key_size: int | None
    weak_key: bool
    expired: bool
    self_signed: bool
    is_ca: bool
    san_count: int
    pq_status: str
    public_key_sha256: str | None = None
    rsa_modulus_hex: str | None = None


@dataclass
class KeyRecord:
    path: str
    in_trust_store: bool
    kind: str  # "private" | "public" | "ssh"
    key_type: str
    key_size: int | None
    weak_key: bool
    pq_status: str
    public_key_sha256: str | None = None
    rsa_modulus_hex: str | None = None


@dataclass
class LibraryRecord:
    name: str
    version: str
    source: str  # "dpkg" | "apk" | "syft"
    pqc_capable: bool


@dataclass
class WeakConfigRecord:
    path: str
    token: str


@dataclass
class ToolObservation:
    """A coarse, per-tool count used for inter-tool divergence analysis. Only counts
    from *independent third-party tools* are comparable; the built-in extractor is
    recorded too but is treated as the primary instrument, not a divergence party."""

    tool: str
    certificates: int
    keys: int
    algorithms: int
    error: str | None = None


@dataclass
class ImageResult:
    reference: str
    digest: str | None
    ok: bool
    error: str | None = None
    files_scanned: int = 0
    certs: list[CertRecord] = field(default_factory=list)
    keys: list[KeyRecord] = field(default_factory=list)
    libraries: list[LibraryRecord] = field(default_factory=list)
    weak_configs: list[WeakConfigRecord] = field(default_factory=list)
    tool_observations: list[ToolObservation] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)
