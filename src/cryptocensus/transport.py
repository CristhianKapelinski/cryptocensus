"""Result bundle (de)serialization for the queue channel.

A worker encodes its full per-image output (structured record, built-in CBOM, raw tool
outputs, per-image log, and the raw bytes of the image's own crypto material) into one
gzip-compressed, base64-encoded string that travels through Redis to the host. The host
collector decodes it and writes it to disk. Compressing on the worker keeps the result
channel small even though raw artifacts are carried end to end.
"""

from __future__ import annotations

import base64
import gzip
import json

from .schema import ImageResult


def encode_bundle(result: ImageResult, raw: dict) -> str:
    own_blobs = {
        sha: base64.b64encode(data).decode("ascii")
        for sha, data in raw.get("blobs", {}).items()
    }
    bundle = {
        "record": result.to_json(),
        "builtin_cbom": raw.get("builtin_cbom"),
        "raw": {
            "cbom_lens": raw.get("cbom_lens"),
            "gitleaks": raw.get("gitleaks"),
            "syft": raw.get("syft"),
            "log": raw.get("log"),
            "blobs": own_blobs,
        },
    }
    compressed = gzip.compress(json.dumps(bundle).encode("utf-8"))
    return base64.b64encode(compressed).decode("ascii")


def decode_bundle(payload: str) -> tuple[dict, dict | None, dict]:
    """Return (record, builtin_cbom, raw) with blob bytes decoded."""
    bundle = json.loads(gzip.decompress(base64.b64decode(payload)))
    raw = dict(bundle.get("raw") or {})
    raw["blobs"] = {
        sha: base64.b64decode(value) for sha, value in (raw.get("blobs") or {}).items()
    }
    return bundle["record"], bundle.get("builtin_cbom"), raw
