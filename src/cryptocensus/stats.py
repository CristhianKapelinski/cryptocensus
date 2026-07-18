"""Wilson confidence interval for a proportion — the inference a uniform-random frame
licenses. Pure standard library, no third-party dependencies."""

from __future__ import annotations

import math


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score confidence interval (default 95%) for a binomial proportion k/n."""
    if n <= 0:
        return (0.0, 0.0)
    p = k / n
    den = 1.0 + z * z / n
    center = p + z * z / (2 * n)
    half = z * math.sqrt((p * (1.0 - p) + z * z / (4 * n)) / n)
    return ((center - half) / den, (center + half) / den)


def wilson_pct(k: int, n: int, z: float = 1.96, digits: int = 1) -> tuple[float, float]:
    """Wilson interval expressed as rounded percentages."""
    lo, hi = wilson(k, n, z)
    return (round(100.0 * lo, digits), round(100.0 * hi, digits))
