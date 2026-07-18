#!/usr/bin/env bash
# Reproduce the paper's central claim from the released dataset, end to end, with one
# command: fetch + verify the dataset if needed, re-run the analyzer, regenerate the
# figures, and print a pass/fail block comparing every reproduced number to the paper.
#
#   bash scripts/run_claim.sh              # downloads the released dataset if absent
#   bash scripts/run_claim.sh DATASET      # uses an existing dataset directory
#
# No Docker, no re-crawl, no GPU. Needs Python 3.11+ (stdlib only for the analysis);
# figures additionally need matplotlib, rendered via `uv` when available and skipped
# otherwise (the numbers are printed regardless).
set -euo pipefail
cd "$(dirname "$0")/.."

DATASET="${1:-$(pwd)/dataset}"
DATASET_URL="${CC_DATASET_URL:-https://github.com/CristhianKapelinski/cryptocensus/releases/download/dataset-v1/cryptocensus-dataset.tar.gz}"
REPO="CristhianKapelinski/cryptocensus"

fetch() {
  local out="$1"
  if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    gh release download dataset-v1 -R "$REPO" -p "$(basename "$out")" -O "$out" --clobber
  else
    curl -fsSL "$DATASET_URL" -o "$out"
  fi
}

if [ ! -d "$DATASET/records" ]; then
  echo "==> Released dataset not found; downloading and verifying"
  mkdir -p "$DATASET"
  tarball="$DATASET/cryptocensus-dataset.tar.gz"
  fetch "$tarball"
  if fetch_sums=$(mktemp) && ( command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1 \
        && gh release download dataset-v1 -R "$REPO" -p SHA256SUMS -O "$fetch_sums" --clobber \
        || curl -fsSL "${DATASET_URL%/*}/SHA256SUMS" -o "$fetch_sums" ); then
    ( cd "$DATASET" && grep "$(basename "$tarball")" "$fetch_sums" | sha256sum -c - ) \
      || { echo "checksum FAILED"; exit 1; }
  else
    echo "WARNING: SHA256SUMS unavailable; proceeding without checksum verification" >&2
  fi
  tar -xzf "$tarball" -C "$DATASET"
  rm -f "$tarball"
fi

PY="${CC_PYTHON:-python3}"
export PYTHONPATH="$(pwd)/src${PYTHONPATH:+:$PYTHONPATH}"

echo "==> Re-running the analyzer (regenerates summary.json from records/)"
"$PY" - "$DATASET" <<'PY'
import sys
from cryptocensus.analyze import analyze, format_report
print(format_report(analyze(sys.argv[1])))
PY

echo "==> Regenerating figures"
if command -v uv >/dev/null 2>&1; then
  uv run --with matplotlib "$PY" scripts/reproduce_figures.py --dataset "$DATASET" --out "$DATASET" \
    || echo "WARNING: figure rendering failed; numbers still printed above" >&2
else
  "$PY" scripts/reproduce_figures.py --dataset "$DATASET" --out "$DATASET" \
    || "$PY" scripts/reproduce_figures.py --dataset "$DATASET" --no-figures
fi

echo "==> Checking reproduced numbers against the paper"
"$PY" scripts/check_claim.py --dataset "$DATASET"
