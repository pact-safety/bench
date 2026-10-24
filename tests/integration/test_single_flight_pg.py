"""Prove single_flight actually excludes a second instance.

The unit tests use a fake connection, so they verify the shape of the calls
but not that Postgres genuinely refuses the second lock. That is the whole
point of the guard, so it gets a real test against a real database.

    pytest -m integration tests/integration/test_single_flight_pg.py
"""

from __future__ import annotations

import os

import pytest

from app.db import LOCK_NEWS_POLLER, connect, single_flight

pytestmark = pytest.mark.integration

_NO_DB = not os.environ.get("DATABASE_URL", "").strip()


@pytest.mark.skipif(_NO_DB, reason="needs DATABASE_URL")
def test_second_connection_is_locked_out():
    """Two connections stand in for two Fly machines. Exactly one wins."""
    a = connect()
    b = connect()
    try:
        with single_flight(a, LOCK_NEWS_POLLER) as first:
            assert first is True, "the first caller should win the lock"
            with single_flight(b, LOCK_NEWS_POLLER) as second:
                assert second is False, (
                    "a second instance took the same lock — the cron would "
                    "run twice and this guard is doing nothing"
                )
        # once the winner exits, the lock is free again for the next tick
        with single_flight(b, LOCK_NEWS_POLLER) as third:
            assert third is True, "lock was not released on exit"
    finally:
        a.close()
        b.close()


@pytest.mark.skipif(_NO_DB, reason="needs DATABASE_URL")
def test_lock_is_released_when_the_body_raises():
    """A tick that blows up must not wedge the cron forever."""
    a = connect()
    b = connect()
    try:
        with pytest.raises(RuntimeError):
            with single_flight(a, LOCK_NEWS_POLLER):
                raise RuntimeError("tick blew up")
        with single_flight(b, LOCK_NEWS_POLLER) as mine:
            assert mine is True, "lock survived a raising body"
    finally:
        a.close()
        b.close()
