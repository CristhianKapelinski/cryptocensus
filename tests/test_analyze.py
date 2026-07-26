from cryptocensus.analyze import aggregate


def _cert(**kw):
    base = dict(in_trust_store=False, signature_hash="sha256", weak_signature=False,
                key_type="RSA", key_size=2048, weak_key=False, expired=False,
                self_signed=True, is_ca=False, san_count=0, pq_status="quantum-vulnerable",
                public_key_sha256="fp-cert", rsa_modulus_hex=None)
    base.update(kw)
    return base


def _image(ref, **kw):
    base = dict(reference=ref, digest="d", ok=True, error=None, files_scanned=1,
                certs=[], keys=[], libraries=[], weak_configs=[], tool_observations=[])
    base.update(kw)
    return base


def test_pqc_recomputed_from_version_not_stored_flag():
    # Stored flag says capable, but openssl 3.0 is not; the recompute must win.
    stale = _image("a", libraries=[{"name": "openssl", "version": "3.0.13",
                                    "source": "dpkg", "pqc_capable": True}])
    real = _image("b", libraries=[{"name": "libssl3", "version": "3.5.4-r0",
                                   "source": "apk", "pqc_capable": False}])
    summary, *_ = aggregate([stale, real])
    assert summary["images_with_pqc_capable_library"] == 1


def test_own_vs_trust_store_split_and_posture():
    img = _image("x", certs=[
        _cert(in_trust_store=False, weak_signature=True, signature_hash="sha1"),
        _cert(in_trust_store=True),
    ])
    summary, *_ = aggregate([img])
    assert summary["certs_total"] == 2
    assert summary["certs_non_trust_store"] == 1
    assert summary["certs_non_trust_store_weak_signature"] == 1
    assert summary["quantum_vulnerable_pct"] == 100.0
    assert summary["post_quantum"] == 0


def test_reuse_and_factorable_on_own_material():
    shared = "fp-shared"
    imgs = [
        _image("i1", keys=[{"in_trust_store": False, "kind": "private", "key_type": "RSA",
                            "key_size": 2048, "weak_key": False, "pq_status": "quantum-vulnerable",
                            "public_key_sha256": shared, "rsa_modulus_hex": None}]),
        _image("i2", keys=[{"in_trust_store": False, "kind": "private", "key_type": "RSA",
                            "key_size": 2048, "weak_key": False, "pq_status": "quantum-vulnerable",
                            "public_key_sha256": shared, "rsa_modulus_hex": None}]),
    ]
    summary, *_ = aggregate(imgs)
    assert summary["non_trust_store_key_fingerprints"] == 1
    assert summary["non_trust_store_keys_reused_across_images"] == 1
