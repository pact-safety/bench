"""Tests for app.cache — the in-process read-through cache."""

from __future__ import annotations

from app import cache


def test_get_calls_loader_once():
    """First call hits the loader; subsequent calls return cached
    value without calling again."""
    calls = []

    def loader():
        calls.append(1)
        return "value"

    assert cache.get("k", loader=loader) == "value"
    assert cache.get("k", loader=loader) == "value"
    assert cache.get("k", loader=loader) == "value"
    assert len(calls) == 1, "loader should fire exactly once"


def test_invalidate_forces_reload():
    counter = {"n": 0}

    def loader():
        counter["n"] += 1
        return counter["n"]

    assert cache.get("k", loader=loader) == 1
    assert cache.get("k", loader=loader) == 1  # cached
    cache.invalidate("k")
    assert cache.get("k", loader=loader) == 2  # reloaded
    assert counter["n"] == 2


def test_invalidate_prefix_drops_matching_entries():
    cache.get("a:1", loader=lambda: "one")
    cache.get("a:2", loader=lambda: "two")
    cache.get("b:1", loader=lambda: "b-one")
    n = cache.invalidate_prefix("a:")
    assert n == 2
    # 'b:1' survives
    assert cache.get("b:1", loader=lambda: "different") == "b-one"


def test_clear_all_drops_everything():
    cache.get("a", loader=lambda: 1)
    cache.get("b", loader=lambda: 2)
    cache.clear_all()
    assert cache.stats()["entries"] == 0


def test_invalidate_missing_key_is_noop():
    cache.invalidate("does-not-exist")  # should not raise


def test_ttl_entry_expires_and_reloads(monkeypatch):
    """TTL'd entries reload after the deadline — the cross-machine
    convergence bound for user settings (a write on the other Fly
    machine can't invalidate our in-process store)."""
    from app import cache as cache_mod

    now = {"t": 1000.0}
    monkeypatch.setattr(cache_mod.time, "monotonic", lambda: now["t"])

    counter = {"n": 0}

    def loader():
        counter["n"] += 1
        return counter["n"]

    assert cache.get("ttl-k", loader=loader, ttl_s=30.0) == 1
    now["t"] += 29.0
    assert cache.get("ttl-k", loader=loader, ttl_s=30.0) == 1  # still fresh
    now["t"] += 2.0
    assert cache.get("ttl-k", loader=loader, ttl_s=30.0) == 2  # expired → reload
    assert counter["n"] == 2


def test_no_ttl_entry_never_expires(monkeypatch):
    from app import cache as cache_mod

    now = {"t": 1000.0}
    monkeypatch.setattr(cache_mod.time, "monotonic", lambda: now["t"])

    calls = []
    cache.get("forever-k", loader=lambda: calls.append(1) or "v")
    now["t"] += 1e9
    cache.get("forever-k", loader=lambda: calls.append(1) or "v")
    assert len(calls) == 1


def test_invalidate_beats_ttl():
    """Explicit invalidation still works on TTL'd entries — the
    writing machine must reflect a settings save immediately, not
    after the TTL."""
    counter = {"n": 0}

    def loader():
        counter["n"] += 1
        return counter["n"]

    assert cache.get("ttl-inv", loader=loader, ttl_s=3600.0) == 1
    cache.invalidate("ttl-inv")
    assert cache.get("ttl-inv", loader=loader, ttl_s=3600.0) == 2


def test_concurrent_get_is_thread_safe():
    """Smoke: the RLock allows recursive/parallel get calls. Not a
    proper concurrency test, just a sanity check that the lock
    doesn't deadlock on a loader that itself reads the cache."""
    def outer_loader():
        return cache.get("inner", loader=lambda: "inner-value")
    result = cache.get("outer", loader=outer_loader)
    assert result == "inner-value"
