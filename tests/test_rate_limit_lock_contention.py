from __future__ import annotations

from types import SimpleNamespace

from api import server


def _request():
    return SimpleNamespace(
        client=SimpleNamespace(host="127.0.0.1"),
        headers={},
    )


def test_shared_rate_limit_network_calls_do_not_hold_memory_lock(monkeypatch):
    server._RATE_LIMIT_BUCKET.clear()
    lock_states = []

    def fake_shared(bucket_key, limit, now, detail):
        lock_states.append(server._RATE_LIMIT_LOCK.locked())
        return True

    monkeypatch.setattr(server, "_hit_shared_redis", fake_shared)

    server.check_rate_limit(_request(), max_per_minute=7, scope="test")

    assert len(lock_states) == 2
    assert lock_states == [False, False]
    assert server._RATE_LIMIT_BUCKET == {}


def test_rate_limit_falls_back_to_locked_memory_when_redis_is_unavailable(monkeypatch):
    server._RATE_LIMIT_BUCKET.clear()
    lock_states = []

    def unavailable(bucket_key, limit, now, detail):
        lock_states.append(server._RATE_LIMIT_LOCK.locked())
        return False

    monkeypatch.setattr(server, "_hit_shared_redis", unavailable)

    server.check_rate_limit(_request(), max_per_minute=7, scope="test")

    assert lock_states == [False]
    assert "*global*" in server._RATE_LIMIT_BUCKET
    assert "test:127.0.0.1" in server._RATE_LIMIT_BUCKET
    assert len(server._RATE_LIMIT_BUCKET["*global*"]) == 1
    assert len(server._RATE_LIMIT_BUCKET["test:127.0.0.1"]) == 1
