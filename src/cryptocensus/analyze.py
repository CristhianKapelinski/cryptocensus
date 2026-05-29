"""Aggregate the collected dataset into the census results.

Methodological notes baked into the code:
  * Trust store vs. own crypto: the CA bundle shipped by the base OS is reported
    separately from cryptographic material the image author introduced ("own").
  * Key reuse and batch-GCD run on OWN keys/moduli only, because the CA bundle is
    legitimately identical across images that share a base layer and would otherwise
    dominate (and falsify) any reuse signal.
  * Tool divergence is computed only between *independent third-party tools*
    (e.g. cbom-lens). The built-in extractor is reported as the calibrated instrument,
    not as a divergence party.
"""

from __future__ import annotations

import csv
import glob
import json
import os
from collections import Counter, defaultdict

from .batchgcd import batch_gcd


def _load(dataset_dir: str) -> list[dict]:
    records = []
    for path in glob.glob(os.path.join(dataset_dir, "records", "*.json")):
        with open(path) as handle:
            records.append(json.load(handle))
    return records


def _pct(part: int, whole: int) -> float:
    return round(100.0 * part / whole, 2) if whole else 0.0


def analyze(dataset_dir: str) -> dict:
    images = _load(dataset_dir)
    ok = [im for im in images if im.get("ok")]

    all_certs, own_certs = [], []
    own_keys, all_keys = [], []
    libs = []
    weak_cfg_tokens: Counter[str] = Counter()
    pqc_capable_images = set()
    divergence = []  # (reference, {tool: certificate_count})

    for im in ok:
        ref = im["reference"]
        per_tool = {}
        for obs in im.get("tool_observations", []):
            if obs.get("tool") in ("builtin", "cbom-lens") and not obs.get("error"):
                per_tool[obs["tool"]] = obs["certificates"]
        if len(per_tool) >= 2:
            divergence.append((ref, per_tool))

        for c in im.get("certs", []):
            all_certs.append(c)
            if not c["in_trust_store"]:
                own_certs.append(c)
        for k in im.get("keys", []):
            all_keys.append(k)
            if not k["in_trust_store"]:
                own_keys.append(k)
        for lib in im.get("libraries", []):
            libs.append(lib)
            if lib["pqc_capable"]:
                pqc_capable_images.add(ref)
        for wc in im.get("weak_configs", []):
            weak_cfg_tokens[wc["token"]] += 1

    # --- public-key asset posture (the headline axis) ----------------------
    pk_assets = [c for c in all_certs] + [k for k in all_keys]
    qv = sum(1 for a in pk_assets if a["pq_status"] == "quantum-vulnerable")
    pqc = sum(1 for a in pk_assets if a["pq_status"] == "post-quantum")

    # --- key reuse on OWN keys only ----------------------------------------
    own_fpr_to_images = defaultdict(set)
    for im in ok:
        for k in im.get("keys", []):
            if not k["in_trust_store"] and k.get("public_key_sha256"):
                own_fpr_to_images[k["public_key_sha256"]].add(im["reference"])
        for c in im.get("certs", []):
            if not c["in_trust_store"] and c.get("public_key_sha256"):
                own_fpr_to_images[c["public_key_sha256"]].add(im["reference"])
    reused = {fpr: imgs for fpr, imgs in own_fpr_to_images.items() if len(imgs) > 1}

    # --- batch-GCD on OWN RSA moduli ---------------------------------------
    own_moduli = []
    for a in own_certs + own_keys:
        if a.get("rsa_modulus_hex"):
            try:
                own_moduli.append(int(a["rsa_modulus_hex"], 16))
            except ValueError:
                pass
    unique_moduli = sorted(set(own_moduli))
    factorable = batch_gcd(unique_moduli)

    summary = {
        "images_total": len(images),
        "images_ok": len(ok),
        "images_unavailable": len(images) - len(ok),
        "unavailable_pct": _pct(len(images) - len(ok), len(images)),
        "public_key_assets": len(pk_assets),
        "quantum_vulnerable": qv,
        "quantum_vulnerable_pct": _pct(qv, len(pk_assets)),
        "post_quantum": pqc,
        "post_quantum_pct": _pct(pqc, len(pk_assets)),
        "certs_total": len(all_certs),
        "certs_own": len(own_certs),
        "certs_weak_signature": sum(1 for c in all_certs if c["weak_signature"]),
        "certs_own_weak_signature": sum(1 for c in own_certs if c["weak_signature"]),
        "keys_own": len(own_keys),
        "own_key_fingerprints": len(own_fpr_to_images),
        "own_keys_reused_across_images": len(reused),
        "own_rsa_moduli_unique": len(unique_moduli),
        "factorable_moduli_shared_prime": len(factorable),
        "images_with_pqc_capable_library": len(pqc_capable_images),
        "weak_config_tokens": dict(weak_cfg_tokens.most_common()),
        "tool_divergence_images": len(divergence),
    }

    _write_artifacts(dataset_dir, all_certs, all_keys, summary, divergence)
    _write_run_manifest(dataset_dir, images)
    return summary


def _write_run_manifest(dataset_dir: str, images: list[dict]) -> None:
    """Pin every scanned image to its resolved digest so the run is 100% reproducible:
    the dataset can be regenerated by re-pulling each `reference@digest` exactly."""
    with open(os.path.join(dataset_dir, "run_manifest.csv"), "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["reference", "digest", "ok", "files_scanned", "error"])
        for im in images:
            writer.writerow([
                im.get("reference"), im.get("digest") or "", im.get("ok"),
                im.get("files_scanned", 0), im.get("error") or "",
            ])


def _write_artifacts(dataset_dir, all_certs, all_keys, summary, divergence):
    with open(os.path.join(dataset_dir, "summary.json"), "w") as handle:
        json.dump(summary, handle, indent=2)
    with open(os.path.join(dataset_dir, "assets.csv"), "w", newline="") as handle:
        cols = ["asset", "path", "in_trust_store", "key_type", "key_size",
                "pq_status", "weak_key", "signature_hash", "weak_signature"]
        writer = csv.DictWriter(handle, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        for c in all_certs:
            writer.writerow({"asset": "certificate", **c})
        for k in all_keys:
            writer.writerow({"asset": f"key:{k['kind']}", **k})
    if divergence:
        with open(os.path.join(dataset_dir, "tool_divergence.csv"), "w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["reference", "builtin_certs", "cbom_lens_certs"])
            for ref, per_tool in divergence:
                writer.writerow([ref, per_tool.get("builtin", ""), per_tool.get("cbom-lens", "")])


def format_report(summary: dict) -> str:
    s = summary
    lines = [
        "=" * 64,
        "CRYPTOCENSUS — RESULTS",
        "=" * 64,
        f"images analyzed (ok/total)      : {s['images_ok']}/{s['images_total']}",
        f"  unavailable (decay/no latest) : {s['images_unavailable']} ({s['unavailable_pct']}%)",
        f"public-key assets catalogued    : {s['public_key_assets']}",
        f"  quantum-vulnerable            : {s['quantum_vulnerable']} ({s['quantum_vulnerable_pct']}%)",
        f"  post-quantum                  : {s['post_quantum']} ({s['post_quantum_pct']}%)",
        f"certificates (own/total)        : {s['certs_own']}/{s['certs_total']}",
        f"  weak signature (own/total)    : {s['certs_own_weak_signature']}/{s['certs_weak_signature']}",
        f"own keys                        : {s['keys_own']}",
        f"  reused across images          : {s['own_keys_reused_across_images']}",
        f"own unique RSA moduli           : {s['own_rsa_moduli_unique']}",
        f"  factorable (shared prime)     : {s['factorable_moduli_shared_prime']}",
        f"images w/ PQC-capable library   : {s['images_with_pqc_capable_library']}",
        f"weak TLS/SSH config tokens      : {s['weak_config_tokens']}",
        f"images for tool-divergence      : {s['tool_divergence_images']}",
        "=" * 64,
    ]
    return "\n".join(lines)
