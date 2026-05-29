"""Construction of the image reference list to be censused.

For a reproducible study the sampling frame is shipped as a file (one ``repo:tag`` per
line); ``from_file`` reads it. ``deterministic_sample`` draws a fixed-seed subset from
a candidate list so a run can be reproduced exactly. A truly uniform-random draw over
the whole Docker Hub namespace requires an enumeration of the namespace (Docker Hub
exposes no uniform-random endpoint); that enumeration is out of scope for this module
and is documented in docs/ARCHITECTURE.md — the released artifact ships the resulting
reference list so the census is reproducible regardless of how the frame was built.
"""

from __future__ import annotations

import hashlib


def from_file(path: str) -> list[str]:
    refs = []
    with open(path) as handle:
        for line in handle:
            line = line.strip()
            if line and not line.startswith("#"):
                refs.append(line)
    return refs


def deterministic_sample(candidates: list[str], n: int, seed: str = "cryptocensus") -> list[str]:
    """Return a stable, seed-dependent subset of `candidates` of size `min(n, len)`.
    Ordering is by a keyed hash, so the same (candidates, n, seed) always yields the
    same sample without storing any random state."""
    scored = sorted(candidates, key=lambda c: hashlib.sha256(f"{seed}:{c}".encode()).hexdigest())
    return scored[: min(n, len(scored))]
