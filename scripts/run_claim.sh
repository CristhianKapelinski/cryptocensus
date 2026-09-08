#!/usr/bin/env bash
# Reproduce the paper's central claim end to end through Docker: fetch + verify the
# dataset, then analyze it, regenerate the figures, and print a pass/fail block. Records
# are read by STREAMING the released archive, so the ~20k record files are never extracted
# to disk — fast, and safe on filesystems that choke on many small files. Needs only Docker
# plus curl/tar and either sha256sum or shasum for the one-time download.
#
#   bash scripts/run_claim.sh              # downloads the released dataset if absent
#   bash scripts/run_claim.sh DATASET      # uses an existing dataset directory or archive
set -euo pipefail
cd "$(dirname "$0")/.."

. "$(dirname "$0")/require.sh"
require_docker

# Absolute path: Docker -v treats a relative path as a named volume, not this host dir.
# Built with mkdir/cd/pwd rather than `realpath -m`, which is GNU-only and absent from the
# BSD userland on macOS.
mkdir -p "${1:-dataset}"
DATASET="$(cd "${1:-dataset}" && pwd)"
IMAGE="${CC_IMAGE:-cryptocensus:latest}"
# The dataset is archived on Zenodo under the concept DOI 10.5281/zenodo.22666280, which
# always resolves to the newest version. We ask the API for that version and build the file
# URL from the record it returns, so a future dataset release needs no change here.
# SHA256SUMS sits beside the tarball in the same record, so the checksum URL is derived from
# DATASET_URL and stays consistent if you override it.
zenodo_latest() { # concept record id -> base URL of the newest version's files
  local rec
  rec=$(curl -fsSL "https://zenodo.org/api/records/$1" \
        | sed -n 's/.*"id"[[:space:]]*:[[:space:]]*\([0-9]\{1,\}\).*/\1/p' | head -1)
  [ -n "$rec" ] || { echo "could not resolve Zenodo concept record $1" >&2; return 1; }
  printf 'https://zenodo.org/records/%s/files' "$rec"
}
DATASET_URL="${CC_DATASET_URL:-$(zenodo_latest 22666280)/cryptocensus-dataset.tar.gz}"
TARBALL="$DATASET/cryptocensus-dataset.tar.gz"

# Fetch the archive into the run folder (never the host /tmp) unless the dataset is already
# present as an extracted records/ dir or as the archive itself.
if [ ! -d "$DATASET/records" ] && [ ! -f "$TARBALL" ]; then
  echo "==> Downloading dataset-v2 into $DATASET and verifying"
  sums="$DATASET/SHA256SUMS"
  curl -fsSL "$DATASET_URL" -o "$TARBALL"
  curl -fsSL "${DATASET_URL%/*}/SHA256SUMS" -o "$sums"
  ( cd "$DATASET" && grep -E 'cryptocensus-dataset\.tar\.gz$' SHA256SUMS | sha256_check ) \
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
