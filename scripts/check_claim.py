#!/usr/bin/env python3
"""Compare the reproduced numbers against the values reported in the paper and print a
pass/fail block. Headline figures are read from the analyzer's ``summary.json``; the
remaining figure-level numbers are recomputed from the records via reproduce_figures.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from reproduce_figures import aggregate, iter_records_dir

# Headline values reported in the paper (Table 2 and the posture/keys sections). Every
# one of these reproduces exactly from the released dataset; they gate the claim.
EXPECTED = {
    "images_ok": 11962,
    "public_key_assets": 4211380,
    "quantum_vulnerable_pct": 100.0,
    "post_quantum": 0,
    "pqc_capable_images": 801,
    "certs_own": 518668,
    "weak_sig_pct": 43.0,
    "rsa_sub2048": 40720,
    "rsa_512": 5552,
    "own_keys": 178455,
    "fingerprints": 7141,
    "reused": 2412,
    "rsa_moduli": 6116,
    "factorable": 4,
    "decay_pct": 34.7,
    "own_priv_ssh_keys": 37077,
    "reused_deployed": 36,
}


def _ok(got, exp) -> bool:
    if isinstance(exp, float):
        return abs(float(got) - exp) <= 0.1
    return got == exp


def check(dataset_dir: str, records: str | None = None) -> bool:
    with open(os.path.join(dataset_dir, "summary.json")) as handle:
        s = json.load(handle)
    fig = aggregate(iter_records_dir(records or dataset_dir), with_batchgcd=False)
    weak_sig_pct = round(100.0 * fig["weak_sig"] / (fig["own_certs"] or 1), 1)

    got = {
        "images_ok": s["images_ok"],
        "public_key_assets": s["public_key_assets"],
        "quantum_vulnerable_pct": s["quantum_vulnerable_pct"],
        "post_quantum": s["post_quantum"],
        "pqc_capable_images": s["images_with_pqc_capable_library"],
        "certs_own": s["certs_own"],
        "weak_sig_pct": weak_sig_pct,
        "rsa_sub2048": fig["rsa_sub2048"],
        "rsa_512": fig["rsa_512"],
        "own_keys": s["keys_own"],
        "fingerprints": s["own_key_fingerprints"],
        "reused": s["own_keys_reused_across_images"],
        "rsa_moduli": s["own_rsa_moduli_unique"],
        "factorable": s["factorable_moduli_shared_prime"],
        "decay_pct": s["decay_pct"],
        "own_priv_ssh_keys": fig["location_total"],
        "reused_deployed": s["deployed_private_keys_reused"],
    }
    results = {k: _ok(got[k], EXPECTED[k]) for k in EXPECTED}
    ok = all(results.values())
    n = s["images_ok"]
    pqc = got["pqc_capable_images"]
    bar = "═" * 62
    print(bar)
    print("  Claim: deployed cryptographic posture is not migrating")
    print(f"  PQC-capable images  : {pqc:,} / {n:,}  ({100.0 * pqc / n:.1f}%)")
    print(f"  Post-quantum assets : {got['post_quantum']} / {got['public_key_assets']:,}"
          f"  ({got['quantum_vulnerable_pct']:.0f}% quantum-vulnerable)")
    print(f"  Weak-signature certs: {weak_sig_pct:.1f}%")
    print(f"  RSA keys < 2048-bit : {got['rsa_sub2048']:,}  ({got['rsa_512']:,} at 512-bit)")
    print(f"  Reused fingerprints : {got['reused']:,} of {got['fingerprints']:,}")
    print(f"  RSA moduli / factorable (batch-GCD): {got['rsa_moduli']:,} / {got['factorable']}")
    print(f"  Unresolved (no latest tag): {got['decay_pct']:.1f}%")
    print(bar)
    print(f"  {'metric':<24}{'reproduced':>14}{'paper':>14}   status")
    for k in EXPECTED:
        e, g = EXPECTED[k], got[k]
        ge = f"{g:,}" if isinstance(g, int) else f"{g:g}"
        ee = f"{e:,}" if isinstance(e, int) else f"{e:g}"
        print(f"  {k:<24}{ge:>14}{ee:>14}   {'OK' if results[k] else 'FAIL'}")
    print(bar)
    print(f"  RESULT: {'OK  - matches Table 2 of the paper' if ok else 'FAIL - see mismatches above'}")
    print(bar)
    return ok


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", required=True, help="directory holding summary.json")
    ap.add_argument("--records", default=None,
                    help="records source for the figure numbers: a directory or a .tar.gz (default: --dataset)")
    args = ap.parse_args(argv)
    return 0 if check(args.dataset, args.records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
