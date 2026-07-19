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

![CryptoCensus pipeline: a uniform-random draw from the sampling frame, resolution of each reference to a content digest, a pull and flattening of each image, a calibrated extraction of its cryptographic material, and classification into population estimates.](docs/pipeline.png)

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
| **Minimum** | x86-64. Minimal test: 2 cores · 4 GB RAM. Claim #1 (`run_claim`): ~6.7 GB peak RAM measured (loads all records for batch-GCD), so **≥ 8 GB RAM** recommended; ~2 GB disk for the dataset archive |
| **OS** | Linux x86-64 (tested on Ubuntu 24.04 / Debian 12) |
| **Software** | Docker ≥ 24 (tested on 27.5; Compose v2 optional). Everything else — Python 3.12, `uv`, crane, the analyzer — runs inside the image; nothing is installed on the host. |
| **Host tools** | `curl`, `tar`, `sha256sum` (coreutils) for the one-time dataset download; `gh` optional (with a `curl` fallback) |
| **Network** | Docker Hub access for image pulls; anonymous pulls are rate-limited, a Docker Hub login raises the limit for the full census (not needed for the minimal test) |

## Dependencies

All third-party tools are pinned in the `Dockerfile` and run inside the image. On the host
the reproduction scripts need only Docker plus `curl`/`tar`/`sha256sum` for the one-time
download — nothing else is installed on the host.

| Tool | Version | Role |
|------|---------|------|
| crane (go-containerregistry) | 0.21.6 | daemonless pull + flatten |
| CBOM-Lens (OmniTrustILM) | 1.0.0 | independent CycloneDX-CBOM extractor (cross-check) |
| gitleaks | 8.30.1 | private-key recall |
| syft | 1.44.0 | crypto-library inventory (optional) |
| Python `cryptography` | ≥41 | certificate/key parsing (built-in instrument) |
| Redis | 7 | distributed task queue |
| uv (Astral) | 0.11.17 | dependency install during the image build |

## Security concerns

The artifact is **safe to run**. Sampled images are **pulled and flattened, never
executed**: `crane` exports the filesystem layers as data, so no untrusted code runs.
Extraction reads files inside an unpacked root filesystem in a scratch directory that is
removed after each image. No credentials are required for the minimal test; for the full
census a Docker Hub token may be supplied via the standard `~/.docker/config.json` and is
only used to authenticate pulls. The pipeline opens no inbound ports other than the Redis
queue you start.

## Installation

Everything runs through one Docker image — this is the only required step:

```bash
git clone https://github.com/CristhianKapelinski/cryptocensus && cd cryptocensus
docker build -t cryptocensus:latest .        # single pinned image; all tools are inside it
```

## Minimal test (~10 minutes on the first run)

```bash
bash scripts/minimal_test.sh   # end-to-end (Docker): build → seed → work → collect → analyze
```

[`minimal_test.sh`](scripts/minimal_test.sh) censuses the five images in
[`sample-images.txt`](config/sample-images.txt) and prints the report. What to look for:
all **5 images scanned**, over a thousand public-key assets, and — the invariant —
**100% quantum-vulnerable, 0% post-quantum**, with a few images shipping a PQC-capable
library and CBOM-Lens running alongside the built-in extractor on every image
(`images for tool-divergence: 5`). Exact counts vary as the sample's tags re-resolve.

## Experiments

We designate **one main claim** for reproduction — the paper's central result. One command
reproduces it from the released dataset and asserts every paper number.

### Claim #1 — the deployed cryptography has not begun its post-quantum migration

Paper: Abstract, Table 2, Section *Post-quantum readiness*.

```bash
scripts/run_claim.sh
```

Downloads and verifies `dataset-v1` (if absent), re-runs the analyzer, regenerates the three
figures, and checks every headline number against the paper. **≈ 13 minutes, ~6.7 GB peak
RAM** measured on an AMD Ryzen 5 8600G (6 cores/12 threads), download excluded; single-threaded
(the analyzer loads all records for the batch-GCD pass over 6,116 moduli, which dominates both
time and memory), no GPU. Numbers reproduce **exactly** — the pipeline uses no randomness and
`dataset/run_manifest.csv` pins every image by digest.

**Expected result** — one `OK` per metric, ending in `RESULT: OK`:

```
  Claim: deployed cryptographic posture is not migrating
  PQC-capable images  : 801 / 11,962  (6.7%)
  Post-quantum assets : 0 / 4,211,380  (100% quantum-vulnerable)
  Weak-signature certs: 43.0%
  RSA keys < 2048-bit : 40,720  (5,552 at 512-bit)
  Reused fingerprints : 2,412 of 7,141
  RSA moduli / factorable (batch-GCD): 6,116 / 4
  Unresolved (no latest tag): 34.7%
  ─────────────────────────────────────────────
  images_ok  11,962 | public_key_assets  4,211,380 | pqc_capable_images  801
  certs_own  518,668 | weak_sig_pct  43 | rsa_sub2048  40,720 | ... every row OK
  RESULT: OK  - matches Table 2 of the paper
```

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
