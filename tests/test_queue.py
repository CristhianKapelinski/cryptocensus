import pytest

from cryptocensus import queue as queue_mod
from cryptocensus.config import Settings
from cryptocensus.queue import TaskQueue


class _FakePipeline:
    def __init__(self, client):
        self._client = client
        self._cmds = []

    def sismember(self, name, value):
        self._cmds.append(("sismember", name, value))
        return self

    def lrem(self, name, count, value):
        self._cmds.append(("lrem", name, count, value))
        return self

    def sadd(self, name, value):
        self._cmds.append(("sadd", name, value))
        return self

    def lpush(self, name, value):
        self._cmds.append(("lpush", name, value))
        return self

    def execute(self):
        results = []
        for name, *args in self._cmds:
            results.append(getattr(self._client, name)(*args))
        return results


class _FakeRedis:
    """In-memory redis lookalike matching the commands TaskQueue issues."""

    def __init__(self):
        self.lists = {}
        self.sets = {}
        self.hashes = {}
        self.keys = {}

    def _list(self, name):
        return self.lists.setdefault(name, [])

    def ping(self):
        return True

    def lpush(self, name, *values):
        lst = self._list(name)
        for value in values:
            lst.insert(0, value)
        return len(lst)

    def llen(self, name):
        return len(self.lists.get(name, []))

    def lrem(self, name, count, value):
        lst = self._list(name)
        remaining = []
        removed = 0
        for item in lst:
            if item == value and removed < abs(count):
                removed += 1
            else:
                remaining.append(item)
        self.lists[name] = remaining
        return removed

    def blmove(self, src, dst, timeout, wherefrom, whereto):
        return self._move(src, dst)

    def lmove(self, src, dst, wherefrom, whereto):
        return self._move(src, dst)

    def _move(self, src, dst):
        lst = self._list(src)
        if not lst:
            return None
        item = lst.pop()
        self._list(dst).insert(0, item)
        return item

    def brpop(self, name, timeout):
        lst = self._list(name)
        if not lst:
            return None
        return [name, lst.pop()]

    def sismember(self, name, value):
        return value in self.sets.setdefault(name, set())

    def sadd(self, name, value):
        self.sets.setdefault(name, set()).add(value)
        return 1

    def scard(self, name):
        return len(self.sets.get(name, set()))

    def hincrby(self, name, key, amount):
        h = self.hashes.setdefault(name, {})
        new = h.get(key, 0) + amount
        h[key] = new
        return new

    def set(self, name, value, nx=False, ex=None):
        if nx and name in self.keys:
            return None
        self.keys[name] = value
        return True

    def eval(self, script, numkeys, *args):
        # compare-and-delete used by release_pull_lock
        key, token = args[0], args[1]
        if self.keys.get(key) == token:
            del self.keys[key]
            return 1
        return 0

    def pipeline(self):
        return _FakePipeline(self)


@pytest.fixture
def fake_redis(monkeypatch):
    client = _FakeRedis()
    module = type("_FakeRedisModule", (), {"from_url": staticmethod(lambda *a, **k: client)})()
    monkeypatch.setattr(queue_mod, "redis", module)
    return client


def _settings(**kw):
    base = dict(redis_url="redis://fake:6379/0", task_queue="t", processing_queue="p",
                result_queue="r", done_set="d", retry_hash="h",
                pull_mutex_key="lock", pull_mutex_ttl_s=60, claim_block_s=1)
    base.update(kw)
    return Settings(**base)


def test_ping(fake_redis):
    assert TaskQueue(_settings()).ping() is True


def test_enqueue_deduplicates_within_batch(fake_redis):
    q = TaskQueue(_settings())
    assert q.enqueue(["a", "b", "a", ""]) == 2
    assert sorted(fake_redis.lists["t"]) == ["a", "b"]


def test_enqueue_skips_references_already_done(fake_redis):
    q = TaskQueue(_settings())
    fake_redis.sets["d"] = {"done1"}
    assert q.enqueue(["done1", "fresh"]) == 1
    assert sorted(fake_redis.lists["t"]) == ["fresh"]
    # A batch that is entirely done pushes nothing.
    assert q.enqueue(["done1"]) == 0
    assert sorted(fake_redis.lists["t"]) == ["fresh"]


def test_enqueue_ignores_empty(fake_redis):
    q = TaskQueue(_settings())
    assert q.enqueue([]) == 0
    assert q.enqueue(["", None]) == 0
    assert "t" not in fake_redis.lists


def test_claim_moves_from_pending_to_processing(fake_redis):
    q = TaskQueue(_settings())
    fake_redis.lists["t"] = ["a", "b", "c"]
    assert q.claim() == "c"
    assert q.claim() == "b"
    assert q.claim() == "a"
    assert q.claim() is None
    assert fake_redis.lists["p"] == ["a", "b", "c"]
    assert fake_redis.lists["t"] == []


def test_ack_moves_reference_to_done(fake_redis):
    q = TaskQueue(_settings())
    fake_redis.lists["p"] = ["x"]
    q.ack("x")
    assert fake_redis.lists["p"] == []
    assert "x" in fake_redis.sets["d"]


def test_requeue_returns_single_reference(fake_redis):
    q = TaskQueue(_settings())
    fake_redis.lists["p"] = ["x", "y"]
    q.requeue("y")
    assert fake_redis.lists["p"] == ["x"]
    assert fake_redis.lists["t"] == ["y"]


def test_requeue_stale_drains_processing(fake_redis):
    q = TaskQueue(_settings())
    fake_redis.lists["p"] = ["x", "y"]
    assert q.requeue_stale() == 2
    assert fake_redis.lists["p"] == []
    assert sorted(fake_redis.lists["t"]) == ["x", "y"]


def test_transient_retry_counts(fake_redis):
    q = TaskQueue(_settings())
    assert q.transient_retry("img") == 1
    assert q.transient_retry("img") == 2
    assert q.transient_retry("other") == 1


def test_pull_lock_acquire_release_and_token_guard(fake_redis):
    q = TaskQueue(_settings())
    assert q.acquire_pull_lock("tok1") is True
    assert q.acquire_pull_lock("tok2") is False  # still held
    q.release_pull_lock("tok2")  # wrong token: lock stays
    assert q.acquire_pull_lock("tok3") is False
    q.release_pull_lock("tok1")  # the holder releases
    assert q.acquire_pull_lock("tok4") is True


def test_result_channel_round_trip(fake_redis):
    q = TaskQueue(_settings())
    assert q.results_pending() == 0
    q.push_result("bundle")
    assert q.results_pending() == 1
    assert q.pop_result(block_s=1) == "bundle"
    assert q.pop_result(block_s=0) is None


def test_stats_reflect_queue_state(fake_redis):
    q = TaskQueue(_settings())
    fake_redis.lists["t"] = ["a", "b"]
    fake_redis.lists["p"] = ["c"]
    fake_redis.lists["r"] = ["b1"]
    fake_redis.sets["d"] = {"x", "y"}
    assert q.stats() == {"pending": 2, "processing": 1, "results_pending": 1, "done": 2}
