import base64
import io
import json
import os
import subprocess
import tarfile

import pytest

from cryptocensus import image
from cryptocensus.image import (
    ImagePullError,
    ImageTooLarge,
    _compressed_size,
    _crane,
    _permanent,
    _safe_extract,
    ensure_login,
    export_rootfs,
    image_digest,
    pin_to_digest,
)


def _write_tar(path, members):
    """members: ("DIR", name) for dirs, (name, data) for regular files."""
    with tarfile.open(path, "w") as tar:
        for member in members:
            if member[0] == "DIR":
                info = tarfile.TarInfo(member[1])
                info.type = tarfile.DIRTYPE
                tar.addfile(info)
            else:
                name, data = member
                if isinstance(data, str):
                    data = data.encode()
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))


def test_pin_to_digest_preserves_pinned_and_appends_digest():
    assert pin_to_digest("alpine:latest", "sha256:abc") == "alpine@sha256:abc"
    assert pin_to_digest("alpine", "sha256:abc") == "alpine@sha256:abc"
    assert pin_to_digest("reg.io/team/img:1.0", "sha256:abc") == "reg.io/team/img@sha256:abc"
    # Already pinned: the caller's digest is ignored, the reference wins.
    assert pin_to_digest("library/alpine@sha256:abc", "sha256:other") == "library/alpine@sha256:abc"


def test_permanent_matches_gone_errors_not_transient():
    assert _permanent("MANIFEST_UNKNOWN: repo not found")
    assert _permanent("unauthorized: authentication required")
    assert _permanent("NAME_UNKNOWN: 404")
    assert not _permanent("429 Too Many Requests")
    assert not _permanent("i/o timeout")
    assert not _permanent("")


def test_safe_extract_writes_regular_files_and_dirs(tmp_path):
    dest = tmp_path / "out"
    tar_path = tmp_path / "rootfs.tar"
    _write_tar(tar_path, [("DIR", "etc/app"), ("etc/app/server.crt", b"CRT"), ("opt/lib/x.so", b"ELF")])
    _safe_extract(str(tar_path), str(dest))
    assert (dest / "etc/app").is_dir()
    assert (dest / "etc/app/server.crt").read_bytes() == b"CRT"
    assert (dest / "opt/lib/x.so").read_bytes() == b"ELF"


def test_safe_extract_blocks_path_traversal(tmp_path):
    # Members that resolve outside dest must be dropped, not extracted.
    dest = tmp_path / "out"
    dest.mkdir()
    tar_path = tmp_path / "evil.tar"
    _write_tar(tar_path, [("../evil.txt", b"ESCAPED"), ("sub/../../evil2.txt", b"ESCAPED"),
                          ("ok.txt", b"OK")])
    _safe_extract(str(tar_path), str(dest))
    assert not (tmp_path / "evil.txt").exists()
    assert not (tmp_path / "evil2.txt").exists()
    assert (dest / "ok.txt").read_bytes() == b"OK"


def test_safe_extract_skips_symlinks(tmp_path):
    # A symlink member must not be materialized into the destination.
    dest = tmp_path / "out"
    dest.mkdir()
    tar_path = tmp_path / "links.tar"
    with tarfile.open(tar_path, "w") as tar:
        info = tarfile.TarInfo("etc")
        info.type = tarfile.DIRTYPE
        tar.addfile(info)
        link = tarfile.TarInfo("etc/pointer")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        tar.addfile(link)
    _safe_extract(str(tar_path), str(dest))
    assert (dest / "etc").is_dir()
    assert not (dest / "etc/pointer").exists()


def test_safe_extract_raises_when_budget_exceeded(tmp_path):
    dest = tmp_path / "out"
    tar_path = tmp_path / "big.tar"
    _write_tar(tar_path, [("payload.bin", b"x" * 100)])
    with pytest.raises(ImageTooLarge):
        _safe_extract(str(tar_path), str(dest), max_extract_bytes=50)
    assert not (dest / "payload.bin").exists()


def test_safe_extract_writes_all_within_budget(tmp_path):
    dest = tmp_path / "out"
    tar_path = tmp_path / "med.tar"
    _write_tar(tar_path, [("a.bin", b"x" * 10), ("b.bin", b"y" * 20)])
    _safe_extract(str(tar_path), str(dest), max_extract_bytes=100)
    assert (dest / "a.bin").read_bytes() == b"x" * 10
    assert (dest / "b.bin").read_bytes() == b"y" * 20


def test_crane_returns_parsed_output(monkeypatch):
    class _Proc:
        returncode = 0
        stdout = "  sha256:abc  \n"
        stderr = ""
    monkeypatch.setattr(image.subprocess, "run", lambda *a, **k: _Proc())
    assert _crane(["crane", "digest", "x"], 5) == (0, "sha256:abc", "")


def test_crane_handles_timeout_and_missing_binary(monkeypatch):
    def _timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("crane", 5)
    monkeypatch.setattr(image.subprocess, "run", _timeout)
    assert _crane(["crane", "digest", "x"], 5) == (1, "", "timed out")

    def _missing(*args, **kwargs):
        raise FileNotFoundError
    monkeypatch.setattr(image.subprocess, "run", _missing)
    with pytest.raises(ImagePullError, match="crane binary not found"):
        _crane(["crane", "digest", "x"], 5)


def test_ensure_login_skips_without_config(monkeypatch):
    calls = []
    monkeypatch.setattr(image.subprocess, "run", lambda *a, **k: calls.append(a))
    assert ensure_login("crane", "index.docker.io", None) == "no DOCKER_CONFIG; skipping login"
    assert ensure_login("crane", "index.docker.io", "") == "no DOCKER_CONFIG; skipping login"
    assert calls == []


def test_ensure_login_uses_docker_hub_credentials(monkeypatch, tmp_path):
    cred = base64.b64encode(b"user:secret").decode()
    (tmp_path / "config.json").write_text(json.dumps(
        {"auths": {"https://index.docker.io/v1/": {"auth": cred}}}))
    captured = {}

    def _fake_run(args, **kwargs):
        captured["args"] = args
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
    monkeypatch.setattr(image.subprocess, "run", _fake_run)
    status = ensure_login("crane", "index.docker.io", str(tmp_path))
    assert status == "logged in as user"
    assert captured["args"] == ["crane", "auth", "login", "index.docker.io", "-u", "user", "-p", "secret"]


def test_ensure_login_reports_login_failure(monkeypatch, tmp_path):
    cred = base64.b64encode(b"u:s").decode()
    (tmp_path / "config.json").write_text(json.dumps(
        {"auths": {"https://index.docker.io/v1/": {"auth": cred}}}))

    def _fail(args, **kwargs):
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="bad creds\n")
    monkeypatch.setattr(image.subprocess, "run", _fail)
    assert ensure_login("crane", "index.docker.io", str(tmp_path)) == "login failed: bad creds"


def test_ensure_login_anonymous_on_corrupt_config(tmp_path):
    (tmp_path / "config.json").write_text("not json")
    assert ensure_login("crane", "index.docker.io", str(tmp_path)) == "could not read auth; anonymous"
    # Missing config dir also degrades to anonymous, never raises.
    assert ensure_login("crane", "index.docker.io", str(tmp_path / "missing")) \
        == "could not read auth; anonymous"


def test_image_digest_returns_digest_or_none(monkeypatch):
    calls = []

    def _fake(args, timeout_s):
        calls.append((args, timeout_s))
        return (0, "sha256:abc", "")
    monkeypatch.setattr(image, "_crane", _fake)
    assert image_digest("alpine", crane_bin="crane", timeout_s=30) == "sha256:abc"
    assert calls[0][0] == ["crane", "digest", "--platform", "linux/amd64", "alpine"]
    assert calls[0][1] == 30

    monkeypatch.setattr(image, "_crane", lambda args, timeout_s: (1, "", "MANIFEST_UNKNOWN"))
    assert image_digest("gone/repo") is None


def test_image_digest_omits_platform_when_empty(monkeypatch):
    calls = []
    monkeypatch.setattr(image, "_crane", lambda args, timeout_s: calls.append(args) or (0, "sha256:d", ""))
    assert image_digest("alpine", platform="") == "sha256:d"
    assert calls[0] == ["crane", "digest", "alpine"]


def test_compressed_size_sums_layers_and_config(monkeypatch):
    manifest = {"layers": [{"size": 10}, {"size": 20}], "config": {"size": 5}}
    monkeypatch.setattr(image, "_crane", lambda args, timeout_s: (0, json.dumps(manifest), ""))
    assert _compressed_size("crane", "img@sha256:x", ["--platform", "linux/amd64"], 120) == 35


def test_compressed_size_none_on_bad_manifest(monkeypatch):
    monkeypatch.setattr(image, "_crane", lambda args, timeout_s: (0, "not json", ""))
    assert _compressed_size("crane", "img@sha256:x", [], 120) is None
    monkeypatch.setattr(image, "_crane", lambda args, timeout_s: (1, "", "err"))
    assert _compressed_size("crane", "img@sha256:x", [], 120) is None


def test_export_rootfs_pulls_and_cleans_tar(monkeypatch, tmp_path):
    dest = tmp_path / "out"
    tar_path = str(dest) + ".tar"
    tarfile.open(tar_path, "w").close()  # crane "exported" an empty tarball
    extracted = []

    def _fake_crane(args, timeout_s):
        if args[1] == "digest":
            return (0, "sha256:abc", "")
        if args[1] == "export":
            return (0, "", "")
        return (1, "", "unexpected")
    monkeypatch.setattr(image, "_crane", _fake_crane)
    monkeypatch.setattr(image, "_safe_extract",
                        lambda tp, d, max_extract_bytes=0: extracted.append((tp, d, max_extract_bytes)))
    digest = export_rootfs("alpine", str(dest), crane_bin="crane", timeout_s=300)
    assert digest == "sha256:abc"
    assert extracted == [(tar_path, str(dest), 0)]
    assert not os.path.exists(tar_path)


def test_export_rootfs_skips_too_large(monkeypatch, tmp_path):
    dest = tmp_path / "out"
    manifest = {"layers": [{"size": 100}], "config": {"size": 0}}

    def _fake_crane(args, timeout_s):
        if args[1] == "digest":
            return (0, "sha256:abc", "")
        if args[1] == "manifest":
            return (0, json.dumps(manifest), "")
        return (1, "", "unexpected")
    monkeypatch.setattr(image, "_crane", _fake_crane)
    with pytest.raises(ImageTooLarge, match="too_large"):
        export_rootfs("alpine", str(dest), crane_bin="crane", max_bytes=50)


def test_export_rootfs_permanent_failure_raises(monkeypatch, tmp_path):
    dest = tmp_path / "out"
    monkeypatch.setattr(image, "_crane", lambda args, timeout_s: (1, "", "MANIFEST_UNKNOWN: repo not found"))
    with pytest.raises(ImagePullError, match="alpine"):
        export_rootfs("alpine", str(dest), crane_bin="crane")


def test_export_rootfs_retries_transient_then_succeeds(monkeypatch, tmp_path):
    dest = tmp_path / "out"
    tar_path = str(dest) + ".tar"
    tarfile.open(tar_path, "w").close()
    state = {"digest_calls": 0}
    sleeps = []

    def _fake_crane(args, timeout_s):
        if args[1] == "digest":
            state["digest_calls"] += 1
            if state["digest_calls"] == 1:
                return (1, "", "i/o timeout")
            return (0, "sha256:abc", "")
        if args[1] == "export":
            return (0, "", "")
        return (1, "", "unexpected")
    monkeypatch.setattr(image, "_crane", _fake_crane)
    monkeypatch.setattr(image, "_safe_extract", lambda tp, d, max_extract_bytes=0: None)
    monkeypatch.setattr(image.time, "sleep", lambda secs: sleeps.append(secs))
    assert export_rootfs("alpine", str(dest), crane_bin="crane") == "sha256:abc"
    assert state["digest_calls"] == 2
    assert len(sleeps) == 1  # backed off once between the two attempts
