"""single_flight: the guard that makes `fly scale count 2` safe.

Every instance arms every APScheduler cron in-process, so without this the
news poller and reflect pre-generation run once per machine — duplicate news
rows, duplicate Anthropic spend.

These are unit tests against a fake connection. The real two-connection
exclusion is proven against Postgres in
tests/integration/test_single_flight_pg.py.
"""

from __future__ import annotations

import pytest

from app.db import LOCK_NEWS_POLLER, LOCK_REFLECT_PREGENERATE, single_flight


class _FakeCur:
    def __init__(self, owner, result):
        self.owner = owner
        self.result = result

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=()):
        self.owner.calls.append((sql, params))

    def fetchone(self):
        if self.owner.shape == "tuple":
            return (self.result,)
        # connect() uses row_factory=dict_row. The fake defaults to that
        # shape on purpose: when it returned tuples, this whole file passed
        # while the guard was inert against the real database.
        return {"locked": self.result}


class _FakeConn:
    """Hands out `lock_result` for pg_try_advisory_lock and records SQL."""

    def __init__(self, lock_result=True, shape="dict"):
        self.lock_result = lock_result
        self.shape = shape
        self.calls: list[tuple] = []

    def cursor(self):
        return _FakeCur(self, self.lock_result)


def test_winner_gets_true_and_releases():
    conn = _FakeConn(lock_result=True)
    with single_flight(conn, LOCK_NEWS_POLLER) as mine:
        assert mine is True
    sqls = [c[0] for c in conn.calls]
    assert any("pg_try_advisory_lock" in s for s in sqls)
    assert any("pg_advisory_unlock" in s for s in sqls), "lock must be released"


def test_loser_gets_false_and_does_not_unlock():
    """Releasing a lock you never took would free the winner's lock."""
    conn = _FakeConn(lock_result=False)
    with single_flight(conn, LOCK_NEWS_POLLER) as mine:
        assert mine is False
    assert not any("pg_advisory_unlock" in c[0] for c in conn.calls)


def test_lock_released_even_when_body_raises():
    conn = _FakeConn(lock_result=True)
    with pytest.raises(RuntimeError):
        with single_flight(conn, LOCK_NEWS_POLLER):
            raise RuntimeError("tick blew up")
    assert any("pg_advisory_unlock" in c[0] for c in conn.calls)


def test_keys_are_distinct():
    """A shared key would make two unrelated jobs block each other."""
    assert LOCK_NEWS_POLLER != LOCK_REFLECT_PREGENERATE


def test_fails_open_when_the_lock_query_errors():
    """A single-instance deploy must not silently stop running its crons
    because the advisory-lock query failed."""

    import psycopg

    class _Broken(_FakeConn):
        def cursor(self):
            raise psycopg.OperationalError("connection gone")

    with single_flight(_Broken(), LOCK_NEWS_POLLER) as mine:
        assert mine is True


def test_no_db_sentinel_yields_true():
    """Unit tests that call a tick body directly should run it."""
    from app.db import _StrictNoDBConn

    with single_flight(_StrictNoDBConn(), LOCK_NEWS_POLLER) as mine:
        assert mine is True


@pytest.mark.parametrize("shape", ["dict", "tuple"])
def test_reads_the_result_whatever_shape_the_cursor_yields(shape):
    """REGRESSION: `connect()` sets row_factory=dict_row, so `row[0]` is a
    KeyError rather than the value. That KeyError was being swallowed by a
    catch-all and the guard degraded to "run unguarded" — i.e. it did
    nothing, on every instance, silently."""
    conn = _FakeConn(lock_result=True, shape=shape)
    with single_flight(conn, LOCK_NEWS_POLLER) as mine:
        assert mine is True
    assert any("pg_advisory_unlock" in c[0] for c in conn.calls), (
        "a real lock was taken, so it must be released"
    )

    conn = _FakeConn(lock_result=False, shape=shape)
    with single_flight(conn, LOCK_NEWS_POLLER) as mine:
        assert mine is False, "a losing instance must not be told it won"


def test_a_programming_error_is_not_swallowed_into_running_unguarded():
    """Fail-open is for database errors only. If it catches everything, a
    bug in this helper turns into a silently disabled guard."""

    class _Bug(_FakeConn):
        def cursor(self):
            raise TypeError("programming error, not a DB error")

    with pytest.raises(TypeError):
        with single_flight(_Bug(), LOCK_NEWS_POLLER):
            pass
