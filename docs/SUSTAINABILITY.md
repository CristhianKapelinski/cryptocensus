# Sustainability (SeloS)

The Sustainable Artifacts seal asks for code that is modular, organized, intelligible and
easy to follow. It states three requirements: minimal code documentation, minimal code
readability, and that evaluators can identify the paper's main claims inside the artifact.
This document answers each one for the **code** and for the **released dataset**, naming the
files to open.

## 1. Code documentation

The pipeline is a packaged `src/` layout of **23 Python modules**, one concern each. **Every
module carries a docstring** stating its responsibility and the methodological decision baked
into it; public functions carry type hints. No module exceeds 321 lines and 16 of the 23 are
under 100, so any one of them can be read in a sitting.

Two examples of decisions that live in a docstring rather than in tribal knowledge:
[`schema.py`](../src/cryptocensus/schema.py) explains why every asset carries its provenance
(so aggregation can separate the OS trust bundle from material the image author introduced),
and `ToolObservation` explains why only independent third-party tools are comparable for
divergence.

[`ARCHITECTURE.md`](ARCHITECTURE.md) maps every component to its module, and documents the
queue semantics, the sampling frame, and the threat model for extraction.

## 2. Code organization and readability

The census is separated into stages that never mix, so a reviewer can follow one asset from
the image it came from to the number it lands in:

| Stage | Module | What it decides |
|---|---|---|
| Draw | [`sampling.py`](../src/cryptocensus/sampling.py) | which repositories enter the census |
| Distribute | [`queue.py`](../src/cryptocensus/queue.py), [`coordinator.py`](../src/cryptocensus/coordinator.py), [`worker.py`](../src/cryptocensus/worker.py) | atomic claim/ack, stale requeue; workers are stateless |
| Acquire | [`image.py`](../src/cryptocensus/image.py) | pull and flatten; images are never executed |
| Extract | [`extractors/`](../src/cryptocensus/extractors/) | one module per evidence source (certs/keys, libraries, secrets, CBOM, SBOM) |
| Classify | [`classify.py`](../src/cryptocensus/classify.py) | `pq_status`, `is_weak_signature_hash`, `is_weak_key`, `library_pqc_capable` |
| Aggregate | [`analyze.py`](../src/cryptocensus/analyze.py) | counts, rates, reuse, the Wilson interval |
| Key analysis | [`batchgcd.py`](../src/cryptocensus/batchgcd.py) | shared-prime detection over the RSA moduli |

Each measurement decision is a **named function, not an inline condition**. Whether a key is
weak, whether a certificate signature is weak, whether an algorithm is post-quantum, and
whether a library is PQC-capable are four functions in `classify.py` that can be read and
unit-tested without touching the analyzer. This is what makes the paper's definitions
auditable.

Nothing is hardcoded: **33 `CC_*` environment variables** resolved in
[`config.py`](../src/cryptocensus/config.py) cover endpoints, binaries, queues, size caps,
timeouts and retries. No host paths and no embedded credentials.

The non-trivial logic is covered by **13 unit tests** in [`tests/`](../tests/) — the
classifier, the batch-GCD, the certificate/key parser and the aggregator — which run with no
network and no containers.

## 3. The released dataset

The dataset is published as the `dataset-v1` release
(`cryptocensus-dataset.tar.gz`, ~2 GB unpacked) and is checksum-verified against `SHA256SUMS`
before use. It is self-describing: every file is either a typed record or a flat table, with
no bespoke binary format.

| File | Content |
|---|---|
| `records/*.json` | one file per image — the run of record, an `ImageResult` serialized as JSON |
| `run_manifest.csv` | `reference, digest, ok, files_scanned, error` — pins every image to the exact bytes analyzed |
| `summary.json` | every aggregate metric in the paper, one key per number |
| `assets.csv` | one row per certificate or key: `asset, reference, path, in_trust_store, key_type, key_size, pq_status, weak_key, signature_hash, weak_signature, public_key_sha256, self_signed, expired` |
| `tool_divergence.csv` | per-image counts from independent tools, for the cross-check |

The record types are declared as dataclasses in
[`schema.py`](../src/cryptocensus/schema.py): `CertRecord`, `KeyRecord`, `LibraryRecord`,
`WeakConfigRecord`, `ToolObservation` and `ImageResult`. Reading that one 87-line file is
enough to know every field in the dataset and its meaning.

Two properties make the data auditable rather than merely available. Every asset keeps its
**provenance** — the image reference, the path inside the image, and whether it sits in the
system trust store — so any aggregate can be traced back to the individual files behind it.
And `run_manifest.csv` pins each image by **content digest**, so a reviewer can re-pull the
exact same bytes rather than whatever `latest` points at today.

## 4. Where the paper's claims live

Every headline number is produced by `analyze.aggregate` into `summary.json`, or by the
figure aggregator in [`reproduce_figures.py`](../scripts/reproduce_figures.py), and is then
asserted against the published value by [`check_claim.py`](../scripts/check_claim.py), whose
`EXPECTED` dictionary is the one place where the paper's numbers are written down.

| Paper number | Key | Computed in |
|---|---|---|
| 11,962 images scanned | `images_ok` | `analyze.aggregate` |
| 4,211,380 public-key assets | `public_key_assets` | `analyze.aggregate` |
| 100% quantum-vulnerable, 0 post-quantum | `quantum_vulnerable_pct`, `post_quantum` | `analyze.aggregate`, labelled by `classify.pq_status` |
| 801 PQC-capable images (6.7%) | `images_with_pqc_capable_library` | `analyze.aggregate`, decided by `classify.library_pqc_capable` |
| 518,668 certificates outside trust stores | `certs_non_trust_store` | `analyze.aggregate` |
| 43% weak signatures | `certs_non_trust_store_weak_signature` | `analyze.aggregate`, decided by `classify.is_weak_signature_hash` |
| 40,720 RSA keys < 2048-bit (5,552 at 512-bit) | `rsa_sub2048`, `rsa_512` | `reproduce_figures.py`, threshold from `classify.is_weak_key` |
| 178,455 keys outside trust stores | `keys_non_trust_store` | `analyze.aggregate` |
| 7,141 fingerprints, 2,412 reused | `non_trust_store_key_fingerprints`, `non_trust_store_keys_reused_across_images` | `analyze.aggregate` |
| 37,077 operational private keys | `location_total` | `reproduce_figures.py` |
| 36 reused operational private keys | `operational_private_keys_reused` | `analyze.aggregate`, paths decided by `_is_operational_key` and `_is_private_key` |
| 6,116 unique RSA moduli, 4 factorable | `non_trust_store_rsa_moduli_unique`, `factorable_moduli_shared_prime` | `batchgcd.batch_gcd` |
| 34.7% unresolved `latest` (95% CI 34.1–35.4%) | `decay_pct`, `decay_ci95` | `analyze.aggregate`, classified by `_reach_class`, interval from `stats.wilson_pct` |

To follow one number end to end, read it in this order: the extractor that produced the
evidence ([`extractors/certs_keys.py`](../src/cryptocensus/extractors/certs_keys.py)), the
classifier that labelled it ([`classify.py`](../src/cryptocensus/classify.py)), the aggregator
that counted it ([`analyze.py`](../src/cryptocensus/analyze.py)), and the row of `assets.csv`
it came from.
