# Artifact Evaluation

This artifact is the complete CryptoCensus pipeline: source, pinned Docker image, a
distributed task queue, a sampling frame, and the analysis that produces the census
results. It targets the **Available**, **Functional**, and **Reproduced** badges.

## Requirements

- Linux x86-64, Docker ≥ 24 (Compose v2 optional).
- Network access to Docker Hub / GHCR (to pull the sampled images and the base images).
- ~2 GB disk for the worker image and the minimal-test images; no GPU.

## Available

The repository contains all source, the `Dockerfile` (all third-party tools pinned by
version), `docker-compose.yml`, the `config/` sampling frame, and `docs/`.

## Functional (≈5 minutes)

```bash
uv sync --extra dev && uv run pytest     # unit tests: classifier, batch-GCD, extractor
bash scripts/minimal_test.sh             # end-to-end: build → seed → work → collect → analyze
```

(`uv` is the only host prerequisite for the unit tests; install it from
https://docs.astral.sh/uv/ . The end-to-end test additionally needs Docker.)

`scripts/minimal_test.sh` starts Redis and a worker, censuses the five images in
`config/sample-images.txt`, and prints the aggregated report plus writes
`dataset/summary.json`, `dataset/assets.csv`, and per-image CBOMs under `dataset/cbom/`.

Expected qualitative results on the minimal frame:
- public-key assets in the hundreds; **~100 % quantum-vulnerable, ~0 % post-quantum**;
- weak SHA-1 signatures present (legacy roots in CA bundles);
- most images ship a PQC-*capable* library (OpenSSL ≥ 3.5) while PQC *usage* is ~0 %;
- the built-in extractor's certificate count matches CBOM-Lens (calibration check).

## Reproduced (full census)

Replace `config/sample-images.txt` with the released uniform-random frame, scale workers
(`docker compose up --scale worker=N`, or workers on multiple hosts pointing at the same
`CC_REDIS_URL`), then `collect` and `analyze`. `dataset/summary.json` reproduces the
numbers reported in the paper; `dataset/assets.csv` supports recomputing every
confidence interval.

## Determinism

Extraction is deterministic given an image digest. Tool versions are pinned in the
`Dockerfile`. `sampling.deterministic_sample` reproduces a subset exactly from a seed.
