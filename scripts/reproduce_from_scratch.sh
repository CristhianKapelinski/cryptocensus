#!/usr/bin/env bash
# MODE B: reproduce the WHOLE census from scratch, on a fresh machine.
# Re-pulls every sampled image by content digest, re-extracts its cryptographic
# material, and re-runs the analysis. This regenerates the dataset that MODE A
# (scripts/reproduce.sh) analyzes, rather than trusting the released one.
#
#   bash scripts/reproduce_from_scratch.sh [FRAME] [WORKERS]
#     FRAME    sampling frame file (default: config/sample-20000.txt, the published frame)
#     WORKERS  parallel workers (default: 2; the pull is network-bound, keep it low)
#
# Authenticated Docker Hub pulls (a login raises the rate limit) are recommended:
# set DOCKER_CONFIG to a config.json with a Docker Hub token, or run `docker login`.
# Wall-clock depends on network bandwidth and image sizes; expect hours for the full
# 20k frame. Use config/sample-images.txt for a fast smoke run.
#
# Reproducibility note: images are pinned to the digest recorded at first scan, so a
# re-run fetches byte-identical bytes; references whose tag has since moved or whose
# repo was deleted are recorded as decay (this is itself a measured quantity).
set -euo pipefail
cd "$(dirname "$0")/.."

FRAME="${1:-config/sample-20000.txt}"
WORKERS="${2:-2}"
IMAGE="${CC_IMAGE:-cryptocensus:latest}"
DATA="$(pwd)/dataset-fresh"
NET="cryptocensus-net"
REDIS="cryptocensus-redis"
REDIS_URL="redis://${REDIS}:6379/0"
DOCKER_CFG="${DOCKER_CONFIG:-}"

[ -f "$FRAME" ] || { echo "sampling frame not found: $FRAME"; exit 1; }
echo "==> Frame: $FRAME ($(wc -l < "$FRAME") references), workers: $WORKERS"
echo "==> Frame checksum: $(sha256sum "$FRAME" | cut -d' ' -f1)"

docker image inspect "$IMAGE" >/dev/null 2>&1 || { echo "==> Building image"; docker build -t "$IMAGE" .; }

cleanup() { docker rm -f "$REDIS" cc-w-1 cc-w-2 cc-w-3 cc-w-4 cc-w-5 cc-w-6 cc-w-7 cc-w-8 >/dev/null 2>&1 || true; }
trap cleanup EXIT
cleanup

docker network create "$NET" >/dev/null 2>&1 || true
docker run -d --name "$REDIS" --network "$NET" redis:7-alpine \
  redis-server --save "" --appendonly no >/dev/null
sleep 2

mnt=""
[ -n "$DOCKER_CFG" ] && mnt="-v $DOCKER_CFG:/cc-dockercfg:ro -e DOCKER_CONFIG=/cc-dockercfg"

echo "==> Seeding the queue"
docker run --rm --network "$NET" -e "CC_REDIS_URL=$REDIS_URL" \
  -v "$(pwd)/$FRAME:/frame.txt:ro" "$IMAGE" seed --file /frame.txt

echo "==> Launching $WORKERS workers (pull -> extract -> push)"
for i in $(seq 1 "$WORKERS"); do
  docker run -d --name "cc-w-$i" --network "$NET" \
    -e "CC_REDIS_URL=$REDIS_URL" -e CC_PULL_MUTEX=true -e CC_PULL_MUTEX_KEY=cryptocensus:pulllock:local \
    $mnt "$IMAGE" work >/dev/null
done

echo "==> Collecting results into $DATA until the queue drains"
mkdir -p "$DATA"
docker run --rm --network "$NET" -e "CC_REDIS_URL=$REDIS_URL" -v "$DATA:/data" "$IMAGE" collect --out /data --follow &
COLLECT=$!

# wait for the queue to drain
while :; do
  pend=$(docker run --rm --network "$NET" -e "CC_REDIS_URL=$REDIS_URL" "$IMAGE" stats | grep -oE 'pending[^,]*' | grep -oE '[0-9]+' || echo 0)
  proc=$(docker run --rm --network "$NET" -e "CC_REDIS_URL=$REDIS_URL" "$IMAGE" stats | grep -oE 'processing[^,]*' | grep -oE '[0-9]+' || echo 0)
  echo "    pending=$pend processing=$proc"
  [ "${pend:-0}" -eq 0 ] && [ "${proc:-0}" -le 2 ] && break
  sleep 30
done
kill "$COLLECT" 2>/dev/null || true

echo "==> Analyzing the freshly-collected dataset"
docker run --rm -v "$DATA:/data" "$IMAGE" analyze --dataset /data
echo "==> Done. Compare $DATA/summary.json against the released dataset/summary.json."
