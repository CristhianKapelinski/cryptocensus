# Architecture

## Design goals

1. **Reproducible** — pinned tools, deterministic extraction, released dataset.
2. **Distributed** — scale horizontally by adding workers on more machines.
3. **Daemonless & safe** — images are pulled and flattened, never executed; the
   tarball is extracted with path-traversal and special-file protection.
4. **Honest measurement** — trust-store and non-trust-store paths are separated; PQC
   *capability* and *usage* are distinguished; only independent tools are compared
   for divergence.

## Components

| Component | Module | Responsibility |
|-----------|--------|----------------|
| Coordinator | `coordinator.py` | seed the queue from a sampling frame |
| Task queue | `queue.py` | Redis reliable queue (claim/ack/requeue, results) |
| Worker | `worker.py` | claim → `image.py` pull/flatten → extractors → result |
| Extractors | `extractors/` | built-in certs/keys, libraries, gitleaks, CBOM-Lens, syft |
| Classifier | `classify.py` | PQC status, weak-signature/weak-key, library PQC capability |
| Batch-GCD | `batchgcd.py` | shared-prime weak-key detection (product/remainder tree) |
| CBOM | `cbom.py` | CycloneDX 1.7 serialization |
| Collector | `collector.py` | drain results into a dataset directory |
| Analyzer | `analyze.py` | aggregate posture, PQC readiness, reuse, divergence |

## Queue semantics

`enqueue` pushes references onto a pending list. A worker `claim` is a single atomic
`BLMOVE pending → processing`, so a task is never held by two workers and a crashed
worker's task survives in `processing` until `requeue-stale` returns it. On success the
worker pushes a result and `ack`s (removes from `processing`, adds to `done`).
Results are a separate list drained by the collector, so the only cross-machine
dependency is reachable Redis — no shared filesystem is required.

### Scaling and tradeoffs

Results are buffered in Redis and then written to disk by one collector. For a
workshop-scale census (10^3–10^5 images) this is comfortable. For registry-scale runs,
swap the result list for object storage (S3/GCS) by replacing `queue.push_result`/
`collector.collect`; nothing else changes. Pulls dominate wall-clock, so workers scale
near-linearly; deduplicating shared base layers (by layer digest) is the main further
optimization and is left as a worker-side cache.

## Sampling frame

Docker Hub exposes no uniform-random endpoint, so a uniform-random census requires an
external enumeration of the namespace; the resulting `repo:tag` list is shipped in
`config/` and consumed by `sampling.from_file`, which makes the census reproducible
independently of how the frame was built. `sampling.deterministic_sample` draws a
fixed-seed subset from a candidate list for exact re-runs.

## Threat model for extraction

Sampled images are untrusted. Workers never execute them: `crane export` produces a
flat tar from registry blobs, and `_safe_extract` writes only regular files inside the
destination, rejecting absolute paths, `..` traversal, and device/fifo/socket entries.
