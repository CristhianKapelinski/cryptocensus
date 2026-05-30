#!/usr/bin/env bash
# Build the image and launch persistent workers on every host in CC_HOSTS.
# Run from a machine with SSH access to the fleet (e.g. the coordinator). Idempotent:
# re-running rebuilds and relaunches workers. Builds run in parallel across hosts.
#
#   CC_REDIS_URL=redis://HOST:6379/0 CC_HOSTS="h1 h2 ..." scripts/deploy_fleet.sh
#
# Optional:
#   CC_IMAGE             (default cryptocensus:latest)
#   CC_WORKERS_PER_HOST  (default 4)
#   CC_DOCKER_CONFIG     path to a Docker config.json (on this machine) with registry
#                        auth; shipped to each host and mounted so crane pulls
#                        authenticated (raises Docker Hub pull-rate limits).
set -euo pipefail

REDIS_URL="${CC_REDIS_URL:?set CC_REDIS_URL=redis://HOST:6379/0}"
HOSTS="${CC_HOSTS:?set CC_HOSTS='host1 host2 ...'}"
IMAGE="${CC_IMAGE:-cryptocensus:latest}"
PER_HOST="${CC_WORKERS_PER_HOST:-4}"
DOCKER_CONFIG_SRC="${CC_DOCKER_CONFIG:-}"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SSH_OPTS=(-o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=10)

deploy_one() {
  local h="$1" log="/tmp/cc_deploy_${1//\//_}.log" mount=""
  {
    tar -C "$SRC" -czf - --exclude=.git --exclude=.venv --exclude=dataset . \
      | ssh "${SSH_OPTS[@]}" "$h" \
        'rm -rf ~/cryptocensus-src && mkdir -p ~/cryptocensus-src && tar -C ~/cryptocensus-src -xzf -'
    if [ -n "$DOCKER_CONFIG_SRC" ]; then
      ssh "${SSH_OPTS[@]}" "$h" 'mkdir -p ~/cc-dockercfg && cat > ~/cc-dockercfg/config.json' < "$DOCKER_CONFIG_SRC"
      mount='-v ~/cc-dockercfg:/cc-dockercfg:ro -e DOCKER_CONFIG=/cc-dockercfg'
    fi
    ssh "${SSH_OPTS[@]}" "$h" "cd ~/cryptocensus-src \
      && docker build -q -t '$IMAGE' . \
      && for i in \$(seq 1 $PER_HOST); do \
           docker rm -f cryptocensus-worker-\$i >/dev/null 2>&1 || true; \
           docker run -d --name cryptocensus-worker-\$i --restart unless-stopped \
             $mount -e CC_REDIS_URL='$REDIS_URL' '$IMAGE' work >/dev/null; \
         done"
  } >"$log" 2>&1 \
    && echo "OK   $h ($PER_HOST workers)" \
    || echo "FAIL $h (see $log on coordinator)"
}

echo "Deploying to: $HOSTS  (redis=$REDIS_URL, $PER_HOST workers/host, auth=$([ -n "$DOCKER_CONFIG_SRC" ] && echo yes || echo no))"
for h in $HOSTS; do deploy_one "$h" & done
wait
echo "Done."
