"""Built-in certificate/key extractor — the calibrated measurement instrument.

It walks the root filesystem once and parses every X.509 certificate, private key,
public key, and SSH key it finds using the `cryptography` library (standard
PEM/DER/X.509/SSH parsing). It also records weak primitive tokens that appear in
TLS/SSH configuration files.

Certificates are tagged with `in_trust_store` so the analyzer can separate the CA
trust bundle shipped by the base OS from cryptographic material introduced by the
image author. This extractor's counts have been calibrated against an independent
tool (CBOM-Lens) and agree exactly on reference images.
"""

from __future__ import annotations

import datetime
import hashlib
import os
import re
import warnings

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import dh, dsa, ec, ed448, ed25519, rsa
from cryptography.utils import CryptographyDeprecationWarning

# Some legacy root CAs in trust bundles carry non-positive serial numbers (disallowed
# by RFC 5280). cryptography emits a deprecation warning when parsing them; we parse
# defensively and skip on hard failure, so the warning is benign noise. Suppress only
# that specific message to keep census logs readable.
warnings.filterwarnings(
    "ignore", message="Parsed a serial number", category=CryptographyDeprecationWarning
)

from ..classify import is_weak_key, is_weak_signature_hash, pq_status
from ..schema import CertRecord, KeyRecord, WeakConfigRecord

_TRUST_MARKERS = (
    "/etc/ssl/certs/",
    "/usr/share/ca-certificates",
    "/usr/local/share/ca-certificates",
    "/etc/ca-certificates",
    "/etc/pki/",
    "/ssl/cert.pem",
    "ca-certificates.crt",
    "/certifi/",
)
_WEAK_CIPHER_RE = re.compile(
    rb"\b(RC4|DES|3DES|MD5|NULL|EXPORT|SSLv2|SSLv3|TLSv1\.0|TLSv1\.1)\b", re.IGNORECASE
)
_CONFIG_NAMES = {"sshd_config", "ssh_config", "openssl.cnf"}
_NOW = datetime.datetime.now(datetime.timezone.utc)


def _in_trust_store(path: str) -> bool:
    return any(marker in path for marker in _TRUST_MARKERS)


def _key_info(public_key) -> tuple[str, int | None, int | None]:
    """Return (family, key_size_bits, rsa_modulus or None)."""
    if isinstance(public_key, rsa.RSAPublicKey):
        return "RSA", public_key.key_size, public_key.public_numbers().n
    if isinstance(public_key, ec.EllipticCurvePublicKey):
        return "EC", public_key.curve.key_size, None
    if isinstance(public_key, dsa.DSAPublicKey):
        return "DSA", public_key.key_size, None
    if isinstance(public_key, ed25519.Ed25519PublicKey):
        return "Ed25519", 256, None
    if isinstance(public_key, ed448.Ed448PublicKey):
        return "Ed448", 448, None
    if isinstance(public_key, dh.DHPublicKey):
        return "DH", public_key.key_size, None
    return type(public_key).__name__, None, None


def _fingerprint(public_key) -> str | None:
    try:
        der = public_key.public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return hashlib.sha256(der).hexdigest()
    except Exception:
        return None


def _cert_expired(cert: x509.Certificate) -> bool:
    try:
        return cert.not_valid_after_utc < _NOW
    except AttributeError:  # cryptography < 42
        naive = cert.not_valid_after
        aware = naive.replace(tzinfo=datetime.timezone.utc) if naive.tzinfo is None else naive
        return aware < _NOW


def _make_cert_record(cert: x509.Certificate, path: str, trust: bool) -> CertRecord:
    family, size, modulus = _key_info(cert.public_key())
    sig = cert.signature_hash_algorithm
    sig_name = sig.name if sig else "none"
    try:
        is_ca = cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
    except x509.ExtensionNotFound:
        is_ca = False
    try:
        san_count = len(cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value)
    except x509.ExtensionNotFound:
        san_count = 0
    return CertRecord(
        path=path,
        in_trust_store=trust,
        signature_hash=sig_name,
        weak_signature=is_weak_signature_hash(sig_name),
        key_type=family,
        key_size=size,
        weak_key=is_weak_key(family, size),
        expired=_cert_expired(cert),
        self_signed=(cert.issuer == cert.subject),
        is_ca=is_ca,
        san_count=san_count,
        pq_status=pq_status(family),
        public_key_sha256=_fingerprint(cert.public_key()),
        rsa_modulus_hex=(hex(modulus) if modulus else None),
    )


def _make_key_record(public_key, path: str, trust: bool, kind: str) -> KeyRecord:
    family, size, modulus = _key_info(public_key)
    return KeyRecord(
        path=path,
        in_trust_store=trust,
        kind=kind,
        key_type=family,
        key_size=size,
        weak_key=is_weak_key(family, size),
        pq_status=pq_status(family),
        public_key_sha256=_fingerprint(public_key),
        rsa_modulus_hex=(hex(modulus) if modulus else None),
    )


def extract(root: str, max_file_bytes: int = 2_000_000):
    """Return (certs, keys, weak_configs, files_scanned)."""
    certs: list[CertRecord] = []
    keys: list[KeyRecord] = []
    weak_configs: list[WeakConfigRecord] = []
    files_scanned = 0

    for dirpath, _dirs, filenames in os.walk(root):
        for filename in filenames:
            path = os.path.join(dirpath, filename)
            try:
                if not os.path.isfile(path) or os.path.islink(path):
                    continue
                size = os.path.getsize(path)
                if size == 0 or size > max_file_bytes:
                    continue
                with open(path, "rb") as handle:
                    data = handle.read()
            except OSError:
                continue

            rel = path[len(root):] or "/"
            trust = _in_trust_store(path)
            lower = filename.lower()

            if filename in _CONFIG_NAMES or lower.endswith((".conf", ".cnf")):
                for token in {m.decode("latin1") for m in _WEAK_CIPHER_RE.findall(data)}:
                    weak_configs.append(WeakConfigRecord(path=rel, token=token))

            # SSH host/public keys.
            if filename.startswith("ssh_host_") or lower.endswith(".pub") or "authorized_keys" in lower:
                try:
                    if b"PRIVATE" in data[:64]:
                        key = serialization.load_ssh_private_key(data, password=None)
                        keys.append(_make_key_record(key.public_key(), rel, trust, "ssh"))
                    else:
                        key = serialization.load_ssh_public_key(data.split(b"\n")[0])
                        keys.append(_make_key_record(key, rel, trust, "ssh"))
                    continue
                except Exception:
                    pass

            # DER-encoded certificates (no PEM armor).
            if lower.endswith((".der", ".crt", ".cer")) and b"-----BEGIN" not in data:
                try:
                    certs.append(_make_cert_record(x509.load_der_x509_certificate(data), rel, trust))
                except Exception:
                    pass
                continue

            if b"-----BEGIN" not in data:
                continue
            files_scanned += 1
            for chunk in data.split(b"-----BEGIN ")[1:]:
                block = b"-----BEGIN " + chunk
                header = block[:46]
                try:
                    if b"CERTIFICATE-----" in header:
                        certs.append(_make_cert_record(x509.load_pem_x509_certificate(block), rel, trust))
                    elif b"PRIVATE KEY-----" in header:
                        key = serialization.load_pem_private_key(block, password=None)
                        keys.append(_make_key_record(key.public_key(), rel, trust, "private"))
                    elif b"PUBLIC KEY-----" in header:
                        key = serialization.load_pem_public_key(block)
                        keys.append(_make_key_record(key, rel, trust, "public"))
                except Exception:
                    pass

    return certs, keys, weak_configs, files_scanned
