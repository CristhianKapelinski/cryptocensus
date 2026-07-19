#!/usr/bin/env python3
"""Regenerate the paper's figures and their underlying numbers from the released dataset.

Every value is computed from the per-image records under ``<dataset>/records/``; no
figure constant is hardcoded. The module exposes :func:`aggregate` (pure over an
iterable of records) so the same computation can be driven from an on-disk dataset or a
streamed archive, and reused by the claim checker.

    uv run --with matplotlib python scripts/reproduce_figures.py --dataset DIR --out DIR
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import Counter, defaultdict
from typing import Iterable, Iterator

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from cryptocensus.batchgcd import batch_gcd
from cryptocensus.analyze import _is_deployed_key, _is_private_key, iter_records, _output_dir
from cryptocensus.extractors.certs_keys import is_crypto_config as _is_crypto_cfg

FAMILIES = ("RSA", "EC", "DSA", "Ed25519")
RSA_SIZES = ("512", "1024", "<2048", "2048", "3072", "4096")
WEAK_RSA = {"512", "1024", "<2048"}
SIG_NAMES = {"sha256": "SHA-256", "sha1": "SHA-1", "sha384": "SHA-384",
             "md5": "MD5", "sha512": "SHA-512"}
WEAK_SIG = {"SHA-1", "MD5"}

# Weak tokens are counted only in the TLS/SSH cryptographic config files (is_crypto_config,
# imported from the extractor so analyzer, extractor, and figures never drift).
TOKEN_NAMES = {"MD5": "MD5", "3DES": "3DES", "DES": "DES", "RC4": "RC4", "NULL": "NULL",
               "EXPORT": "EXPORT", "SSLV2": "SSLv2", "SSLV3": "SSLv3",
               "TLSV1.0": "TLSv1.0", "TLSV1.1": "TLSv1.1"}
TOKEN_ORDER = ["MD5", "3DES", "SSLv3", "TLSv1.1", "RC4", "NULL", "DES", "SSLv2",
               "EXPORT", "TLSv1.0"]

CCDF_X = (1, 2, 3, 4, 5, 10, 20, 50, 100, 200, 500, 1000, 2000)

# Cited headline rates from prior batch-GCD studies (external to this dataset); "this
# work" is computed. Unit differs per study and is stated in the label.
FACTORABLE_LIT = [("TLS hosts\n(% of hosts)", 0.50), ("Developer RSA\n(% of RSA keys)", 0.00056)]


# A dataset directory or a released .tar.gz archive (streamed, not extracted).
iter_records_dir = iter_records


def _key_location(path: str) -> str:
    p = path.lower()
    if any(s in p for s in ("/test", "test/", "/tests", "example", "fixture")):
        return "test/example material"
    if any(s in p for s in ("site-packages", "dist-packages", "node_modules", "/gems")):
        return "language-runtime deps"
    if "/etc/ssh" in p or "ssh_host" in p:
        return "SSH host keys"
    if "/etc/ssl" in p or "/etc/pki" in p or "/pki/" in p:
        return "system TLS dirs"
    if any(s in p for s in ("/app", "/srv", "/opt", "/home", "/var/www")):
        return "application dirs"
    return "libraries / other files"


LOCATION_ORDER = ["test/example material", "libraries / other files", "language-runtime deps",
                  "application dirs", "SSH host keys", "system TLS dirs"]


def aggregate(records: Iterable[dict], with_batchgcd: bool = True) -> dict:
    """Compute the data behind every figure. Pure over ``records``. Set
    ``with_batchgcd=False`` to skip the shared-prime scan when the factorable count is
    already known (e.g. from summary.json), which dominates the runtime."""
    family = Counter()
    rsa_size = Counter()
    sig = Counter()
    tokens = Counter()
    location = Counter()
    cert_health = Counter()
    own_certs = own_keys = rsa_sub = 0
    fpr_imgs: dict[str, set] = defaultdict(set)
    deployed_fpr_imgs: dict[str, set] = defaultdict(set)
    moduli: set[int] = set()

    for r in records:
        if not r.get("ok"):
            continue
        ref = r["reference"]
        for c in r.get("certs", []):
            if c.get("in_trust_store"):
                continue
            own_certs += 1
            family[_family_bucket(c.get("key_type"))] += 1
            rsa_sub += _count_rsa(c, rsa_size)
            sig[_sig_bucket(c.get("signature_hash"))] += 1
            if c.get("self_signed"):
                cert_health["self-signed"] += 1
            if c.get("is_ca"):
                cert_health["CA cert"] += 1
            if c.get("expired"):
                cert_health["expired"] += 1
            fpr = c.get("public_key_sha256")
            if fpr:
                fpr_imgs[fpr].add(ref)
            _collect_modulus(c, moduli)
        for k in r.get("keys", []):
            if k.get("in_trust_store"):
                continue
            own_keys += 1
            family[_family_bucket(k.get("key_type"))] += 1
            rsa_sub += _count_rsa(k, rsa_size)
            fpr = k.get("public_key_sha256")
            if fpr:
                fpr_imgs[fpr].add(ref)
            if _is_private_key(k):
                location[_key_location(k.get("path", ""))] += 1
                if fpr and _is_deployed_key(k.get("path", "")):
                    deployed_fpr_imgs[fpr].add(ref)
            _collect_modulus(k, moduli)
        for wc in r.get("weak_configs", []):
            canon = TOKEN_NAMES.get(wc.get("token", "").upper())
            if canon and _is_crypto_cfg(wc.get("path", "")):
                tokens[canon] += 1

    unique_moduli = sorted(moduli)
    factorable = batch_gcd(unique_moduli) if with_batchgcd else {}
    counts = sorted(len(s) for s in fpr_imgs.values())
    fingerprints = len(counts) or 1
    reused = sum(1 for c in counts if c > 1)
    reused_deployed = sum(1 for s in deployed_fpr_imgs.values() if len(s) > 1)
    max_share = counts[-1] if counts else 0

    def ccdf(x: int) -> float:
        return round(100.0 * sum(1 for c in counts if c >= x) / fingerprints, 2)

    rsa_own = sum(rsa_size.values())
    return {
        "own_certs": own_certs,
        "own_keys": own_keys,
        "family": [(f, family.get(f, 0)) for f in FAMILIES]
                  + [("Other", sum(v for k, v in family.items() if k not in FAMILIES))],
        "rsa_size": [(s, rsa_size.get(s, 0)) for s in RSA_SIZES]
                    + [("other", sum(v for k, v in rsa_size.items() if k not in RSA_SIZES))],
        "rsa_own": rsa_own,
        "rsa_sub2048": rsa_sub,
        "rsa_512": rsa_size.get("512", 0),
        "sig": sig.most_common(),
        "weak_sig": sum(v for k, v in sig.items() if k in WEAK_SIG),
        "tokens": _ordered_tokens(tokens),
        "location": [(l, location.get(l, 0)) for l in LOCATION_ORDER],
        "location_total": sum(location.values()),
        "fingerprints": len(counts),
        "reused": reused,
        "reused_deployed": reused_deployed,
        "reuse_ccdf": [(x, ccdf(x)) for x in CCDF_X] + [(max_share, ccdf(max_share))],
        "top_key_images": max_share,
        "rsa_moduli": len(unique_moduli),
        "factorable": len(factorable),
        "factorable_pct": round(100.0 * len(factorable) / (len(unique_moduli) or 1), 4),
        "cert_health": [(k, round(100.0 * cert_health.get(k, 0) / (own_certs or 1), 1))
                        for k in ("self-signed", "CA cert", "expired")],
    }


def _ordered_tokens(tokens: Counter) -> list[tuple[str, int]]:
    present = [(t, tokens[t]) for t in TOKEN_ORDER if tokens.get(t)]
    return present or tokens.most_common()


def _family_bucket(kt: str | None) -> str:
    return kt if kt in FAMILIES else "Other"


def _rsa_bucket(size: int | None) -> str:
    s = str(size)
    if s in RSA_SIZES:
        return s
    if isinstance(size, int) and size < 2048:
        return "<2048"
    return "other"


def _count_rsa(asset: dict, rsa_size: Counter) -> int:
    """Bucket an RSA asset for figure (b) and report whether it is sub-2048-bit."""
    if asset.get("key_type") != "RSA":
        return 0
    size = asset.get("key_size")
    rsa_size[_rsa_bucket(size)] += 1
    return 1 if isinstance(size, int) and size < 2048 else 0


def _sig_bucket(name: str | None) -> str:
    return SIG_NAMES.get((name or "").lower(), "Other")


def _collect_modulus(asset: dict, moduli: set[int]) -> None:
    hexmod = asset.get("rsa_modulus_hex")
    if hexmod:
        try:
            moduli.add(int(hexmod, 16))
        except ValueError:
            pass


def print_numbers(d: dict) -> None:
    print("=" * 60)
    print("FIGURE DATA (computed from records/)")
    print("=" * 60)
    print(f"own certs={d['own_certs']:,}  own keys={d['own_keys']:,}")
    print(f"(a) key family        : {d['family']}")
    print(f"(b) RSA key size      : {d['rsa_size']}  (RSA<2048={d['rsa_sub2048']:,}, "
          f"512={d['rsa_512']:,}, own RSA={d['rsa_own']:,})")
    print(f"(c) signature hash    : {d['sig']}")
    print(f"    weak-sig share    : {d['weak_sig']:,}/{d['own_certs']:,} "
          f"= {100.0 * d['weak_sig'] / (d['own_certs'] or 1):.1f}%")
    print(f"(d) weak tokens       : {d['tokens']}")
    print(f"fig3 key location     : {d['location']}  (total={d['location_total']:,})")
    print(f"fig4a reuse           : fingerprints={d['fingerprints']:,}, reused>1={d['reused']:,}, "
          f"reused deployed={d['reused_deployed']:,}, max share={d['top_key_images']:,}")
    print(f"fig4b factorable      : {d['factorable']}/{d['rsa_moduli']:,} = {d['factorable_pct']}%")
    print(f"fig4c cert health     : {d['cert_health']}")
    print("=" * 60)


def render(d: dict, out_dir: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({
        "font.family": "serif",
        "font.serif": ["Liberation Serif", "Nimbus Roman", "Times New Roman", "DejaVu Serif"],
        "mathtext.fontset": "cm",
        "font.size": 10.5, "axes.labelsize": 10.5, "axes.titlesize": 11,
        "xtick.labelsize": 9.5, "ytick.labelsize": 9.5, "legend.fontsize": 9,
        "figure.dpi": 300, "savefig.dpi": 300, "savefig.bbox": "tight",
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.linewidth": 0.6, "axes.axisbelow": True,
        "axes.titlepad": 4.0, "axes.labelpad": 2.5,
        "xtick.major.width": 0.6, "ytick.major.width": 0.6,
        "lines.linewidth": 1.6, "legend.frameon": False,
        "axes.grid": True, "grid.color": "#d8d8d8", "grid.linewidth": 0.5,
    })
    red, steel, grey = "#c0392b", "#34495e", "#95a5a6"

    def kfmt(v):
        if v >= 10000:
            return f"{v / 1000:.0f}k"
        if v >= 1000:
            return f"{v / 1000:.1f}k"
        return f"{v:,}"

    _posture(d, plt, out_dir, red, steel, kfmt)
    _repro(d, plt, out_dir, red, steel, grey)
    _keys(d, plt, out_dir, steel)


def _posture(d, plt, out_dir, red, steel, kfmt):
    fig, (a, b, c, e) = plt.subplots(1, 4, figsize=(7.4, 2.05))

    labels = [k for k, _ in d["family"]][::-1]
    vals = [v for _, v in d["family"]][::-1]
    a.barh(labels, vals, color=steel)
    a.set_xlim(0, max(vals) * 1.32)
    for i, v in enumerate(vals):
        a.text(v + max(vals) * 0.03, i, kfmt(v), va="center", fontsize=8.5)
    a.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v / 1000:.0f}k" if v else "0"))
    a.set_xlabel("own public-key assets")
    a.set_title("(a) key family", loc="left", fontsize=10, fontweight="bold")

    sizes = [k for k, _ in d["rsa_size"]]
    svals = [v for _, v in d["rsa_size"]]
    b.bar(sizes, svals, color=[red if s in WEAK_RSA else steel for s in sizes])
    b.set_ylim(0, (max(svals) or 1) * 1.22)
    for i, v in enumerate(svals):
        b.text(i, v + (max(svals) or 1) * 0.03, kfmt(v), ha="center", fontsize=8.5,
               color=red if sizes[i] in WEAK_RSA else "black")
    b.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v / 1000:.0f}k" if v else "0"))
    b.set_ylabel("RSA keys")
    b.set_xlabel("key size (bits)")
    b.tick_params(axis="x", rotation=38, labelsize=8.5)
    b.set_title("(b) RSA key size", loc="left", fontsize=10, fontweight="bold")

    order = sorted(d["sig"], key=lambda kv: kv[1], reverse=True)
    hl = [k for k, _ in order][::-1]
    hv = [v for _, v in order][::-1]
    c.barh(hl, hv, color=[red if h in WEAK_SIG else steel for h in hl])
    c.set_xlim(0, (max(hv) if hv else 1) * 1.32)
    for i, v in enumerate(hv):
        c.text(v + (max(hv) if hv else 1) * 0.03, i, kfmt(v), va="center", fontsize=8.5,
               color=red if hl[i] in WEAK_SIG else "black")
    c.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v / 1000:.0f}k" if v else "0"))
    c.set_xlabel("own certificates")
    c.set_title("(c) signature hash", loc="left", fontsize=10, fontweight="bold")

    tl = [k for k, _ in d["tokens"]][::-1]
    tv = [v for _, v in d["tokens"]][::-1]
    e.barh(tl, tv, color=red)
    e.set_xscale("log")
    e.set_xlim(1, 1.2e5)
    for i, v in enumerate(tv):
        e.text(v * 1.35, i, kfmt(v), va="center", fontsize=7.5)
    e.set_xlabel("config tokens (log)")
    e.set_title("(d) weak tokens", loc="left", fontsize=10, fontweight="bold")

    fig.tight_layout(w_pad=1.2)
    fig.savefig(os.path.join(out_dir, "fig_posture.pdf"))
    plt.close(fig)


def _repro(d, plt, out_dir, red, steel, grey):
    fig, (a, b, c) = plt.subplots(1, 3, figsize=(7.2, 2.15))

    xs = [p[0] for p in d["reuse_ccdf"]]
    ys = [p[1] for p in d["reuse_ccdf"]]
    two = next((y for x, y in d["reuse_ccdf"] if x == 2), 0)
    top = d["top_key_images"]
    top_y = next((y for x, y in d["reuse_ccdf"] if x == top), 0)
    a.plot(xs, ys, color=steel, marker="o", ms=2.4, lw=1.3)
    a.scatter([2], [two], color=red, s=20, zorder=4)
    a.set_xscale("log")
    a.set_yscale("log")
    a.set_xlim(0.9, max(6500, top * 1.4))
    a.set_ylim(0.02, 220)
    a.set_yticks([0.1, 1, 10, 100])
    a.set_yticklabels(["0.1%", "1%", "10%", "100%"])
    a.minorticks_off()
    a.set_xlabel("images sharing a key")
    a.set_ylabel("share of keys (CCDF)")
    a.set_title("(a) key reuse", loc="left", fontsize=10, fontweight="bold")
    a.annotate(f"{two:.0f}% in\n>1 image", xy=(2, two), xytext=(6, 60), fontsize=8, color=red,
               arrowprops=dict(arrowstyle="-", lw=0.5, color=grey))
    a.annotate(f"max {top:,}", xy=(top, top_y), xytext=(7, 0.045), fontsize=8,
               arrowprops=dict(arrowstyle="-", lw=0.5, color=grey))

    rows = [FACTORABLE_LIT[0], ("Containers, ours\n(% of moduli)", d["factorable_pct"]),
            FACTORABLE_LIT[1]][::-1]
    labels = [r[0] for r in rows]
    vals = [r[1] for r in rows]
    cols = [red if "ours" in r[0] else steel for r in rows]
    y = list(range(len(rows)))
    b.hlines(y, 1e-4, vals, color="#cfcfcf", linewidth=0.9, zorder=1)
    b.scatter(vals, y, color=cols, s=34, zorder=3)
    b.set_yticks(y)
    b.set_yticklabels(labels)
    b.set_xscale("log")
    b.set_xlim(1e-4, 3.5)
    b.set_xticks([1e-4, 1e-2, 1])
    b.set_xticklabels(["0.0001%", "0.01%", "1%"], fontsize=8.5)
    b.minorticks_off()
    b.set_xlabel("share factorable (log; unit per study)")
    b.set_title("(b) factorable rate", loc="left", fontsize=10, fontweight="bold")
    for yi, v in zip(y, vals):
        b.text(v * 2.0, yi, f"{v:g}%", va="center", fontsize=8.5)

    rows = d["cert_health"][::-1]
    labels = [r[0] for r in rows]
    vals = [r[1] for r in rows]
    cols = [red if r[0] == "expired" else steel for r in rows]
    c.barh(labels, vals, color=cols, height=0.6)
    c.set_xlim(0, 108)
    c.set_xlabel("% of own certs")
    c.set_title("(c) certificate health", loc="left", fontsize=10, fontweight="bold")
    for i, v in enumerate(vals):
        c.text(v + 2.5, i, f"{v:.0f}%", va="center", fontsize=8.5)

    fig.tight_layout(w_pad=1.2)
    fig.savefig(os.path.join(out_dir, "fig_repro.pdf"))
    plt.close(fig)


def _keys(d, plt, out_dir, steel):
    fig, ax = plt.subplots(figsize=(7.2, 1.5))
    total = d["location_total"] or 1
    rows = [(l, n, round(100.0 * n / total, 1)) for l, n in d["location"]][::-1]
    labels = [r[0] for r in rows]
    vals = [r[2] for r in rows]
    counts = [r[1] for r in rows]
    ax.barh(labels, vals, color=steel, height=0.62)
    ax.set_xlim(0, 60)
    for i, (v, n) in enumerate(zip(vals, counts)):
        ax.text(v + 0.8, i, f"{v:.1f}%  ({n:,})", va="center", fontsize=8.5)
    ax.set_xlabel(f"share of own private and SSH host keys ({total:,})")
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, "fig_keys.pdf"))
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", required=True, help="dataset directory (records/) or a released .tar.gz archive")
    ap.add_argument("--out", default=None, help="output directory for the PDFs (default: alongside --dataset)")
    ap.add_argument("--no-figures", action="store_true", help="print numbers only, skip PDFs")
    args = ap.parse_args(argv)

    src = args.dataset
    if not (os.path.isdir(os.path.join(src, "records")) or os.path.isfile(src)):
        print(f"no records/ directory or archive at {src}", file=sys.stderr)
        return 2

    data = aggregate(iter_records(src))
    print_numbers(data)
    if not args.no_figures:
        out = args.out or _output_dir(src)
        os.makedirs(out, exist_ok=True)
        render(data, out)
        print(f"wrote fig_posture.pdf, fig_repro.pdf, fig_keys.pdf to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
