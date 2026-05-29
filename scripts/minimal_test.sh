#!/usr/bin/env bash
# Minimal end-to-end test, without Docker Compose: builds the image, brings up Redis
# and one worker on a user-defined network, censuses the sample frame, and analyzes.
set -euo pipefail

cd "$(dirname "$0")/.."

IMAGE="cryptocensus:latest"
NET="cryptocensus-net"
REDIS="cryptocensus-redis"
REDIS_URL="redis://${REDIS}:6379/0"
DATASET="$(pwd)/dataset"

cleanup() {
  docker rm -f "${REDIS}" >/dev/null 2>&1 || true
  docker network rm "${NET}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "==> Building worker image"
docker build -t "${IMAGE}" .

echo "==> Starting Redis"
docker network create "${NET}" >/dev/null 2>&1 || true
docker run -d --name "${REDIS}" --network "${NET}" redis:7-alpine \
  redis-server --save "" --appendonly no >/dev/null
sleep 2

run() { docker run --rm --user "$(id -u):$(id -g)" --network "${NET}" -e "CC_REDIS_URL=${REDIS_URL}" "$@"; }

echo "==> Seeding the queue"
run -v "$(pwd)/config:/frame:ro" "${IMAGE}" seed --file /frame/sample-images.txt

echo "==> Running a worker (pushes results to Redis) until the queue drains"
run "${IMAGE}" work --idle-exit 3

echo "==> Collecting results into ${DATASET} (host side)"
mkdir -p "${DATASET}"
run -v "${DATASET}:/data" "${IMAGE}" collect --out /data

echo "==> Analyzing"
run -v "${DATASET}:/data" "${IMAGE}" analyze --dataset /data

echo "==> Done. Artifacts in ${DATASET}/"
