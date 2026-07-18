#!/usr/bin/env bash
# Reproduce the paper's central claim end to end, entirely through Docker: fetch + verify
# the dataset, then re-run the analyzer, regenerate the figures, and print a pass/fail
# block comparing every reproduced number to the paper. No host Python or uv — only Docker
# plus coreutils (curl/tar/sha256sum) for the one-time download.
#
#   bash scripts/run_claim.sh              # downloads the released dataset if absent
#   bash scripts/run_claim.sh DATASET      # uses an existing dataset directory
set -euo pipefail
cd "$(dirname "$0")/.."

# Absolute path: Docker -v treats a relative path as a named volume, not this host dir.
DATASET="$(realpath -m "${1:-dataset}")"
IMAGE="${CC_IMAGE:-cryptocensus:latest}"
DATASET_URL="${CC_DATASET_URL:-https://github.com/CristhianKapelinski/cryptocensus/releases/download/dataset-v1/cryptocensus-dataset.tar.gz}"
REPO="CristhianKapelinski/cryptocensus"

if [ ! -d "$DATASET/records" ]; then
  echo "==> Released dataset not found; downloading and verifying"
  mkdir -p "$DATASET"
  TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
  tarball="$TMP/cryptocensus-dataset.tar.gz"
  if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    gh release download dataset-v1 -R "$REPO" -p "$(basename "$tarball")" -O "$tarball" --clobber
    gh release download dataset-v1 -R "$REPO" -p SHA256SUMS -O "$TMP/SHA256SUMS" --clobber
  else
    curl -fsSL "$DATASET_URL" -o "$tarball"
    curl -fsSL "${DATASET_URL%/*}/SHA256SUMS" -o "$TMP/SHA256SUMS"
  fi
  ( cd "$TMP" && grep -E 'cryptocensus-dataset\.tar\.gz$' SHA256SUMS | sha256sum -c - ) \
    || { echo "checksum FAILED"; exit 1; }
  tar -xzf "$tarball" -C "$DATASET"
fi

docker image inspect "$IMAGE" >/dev/null 2>&1 || { echo "==> Building image (~3 min)"; docker build -t "$IMAGE" .; }

run() { docker run --rm --user "$(id -u):$(id -g)" -v "$DATASET":/data "$@"; }

echo "==> Re-running the analyzer (regenerates summary.json from records/)"
run "$IMAGE" analyze --dataset /data

echo "==> Regenerating figures"
run --entrypoint python3 "$IMAGE" scripts/reproduce_figures.py --dataset /data --out /data \
  || echo "WARNING: figure rendering failed; numbers are still checked below" >&2

echo "==> Checking reproduced numbers against the paper"
run --entrypoint python3 "$IMAGE" scripts/check_claim.py --dataset /data
