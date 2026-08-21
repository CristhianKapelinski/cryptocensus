import os

import pytest

from cryptocensus import worker
from cryptocensus.config import Settings
from cryptocensus.image import ImagePullError
from cryptocensus.schema import CertRecord, ImageResult
from cryptocensus.transport import decode_bundle
from cryptocensus.worker import (
    _force_rmtree,
    _is_transient,
    _pull_locked,
    _safe_name,
    process_image,
    run_worker,
)


def test_safe_name_sanitizes_reference():
    assert _safe_name("library/alpine:latest") == "library_alpine_latest"
    assert _safe_name("alpine") == "alpine"
    assert _safe_name("a/b+c") == "a_b_c"


def test_force_rmtree_removes_restrictive_dirs(tmp_path):
    root = tmp_path / "tree"
    sub = root / "nested" / "deeper"
    sub.mkdir(parents=True)
    (sub / "f").write_text("x")
    os.chmod(sub, 0o500)  # read-only: a plain rmtree would fail here
    _force_rmtree(str(root))
    assert not root.exists()


def test_force_rmtree_noop_on_missing(tmp_path):
    _force_rmtree(str(tmp_path / "nope"))  # must not raise


def test_is_transient_markers():
    assert _is_transient("write /tmp: no space left on device")
    assert _is_transient("i/o timeout")
    assert _is_transient("429 Too Many Requests")
    assert _is_transient("connection reset by peer")
    assert not _is_transient("MANIFEST_UNKNOWN: not found")
    assert not _is_transient(None)
    assert not _is_transient("")


def test_pull_locked_without_mutex_calls_export_directly(monkeypatch, tmp_path):
    s = Settings(work_dir=str(tmp_path), pull_mutex_enabled=False, crane_bin="crane")
    calls = []
    monkeypatch.setattr(worker, "export_rootfs",
                        lambda *a, **k: calls.append((a, k)) or "sha256:d")
    assert _pull_locked("alpine", str(tmp_path / "w"), s, None) == "sha256:d"
    assert calls[0][0][0] == "alpine"
    assert calls[0][1]["crane_bin"] == "crane"


def test_pull_locked_acquires_and_releases_mutex(monkeypatch, tmp_path):
    s = Settings(work_dir=str(tmp_path), pull_mutex_enabled=True, pull_mutex_wait_s=0.01)
    events = []

    class _Q:
        def acquire_pull_lock(self, token):
            events.append(("acquire", token))
            return True

        def release_pull_lock(self, token):
            events.append(("release", token))

    def _export(*a, **k):
        events.append(("export", k["crane_bin"]))
        return "sha256:d"
    monkeypatch.setattr(worker, "export_rootfs", _export)
    assert _pull_locked("alpine", str(tmp_path / "w"), s, _Q()) == "sha256:d"
    assert events[0][0] == "acquire"
    assert events[1] == ("export", "crane")
    assert events[-1][0] == "release"
    # The lock token is host-scoped by pid and names the image being pulled.
    token = events[0][1]
    assert "alpine" in token and str(os.getpid()) in token


def test_pull_locked_waits_when_lock_busy(monkeypatch, tmp_path):
    s = Settings(work_dir=str(tmp_path), pull_mutex_enabled=True, pull_mutex_wait_s=0.0)
    attempts = {"n": 0}
    sleeps = []

    class _Q:
        def acquire_pull_lock(self, token):
            attempts["n"] += 1
            return attempts["n"] >= 3

        def release_pull_lock(self, token):
            pass
    monkeypatch.setattr(worker, "export_rootfs", lambda *a, **k: "sha256:d")
    monkeypatch.setattr(worker.time, "sleep", lambda secs: sleeps.append(secs))
    assert _pull_locked("alpine", str(tmp_path / "w"), s, _Q()) == "sha256:d"
    assert attempts["n"] == 3
    assert len(sleeps) == 2


def test_process_image_pull_failure_returns_non_ok(monkeypatch, tmp_path):
    s = Settings(work_dir=str(tmp_path), enable_certs_keys=True)

    def _boom(*a, **k):
        raise ImagePullError("registry down")
    monkeypatch.setattr(worker, "_pull_locked", _boom)
    result, raw = process_image("alpine", s, None)
    assert result.ok is False
    assert result.error == "pull: registry down"
    assert "pull failed" in raw["log"]


def test_process_image_runs_extractors_and_cleans_workdir(monkeypatch, tmp_path):
    s = Settings(work_dir=str(tmp_path), enable_certs_keys=True, enable_libraries=True,
                 enable_syft=False, enable_secrets=False, enable_cbom_lens=False,
                 max_file_bytes=1000)

    def _fake_pull(ref, w, settings, queue):
        os.makedirs(w, exist_ok=True)
        with open(os.path.join(w, "file.txt"), "w") as fh:
            fh.write("hi")
        return "sha256:abc"
    monkeypatch.setattr(worker, "_pull_locked", _fake_pull)
    cert = CertRecord(path="etc/x.pem", in_trust_store=False, signature_hash="sha256",
                      weak_signature=False, key_type="RSA", key_size=2048, weak_key=False,
                      expired=False, self_signed=True, is_ca=False, san_count=0,
                      pq_status="quantum-vulnerable")
    monkeypatch.setattr(worker.certs_keys, "extract",
                        lambda root, max_bytes: ([cert], [], [], 1, {"deadbeef": b"\x30\x82"}))
    monkeypatch.setattr(worker.libraries, "extract",
                        lambda root: [{"name": "openssl", "version": "3.0.13",
                                       "source": "dpkg", "pqc_capable": False}])

    result, raw = process_image("alpine", s, None)
    assert result.ok is True and result.digest == "sha256:abc"
    assert result.certs == [cert]
    assert len(result.tool_observations) == 1
    assert result.tool_observations[0].tool == "builtin"
    assert raw["blobs"] == {"deadbeef": b"\x30\x82"}
    assert raw["builtin_cbom"]["bomFormat"] == "CycloneDX"
    assert "pull ok" in raw["log"]
    # The flattened rootfs is removed once processing finishes.
    assert not (tmp_path / "alpine").exists()


def test_process_image_cleans_up_on_extractor_error(monkeypatch, tmp_path):
    s = Settings(work_dir=str(tmp_path), enable_certs_keys=True, enable_syft=False)
    monkeypatch.setattr(worker, "_pull_locked",
                        lambda *a, **k: (os.makedirs(a[1], exist_ok=True) or "sha256:d"))
    monkeypatch.setattr(worker.certs_keys, "extract",
                        lambda root, max_bytes: (_ for _ in ()).throw(ValueError("boom")))
    with pytest.raises(ValueError):
        process_image("alpine", s, None)
    assert not (tmp_path / "alpine").exists()


def test_run_worker_exits_when_idle(monkeypatch, tmp_path):
    s = Settings(work_dir=str(tmp_path), docker_config="")

    class _Q:
        def claim(self):
            return None

        def stats(self):
            return {"pending": 0, "processing": 0, "results_pending": 0, "done": 0}
    monkeypatch.setattr(worker, "TaskQueue", lambda settings: _Q())
    monkeypatch.setattr(worker, "ensure_login", lambda *a, **k: "test")
    run_worker(s, idle_exit=1)  # must return, not loop forever


def test_run_worker_processes_and_acks(monkeypatch, tmp_path):
    s = Settings(work_dir=str(tmp_path), docker_config="")

    class _Q:
        def __init__(self):
            self.claims = iter(["alpine", None])
            self.pushed = []
            self.acked = []

        def claim(self):
            return next(self.claims, None)

        def stats(self):
            return {"processing": 0}

        def push_result(self, payload):
            self.pushed.append(payload)

        def ack(self, reference):
            self.acked.append(reference)
    queue = _Q()
    monkeypatch.setattr(worker, "TaskQueue", lambda settings: queue)
    monkeypatch.setattr(worker, "ensure_login", lambda *a, **k: "test")
    ok = ImageResult(reference="alpine", digest="sha256:abc", ok=True)
    monkeypatch.setattr(worker, "process_image", lambda ref, s, q: (ok, {"log": "", "blobs": {}}))
    run_worker(s, idle_exit=1)
    assert queue.acked == ["alpine"]
    assert len(queue.pushed) == 1
    record, _cbom, _raw = decode_bundle(queue.pushed[0])
    assert record["reference"] == "alpine"


def test_run_worker_requeues_transient_failures(monkeypatch, tmp_path):
    s = Settings(work_dir=str(tmp_path), docker_config="", max_transient_retries=5)

    class _Q:
        def __init__(self):
            self.claims = iter(["img", None])
            self.requeued = []
            self.retries = 0

        def claim(self):
            return next(self.claims, None)

        def stats(self):
            return {"processing": 0}

        def transient_retry(self, ref):
            self.retries += 1
            return self.retries

        def requeue(self, ref):
            self.requeued.append(ref)

        def push_result(self, payload):
            raise AssertionError("transient results must not be pushed")

        def ack(self, ref):
            raise AssertionError("transient failures must not be acked")
    queue = _Q()
    monkeypatch.setattr(worker, "TaskQueue", lambda settings: queue)
    monkeypatch.setattr(worker, "ensure_login", lambda *a, **k: "test")
    failed = ImageResult(reference="img", digest=None, ok=False, error="i/o timeout")
    monkeypatch.setattr(worker, "process_image", lambda ref, s, q: (failed, {"log": ""}))
    run_worker(s, idle_exit=1)
    assert queue.requeued == ["img"]


def test_run_worker_copies_docker_config_to_writable(monkeypatch, tmp_path):
    s = Settings(work_dir=str(tmp_path), docker_config=str(tmp_path), crane_bin="crane",
                 registry="index.docker.io")
    (tmp_path / "config.json").write_text('{"auths": {}}')
    copied = []
    login_cfg = []
    monkeypatch.setattr(worker.shutil, "copy",
                        lambda src, dst: copied.append((src, dst)))
    monkeypatch.setattr(worker.os, "makedirs", lambda *a, **k: None)
    fake_env = {}
    monkeypatch.setattr(worker.os, "environ", fake_env)

    class _Q:
        def claim(self):
            return None

        def stats(self):
            return {"processing": 0}
    monkeypatch.setattr(worker, "TaskQueue", lambda settings: _Q())
    monkeypatch.setattr(worker, "ensure_login",
                        lambda crane, registry, cfg: login_cfg.append(cfg) or "logged")
    run_worker(s, idle_exit=1)
    assert copied == [(str(tmp_path / "config.json"), "/tmp/cc-dockercfg/config.json")]
    assert fake_env["DOCKER_CONFIG"] == "/tmp/cc-dockercfg"
    assert login_cfg == ["/tmp/cc-dockercfg"]
