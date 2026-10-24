"""PooledConnection — the psycopg_pool facade behind `connect()`.

Replaces test_resilient_connection.py: the class it tested is gone,
and the pool's `check=` + `_check_if_idle` now carry the
dead-connection self-healing that killed the 2026-07-19/21 outages.
What must hold, because the whole app calls the facade as if it were
one shared connection:

  - `with conn.cursor() as cur:` leases a pooled connection for the
    block and returns it afterwards
  - nested cursors inside `transaction()` / `bound()` reuse the SAME
    underlying connection (transactional deletes, advisory locks)
  - the idle-aware check policy: fresh/recent connections skip the
    ping, stale ones get it, and a raised block does NOT stamp its
    connection as healthy
  - single_flight locks and unlocks on one pinned connection, fails
    OPEN when no connection is available, and discards the session
    when the unlock fails (a healthy member returning to the pool
    still holding the lock would starve the cron on every instance)
  - commit()/rollback() are no-ops without a pin, delegate with one
  - the LIS_NO_DB sentinel path is unchanged
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from app.db import (
    LOCK_NEWS_POLLER,
    PooledConnection,
    _check_if_idle,
    _StrictNoDBConn,
    connect,
    single_flight,
)


class _FakePool:
    """Stands in for psycopg_pool.ConnectionPool: hands out MagicMock
    connections and records checkout/return pairing."""

    def __init__(self, connect_error: Exception | None = None) -> None:
        self.handed_out: list[MagicMock] = []
        self.returned: list[MagicMock] = []
        self.closed = False
        self._connect_error = connect_error

    @contextmanager
    def connection(self):
        if self._connect_error is not None:
            raise self._connect_error
        conn = MagicMock()
        cur = MagicMock()
        cur.__enter__ = MagicMock(return_value=cur)
        cur.__exit__ = MagicMock(return_value=False)
        # dict_row shape so single_flight's _scalar reads it correctly.
        cur.fetchone.return_value = {"locked": True}
        conn.cursor.return_value = cur
        tx = MagicMock()
        tx.__enter__ = MagicMock(return_value=tx)
        tx.__exit__ = MagicMock(return_value=False)
        conn.transaction.return_value = tx
        self.handed_out.append(conn)
        try:
            yield conn
        finally:
            self.returned.append(conn)

    def close(self) -> None:
        self.closed = True


@pytest.fixture()
def pool_and_conn():
    pool = _FakePool()
    return pool, PooledConnection(pool)  # type: ignore[arg-type]


def test_cursor_block_leases_and_returns(pool_and_conn):
    pool, conn = pool_and_conn
    with conn.cursor() as cur:
        cur.execute("SELECT 1")
        assert len(pool.handed_out) == 1
        assert pool.returned == []  # still leased inside the block
    assert pool.returned == pool.handed_out
    raw = pool.handed_out[0]
    raw.cursor.return_value.execute.assert_called_once_with("SELECT 1")
    # The cursor context was exited with the lease (psycopg closes on
    # __exit__).
    raw.cursor.return_value.__exit__.assert_called_once()


def test_sequential_cursor_blocks_use_separate_leases(pool_and_conn):
    pool, conn = pool_and_conn
    with conn.cursor():
        pass
    with conn.cursor():
        pass
    assert len(pool.handed_out) == 2


def test_transaction_pins_one_connection_for_nested_cursors(pool_and_conn):
    """The /settings/reset shape: cursor() inside transaction() must
    join the open transaction, i.e. hit the same pooled connection."""
    pool, conn = pool_and_conn
    with conn.transaction():
        with conn.cursor():
            pass
        with conn.cursor():
            pass
    assert len(pool.handed_out) == 1
    pinned = pool.handed_out[0]
    pinned.transaction.assert_called_once()
    assert pinned.cursor.call_count == 2


def test_transaction_passes_psycopg_args_through(pool_and_conn):
    pool, conn = pool_and_conn
    with conn.transaction("sp1", force_rollback=True):
        pass
    pool.handed_out[0].transaction.assert_called_once_with(
        "sp1", force_rollback=True
    )


def test_bound_is_reentrant(pool_and_conn):
    pool, conn = pool_and_conn
    with conn.bound():
        with conn.bound():
            with conn.cursor():
                pass
    assert len(pool.handed_out) == 1


def test_bound_unpins_after_exit(pool_and_conn):
    pool, conn = pool_and_conn
    with conn.bound():
        pass
    with conn.cursor():
        pass
    assert len(pool.handed_out) == 2  # second block took a fresh lease


def test_clean_exit_stamps_connection_as_recently_used(pool_and_conn):
    pool, conn = pool_and_conn
    with conn.cursor():
        pass
    assert isinstance(pool.handed_out[0]._bench_last_used, float)


def test_raised_block_does_not_stamp(pool_and_conn):
    """A block that raised must not vouch for its connection: the old
    ResilientConnection only advanced its stamp on confirmed-good use.
    Without this, a connection that just failed would skip the checkout
    ping and be handed, still dead, to the next request."""
    pool, conn = pool_and_conn
    with pytest.raises(RuntimeError):
        with conn.cursor():
            raise RuntimeError("boom")
    raw = pool.handed_out[0]
    # MagicMock auto-creates attributes on read; a REAL stamp is a float.
    assert not isinstance(raw._bench_last_used, float)
    assert pool.returned == [raw]  # lease still returned


def test_commit_rollback_are_noops_without_pin(pool_and_conn):
    """~53 repo call sites do `self.conn.commit()` after their cursor
    block closes. Under autocommit that was already a no-op; the facade
    must accept it without touching the pool."""
    pool, conn = pool_and_conn
    conn.commit()
    conn.rollback()
    assert pool.handed_out == []


def test_commit_rollback_delegate_when_pinned(pool_and_conn):
    """Inside a bound scope (cron job body) error-recovery rollback()
    must reach the real pinned connection."""
    pool, conn = pool_and_conn
    with conn.bound():
        conn.commit()
        conn.rollback()
    raw = pool.handed_out[0]
    raw.commit.assert_called_once()
    raw.rollback.assert_called_once()


def test_close_closes_pool(pool_and_conn):
    pool, conn = pool_and_conn
    conn.close()
    assert pool.closed is True


# ---------- idle-aware checkout check ---------------------------------------


def test_check_pings_unstamped_connection(monkeypatch):
    ping = MagicMock()
    monkeypatch.setattr(
        "app.db.psycopg_pool.ConnectionPool.check_connection", ping
    )
    raw = MagicMock(spec=[])  # no _bench_last_used attribute
    _check_if_idle(raw)
    ping.assert_called_once_with(raw)


def test_check_skips_recently_used_connection(monkeypatch):
    ping = MagicMock()
    monkeypatch.setattr(
        "app.db.psycopg_pool.ConnectionPool.check_connection", ping
    )
    import app.db as db_mod

    raw = MagicMock()
    raw._bench_last_used = db_mod.time.monotonic()
    _check_if_idle(raw)
    ping.assert_not_called()


def test_check_pings_stale_connection(monkeypatch):
    ping = MagicMock()
    monkeypatch.setattr(
        "app.db.psycopg_pool.ConnectionPool.check_connection", ping
    )
    import app.db as db_mod

    raw = MagicMock()
    raw._bench_last_used = db_mod.time.monotonic() - db_mod._CHECK_IDLE_S - 1
    _check_if_idle(raw)
    ping.assert_called_once_with(raw)


# ---------- single_flight ----------------------------------------------------


def test_single_flight_locks_and_unlocks_on_same_connection(pool_and_conn):
    """Advisory locks are session-scoped: lock and unlock MUST happen
    on the same pooled connection, held for the whole job."""
    pool, conn = pool_and_conn

    with single_flight(conn, LOCK_NEWS_POLLER) as mine:
        assert mine is True
        # Job body doing its own queries stays on the pinned conn.
        with conn.cursor():
            pass
    assert len(pool.handed_out) == 1
    executed = [
        c.args[0]
        for c in pool.handed_out[0].cursor.return_value.execute.call_args_list
    ]
    assert any("pg_try_advisory_lock" in q for q in executed)
    assert any("pg_advisory_unlock" in q for q in executed)


def test_single_flight_fails_open_when_pool_unavailable():
    """PoolTimeout / dial failure at checkout must degrade to 'run
    unguarded' (the documented single-instance policy), not raise out
    of the tick."""
    import psycopg

    pool = _FakePool(connect_error=psycopg.OperationalError("pool timeout"))
    conn = PooledConnection(pool)  # type: ignore[arg-type]
    with single_flight(conn, LOCK_NEWS_POLLER) as mine:
        assert mine is True


def test_single_flight_discards_session_when_unlock_fails(pool_and_conn):
    """A healthy member going back to the pool still holding the lock
    would make every instance's try-lock return False until the member
    is recycled — the cron silently starves. Closing the session kills
    the lock with it."""
    import psycopg

    pool, conn = pool_and_conn

    def _execute(sql, *a, **k):
        if "pg_advisory_unlock" in sql:
            raise psycopg.OperationalError("connection flaked")

    with single_flight(conn, LOCK_NEWS_POLLER) as mine:
        assert mine is True
        pool.handed_out[0].cursor.return_value.execute.side_effect = _execute
    pool.handed_out[0].close.assert_called_once()


def test_single_flight_yields_true_for_no_db_sentinel():
    with single_flight(_StrictNoDBConn(), LOCK_NEWS_POLLER) as mine:  # type: ignore[arg-type]
        assert mine is True


# ---------- connect() wiring -------------------------------------------------


def test_connect_returns_pool_facade_with_healing_wired(monkeypatch):
    import app.db as db_mod

    fake_pool_cls = MagicMock()
    monkeypatch.setattr("app.db.psycopg_pool.ConnectionPool", fake_pool_cls)
    out = connect("postgresql://x")
    assert isinstance(out, PooledConnection)
    kwargs = fake_pool_cls.call_args.kwargs
    # The psycopg kwargs the app depends on (dict rows, autocommit, no
    # server-side prepare).
    assert kwargs["kwargs"]["autocommit"] is True
    assert kwargs["kwargs"]["prepare_threshold"] is None
    assert kwargs["open"] is True
    # The self-healing + fail-fast wiring. Deleting any of these
    # silently reintroduces the 2026-07-19/21 outage class or the
    # 30s-stall-under-outage failure shape.
    assert kwargs["check"] is db_mod._check_if_idle
    assert kwargs["configure"] is db_mod._stamp_fresh
    assert kwargs["timeout"] == 5.0
    fake_pool_cls.return_value.wait.assert_called_once()


def test_no_db_sentinel_stays_unwrapped(monkeypatch):
    """The sentinel's job is to raise loudly — wrapping it would turn
    that into a confusing reconnect loop."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("LIS_NO_DB", "1")
    out = connect()
    assert isinstance(out, _StrictNoDBConn)


def test_sentinel_raises_on_transaction_and_bound():
    s = _StrictNoDBConn()
    with pytest.raises(RuntimeError):
        s.transaction()
    with pytest.raises(RuntimeError):
        s.bound()
