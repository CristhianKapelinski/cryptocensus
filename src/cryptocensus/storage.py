"""Per-image output bundle writer (content-addressed, deduplicated).

The host collector calls this for every result it drains from the queue, writing a
self-contained, reproducible dataset:

    <output>/records/<digest>.json          structured record (all parsed findings)
    <output>/cbom/<digest>.cbom.json         built-in CycloneDX 1.7 CBOM
    <output>/raw/<digest>/cbom-lens.json.gz  full third-party CBOM-Lens output
    <output>/raw/<digest>/gitleaks.json.gz   full gitleaks findings
    <output>/raw/<digest>/syft.json.gz       full syft SBOM (if enabled)
    <output>/raw/<digest>/log.txt.gz         per-image processing log
    <output>/blobs/<sha256>.pem              raw bytes of the image's own crypto material

Raw tool outputs and logs are gzip-compressed; cryptographic blobs are content-addressed
by sha256 and deduplicated on write, so material shared across images is stored once.
"""

from __future__ import annotations

import gzip
import json
import os
import re


def _key(record: dict) -> str:
    digest = record.get("digest")
    if digest:
        return digest.replace(":", "_")
    return re.sub(r"[^A-Za-z0-9_.-]", "_", record.get("reference", "unknown"))


def _write_json(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        json.dump(obj, handle, indent=2)


def _write_json_gz(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(obj, handle)


def write_bundle(output_dir: str, record: dict, builtin_cbom: dict | None,
                 raw: dict, save_raw: bool = True) -> None:
    """Write one image's result. `raw` may contain cbom_lens/gitleaks/syft (JSON),
    `log` (str), and `blobs` ({sha256: bytes})."""
    key = _key(record)
    _write_json(os.path.join(output_dir, "records", f"{key}.json"), record)
    if builtin_cbom is not None:
        _write_json(os.path.join(output_dir, "cbom", f"{key}.cbom.json"), builtin_cbom)

    if not save_raw:
        return

    raw_dir = os.path.join(output_dir, "raw", key)
    if raw.get("cbom_lens") is not None:
        _write_json_gz(os.path.join(raw_dir, "cbom-lens.json.gz"), raw["cbom_lens"])
    if raw.get("gitleaks") is not None:
        _write_json_gz(os.path.join(raw_dir, "gitleaks.json.gz"), raw["gitleaks"])
    if raw.get("syft") is not None:
        _write_json_gz(os.path.join(raw_dir, "syft.json.gz"), raw["syft"])
    if raw.get("log"):
        os.makedirs(raw_dir, exist_ok=True)
        with gzip.open(os.path.join(raw_dir, "log.txt.gz"), "wt", encoding="utf-8") as handle:
            handle.write(raw["log"])

    blobs_dir = os.path.join(output_dir, "blobs")
    os.makedirs(blobs_dir, exist_ok=True)
    for sha, data in raw.get("blobs", {}).items():
        path = os.path.join(blobs_dir, f"{sha}.pem")
        if not os.path.exists(path):
            try:
                with open(path, "wb") as handle:
                    handle.write(data)
            except OSError:
                continue
