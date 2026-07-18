"""Classification of cryptographic primitives.

Two orthogonal questions are answered here:

1. Post-quantum status of a *public-key* primitive. Shor's algorithm breaks the
   integer-factorization and discrete-logarithm problems, so RSA/DSA/DH and all
   elliptic-curve schemes are *quantum-vulnerable*. The NIST FIPS 203/204/205
   families (ML-KEM, ML-DSA, SLH-DSA) and other lattice/hash/code schemes are
   *post-quantum*.
2. Whether a signature hash or a key size is *weak* by current deployment
   guidance (NIST SP 800-57, SP 800-131A; OWASP).

References:
  - NIST FIPS 203 (ML-KEM), 204 (ML-DSA), 205 (SLH-DSA), Aug 2024.
  - NIST IR 8547, transition to post-quantum cryptography standards.
  - NIST SP 800-131A Rev. 2, transitioning the use of cryptographic algorithms.
"""

from __future__ import annotations

import re

# OpenSSL library packages whose version tracks OpenSSL itself (Debian and Alpine
# naming). Matched exactly so that OpenSSL-linking packages like libcurl4-openssl-dev
# are not mistaken for OpenSSL.
_OPENSSL_PKG = re.compile(r"^(openssl|libssl\d*|libcrypto\d*)(-dev|-libs)?$")

# Public-key families broken by a cryptographically relevant quantum computer.
QUANTUM_VULNERABLE_FAMILIES = {
    "RSA", "DSA", "DH", "ELGAMAL",
    "EC", "ECDSA", "ECDH", "ECMQV", "ECC", "EDDSA", "ED25519", "ED448",
    "X25519", "X448",
}

# Post-quantum families (NIST standards + common round-3/4 names).
POST_QUANTUM_FAMILIES = {
    "ML-KEM", "MLKEM", "KYBER",
    "ML-DSA", "MLDSA", "DILITHIUM",
    "SLH-DSA", "SLHDSA", "SPHINCS",
    "FN-DSA", "FALCON",
    "FRODOKEM", "FRODO", "HQC", "BIKE", "CLASSIC-MCELIECE", "MCELIECE",
    "XMSS", "LMS",  # stateful hash-based signatures (quantum-resistant)
}

SYMMETRIC_FAMILIES = {"AES", "CHACHA20", "CHACHA", "CAMELLIA", "ARIA", "3DES", "DES", "RC4", "BLOWFISH"}
HASH_FAMILIES = {"SHA1", "SHA-1", "SHA224", "SHA256", "SHA384", "SHA512", "SHA3", "MD5", "MD4", "BLAKE2", "SM3"}

# Weak signature hash algorithms (collision-broken / deprecated for signatures).
WEAK_SIGNATURE_HASHES = {"md5", "md4", "md2", "sha1", "sha-1"}
# Broken/legacy symmetric primitives that must not appear in TLS/SSH configs.
WEAK_SYMMETRIC = {"rc4", "des", "3des", "tripledes", "null", "export"}

# Minimum secure key sizes (bits).
MIN_RSA_BITS = 2048
MIN_DSA_BITS = 2048
MIN_EC_BITS = 256


def _normalize(name: str) -> str:
    return (name or "").strip().upper().replace("_", "-")


def pq_status(algorithm: str) -> str:
    """Return one of: 'quantum-vulnerable', 'post-quantum', 'symmetric', 'hash', 'unknown'.

    Accepts public-key family names ("RSA", "EC"), composite signature names
    ("ECDSA-SHA384", "SHA256-RSA"), and PQC names ("ML-KEM", "Kyber").
    """
    n = _normalize(algorithm)
    if not n:
        return "unknown"
    # A composite/hybrid name (e.g. "X25519-ML-KEM-768") is post-quantum if any PQ
    # family name appears anywhere in it, so test PQ membership by substring first.
    if any(family in n for family in POST_QUANTUM_FAMILIES):
        return "post-quantum"
    tokens = set(n.replace("+", "-").split("-")) | {n}
    for t in tokens:
        if t in QUANTUM_VULNERABLE_FAMILIES:
            return "quantum-vulnerable"
    # Some parsers report the public-key class name rather than the bare family
    # (e.g. "X25519PUBLICKEY", "ED25519PRIVATEKEY"); match a vulnerable family as a
    # substring so these classical schemes are not left "unknown".
    for family in QUANTUM_VULNERABLE_FAMILIES:
        if family in n:
            return "quantum-vulnerable"
    for t in tokens:
        if t in SYMMETRIC_FAMILIES:
            return "symmetric"
    for t in tokens:
        if t in HASH_FAMILIES:
            return "hash"
    return "unknown"


def is_weak_signature_hash(hash_name: str) -> bool:
    return (hash_name or "").strip().lower() in WEAK_SIGNATURE_HASHES


def is_weak_key(key_type: str, key_size: int | None) -> bool:
    """Return True if a public key is below the minimum secure size for its family."""
    if key_size is None:
        return False
    fam = _normalize(key_type)
    if fam == "RSA":
        return key_size < MIN_RSA_BITS
    if fam == "DSA":
        return key_size < MIN_DSA_BITS
    if fam in ("EC", "ECDSA", "ECDH", "ECC"):
        return key_size < MIN_EC_BITS
    return False


def library_pqc_capable(name: str, version: str) -> bool:
    """Heuristic, version-based PQC capability fingerprint (in the spirit of QED-Lite,
    IACR ePrint 2026/660): a deployed library can negotiate post-quantum schemes only
    if its version is recent enough. This is a *capability* signal, not *usage*.

    Conservative thresholds:
      - openssl/libssl/libcrypto >= 3.5 ship native ML-KEM/ML-DSA.
      - any package whose name references oqs/liboqs is PQC-capable by construction.

    The name is matched exactly against the OpenSSL library packages, not as a
    substring: a substring match wrongly flags packages that merely link OpenSSL,
    such as ``libcurl4-openssl-dev`` (whose 7.x/8.x version trivially exceeds 3.5).
    """
    n = (name or "").lower()
    v = (version or "").strip()
    if "oqs" in n:
        return True
    # Actual OpenSSL library packages, whose version tracks OpenSSL's own.
    if _OPENSSL_PKG.match(n):
        # Compare the leading "major.minor" numerically against 3.5, dropping any
        # Debian epoch prefix ("1:3.5.0" -> "3.5.0").
        try:
            parts = v.split(":")[-1].replace("~", ".").replace("-", ".").split(".")
            major = int(parts[0])
            minor = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
            return (major, minor) >= (3, 5)
        except (ValueError, IndexError):
            return False
    return False
