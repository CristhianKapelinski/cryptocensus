"""Aggregate the collected dataset into the census results.

Methodological notes baked into the code:
  * Trust-store vs. non-trust-store crypto: files under known CA-bundle paths are
    reported separately from material elsewhere. This path classification does not
    establish authorship or runtime use. Legacy output fields retain the name "own".
  * Key reuse and batch-GCD run on non-trust-store keys/moduli only, because CA bundles are
    legitimately identical across images that share a base layer and would otherwise
    dominate (and falsify) any reuse signal.
  * Tool divergence is computed only between *independent third-party tools*
    (e.g. cbom-lens). The built-in extractor is the primary instrument, not a
    divergence party.
"""

from __future__ import annotations

import csv
import glob
import json
import os
import sys
import tarfile
from collections import Counter, defaultdict

from .batchgcd import batch_gcd
from .classify import library_pqc_capable
from .extractors.certs_keys import is_crypto_config
from .stats import wilson_pct


def iter_records(source: str):
    """Yield per-image record dicts from a dataset directory (its ``records/*.json``) or
    directly from the released ``.tar.gz`` archive, streamed member by member so the ~20k
    record files never have to be extracted to disk — fast, and safe on filesystems that
    choke on many small files."""
    if os.path.isdir(source):
        for path in glob.glob(os.path.join(source, "records", "*.json")):
            with open(path) as handle:
                yield json.load(handle)
        return
    with tarfile.open(source, "r:gz") as tf:
        for member in tf:
            if not (member.isfile() and member.name.startswith("records/")
                    and member.name.endswith(".json")):
                continue
            handle = tf.extractfile(member)
            if handle is None:
                continue
            try:
                yield json.load(handle)
            except (ValueError, OSError):
                continue


def _output_dir(source: str) -> str:
    """Where analyze writes its results: the dataset dir itself, or the archive's dir."""
    return source if os.path.isdir(source) else (os.path.dirname(source) or ".")


def _pct(part: int, whole: int) -> float:
    return round(100.0 * part / whole, 2) if whole else 0.0


def _reach_class(error: str | None) -> str:
    """Bucket an unavailable image by why it failed, so genuine decay (a reference that
    resolves to nothing) is separated from a bounded/oversized extraction (`too_large`),
    a disk/network artifact (`infra`), an arch/auth issue, or anything else. Only `gone`
    counts toward decay; the rest are alive images we did not (fully) scan."""
    e = (error or "").lower()
    if "too_large" in e or "exceeds" in e:
        return "too_large"
    if "no space" in e or "errno 28" in e or "register layer" in e or "write /" in e:
        return "infra"
    if "no matching" in e or "no child with platform" in e or "platform" in e:
        return "arch"
    if any(s in e for s in ("denied", "unauthorized", "forbidden", "authentication required")):
        return "auth"
    if any(s in e for s in ("not found", "manifest unknown", "manifest_unknown", "name unknown",
                            "name_unknown", "does not exist", "no such", "failed to resolve",
                            "unknown tag")):
        return "gone"
    return "other"


# Filesystem locations associated with operational private-key use. A PEM private-key block
# also appears inside library binaries, test fixtures, package caches, and documentation;
# those are usually example keys, so they are excluded and reuse is measured over
# operational paths only (SSH host keys, system TLS keys, application key files).
_KEY_EXCLUDE_SUBSTR = (
    "test", "example", "sample", "fixture", "/testdata/", "node_modules",
    "/vendor/", "/.npm/", "/.cache/", "/.git/", "/doc/", "/docs/",
)
_KEY_EXCLUDE_SUFFIX = (
    ".md", ".txt", ".rst", ".html", ".htm", ".db", ".sqlite", ".sql", ".json",
    ".yaml", ".yml", ".go", ".js", ".py", ".c", ".h", ".rb", ".so", ".dll", ".dylib",
)
_KEY_LIBRARY_SUBSTR = ("site-packages", "/lib/", "/usr/share/", "/usr/lib",
                       "dist-packages", "/go/", "/perl", "/ruby", "/gem")
_KEY_DEPLOYED_DIRS = ("/opt/", "/srv/", "/var/www", "/app", "/home", "/root", "/usr/local/")


def _is_operational_key(path: str) -> bool:
    p = (path or "").lower()
    if any(t in p for t in _KEY_EXCLUDE_SUBSTR):
        return False
    if p.endswith(_KEY_EXCLUDE_SUFFIX) or ".so." in p or "/bin/" in p or "/sbin/" in p:
        return False
    if "ssh_host_" in p or p.startswith(("/etc/ssl", "/etc/pki", "/etc/tls")):
        return True
    if any(t in p for t in _KEY_LIBRARY_SUBSTR):
        return False
    return p.startswith(_KEY_DEPLOYED_DIRS)


def _is_private_key(key: dict) -> bool:
    """A private key or an SSH host private key (not a .pub / authorized_keys public key)."""
    path = (key.get("path") or "").lower()
    if key.get("kind") == "private":
        return True
    return key.get("kind") == "ssh" and not (path.endswith(".pub") or "authorized_keys" in path)


def aggregate(images: list[dict]) -> tuple[dict, list[dict], list[dict], list]:
    """Reduce per-image records to the census summary. Deterministic and I/O-free (so it is
    testable without disk), over a re-iterable list of records from disk or an archive
    stream; each asset dict is annotated in place with its image `reference`.

    PQC capability is recomputed here from each library's name and version rather than
    read from the record, so a corrected classifier applies to the released dataset
    without re-collecting it.
    """
    ok = [im for im in images if im.get("ok")]

    reach = Counter(_reach_class(im.get("error")) for im in images if not im.get("ok"))
    reach["scanned"] = len(ok)
    genuine_decay = reach.get("gone", 0)
    # Non-resolution rate over every reference with a determinate outcome: scanned, plus
    # those that resolved but fell out of scope, plus those that did not resolve.
    decay_den = len(images)
    decay_lo, decay_hi = wilson_pct(genuine_decay, decay_den)

    all_certs, non_trust_store_certs = [], []
    non_trust_store_keys, all_keys = [], []
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
            c["reference"] = ref
            all_certs.append(c)
            if not c["in_trust_store"]:
                non_trust_store_certs.append(c)
        for k in im.get("keys", []):
            k["reference"] = ref
            all_keys.append(k)
            if not k["in_trust_store"]:
                non_trust_store_keys.append(k)
        for lib in im.get("libraries", []):
            if library_pqc_capable(lib.get("name", ""), lib.get("version", "")):
                pqc_capable_images.add(ref)
        for wc in im.get("weak_configs", []):
            # Count a weak token only if it was recorded in a real crypto config file. The
            # released records were collected before the extractor applied this filter, so
            # re-applying it here keeps /dev/null (NULL), a shell `export` (EXPORT) and the
            # like out of the counts, matching the figures and the paper.
            if is_crypto_config(wc.get("path", "")):
                weak_cfg_tokens[wc["token"].upper()] += 1

    pk_assets = all_certs + all_keys
    qv = sum(1 for a in pk_assets if a["pq_status"] == "quantum-vulnerable")
    pqc = sum(1 for a in pk_assets if a["pq_status"] == "post-quantum")

    # Reuse and batch-GCD run on non-trust-store material only (see module docstring).
    non_trust_store_fpr_to_images = defaultdict(set)
    operational_fpr_to_images = defaultdict(set)
    for im in ok:
        for k in im.get("keys", []):
            if k["in_trust_store"] or not k.get("public_key_sha256"):
                continue
            non_trust_store_fpr_to_images[k["public_key_sha256"]].add(im["reference"])
            if _is_private_key(k) and _is_operational_key(k.get("path", "")):
                operational_fpr_to_images[k["public_key_sha256"]].add(im["reference"])
        for c in im.get("certs", []):
            if not c["in_trust_store"] and c.get("public_key_sha256"):
                non_trust_store_fpr_to_images[c["public_key_sha256"]].add(im["reference"])
    reused = {fpr for fpr, imgs in non_trust_store_fpr_to_images.items() if len(imgs) > 1}
    # Security-relevant subset: private keys in operational paths recurring across images, where a
    # single shipped key compromises every image that carries it.
    reused_operational = {
        fpr for fpr, imgs in operational_fpr_to_images.items() if len(imgs) > 1
    }

    non_trust_store_moduli = []
    for a in non_trust_store_certs + non_trust_store_keys:
        if a.get("rsa_modulus_hex"):
            try:
                non_trust_store_moduli.append(int(a["rsa_modulus_hex"], 16))
            except ValueError:
                pass
    unique_moduli = sorted(set(non_trust_store_moduli))
    if unique_moduli:
        print(f"  running batch-GCD over {len(unique_moduli):,} moduli …", file=sys.stderr)
    factorable = batch_gcd(unique_moduli)

    summary = {
        "images_total": len(images),
        "images_ok": len(ok),
        "images_unavailable": len(images) - len(ok),
        "unavailable_pct": _pct(len(images) - len(ok), len(images)),
        "reachability": dict(reach),
        "genuine_decay": genuine_decay,
        "too_large": reach.get("too_large", 0),
        "decay_denominator": decay_den,
        "decay_pct": _pct(genuine_decay, decay_den),
        "decay_ci95": [decay_lo, decay_hi],
        "public_key_assets": len(pk_assets),
        "quantum_vulnerable": qv,
        "quantum_vulnerable_pct": _pct(qv, len(pk_assets)),
        "post_quantum": pqc,
        "post_quantum_pct": _pct(pqc, len(pk_assets)),
        "certs_total": len(all_certs),
        "certs_non_trust_store": len(non_trust_store_certs),
        "certs_weak_signature": sum(1 for c in all_certs if c["weak_signature"]),
        "certs_non_trust_store_weak_signature": sum(
            1 for c in non_trust_store_certs if c["weak_signature"]
        ),
        "keys_non_trust_store": len(non_trust_store_keys),
        "non_trust_store_key_fingerprints": len(non_trust_store_fpr_to_images),
        "non_trust_store_keys_reused_across_images": len(reused),
        "operational_private_keys_reused": len(reused_operational),
        "non_trust_store_rsa_moduli_unique": len(unique_moduli),
        "factorable_moduli_shared_prime": len(factorable),
        "images_with_pqc_capable_library": len(pqc_capable_images),
        "weak_config_tokens": dict(weak_cfg_tokens.most_common()),
        "tool_divergence_images": len(divergence),
    }
    return summary, all_certs, all_keys, divergence


def analyze(source: str) -> dict:
    """Aggregate a dataset directory or a released ``.tar.gz`` archive; write the results
    next to it (into the directory, or the archive's parent directory)."""
    images = list(iter_records(source))
    out_dir = _output_dir(source)
    summary, all_certs, all_keys, divergence = aggregate(images)
    _write_artifacts(out_dir, all_certs, all_keys, summary, divergence)
    _write_run_manifest(out_dir, images)
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
        cols = ["asset", "reference", "path", "in_trust_store", "key_type", "key_size",
                "pq_status", "weak_key", "signature_hash", "weak_signature",
                "public_key_sha256", "self_signed", "expired"]
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
        f"  unavailable (raw)             : {s['images_unavailable']} ({s['unavailable_pct']}%)",
        f"  unresolved (no latest tag)    : {s['decay_pct']}% (95% CI {s['decay_ci95'][0]}-{s['decay_ci95'][1]}, n={s['decay_denominator']})",
        f"  too-large stratum             : {s['too_large']}",
        f"  reachability                  : {s['reachability']}",
        f"public-key assets catalogued    : {s['public_key_assets']}",
        f"  quantum-vulnerable            : {s['quantum_vulnerable']} ({s['quantum_vulnerable_pct']}%)",
        f"  post-quantum                  : {s['post_quantum']} ({s['post_quantum_pct']}%)",
        f"certificates (non-trust-store/total): {s['certs_non_trust_store']}/{s['certs_total']}",
        f"  weak signature (non-trust-store/total): "
        f"{s['certs_non_trust_store_weak_signature']}/{s['certs_weak_signature']}",
        f"non-trust-store keys            : {s['keys_non_trust_store']}",
        f"  reused across images          : {s['non_trust_store_keys_reused_across_images']}",
        f"  operational private keys reused: {s['operational_private_keys_reused']}",
        f"non-trust-store unique RSA moduli: {s['non_trust_store_rsa_moduli_unique']}",
        f"  factorable (shared prime)     : {s['factorable_moduli_shared_prime']}",
        f"images w/ PQC-capable library   : {s['images_with_pqc_capable_library']}",
        f"weak TLS/SSH config tokens      : {s['weak_config_tokens']}",
        f"images for tool-divergence      : {s['tool_divergence_images']}",
        "=" * 64,
    ]
    return "\n".join(lines)
