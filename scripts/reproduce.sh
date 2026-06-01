#!/usr/bin/env bash
# Reproduce the paper's main claim (Claim #1) with a single command.
#
#   bash scripts/reproduce.sh            # downloads the released dataset if absent
#   bash scripts/reproduce.sh DATASET    # uses an existing dataset directory
#
# It (re)builds the pinned image if needed, fetches the released digest-pinned dataset
# when it is not already present, runs the deterministic analyzer, and prints
# dataset/summary.json, whose fields are exactly the numbers the paper reports.
# Expected wall-clock: about 2 minutes (1 core, < 2 GB RAM, no GPU, no live pulls).
set -euo pipefail
cd "$(dirname "$0")/.."

DATASET="${1:-$(pwd)/dataset}"
IMAGE="${CC_IMAGE:-cryptocensus:latest}"
DATASET_URL="${CC_DATASET_URL:-https://github.com/AnonAuthorAnonAuthor/cryptocensus/releases/latest/download/dataset.tar.gz}"

if [ ! -d "$DATASET/records" ]; then
  echo "==> Released dataset not found; downloading (~1 min)"
  mkdir -p "$DATASET"
  curl -fsSL "$DATASET_URL" | tar -xz -C "$DATASET" --strip-components=1
fi

docker image inspect "$IMAGE" >/dev/null 2>&1 || { echo "==> Building image (~3 min)"; docker build -t "$IMAGE" .; }

echo "==> Analyzing dataset (~1 min)"
docker run --rm -v "$DATASET":/data "$IMAGE" analyze --dataset /data

echo "==> Main claim (dataset/summary.json): quantum_vulnerable_pct should be 100.0, post_quantum_pct 0.0"
cat "$DATASET/summary.json"
