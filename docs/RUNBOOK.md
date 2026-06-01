# CryptoCensus Operations Runbook

Everything a new operator (human or agent) needs to continue this measurement.

## What this is

A distributed census of the cryptographic posture and post-quantum readiness of public
container images. Source and full design: the repository below; read `README.md` and
`docs/ARCHITECTURE.md` first.

- Repository: https://github.com/AnonAuthorAnonAuthor/cryptocensus (private)
- Sampling frame: `config/sample-20000.txt` — 20,000 image references drawn uniformly at
  random from a 12,716,568-repository Docker Hub crawl (the `ditector_mongo` MongoDB on
  `host-a`, db `dockerhub_data`, collection `repositories_data`). Frozen file; reproducible
  by its checksum.

## Topology

| Role | Machine | Notes |
|------|---------|-------|
| Coordinator / SSH hub | `coord-host` (tailscale <coord-tailnet-ip>) | has SSH access + keys to the whole fleet; cluster keys in `~/.ssh/cluster/`. |
| Host (queue + results) | `host-a` (LAN 203.0.113.10, alias `host-a`) | runs Redis and the collector; also hosts the source MongoDB. 242 GB free. |
| Workers | `host-b` (=alias `host-b`), `worker6 worker7 worker9 worker2 worker3` | x86_64 + Docker; pull tasks, push results. |

Excluded / unusable: `host-x`, `host-y` (forbidden); `host-z` (Android); `worker1`, `worker8`
(disk full, 0 GB); `worker3`, `worker4`, `worker5` (offline at last check; re-probe from `host-a`).

The fleet is on the 203.0.113.0/24 LAN and reaches Redis at `203.0.113.10:6379`.

## What is running

- `host-a`: `cryptocensus-redis` (Redis 7, `--restart unless-stopped`, port 6379) and
  `cryptocensus-collector` (`collect --follow`, writes the dataset to `~/cc-data`).
- Each worker host: `cryptocensus-worker-1..N` containers (`work`, `--restart
  unless-stopped`), pulling from the queue forever.
- Dataset accumulates on `host-a:~/cc-data` (`records/`, `cbom/`, `raw/`, `blobs/`).

## Daily operations (run from `coord-host`, which can SSH to every host)

Check progress (queue + done count):
```
ssh host-a 'docker exec cryptocensus-redis redis-cli mget >/dev/null 2>&1; \
  for k in tasks processing results; do echo -n "$k="; docker exec cryptocensus-redis redis-cli llen cryptocensus:$k; done; \
  echo -n done=; docker exec cryptocensus-redis redis-cli scard cryptocensus:done'
```

Seed (enqueue images). From any host with the repo + Redis reachability:
```
docker run --rm --network host -e CC_REDIS_URL=redis://localhost:6379/0 \
  -v $PWD/config/sample-20000.txt:/f.txt:ro cryptocensus:latest seed --file /f.txt
```

Add / refresh workers on the fleet (idempotent, parallel builds). `CC_DOCKER_CONFIG`
points at a Docker `config.json` with the `<registry-user>` registry auth so workers pull
authenticated (anonymous pulls hit Docker Hub's ~100/6h-per-IP limit and stall):
```
cd ~/cryptocensus   # a clone of the repo on the coordinator
ssh host-a 'cat ~/.docker/config.json' > /tmp/dockercfg.json   # <registry-user> auth
CC_REDIS_URL=redis://203.0.113.10:6379/0 \
CC_HOSTS="host-b worker6 worker7 worker9 worker2 worker3" \
CC_WORKERS_PER_HOST=4 CC_DOCKER_CONFIG=/tmp/dockercfg.json scripts/deploy_fleet.sh
```
host-a's own workers mount its host config directly:
`-v ~/.docker:/cc-dockercfg:ro -e DOCKER_CONFIG=/cc-dockercfg`.

Analyze the dataset (snapshot anytime; safe while the run continues):
```
ssh host-a 'docker run --rm -v ~/cc-data:/data cryptocensus:latest analyze --dataset /data'
# headline numbers + summary.json, assets.csv, run_manifest.csv (reference->digest), tool_divergence.csv
```

Recover a crashed worker's in-flight tasks:
```
ssh host-a 'docker run --rm --network host -e CC_REDIS_URL=redis://localhost:6379/0 cryptocensus:latest requeue-stale'
```

Stop everything (does not delete the dataset):
```
# workers
for h in host-b worker6 worker7 worker9 worker2 worker3; do ssh $h 'docker rm -f $(docker ps -aq --filter name=cryptocensus-worker) 2>/dev/null'; done
# host
ssh host-a 'docker rm -f cryptocensus-collector cryptocensus-redis 2>/dev/null'   # keep redis if you only pause workers
```

## Configuration (all via environment, nothing hardcoded)

Key knobs (see `src/cryptocensus/config.py`): `CC_REDIS_URL`, `CC_WORKERS_PER_HOST`,
`CC_ENABLE_*` (toggle extractors), `CC_PULL_RETRIES` / `CC_PULL_RETRY_BACKOFF_S`,
`CC_PLATFORM` (default `linux/amd64`), `CC_TOOL_TIMEOUT_S`, `CC_MAX_FILE_BYTES`,
`CC_SAVE_RAW`.

## Expected behavior

- ~38–40% of sampled references are unavailable (decay / no `:latest`); this is measured,
  not an error. Missing-tag/repo/auth failures fail fast; only transient registry errors
  are retried with backoff.
- Public-key assets are ~100% quantum-vulnerable, ~0% post-quantum (the headline).
- Images are pulled by resolved digest and the digest is recorded, so the run is 100%
  reproducible (`run_manifest.csv`).

## Credentials

- `coord-host` SSH password is held by the operator; fleet hosts use keys already in
  `coord-host`'s SSH config (clusters via `~/.ssh/cluster/`).
- GitHub access uses the token stored in `coord-host:~/.git-credentials` (helper `store`).
- The repo is private (double-blind venue); make it anonymous before any public release.

## For a new agent: start here

1. `ssh host-a` and run the progress check above to see queue state and `done` count.
2. If workers are down, redeploy with `scripts/deploy_fleet.sh` (above).
3. Snapshot results anytime with `analyze`.
4. When `tasks=0 processing=0` and `done` ≈ seeded count, the run is complete: run a
   final `analyze`, copy `host-a:~/cc-data` somewhere safe, and proceed to the paper.
