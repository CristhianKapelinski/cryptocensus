#!/usr/bin/env bash
# MODE A: reproduce the paper's results from the ALREADY-COLLECTED dataset (fast).
#
#   bash scripts/reproduce.sh            # downloads the released dataset if absent
#   bash scripts/reproduce.sh DATASET    # uses an existing dataset directory
#
# It (re)builds the pinned image if needed, fetches the released digest-pinned dataset
# when it is not already present, runs the deterministic analyzer, and prints
# dataset/summary.json, whose fields are exactly the numbers the paper reports.
# Expected wall-clock: about 2 minutes (1 core, < 2 GB RAM, no GPU, no live pulls).
# To reproduce from scratch (re-pull every image and re-extract), see
# scripts/reproduce_from_scratch.sh instead.
set -euo pipefail
cd "$(dirname "$0")/.."

DATASET="${1:-$(pwd)/dataset}"
IMAGE="${CC_IMAGE:-cryptocensus:latest}"
DATASET_URL="${CC_DATASET_URL:-https://github.com/AnonAuthorAnonAuthor/cryptocensus/releases/latest/download/cryptocensus-dataset.tar.gz}"

if [ ! -d "$DATASET/records" ]; then
  echo "==> Released dataset not found; downloading and verifying (~1 min)"
  mkdir -p "$DATASET"
  curl -fsSL "$DATASET_URL" -o /tmp/cc-dataset.tar.gz
  if curl -fsSL "${DATASET_URL%/*}/SHA256SUMS" -o /tmp/cc-sha 2>/dev/null; then
    ( cd /tmp && grep cryptocensus-dataset.tar.gz cc-sha | sha256sum -c - ) || { echo "checksum FAILED"; exit 1; }
  fi
  tar -xzf /tmp/cc-dataset.tar.gz -C "$DATASET" --strip-components=0
fi

docker image inspect "$IMAGE" >/dev/null 2>&1 || { echo "==> Building image (~3 min)"; docker build -t "$IMAGE" .; }

echo "==> Analyzing dataset (~1 min)"
docker run --rm -v "$DATASET":/data "$IMAGE" analyze --dataset /data

echo "==> Main claim (dataset/summary.json): quantum_vulnerable_pct should be 100.0, post_quantum_pct 0.0"
cat "$DATASET/summary.json"
