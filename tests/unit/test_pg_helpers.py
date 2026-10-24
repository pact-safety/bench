"""Tests for app.repositories._pg — the shared psycopg→Python boundary.

The `naive_utc` helper is the fix for an entire class of crashes: any
TIMESTAMPTZ value compared against `datetime.utcnow()` (naive) would
raise `TypeError: can't compare offset-naive and offset-aware datetimes`.
We hit this twice — once in attempts (fixed in Phase 4), once in
content_progress (fixed when /today/next 500'd).

Lock the boundary contract in so the bug can't come back."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.repositories._pg import jsonb, naive_utc, uuid_str


def test_naive_utc_strips_tz():
    aware = datetime(2026, 5, 14, 12, 0, 0, tzinfo=timezone.utc)
    out = naive_utc(aware)
    assert out.tzinfo is None
    assert out.year == 2026 and out.hour == 12


def test_naive_utc_converts_non_utc_to_utc():
    """A datetime in a non-UTC zone (eg Asia/Bangkok) should be
    converted to UTC before stripping tz."""
    from datetime import timezone
    bkk = timezone(timedelta(hours=7))
    aware = datetime(2026, 5, 14, 19, 0, 0, tzinfo=bkk)
    out = naive_utc(aware)
    assert out.tzinfo is None
    assert out.hour == 12  # 19:00 +0700 → 12:00 UTC


def test_naive_utc_passes_through_naive():
    """Already-naive datetimes stay naive."""
    naive = datetime(2026, 5, 14, 12, 0, 0)
    assert naive_utc(naive) == naive


def test_naive_utc_handles_none():
    assert naive_utc(None) is None


def test_compare_against_utcnow_doesnt_explode():
    """The original failure mode — locked in as a positive test.

    Comparing a Postgres TIMESTAMPTZ value (after going through
    naive_utc) with `datetime.utcnow()` must not raise TypeError."""
    # Simulate what psycopg returns: a tz-aware datetime.
    pg_value = datetime(2026, 5, 14, 12, 0, 0, tzinfo=timezone.utc)
    horizon = datetime.utcnow() - timedelta(days=3)
    # Without naive_utc, this raises. With it, it returns a bool.
    result = naive_utc(pg_value) < horizon
    assert isinstance(result, bool)


def test_jsonb_passes_through_dicts_and_lists():
    assert jsonb({"a": 1}) == {"a": 1}
    assert jsonb([1, 2, 3]) == [1, 2, 3]


def test_jsonb_decodes_strings():
    """For columns that come back as JSON-encoded strings (rare with
    psycopg's default adapter, but defensive)."""
    assert jsonb('{"a": 1}') == {"a": 1}
    assert jsonb('[1, 2]') == [1, 2]


def test_jsonb_handles_none():
    assert jsonb(None) is None


def test_uuid_str_handles_uuid_object():
    import uuid
    u = uuid.UUID("00000000-1111-2222-3333-444444444444")
    assert uuid_str(u) == "00000000-1111-2222-3333-444444444444"


def test_uuid_str_passes_through_string():
    assert uuid_str("00000000-1111-2222-3333-444444444444") == "00000000-1111-2222-3333-444444444444"


def test_uuid_str_handles_none():
    assert uuid_str(None) is None
