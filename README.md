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

## README structure

| Section | Description |
|---|---|
| Seals considered | Quality seals targeted by this artifact |
| Basic information | Hardware, OS, and software environment |
| Dependencies | Required packages and external tools |
| Security concerns | Risks and mitigations for evaluators |
| Installation | Step-by-step local setup |
| Minimal test | Quick functional verification (~5 min) |
| Experiments | Reproduction of the paper's main claim |
| License | Licensing information |

## Seals considered

The seals considered are **Available (SeloD)**, **Functional (SeloF)**, **Sustainable
(SeloS)**, and **Reproducible (SeloR)**.

- **Available (SeloD):** all source, the pinned [`Dockerfile`](Dockerfile), the sampling frames, and the docs are in this public repo under an open license.
- **Functional (SeloF):** unit tests plus [`scripts/minimal_test.sh`](scripts/minimal_test.sh) build and run the full pipeline end to end.
- **Sustainable (SeloS):** a modular [`src/`](src/cryptocensus/) package, one module per concern, fully env-configured with no hardcoded paths, documented in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).
- **Reproducible (SeloR):** [`scripts/run_claim.sh`](scripts/run_claim.sh) regenerates and asserts every headline number from the released dataset; [`scripts/reduced_census.sh`](scripts/reduced_census.sh) re-runs the live pipeline at small scale.

## Basic information (environment)

| | |
|---|---|
| **Hardware (paper census)** | commodity x86-64 hosts (8-core Intel i7-9700 · 32 GB RAM · Debian/Ubuntu) |
| **Minimum (minimal test / Claim #1)** | x86-64 · 2 cores · 4 GB RAM · ~2 GB disk |
| **OS** | Linux x86-64 (tested on Ubuntu 24.04 / Debian 12) |
| **Software** | Docker ≥ 24 (tested on 27.5; Compose v2 optional) · Python ≥ 3.11 on the host · [`uv`](https://astral.sh/uv) (the container ships Python 3.12) |
| **Host tools** | `curl`, `tar`, `sha256sum` (coreutils); `gh` optional (with a `curl` fallback) |
| **Network** | Docker Hub access for image pulls; anonymous pulls are rate-limited, a Docker Hub login raises the limit for the full census (not needed for the minimal test) |

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
# 1. Clone the repository
git clone https://github.com/CristhianKapelinski/cryptocensus && cd cryptocensus

# 2. Install uv (if not already installed) — used for the unit tests and figure rendering
curl -LsSf https://astral.sh/uv/install.sh | sh

# 3. Build the single pinned image
docker build -t cryptocensus:latest .

# 4. (host, for the unit tests) install Python dependencies
uv sync --extra dev
```

## Minimal test (≈5 minutes)

Two independent checks; either confirms the artifact is functional.

```bash
uv run pytest                # unit tests: classifier, batch-GCD, extractor (no network)
bash scripts/minimal_test.sh # end-to-end: build → seed → work → collect → analyze
```

[`minimal_test.sh`](scripts/minimal_test.sh) censuses the five images in
[`sample-images.txt`](config/sample-images.txt) and prints the report. Expected on this
tiny frame: hundreds of public-key assets, **100% quantum-vulnerable and 0% post-quantum**,
SHA-1 signatures present, and the built-in extractor's certificate count agreeing with
CBOM-Lens.

## Experiments (reproducing the paper's main claim)

Per the SBC guidance, we designate **one main claim** for reproduction. It is the
paper's central result and the cheapest to verify. A single command reproduces it, along
with every headline number and all three figures, directly from the released dataset:

```bash
scripts/run_claim.sh            # fetches+verifies dataset-v1 if absent, then reproduces
```

It re-runs the analyzer, regenerates the figures (no figure constant is hardcoded; each is
computed from `dataset/records/`), and asserts every paper number against the reproduced
value. On this host the full run (download excluded) takes about 10-12 minutes; the
analyzer alone is ~5-6 minutes (dominated by the batch-GCD pass over 6,116 moduli).

It prints one `OK` row per metric and this summary; **every row must read `OK` and it must
print `RESULT: OK`**:

```
  Claim: deployed cryptographic posture is not migrating
  PQC-capable images  : 801 / 11,962  (6.7%)
  Post-quantum assets : 0 / 4,211,380  (100% quantum-vulnerable)
  Weak-signature certs: 43.0%
  RSA keys < 2048-bit : 40,720  (5,552 at 512-bit)
  Reused fingerprints : 2,412 of 7,141
  RSA moduli / factorable (batch-GCD): 6,116 / 4
  Unresolved (no latest tag): 34.7%
  RESULT: OK  - matches Table 2 of the paper
```

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
  uses **no randomness**, so the released dataset's numbers reproduce **exactly** (not
  within a tolerance). `dataset/run_manifest.csv` pins every `reference -> digest`, so even
  re-pulling the images yields byte-identical inputs. (The only clock-dependent field is a
  certificate's `expired` flag, evaluated at scan time; it does not affect any gated number.)

`scripts/check_claim.py` gates every headline number: the PQC-capable count (801, recomputed
from library versions), weak signatures (43%), sub-2048-bit RSA (40,720), key reuse (2,412
reused of 7,141 own fingerprints; 36 deployed private keys), batch-GCD (4 of 6,116 moduli),
and unresolved references (34.7%, no `latest` tag).
The headline totals are fields of `dataset/summary.json`; the figure sub-breakdowns are
recomputed from `dataset/records/` by `scripts/reproduce_figures.py`.

### Optional: re-run the census live

Not required for Claim #1. [`scripts/reduced_census.sh`](scripts/reduced_census.sh) runs
the whole pipeline live on a single host, no Docker Hub login, over a few repositories
drawn from the frame (default 10, configurable):

```bash
bash scripts/reduced_census.sh        # 10 repositories
bash scripts/reduced_census.sh 25     # N repositories
```

It starts Redis and one worker, seeds the draw, pulls and flattens each image with
`crane`, extracts, and analyzes into `dataset-reduced/summary.json`.

To rebuild the full 20,000-reference dataset, [`scripts/reproduce_from_scratch.sh`](scripts/reproduce_from_scratch.sh)
re-pulls every image in [`sample-20000.txt`](config/sample-20000.txt) by digest. On a
single host this is bound by Docker Hub's pull limit (~200 images per 6 h per IP), so the
full frame takes roughly `20,000 / 200 * 6 h ≈ 600 h` (about **three to four weeks**); the
original census parallelized the queue across several hosts (distinct IPs) to finish
sooner. This is why the released dataset (Mode A above) is the canonical reproduction and
`reduced_census.sh` exists to exercise the live pipeline in minutes.

All behaviour is `CC_*`-configured; the full config reference, the sampling-frame
construction, and the measurement's limitations are in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## License

MIT — see [LICENSE](LICENSE).
