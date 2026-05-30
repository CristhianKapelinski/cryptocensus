#!/usr/bin/env bash
# Reproduce the paper's headline numbers (Claims C1-C5) from a CryptoCensus
# dataset directory produced by the workers/collector.
#
#   scripts/reproduce.sh [DATASET_DIR]      # default: ./dataset
#
# It (re)builds the pinned image if needed, runs the deterministic analyzer over
# the dataset, and prints summary.json, whose fields are exactly the numbers the
# paper reports. assets.csv (per-asset rows) is written alongside for recomputing
# every confidence interval and regenerating the figures.
set -euo pipefail
cd "$(dirname "$0")/.."

DATASET="${1:-$(pwd)/dataset}"
IMAGE="${CC_IMAGE:-cryptocensus:latest}"

[ -d "$DATASET/records" ] || { echo "no records/ under $DATASET; run the census first (see README)"; exit 1; }
docker image inspect "$IMAGE" >/dev/null 2>&1 || docker build -t "$IMAGE" .

echo "==> Analyzing $DATASET"
docker run --rm -v "$DATASET":/data "$IMAGE" analyze --dataset /data

echo "==> Headline numbers (dataset/summary.json):"
cat "$DATASET/summary.json"
