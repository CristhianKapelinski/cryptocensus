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
# SHA256 of the published uniform-random frame; verified when the default frame is used.
FRAME_SHA256=602a39dd5b4e3b2f8d4813c71b10e5d33cc2468cd36b731c8a4af133e8aa76e8
WORKERS="${2:-2}"
IMAGE="${CC_IMAGE:-cryptocensus:latest}"
DATA="$(pwd)/dataset-fresh"
NET="cryptocensus-net"
REDIS="cryptocensus-redis"
REDIS_URL="redis://${REDIS}:6379/0"
DOCKER_CFG="${DOCKER_CONFIG:-}"

[ -f "$FRAME" ] || { echo "sampling frame not found: $FRAME"; exit 1; }
echo "==> Frame: $FRAME ($(wc -l < "$FRAME") references), workers: $WORKERS"
if [ "$FRAME" = "config/sample-20000.txt" ]; then
  echo "${FRAME_SHA256}  ${FRAME}" | sha256sum -c - || { echo "frame checksum FAILED"; exit 1; }
else
  echo "==> Frame checksum: $(sha256sum "$FRAME" | cut -d' ' -f1)"
fi

docker image inspect "$IMAGE" >/dev/null 2>&1 || { echo "==> Building image"; docker build -t "$IMAGE" .; }

cleanup() { docker rm -f "$REDIS" $(docker ps -aq --filter name='cc-w-') >/dev/null 2>&1 || true; }
trap cleanup EXIT
cleanup

docker network create "$NET" >/dev/null 2>&1 || true
# A container left behind by an interrupted run holds this fixed name, and
# `docker run --name` refuses to reuse it -- so the evaluator's first command fails
# with a name conflict on a machine that is otherwise fine. Clear it first.
docker rm -f "$REDIS" >/dev/null 2>&1 || true
docker run -d --name "$REDIS" --network "$NET" \
  redis:7-alpine@sha256:6ab0b6e7381779332f97b8ca76193e45b0756f38d4c0dcda72dbb3c32061ab99 \
  redis-server --save "" --appendonly no >/dev/null
echo "==> Waiting for Redis"
for _ in $(seq 1 30); do
  docker exec "$REDIS" redis-cli ping 2>/dev/null | grep -q PONG && break
  sleep 1
done

mnt=""
[ -n "$DOCKER_CFG" ] && mnt="-v $DOCKER_CFG:/cc-dockercfg:ro -e DOCKER_CONFIG=/cc-dockercfg"

echo "==> Seeding the queue"
docker run --rm --network "$NET" -e "CC_REDIS_URL=$REDIS_URL" \
  -v "$(pwd)/$FRAME:/frame.txt:ro" "$IMAGE" seed --file /frame.txt

echo "==> Launching $WORKERS workers (pull -> extract -> push)"
for i in $(seq 1 "$WORKERS"); do
  docker rm -f "cc-w-$i" >/dev/null 2>&1 || true
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
  pend=$(docker run --rm --network "$NET" -e "CC_REDIS_URL=$REDIS_URL" "$IMAGE" stats | grep -oE "'pending': *[0-9]+" | grep -oE '[0-9]+' || echo 0)
  proc=$(docker run --rm --network "$NET" -e "CC_REDIS_URL=$REDIS_URL" "$IMAGE" stats | grep -oE "'processing': *[0-9]+" | grep -oE '[0-9]+' || echo 0)
  echo "    pending=$pend processing=$proc"
  [ "${pend:-0}" -eq 0 ] && [ "${proc:-0}" -le 2 ] && break
  sleep 30
done
kill "$COLLECT" 2>/dev/null || true

echo "==> Analyzing the freshly-collected dataset"
docker run --rm -v "$DATA:/data" "$IMAGE" analyze --dataset /data
echo "==> Done. Compare $DATA/summary.json against the released dataset/summary.json."
