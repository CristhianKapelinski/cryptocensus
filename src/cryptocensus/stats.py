"""Statistics helpers for the census analysis: a Wilson confidence interval for a
proportion (the inference a uniform-random frame licenses) and the agreement measures
used for tool divergence. Pure standard library, no third-party dependencies."""

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


def jaccard(a: set, b: set) -> float:
    """Jaccard similarity of two finding sets (1.0 = identical, 0.0 = disjoint)."""
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def fleiss_kappa(item_counts: list[tuple[int, int]]) -> float:
    """Fleiss' kappa from per-item (raters_that_found, raters_total) pairs."""
    if not item_counts:
        return 0.0
    n_items = len(item_counts)
    raters = item_counts[0][1]
    if raters < 2:
        return 0.0
    p_found = sum(found for found, _ in item_counts) / (n_items * raters)
    pe = p_found ** 2 + (1.0 - p_found) ** 2
    pbar = sum(
        (found * found + (raters - found) * (raters - found) - raters) / (raters * (raters - 1))
        for found, _ in item_counts
    ) / n_items
    return (pbar - pe) / (1.0 - pe) if pe < 1.0 else 1.0
