from cryptocensus import collector
from cryptocensus.collector import collect
from cryptocensus.config import Settings


def _settings(**kw):
    base = dict(redis_url="redis://fake:6379/0", save_raw=True)
    base.update(kw)
    return Settings(**base)


class _Queue:
    """Scripted TaskQueue lookalike for the collector drain loop."""

    def __init__(self, payloads, stats):
        self.payloads = list(payloads)
        self.stats_value = stats
        self.pop_calls = 0

    def pop_result(self, block_s=2):
        self.pop_calls += 1
        if self.payloads:
            return self.payloads.pop(0)
        return None

    def stats(self):
        return self.stats_value


def test_collect_exits_when_queues_drained(monkeypatch, tmp_path):
    queue = _Queue([], {"pending": 0, "processing": 0, "results_pending": 0})
    monkeypatch.setattr(collector, "TaskQueue", lambda s: queue)
    written = []
    monkeypatch.setattr(collector, "write_bundle", lambda *a, **k: written.append(a))
    assert collect(str(tmp_path), s=_settings()) == 0
    assert written == []


def test_collect_writes_each_bundle(monkeypatch, tmp_path):
    queue = _Queue(["p1", "p2"], {"pending": 0, "processing": 0, "results_pending": 0})
    monkeypatch.setattr(collector, "TaskQueue", lambda s: queue)
    monkeypatch.setattr(collector, "decode_bundle",
                        lambda payload: ({"reference": payload, "digest": "sha256:x"},
                                         {"bom": True}, {"log": payload}))
    calls = []
    monkeypatch.setattr(collector, "write_bundle",
                        lambda out, record, cbom, raw, save_raw=True:
                        calls.append((out, record["reference"], cbom, raw, save_raw)))
    assert collect(str(tmp_path), s=_settings()) == 2
    assert calls == [(str(tmp_path), "p1", {"bom": True}, {"log": "p1"}, True),
                     (str(tmp_path), "p2", {"bom": True}, {"log": "p2"}, True)]


def test_collect_stops_at_max_results(monkeypatch, tmp_path):
    queue = _Queue(["p1", "p2", "p3"], {"pending": 0, "processing": 0, "results_pending": 0})
    monkeypatch.setattr(collector, "TaskQueue", lambda s: queue)
    monkeypatch.setattr(collector, "decode_bundle",
                        lambda payload: ({"reference": payload, "digest": None}, None, {"log": ""}))
    written = []
    monkeypatch.setattr(collector, "write_bundle", lambda *a, **k: written.append(a[1]))
    assert collect(str(tmp_path), s=_settings(), max_results=2) == 2
    assert [r["reference"] for r in written] == ["p1", "p2"]
    assert queue.pop_calls == 2


def test_collect_skips_undecodable_bundle(monkeypatch, tmp_path):
    queue = _Queue(["bad"], {"pending": 0, "processing": 0, "results_pending": 0})
    monkeypatch.setattr(collector, "TaskQueue", lambda s: queue)
    monkeypatch.setattr(collector, "decode_bundle", lambda payload: (_ for _ in ()).throw(ValueError("corrupt")))
    written = []
    monkeypatch.setattr(collector, "write_bundle", lambda *a, **k: written.append(a))
    assert collect(str(tmp_path), s=_settings()) == 0
    assert written == []


def test_collect_follow_keeps_waiting_when_empty(monkeypatch, tmp_path):
    # follow=True must not exit when the queues momentarily empty; it keeps polling.
    class _Scripted:
        def __init__(self):
            self.pops = [None, "p1"]
            self.pop_calls = 0

        def pop_result(self, block_s=2):
            self.pop_calls += 1
            return self.pops.pop(0) if self.pops else None

        def stats(self):
            return {"pending": 0, "processing": 0, "results_pending": 0}
    queue = _Scripted()
    monkeypatch.setattr(collector, "TaskQueue", lambda s: queue)
    monkeypatch.setattr(collector, "decode_bundle",
                        lambda payload: ({"reference": payload, "digest": None}, None, {"log": ""}))
    written = []
    monkeypatch.setattr(collector, "write_bundle", lambda *a, **k: written.append(a[1]))
    assert collect(str(tmp_path), s=_settings(), max_results=1, follow=True) == 1
    assert [r["reference"] for r in written] == ["p1"]
    assert queue.pop_calls == 2  # first (empty) poll was waited through


def test_collect_passes_save_raw_flag(monkeypatch, tmp_path):
    queue = _Queue(["p1"], {"pending": 0, "processing": 0, "results_pending": 0})
    monkeypatch.setattr(collector, "TaskQueue", lambda s: queue)
    monkeypatch.setattr(collector, "decode_bundle",
                        lambda payload: ({"reference": payload, "digest": None}, None, {"log": ""}))
    seen = {}

    def _write(out, record, cbom, raw, save_raw=True):
        seen["save_raw"] = save_raw
    monkeypatch.setattr(collector, "write_bundle", _write)
    assert collect(str(tmp_path), s=_settings(save_raw=False), max_results=1) == 1
    assert seen["save_raw"] is False
