# Sustainability (SeloS)

The Sustainable Artifacts seal asks for an artifact that is modular, organized,
intelligible and easy to follow. It states three requirements: minimal code
documentation, minimal code readability, and that evaluators can identify the paper's main
claims inside the artifact. This document answers each requirement for the **code** and for
the **released dataset**, and names the file to open in every case.

## 1. Code documentation

The pipeline is a packaged `src/` layout of **23 Python modules**, one concern each.
**Every module carries a docstring** that states its responsibility and the methodological
decision built into it. Public functions carry type hints. No module exceeds 321 lines and
16 of the 23 are under 100, so any one of them can be read in a sitting.

Two decisions live in a docstring rather than in the authors' heads.
[`schema.py`](../src/cryptocensus/schema.py) records why every asset carries its
provenance: aggregation has to separate the certificate-authority bundle that the base
operating system ships from cryptographic material the image author introduced, because
only the second kind says anything about that image. `ToolObservation` records why only
independent third-party tools are comparable when measuring divergence, since the built-in
extractor is the primary instrument rather than a peer.

[`ARCHITECTURE.md`](ARCHITECTURE.md) maps every component to its module, and documents the
queue semantics, the sampling frame, and the threat model for extraction.

## 2. Code organization and readability

The census is split into stages that never mix, so a reviewer can follow one asset from the
image it came from to the number it lands in.

| Stage | Module | What it decides |
|---|---|---|
| Draw | [`sampling.py`](../src/cryptocensus/sampling.py) | which repositories enter the census |
| Distribute | [`queue.py`](../src/cryptocensus/queue.py), [`coordinator.py`](../src/cryptocensus/coordinator.py), [`worker.py`](../src/cryptocensus/worker.py) | atomic claim and acknowledge, stale requeue; workers hold no state and restart freely |
| Acquire | [`image.py`](../src/cryptocensus/image.py) | pulls each image and flattens its layers into a plain directory tree; images are never executed |
| Extract | [`extractors/`](../src/cryptocensus/extractors/) | one module per evidence source: certificates and keys, installed libraries, secrets, and two inventories of what an image contains (a cryptography bill of materials and a software bill of materials) |
| Classify | [`classify.py`](../src/cryptocensus/classify.py) | `pq_status`, `is_weak_signature_hash`, `is_weak_key`, `library_pqc_capable` |
| Aggregate | [`analyze.py`](../src/cryptocensus/analyze.py) | counts, rates, key reuse, and the confidence interval on each proportion |
| Key analysis | [`batchgcd.py`](../src/cryptocensus/batchgcd.py) | searches the collected RSA keys for pairs that share a prime factor, which exposes the private key of both |

Every measurement decision is a **named function, not a condition buried in a loop**. Four
functions in `classify.py` carry the paper's definitions, and each can be read and
unit-tested without opening the analyzer:

- `pq_status` decides whether an algorithm is quantum-vulnerable or post-quantum.
- `is_weak_signature_hash` flags certificates signed with SHA-1 or MD5. Both have practical
  collision attacks, so an attacker can craft a second certificate carrying the same
  signature, which is why they are unfit for signing.
- `is_weak_key` flags keys too short to resist classical factoring. The 512-bit RSA keys
  the census finds are factorable with ordinary computing resources today, independently of
  any quantum threat.
- `library_pqc_capable` decides whether an installed library supports post-quantum
  algorithms. Capability is kept separate from use throughout: a library that *can* do
  post-quantum work says nothing about whether a post-quantum key was ever generated.

Nothing is hardcoded. **33 `CC_*` environment variables** resolved in
[`config.py`](../src/cryptocensus/config.py) cover endpoints, binaries, queues, size caps,
timeouts and retries. There are no host paths and no embedded credentials.

The non-trivial logic is covered by **13 unit tests** in [`tests/`](../tests/): the
classifier, the batch-GCD pass, the certificate and key parser, and the aggregator. They
need no network and no containers.

## 3. The released dataset

The dataset is published as the `dataset-v1` release (`cryptocensus-dataset.tar.gz`, about
2 GB unpacked) and is checked against `SHA256SUMS` before use. Every file is either a typed
record or a flat table, so nothing requires a custom reader.

| File | Content |
|---|---|
| `records/*.json` | one file per image, the run of record, an `ImageResult` serialized as JSON |
| `run_manifest.csv` | `reference, digest, ok, files_scanned, error`; pins every image to the exact bytes analyzed |
| `summary.json` | every aggregate metric in the paper, one key per number |
| `assets.csv` | one row per certificate or key: `asset, reference, path, in_trust_store, key_type, key_size, pq_status, weak_key, signature_hash, weak_signature, public_key_sha256, self_signed, expired` |
| `tool_divergence.csv` | per-image counts from independent tools, for the cross-check |

The record types are declared as dataclasses in
[`schema.py`](../src/cryptocensus/schema.py): `CertRecord`, `KeyRecord`, `LibraryRecord`,
`WeakConfigRecord`, `ToolObservation` and `ImageResult`. Reading that one 87-line file is
enough to know every field in the dataset and what it means.

Two properties make the data auditable rather than merely available. Every asset keeps its
**provenance**, meaning the image it came from, the path it occupied inside that image, and
whether it sits in the system trust store, so any aggregate can be traced back to the
individual files behind it. And `run_manifest.csv` pins each image by **content digest**,
the hash of the exact image bytes, so a reviewer re-pulls the same image rather than
whatever the `latest` tag points at today.

One caution when reading the reuse figures. A repeated **public** key across images is
common and harmless. What the paper counts as a risk is a repeated **private** key found on
a path where a service would actually load it, because only then does compromising one
image expose the others.

## 4. Where the paper's claims live

Every headline number is produced by `analyze.aggregate` into `summary.json`, or by the
figure aggregator in [`reproduce_figures.py`](../scripts/reproduce_figures.py). Each is then
compared against the published value by [`check_claim.py`](../scripts/check_claim.py), whose
`EXPECTED` dictionary is the single place where the paper's numbers are written down.

| Paper number | Key | Computed in |
|---|---|---|
| 11,962 images scanned | `images_ok` | `analyze.aggregate` |
| 4,211,380 public-key assets | `public_key_assets` | `analyze.aggregate` |
| 100% quantum-vulnerable, 0 post-quantum | `quantum_vulnerable_pct`, `post_quantum` | `analyze.aggregate`, labelled by `classify.pq_status` |
| 801 images with a post-quantum capable library (6.7%) | `images_with_pqc_capable_library` | `analyze.aggregate`, decided by `classify.library_pqc_capable` |
| 518,668 certificates outside trust stores | `certs_non_trust_store` | `analyze.aggregate` |
| 43% signed with SHA-1 or MD5 | `certs_non_trust_store_weak_signature` | `analyze.aggregate`, decided by `classify.is_weak_signature_hash` |
| 40,720 RSA keys under 2048-bit, 5,552 of them 512-bit | `rsa_sub2048`, `rsa_512` | `reproduce_figures.py`, threshold from `classify.is_weak_key` |
| 178,455 keys outside trust stores | `keys_non_trust_store` | `analyze.aggregate` |
| 7,141 distinct key fingerprints, 2,412 seen in more than one image | `non_trust_store_key_fingerprints`, `non_trust_store_keys_reused_across_images` | `analyze.aggregate` |
| 37,077 private keys on operational paths | `location_total` | `reproduce_figures.py` |
| 36 of those private keys repeated across images | `operational_private_keys_reused` | `analyze.aggregate`, paths decided by `_is_operational_key` and `_is_private_key` |
| 6,116 distinct RSA moduli, 4 sharing a prime factor | `non_trust_store_rsa_moduli_unique`, `factorable_moduli_shared_prime` | `batchgcd.batch_gcd` |
| 34.7% of repositories with no pullable `latest` (95% CI 34.1 to 35.4) | `decay_pct`, `decay_ci95` | `analyze.aggregate`, classified by `_reach_class`; interval from `stats.wilson_pct`, which gives a confidence interval for a proportion |

To follow one number from end to end, read it in this order: the extractor that produced
the evidence ([`extractors/certs_keys.py`](../src/cryptocensus/extractors/certs_keys.py)),
the classifier that labelled it ([`classify.py`](../src/cryptocensus/classify.py)), the
aggregator that counted it ([`analyze.py`](../src/cryptocensus/analyze.py)), and the rows of
`assets.csv` it was counted from.
