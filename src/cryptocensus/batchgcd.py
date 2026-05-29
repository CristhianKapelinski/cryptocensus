"""Shared-prime weak-key detection over a set of RSA moduli.

If two RSA moduli share a prime factor (a symptom of low-entropy key generation),
their GCD reveals that factor and both keys are trivially factorable. Computing the
pairwise GCD of every pair is O(n^2) big-integer operations; the product/remainder
tree of Bernstein et al. computes, for every modulus N_i, gcd(N_i, (prod_j N_j) / N_i)
in quasi-linear time. This is the method popularized by "Mining Your Ps and Qs"
(Heninger et al., USENIX Security 2012) and refined for low-entropy corpora by
Pelofske (arXiv:2405.03166, 2024).

The public entry point is `batch_gcd`.
"""

from __future__ import annotations

import math
from typing import Sequence


def _product_tree(moduli: Sequence[int]) -> list[list[int]]:
    """Bottom-up product tree. Level 0 is the leaves; the last level is the
    single product of all moduli."""
    level = list(moduli)
    tree = [level]
    while len(level) > 1:
        nxt = [level[i] * level[i + 1] for i in range(0, len(level) - 1, 2)]
        if len(level) % 2 == 1:
            nxt.append(level[-1])
        tree.append(nxt)
        level = nxt
    return tree


def batch_gcd(moduli: Sequence[int]) -> dict[int, int]:
    """Return {index: nontrivial_gcd} for every modulus that shares a factor with
    at least one other modulus in the set.

    The returned GCD is gcd(N_i, P/N_i) where P is the product of all moduli; for a
    modulus that shares exactly one prime with one other key this equals that prime.
    """
    moduli = [int(m) for m in moduli]
    n = len(moduli)
    if n < 2:
        return {}

    tree = _product_tree(moduli)
    # Descend the remainder tree: R holds P mod (node^2) at each level.
    remainders = tree[-1]  # root: the full product P (single element)
    for depth in range(len(tree) - 2, -1, -1):
        level = tree[depth]
        remainders = [remainders[i // 2] % (level[i] ** 2) for i in range(len(level))]

    result: dict[int, int] = {}
    for i, mod in enumerate(moduli):
        # P is divisible by N_i, so (P mod N_i^2) is divisible by N_i; the quotient is exact.
        quotient = remainders[i] // mod
        g = math.gcd(quotient, mod)
        if g != 1:
            result[i] = g
    return result
