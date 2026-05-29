"""Serialize an ImageResult to a CycloneDX 1.7 Cryptography Bill of Materials.

CycloneDX 1.7 (ECMA-424, 2nd ed.) is the current standard for representing
cryptographic assets. We emit one CBOM per image: certificates as `certificate`
components, keys as `related-crypto-material`, and the public-key/signature
algorithms as `algorithm` components carrying the NIST quantum-vulnerability
classification in a property.
"""

from __future__ import annotations

from typing import Any

from .schema import ImageResult

_SPEC_VERSION = "1.7"


def _algorithm_component(name: str, pq_status: str) -> dict[str, Any]:
    return {
        "type": "cryptographic-asset",
        "name": name,
        "cryptoProperties": {
            "assetType": "algorithm",
            "algorithmProperties": {
                "primitive": "unknown",
                "classicalSecurityLevel": 0,
            },
        },
        "properties": [{"name": "cryptocensus:pqStatus", "value": pq_status}],
    }


def build_cbom(result: ImageResult) -> dict[str, Any]:
    components: list[dict[str, Any]] = []
    algorithms_seen: set[str] = set()

    for cert in result.certs:
        components.append({
            "type": "cryptographic-asset",
            "name": cert.path,
            "cryptoProperties": {
                "assetType": "certificate",
                "certificateProperties": {
                    "signatureAlgorithmRef": cert.signature_hash,
                    "subjectPublicKeyRef": f"{cert.key_type}-{cert.key_size}",
                },
            },
            "properties": [
                {"name": "cryptocensus:inTrustStore", "value": str(cert.in_trust_store).lower()},
                {"name": "cryptocensus:pqStatus", "value": cert.pq_status},
                {"name": "cryptocensus:weakSignature", "value": str(cert.weak_signature).lower()},
                {"name": "cryptocensus:expired", "value": str(cert.expired).lower()},
            ],
        })
        algorithms_seen.add((cert.key_type, cert.pq_status))

    for key in result.keys:
        components.append({
            "type": "cryptographic-asset",
            "name": key.path,
            "cryptoProperties": {
                "assetType": "related-crypto-material",
                "relatedCryptoMaterialProperties": {
                    "type": "private-key" if key.kind == "private" else "public-key",
                    "size": key.key_size,
                },
            },
            "properties": [
                {"name": "cryptocensus:inTrustStore", "value": str(key.in_trust_store).lower()},
                {"name": "cryptocensus:pqStatus", "value": key.pq_status},
            ],
        })
        algorithms_seen.add((key.key_type, key.pq_status))

    for key_type, pq_status in sorted(algorithms_seen):
        components.append(_algorithm_component(key_type, pq_status))

    return {
        "bomFormat": "CycloneDX",
        "specVersion": _SPEC_VERSION,
        "version": 1,
        "metadata": {
            "component": {
                "type": "container",
                "name": result.reference,
                "version": result.digest or "unknown",
            },
            "tools": [{"vendor": "cryptocensus", "name": "cryptocensus"}],
        },
        "components": components,
    }
