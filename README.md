# CryptoCensus

A reproducible, distributed census of the **cryptographic posture** and
**post-quantum readiness** of public container images.

Every container starts from an image that ships certificates, keys, cryptographic
libraries, and TLS/SSH configuration. CryptoCensus pulls images at scale, extracts
that cryptographic material with several independent tools, and reports — with
confidence-interval-ready per-asset data — how much of it is weak, expired, reused,
or **quantum-vulnerable (RSA/ECC) versus post-quantum ready**.

The headline question: *what fraction of the cryptography actually shipped inside the
container ecosystem will be broken by a quantum computer, and is anything ready for
the migration mandated by NIST (FIPS 203/204/205; IR 8547; CSWP 39)?*

## What it measures

For each image, on a single filesystem pass plus independent tool runs:

- **Algorithm strength** — MD5/SHA-1 signatures, RSA &lt; 2048, weak EC/DSA, weak
  cipher tokens (RC4/DES/3DES/NULL/SSLv3) in TLS/SSH configs.
- **Certificates & keys** — validity, self-signed, CA flag, key type/size; the system
  **CA trust bundle is separated from the image author's own material**.
- **Post-quantum status** — each public-key asset is classified
  `quantum-vulnerable | post-quantum`; libraries get a version-based PQC-capability
  flag (the QED-Lite fingerprinting idea), so *capability* and *usage* are distinguished.
- **Key reuse & weak keys** — identical public keys reused across images, and
  shared-prime factorable RSA moduli via batch-GCD — computed on **own** keys only.
- **Inter-tool divergence** — independent third-party extractors are compared on the
  same images (NIST SP 1800-38: "no single tool finds everything").

## Architecture

```
            ┌─────────────┐   seed    ┌──────────────────────────┐
            │ coordinator │ ────────▶ │        Redis queue        │
            └─────────────┘           │ tasks → processing → done │
                                      └──────────┬───────────────┘
                claim (BLMOVE, atomic)           │ results list
        ┌───────────────┬───────────────┬────────┴────────┐
        ▼               ▼               ▼                  ▼
   ┌─────────┐     ┌─────────┐     ┌─────────┐        ┌───────────┐
   │ worker  │ ... │ worker  │ ... │ worker  │        │ collector │──▶ dataset/
   │ (host A)│     │ (host B)│     │ (host C)│        │ + analyze │     records/
   └─────────┘     └─────────┘     └─────────┘        └───────────┘     cbom/
   crane pull → flatten → extractors → CBOM 1.7                         summary.json
```

Workers are stateless and daemonless (images are pulled and flattened with `crane`,
never executed). The only cross-machine dependency is a reachable Redis; add workers on
any host by pointing `CC_REDIS_URL` at it. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Quickstart (single host, Docker Compose)

```bash
docker compose up -d --build redis worker          # Redis + 2 workers
docker compose run --rm tools seed    --file /frame/sample-images.txt
# workers write per-image bundles into ./dataset as they process; when it drains:
docker compose run --rm tools analyze --dataset /data
cat dataset/summary.json
```

Without Compose, `scripts/minimal_test.sh` runs the same flow end to end with plain
`docker run` on a user-defined network.

## Multi-machine fleet

1. Start Redis on a coordinator host (`redis://COORD:6379/0`), reachable by the fleet.
2. On every worker host: `docker run cryptocensus work` with
   `CC_REDIS_URL=redis://COORD:6379/0`. Workers self-balance via atomic claims.
3. Seed once from the coordinator; collect and analyze when the queue drains.
4. Recover a crashed worker's in-flight tasks with `cryptocensus requeue-stale`.

## Outputs (the released dataset)

- `dataset/records/<ref>.json` — full structured per-image record (includes the
  resolved image digest).
- `dataset/cbom/<ref>.cbom.json` — CycloneDX 1.7 CBOM per image.
- `dataset/summary.json`, `dataset/assets.csv`, `dataset/tool_divergence.csv`.
- `dataset/run_manifest.csv` — every image pinned to the `sha256` digest that was
  scanned, for 100% reproducible re-pulls.

## Reproducibility

Each image's tag is resolved to an immutable digest *before* scanning, and the image
is pulled by digest (`repo@sha256:...`), so the recorded digest is exactly the bytes
that were measured. `run_manifest.csv` records every `reference -> digest`, which lets
anyone regenerate the dataset even after `:latest` tags move or repositories are
deleted. The sampling frame is shipped as a fixed file with a recorded checksum.

## Pinned third-party tools

| Tool | Version | Role |
|------|---------|------|
| crane (go-containerregistry) | 0.21.6 | daemonless pull + flatten |
| CBOM-Lens (OmniTrustILM) | 1.0.0 | independent CycloneDX-CBOM extractor |
| gitleaks | 8.30.1 | private-key recall |
| syft | 1.44.0 | crypto-library inventory (optional) |
| Python `cryptography` | ≥41 | certificate/key parsing (built-in extractor) |

## Configuration

All behaviour is environment-driven (see `src/cryptocensus/config.py`): `CC_REDIS_URL`,
queue names, per-extractor toggles (`CC_ENABLE_*`), and timeouts. Extractors can be
disabled individually for ablation and performance studies.

## Tests

Dependencies are managed with [uv](https://docs.astral.sh/uv/):

```bash
uv sync --extra dev && uv run pytest     # unit tests (no Docker, no network)
```

## Limitations

CryptoCensus measures *deployed cryptographic material* (certificates, keys, configs,
library versions). It does **not** decompile binaries to prove an algorithm is invoked
at runtime; PQC capability is a version signal, not usage. Sampling-frame construction
is documented in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). See also
[docs/ARTIFACT.md](docs/ARTIFACT.md) for artifact-evaluation instructions.

## License

MIT — see [LICENSE](LICENSE).
