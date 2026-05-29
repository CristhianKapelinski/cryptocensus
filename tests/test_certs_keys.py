"""End-to-end test of the built-in extractor against synthesized material."""

import datetime
import os

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import NameOID

from cryptocensus.extractors import certs_keys


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(data)


def _self_signed(key, hash_alg):
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "cryptocensus.test")])
    now = datetime.datetime.now(datetime.timezone.utc)
    return (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=365))
        .sign(key, hash_alg)
    )


def test_extract_certs_and_keys(tmp_path):
    root = str(tmp_path)

    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cert = _self_signed(rsa_key, hashes.SHA256())
    _write(os.path.join(root, "etc/app/server.crt"),
           cert.public_bytes(serialization.Encoding.PEM))
    _write(os.path.join(root, "etc/app/server.key"),
           rsa_key.private_bytes(serialization.Encoding.PEM,
                                 serialization.PrivateFormat.PKCS8,
                                 serialization.NoEncryption()))

    # A trust-store certificate (should be tagged in_trust_store).
    ca = _self_signed(rsa.generate_private_key(public_exponent=65537, key_size=2048), hashes.SHA256())
    _write(os.path.join(root, "etc/ssl/certs/ca.pem"),
           ca.public_bytes(serialization.Encoding.PEM))

    # An EC public key (own material).
    ec_key = ec.generate_private_key(ec.SECP256R1())
    _write(os.path.join(root, "opt/keys/ec.pub"),
           ec_key.public_key().public_bytes(serialization.Encoding.PEM,
                                             serialization.PublicFormat.SubjectPublicKeyInfo))

    certs, keys, weak_configs, files_scanned, blobs = certs_keys.extract(root)
    # Raw bytes of every parsed cert/key are retained, content-addressed by sha256.
    assert len(blobs) >= 3
    assert all(isinstance(v, (bytes, bytearray)) for v in blobs.values())

    assert len(certs) == 2
    own = [c for c in certs if not c.in_trust_store]
    trust = [c for c in certs if c.in_trust_store]
    assert len(own) == 1 and len(trust) == 1
    assert own[0].key_type == "RSA" and own[0].key_size == 2048
    assert all(c.pq_status == "quantum-vulnerable" for c in certs)
    assert all(c.self_signed for c in certs)

    private_keys = [k for k in keys if k.kind == "private"]
    assert len(private_keys) == 1 and private_keys[0].key_type == "RSA"
    assert any(k.key_type == "EC" for k in keys)
    assert files_scanned >= 3
