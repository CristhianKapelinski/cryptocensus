#!/usr/bin/env bash
# Reduced live census on a single host: draw N repositories from the uniform-random
# sampling frame, pull and census them with one worker, and analyze — the full pipeline
# at small scale. No Docker Hub login (a handful of anonymous pulls stay well under the
# rate limit) and no second host.
#
#   bash scripts/reduced_census.sh          # 10 repositories (default)
#   bash scripts/reduced_census.sh 25       # N repositories
set -euo pipefail
cd "$(dirname "$0")/.."

N="${1:-10}"
IMAGE="${CC_IMAGE:-cryptocensus:latest}"
NET="cryptocensus-net"
REDIS="cryptocensus-redis"
REDIS_URL="redis://${REDIS}:6379/0"
DATASET="$(pwd)/dataset-reduced"
FRAME="config/sample-20000.txt"
FRAME_N="$(mktemp)"

cleanup() {
  rm -f "$FRAME_N"
  docker rm -f "$REDIS" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# First N references of the uniform frame, in its deterministic hash-keyed order.
# (awk, not `grep | head`, so head closing the pipe cannot SIGPIPE-kill grep under pipefail.)
awk -v n="$N" 'NF && $1 !~ /^#/ { print; if (++c >= n) exit }' "$FRAME" > "$FRAME_N"
echo "==> Reduced census over $N repositories drawn from $FRAME"

docker image inspect "$IMAGE" >/dev/null 2>&1 || { echo "==> Building image"; docker build -t "$IMAGE" .; }

docker network create "$NET" >/dev/null 2>&1 || true
docker run -d --name "$REDIS" --network "$NET" \
  redis:7-alpine@sha256:6ab0b6e7381779332f97b8ca76193e45b0756f38d4c0dcda72dbb3c32061ab99 \
  redis-server --save "" --appendonly no >/dev/null
for _ in $(seq 1 30); do docker exec "$REDIS" redis-cli ping 2>/dev/null | grep -q PONG && break; sleep 1; done

run() { docker run --rm --user "$(id -u):$(id -g)" --network "$NET" -e "CC_REDIS_URL=$REDIS_URL" "$@"; }

echo "==> Seeding the queue"
run -v "$FRAME_N:/frame.txt:ro" "$IMAGE" seed --file /frame.txt

echo "==> Running one worker (pulls, flattens, extracts) until the queue drains"
run "$IMAGE" work --idle-exit 5

echo "==> Collecting and analyzing"
mkdir -p "$DATASET"
run -v "$DATASET:/data" "$IMAGE" collect --out /data
run -v "$DATASET:/data" "$IMAGE" analyze --dataset /data
echo "==> Done. Reduced dataset in $DATASET/ (see summary.json)."
