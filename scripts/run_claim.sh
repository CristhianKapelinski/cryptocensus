#!/usr/bin/env bash
# Reproduce the paper's central claim end to end through Docker: fetch + verify the
# dataset, then analyze it, regenerate the figures, and print a pass/fail block. Records
# are read by STREAMING the released archive, so the ~20k record files are never extracted
# to disk — fast, and safe on filesystems that choke on many small files. Needs only Docker
# plus coreutils (curl/tar/sha256sum) for the one-time download.
#
#   bash scripts/run_claim.sh              # downloads the released dataset if absent
#   bash scripts/run_claim.sh DATASET      # uses an existing dataset directory or archive
set -euo pipefail
cd "$(dirname "$0")/.."

. "$(dirname "$0")/require.sh"
require_docker

# Absolute path: Docker -v treats a relative path as a named volume, not this host dir.
DATASET="$(realpath -m "${1:-dataset}")"
IMAGE="${CC_IMAGE:-cryptocensus:latest}"
# dataset-v1 lives in this project's generic package registry; SHA256SUMS sits beside it,
# so the checksum URL is derived from DATASET_URL and stays consistent if you override it.
DATASET_URL="${CC_DATASET_URL:-https://gitlab.com/api/v4/projects/85478201/packages/generic/cryptocensus-dataset/v1/cryptocensus-dataset.tar.gz}"
TARBALL="$DATASET/cryptocensus-dataset.tar.gz"

mkdir -p "$DATASET"

# Fetch the archive into the run folder (never the host /tmp) unless the dataset is already
# present as an extracted records/ dir or as the archive itself.
if [ ! -d "$DATASET/records" ] && [ ! -f "$TARBALL" ]; then
  echo "==> Downloading dataset-v1 into $DATASET and verifying"
  sums="$DATASET/SHA256SUMS"
  curl -fsSL "$DATASET_URL" -o "$TARBALL"
  curl -fsSL "${DATASET_URL%/*}/SHA256SUMS" -o "$sums"
  ( cd "$DATASET" && grep -E 'cryptocensus-dataset\.tar\.gz$' SHA256SUMS | sha256sum -c - ) \
    || { echo "checksum FAILED"; rm -f "$TARBALL" "$sums"; exit 1; }
  rm -f "$sums"
fi

# Records source: the extracted dir if you already have one, else the archive (streamed).
if [ -d "$DATASET/records" ]; then SRC=/data; else SRC="/data/$(basename "$TARBALL")"; fi

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then echo "==> Building image (first time)"; docker build -t "$IMAGE" .; fi

run() { docker run --rm --user "$(id -u):$(id -g)" -v "$DATASET":/data "$@"; }

echo "==> Analyzing (streaming records; summary.json written to $DATASET)"
run "$IMAGE" analyze --dataset "$SRC"

echo "==> Regenerating figures"
if run --entrypoint python3 "$IMAGE" scripts/reproduce_figures.py --dataset "$SRC" --out /data; then
  echo "    figures written to $DATASET/ (fig_posture.pdf, fig_repro.pdf, fig_keys.pdf)"
  if command -v xdg-open >/dev/null 2>&1 && [ -n "${DISPLAY:-}" ]; then
    for f in fig_posture fig_repro fig_keys; do xdg-open "$DATASET/$f.pdf" >/dev/null 2>&1 & done
    echo "    (opened them in your PDF viewer)"
  fi
else
  echo "WARNING: figure rendering failed; numbers are still checked below" >&2
fi

echo "==> Checking reproduced numbers against the paper"
run --entrypoint python3 "$IMAGE" scripts/check_claim.py --dataset /data --records "$SRC"
