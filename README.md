# CryptoCensus

**A reproducible, distributed census of the cryptographic posture and post-quantum
readiness of public container images.**

This repository is the research artifact for the paper *"CryptoCensus: Cryptographic
Posture and Post-Quantum Readiness of Docker Hub"*. It pulls a
uniform-random sample of Docker Hub images pinned by content digest, extracts the
certificates, keys, cryptographic libraries, and weak TLS/SSH configuration each one
ships, and reports how much of that material is weak, expired, reused, or
**quantum-vulnerable (RSA/ECC) versus post-quantum ready** (NIST FIPS 203/204/205;
IR 8547). Across the measured sample of **11,962 images and 4,211,380 public-key
assets, 100% are quantum-vulnerable and 0% are post-quantum.** The artifact reproduces
every quantitative claim in the paper from the released dataset.

> **Paper:** *CryptoCensus: Cryptographic Posture and Post-Quantum Readiness of Docker Hub*, SBSeg 2026 (WTICG).

This README is the single self-contained guide a reviewer needs; it follows the SBC
artifact-evaluation checklist. The files under `docs/` are complementary.

## Quick start for reviewers (copy-paste, runs everything)

Two commands confirm the artifact end to end; each is self-contained, builds what it
needs, and prints its result. Total **≈ 17 minutes on a laptop** (no GPU).

```bash
git clone https://github.com/CristhianKapelinski/cryptocensus && cd cryptocensus
bash scripts/minimal_test.sh    # SeloF: builds image + runs the full pipeline on 5 images         (~5 min)
bash scripts/run_claim.sh       # SeloR: downloads+verifies the dataset, reproduces every number  (~12 min)
```

`run_claim.sh` asserts every paper number against the reproduced value and ends with the
block below (it prints one `OK` row per metric in between); **the last line must be `RESULT: OK`**:

```
  Claim: deployed cryptographic posture is not migrating
  PQC-capable images  : 801 / 11,962  (6.7%)
  Post-quantum assets : 0 / 4,211,380  (100% quantum-vulnerable)
  Weak-signature certs: 43.0%  |  RSA < 2048-bit: 40,720 (5,552 at 512-bit)
  Reused fingerprints : 2,412 of 7,141  |  deployed private keys: 36
  Factorable moduli   : 4 of 6,116  |  Unresolved (decay): 36.7%
  RESULT: OK  - matches Table 2 of the paper
```

The faster `scripts/reproduce.sh` (analyzer only, ~6 min) regenerates `summary.json`
without the figures or the assert block, if you only want the raw numbers.

Optional unit tests, no Docker (~1 min): `uv sync --extra dev && uv run pytest`.

### Two reproduction modes

- **Mode A, from the collected data (fast, ~6 min):** `scripts/reproduce.sh` downloads the
  released digest-pinned dataset, verifies its `SHA256SUMS`, and re-runs the deterministic
  analyzer to regenerate `summary.json` (the numbers in the paper). `scripts/run_claim.sh`
  additionally regenerates the figures and asserts every number (~12 min).
- **Mode B, from scratch (hours):** `scripts/reproduce_from_scratch.sh` re-pulls every image
  in the published sampling frame by content digest, re-extracts its cryptographic material,
  and re-runs the analysis, regenerating the dataset rather than trusting the released one.
  Network-bound; authenticated Docker Hub pulls recommended. Use `config/sample-images.txt`
  for a fast smoke run, `config/sample-20000.txt` for the full frame.

## README structure

```
README.md            this document (artifact-evaluation checklist)
Dockerfile           single pinned image with all third-party tools
docker-compose.yml   single-host stack: redis + workers + tools
src/cryptocensus/    Python package (sampler, queue, extractors, analyzer, CLI)
config/              sampling frames: sample-images.txt (minimal), sample-20000.txt (full)
scripts/             minimal_test.sh, reproduce.sh (mode A), reproduce_from_scratch.sh (mode B), deploy_fleet.sh
docs/                ARCHITECTURE.md (design, sampling frame, full config reference)
tests/               unit tests (no Docker, no network)
LICENSE              MIT
```

Workers are stateless and **daemonless**: images are pulled and flattened with `crane`
and never executed. The only cross-machine dependency is a reachable Redis queue;
results are pushed back and merged by a collector into `dataset/`.

## Badges claimed (Selos)

- **Available (SeloD):** all source, the pinned `Dockerfile`, the sampling frames, and
  the documentation are in this public repository under an open license.
- **Functional (SeloF):** unit tests plus an end-to-end minimal test build and run the
  full pipeline (see *Minimal test*).
- **Sustainable (SeloS):** the code is a modular `src/` package (one module per concern:
  sampling, queue, transport, extractors, analysis), fully environment-configured with
  no hardcoded paths or hosts, and documented in `docs/ARCHITECTURE.md`.
- **Reproducible (SeloR):** `scripts/reproduce.sh` regenerates the paper's headline
  numbers from the released digest-pinned dataset, and `run_manifest.csv` lets anyone
  re-pull the exact images that were measured (see *Experiments*).

## Basic information (environment)

- Linux x86-64; **Docker ≥ 24** (Docker Compose v2 optional); tested on Docker 27.5.
- Host tools: `curl`, `tar`, `sha256sum` (coreutils) to fetch and verify the dataset;
  `python3 ≥ 3.11` on the host for `run_claim.sh` (figure generation and the assert block).
  `gh` is used to fetch the release if present, with a `curl` fallback.
- No GPU. The minimal test runs on any laptop (2 cores, 4 GB RAM, ~2 GB disk).
- Network access to Docker Hub to pull the base image, the tooling, and the sampled
  images. Anonymous pulls are rate-limited; a Docker Hub login raises the limit for the
  full census (not needed for the minimal test).
- Python: the container ships **3.12**; the package requires **≥ 3.11** and is needed on
  the host only for the unit tests, via [uv](https://docs.astral.sh/uv/) (no Docker required).

## Dependencies

All third-party tools that run inside the pipeline are pinned in the `Dockerfile`. On the
host, the reproduction scripts need only Docker, `curl`/`tar`/`sha256sum`, and `python3`
(plus `uv` for the unit tests) — all listed under *Basic information* above.

| Tool | Version | Role |
|------|---------|------|
| crane (go-containerregistry) | 0.21.6 | daemonless pull + flatten |
| CBOM-Lens (OmniTrustILM) | 1.0.0 | independent CycloneDX-CBOM extractor (cross-check) |
| gitleaks | 8.30.1 | private-key recall |
| syft | 1.44.0 | crypto-library inventory (optional) |
| Python `cryptography` | ≥41 | certificate/key parsing (built-in instrument) |
| Redis | 7 | distributed task queue |
| uv (Astral) | 0.11.17 | dependency management / unit tests |

## Security concerns

The artifact is **safe to run**. Sampled images are **pulled and flattened, never
executed**: `crane` exports the filesystem layers as data, so no untrusted code runs.
Extraction reads files inside an unpacked root filesystem in a scratch directory that is
removed after each image. No credentials are required for the minimal test; for the full
census a Docker Hub token may be supplied via the standard `~/.docker/config.json` and is
only used to authenticate pulls. The pipeline opens no inbound ports other than the Redis
queue you start.

## Installation

```bash
git clone https://github.com/CristhianKapelinski/cryptocensus && cd cryptocensus
docker build -t cryptocensus:latest .        # builds the single pinned image
```

For the unit tests (host, no Docker):

```bash
uv sync --extra dev
```

## Minimal test (≈5 minutes)

Two independent checks; either confirms the artifact is functional.

```bash
uv run pytest                # unit tests: classifier, batch-GCD, extractor (no network)
bash scripts/minimal_test.sh # end-to-end: build → seed → work → collect → analyze
```

`scripts/minimal_test.sh` starts Redis and one worker, censuses the five images in
`config/sample-images.txt`, and writes `dataset/summary.json`, `dataset/assets.csv`, and
per-image CBOMs under `dataset/cbom/`, then prints the aggregated report. Expected
qualitative result on this tiny frame: hundreds of public-key assets, **100%
quantum-vulnerable and 0% post-quantum**, SHA-1 signatures present, most images shipping
a PQC-*capable* library while PQC *usage* is 0%, and the built-in extractor's certificate
count agreeing with CBOM-Lens (the instrument calibration check).

## Experiments (reproducing the paper's main claim)

Per the SBC guidance, we designate **one main claim** for reproduction. It is the
paper's central result and the cheapest to verify. A single command reproduces it, along
with every headline number and all three figures, directly from the released dataset:

```bash
scripts/run_claim.sh            # fetches+verifies dataset-v1 if absent, then reproduces
```

It re-runs the analyzer, regenerates the figures (no figure constant is hardcoded; each is
computed from `dataset/records/`), and asserts every paper number against the reproduced
value, printing an `OK`/`FAIL` block. On this host the full run (download excluded) takes
about 10-12 minutes; the analyzer alone is ~5-6 minutes (dominated by the batch-GCD pass
over 6,116 moduli).

### Claim #1 (central result)

Over the uniform-random sample of Docker Hub images (11,962 images, 4,211,380 public-key
assets), **100% of public-key assets are quantum-vulnerable and 0% are post-quantum**,
while about one image in five already ships a PQC-*capable* library it never uses (paper
Abstract; Section "Post-quantum readiness"; Figure "Own cryptographic material").

**Reproduce (from the released dataset, single host, no special hardware):**

```bash
# fetch the released dataset/ (digest-pinned per-image records), then:
scripts/reproduce.sh dataset
```

- **Resources / time:** 1 core, < 2 GB RAM, **≈ 6 minutes** (the batch-GCD pass over 6,116
  moduli dominates). No GPU. Network is used only once, to download the dataset; the
  analysis itself runs fully offline on the local files.
- **Expected output:** `dataset/summary.json` shows `quantum_vulnerable_pct: 100.0`,
  `post_quantum_pct: 0.0`, and `images_with_pqc_capable_library` > 0. The same run writes
  `dataset/assets.csv` (one row per asset), from which the paper's figure and confidence
  intervals are recomputed.
- **Determinism:** extraction is deterministic given an image digest and the pipeline
  uses **no randomness**, so the numbers reproduce **exactly** (not within a tolerance).
  `dataset/run_manifest.csv` pins every `reference -> digest`, so even re-pulling the
  images yields byte-identical inputs.

`scripts/check_claim.py` gates every headline number: the PQC-capable count (801, recomputed
from library versions), weak signatures (43%), sub-2048-bit RSA (40,720), key reuse (2,412
reused of 7,141 own fingerprints; 36 deployed private keys), batch-GCD (4 of 6,116 moduli),
and decay (36.7%).
The headline totals are fields of `dataset/summary.json`; the figure sub-breakdowns are
recomputed from `dataset/records/` by `scripts/reproduce_figures.py`.

### Optional: re-run the full census end to end

Not required to verify Claim #1 (the released dataset does that in minutes). To rebuild
the dataset from scratch: use the full uniform-random frame `config/sample-20000.txt`
(fixed checksum), `docker compose up -d --build redis worker` scaled with
`--scale worker=N` (or `cryptocensus work` on several hosts sharing one `CC_REDIS_URL`),
`seed`, then `collect` and `scripts/reproduce.sh dataset`; `cryptocensus requeue-stale`
recovers a crashed worker's in-flight tasks. Our run used commodity x86-64 hosts
(8-core Intel i7-9700, 32 GB RAM, Debian/Ubuntu); wall-clock scales with worker count and
Docker Hub pull bandwidth.

All behaviour is environment-driven and nothing is hardcoded; the full configuration
reference (`CC_*` knobs), the sampling-frame construction, and the measurement's
limitations (it measures *deployed* cryptographic material and treats PQC capability as a
version signal, not proof of runtime use) are documented in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## License

MIT — see [LICENSE](LICENSE).
