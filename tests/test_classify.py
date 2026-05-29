from cryptocensus.classify import (
    is_weak_key,
    is_weak_signature_hash,
    library_pqc_capable,
    pq_status,
)


def test_pq_status_public_key_families():
    assert pq_status("RSA") == "quantum-vulnerable"
    assert pq_status("EC") == "quantum-vulnerable"
    assert pq_status("ECDSA-SHA384") == "quantum-vulnerable"
    assert pq_status("Ed25519") == "quantum-vulnerable"


def test_pq_status_post_quantum():
    assert pq_status("ML-KEM") == "post-quantum"
    assert pq_status("Kyber") == "post-quantum"
    assert pq_status("ML-DSA-65") == "post-quantum"
    assert pq_status("SPHINCS+") == "post-quantum"
    # Hybrid: a PQ part makes the suite post-quantum.
    assert pq_status("X25519-ML-KEM-768") == "post-quantum"


def test_pq_status_other():
    assert pq_status("AES") == "symmetric"
    assert pq_status("SHA256") == "hash"
    assert pq_status("") == "unknown"


def test_weak_signature_and_key():
    assert is_weak_signature_hash("sha1")
    assert is_weak_signature_hash("MD5")
    assert not is_weak_signature_hash("sha256")
    assert is_weak_key("RSA", 1024)
    assert not is_weak_key("RSA", 2048)
    assert is_weak_key("EC", 160)
    assert not is_weak_key("EC", 256)
    assert not is_weak_key("Ed25519", 256)


def test_library_pqc_capability():
    assert library_pqc_capable("openssl", "3.5.6-1")
    assert library_pqc_capable("libssl3", "3.6.0")
    assert not library_pqc_capable("openssl", "3.0.13")
    assert not library_pqc_capable("libgcrypt20", "1.10.1")
    assert library_pqc_capable("liboqs", "0.10")
