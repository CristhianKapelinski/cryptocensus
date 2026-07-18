#!/usr/bin/env bash
# MODE A: reproduce the paper's results from the ALREADY-COLLECTED dataset (fast).
#
#   bash scripts/reproduce.sh            # downloads the released dataset if absent
#   bash scripts/reproduce.sh DATASET    # uses an existing dataset directory
#
# It (re)builds the pinned image if needed, fetches the released digest-pinned dataset
# when it is not already present, runs the deterministic analyzer, and prints
# dataset/summary.json, whose fields are exactly the numbers the paper reports.
# Expected wall-clock: about 6 minutes (1 core, < 2 GB RAM, no GPU, no live pulls;
# the batch-GCD pass over 6,116 moduli dominates).
# To reproduce from scratch (re-pull every image and re-extract), see
# scripts/reproduce_from_scratch.sh instead.
set -euo pipefail
cd "$(dirname "$0")/.."

DATASET="${1:-$(pwd)/dataset}"
IMAGE="${CC_IMAGE:-cryptocensus:latest}"
# Pinned to a fixed release tag for reproducibility. CC_DATASET_URL overrides it
# (e.g. a local mirror).
DATASET_URL="${CC_DATASET_URL:-https://github.com/CristhianKapelinski/cryptocensus/releases/download/dataset-v1/cryptocensus-dataset.tar.gz}"

if [ ! -d "$DATASET/records" ]; then
  echo "==> Released dataset not found; downloading and verifying (~1 min)"
  mkdir -p "$DATASET"
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  if ! curl -fsSL "$DATASET_URL" -o "$TMP/cryptocensus-dataset.tar.gz"; then
    echo "Could not fetch the dataset from $DATASET_URL."
    echo "If the download fails (offline mirror, rate limit), fetch the release"
    echo "asset cryptocensus-dataset.tar.gz manually and pass its directory:"
    echo "    bash scripts/reproduce.sh /path/to/extracted/dataset"
    exit 1
  fi
  if ! curl -fsSL "${DATASET_URL%/*}/SHA256SUMS" -o "$TMP/SHA256SUMS"; then
    echo "Could not fetch SHA256SUMS from ${DATASET_URL%/*}/SHA256SUMS; refusing to use an unverified download."
    exit 1
  fi
  ( cd "$TMP" && grep -E 'cryptocensus-dataset\.tar\.gz$' SHA256SUMS | sha256sum -c - ) || { echo "checksum FAILED"; exit 1; }
  tar -xzf "$TMP/cryptocensus-dataset.tar.gz" -C "$DATASET" --strip-components=0
fi

docker image inspect "$IMAGE" >/dev/null 2>&1 || { echo "==> Building image (~3 min)"; docker build -t "$IMAGE" .; }

echo "==> Analyzing dataset (~5 min; batch-GCD over 6,116 moduli)"
docker run --rm -v "$DATASET":/data "$IMAGE" analyze --dataset /data

echo "==> Main claim (dataset/summary.json): quantum_vulnerable_pct should be 100.0, post_quantum_pct 0.0"
cat "$DATASET/summary.json"
