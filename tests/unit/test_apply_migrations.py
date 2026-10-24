"""Tests for app.db.apply_migrations transparency + escape-hatch behavior."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock

import psycopg
import pytest

from app import db as db_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_conn(applied_filenames: list[str]) -> MagicMock:
    """A MagicMock that pretends to be a psycopg connection with an
    existing ``schema_migrations`` table containing the given filenames."""
    conn = MagicMock(spec=psycopg.Connection)
    cursor_ctx = MagicMock()
    cur = MagicMock()
    cursor_ctx.__enter__.return_value = cur
    cursor_ctx.__exit__.return_value = None
    conn.cursor.return_value = cursor_ctx
    cur.fetchall.return_value = [{"filename": f} for f in applied_filenames]
    return conn, cur


def _write_migration(dir_: Path, name: str, sql: str = "SELECT 1;") -> None:
    (dir_ / name).write_text(sql)


# ---------------------------------------------------------------------------
# Escape hatch: LIS_DISABLE_AUTO_MIGRATE=1
# ---------------------------------------------------------------------------


def test_skips_when_LIS_DISABLE_AUTO_MIGRATE_set(
    monkeypatch, tmp_path, caplog
):
    """When the env var is set, do nothing — even if there are pending
    migrations on disk."""
    monkeypatch.setenv("LIS_DISABLE_AUTO_MIGRATE", "1")
    migrations_dir = tmp_path / "migrations_pg"
    migrations_dir.mkdir()
    _write_migration(migrations_dir, "001_foo.sql")

    conn = MagicMock(spec=psycopg.Connection)

    with caplog.at_level(logging.INFO, logger="bench.db.migrations"):
        db_module.apply_migrations(conn, migrations_dir)

    # No cursor was opened — we returned before any DB access.
    conn.cursor.assert_not_called()
    assert any("LIS_DISABLE_AUTO_MIGRATE" in r.message for r in caplog.records)


@pytest.mark.parametrize("value", ["1", "true", "yes", "TRUE", "Yes"])
def test_LIS_DISABLE_AUTO_MIGRATE_truthy_values(monkeypatch, tmp_path, value):
    monkeypatch.setenv("LIS_DISABLE_AUTO_MIGRATE", value)
    migrations_dir = tmp_path / "migrations_pg"
    migrations_dir.mkdir()
    conn = MagicMock(spec=psycopg.Connection)
    db_module.apply_migrations(conn, migrations_dir)
    conn.cursor.assert_not_called()


@pytest.mark.parametrize("value", ["0", "false", "", "no"])
def test_LIS_DISABLE_AUTO_MIGRATE_falsy_values_run_migrations(
    monkeypatch, tmp_path, value
):
    monkeypatch.setenv("LIS_DISABLE_AUTO_MIGRATE", value)
    migrations_dir = tmp_path / "migrations_pg"
    migrations_dir.mkdir()  # no files → loop is no-op
    conn, cur = _fake_conn(applied_filenames=[])
    db_module.apply_migrations(conn, migrations_dir)
    # Cursor opened (we tried to query schema_migrations).
    assert conn.cursor.call_count >= 1


# ---------------------------------------------------------------------------
# StrictNoDB sentinel passthrough (preserves existing behavior)
# ---------------------------------------------------------------------------


def test_no_op_against_strict_no_db_sentinel(tmp_path, caplog):
    """The LIS_NO_DB sentinel must not raise even though the cursor
    would. Preserves the import-time-import-without-DB property."""
    sentinel = db_module._StrictNoDBConn()
    migrations_dir = tmp_path / "migrations_pg"
    migrations_dir.mkdir()
    _write_migration(migrations_dir, "001_foo.sql")

    with caplog.at_level(logging.INFO, logger="bench.db.migrations"):
        db_module.apply_migrations(sentinel, migrations_dir)

    # No exception. We log that we skipped.
    assert any("LIS_NO_DB" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Drift detection logging
# ---------------------------------------------------------------------------


def test_logs_pending_count_and_each_pending_filename(
    monkeypatch, tmp_path, caplog
):
    """The drift situation that prompted this fix: prod had 001+002
    recorded, with 003-010 on disk but not in schema_migrations. The
    logs MUST surface that delta on every boot so we never fly blind."""
    monkeypatch.delenv("LIS_DISABLE_AUTO_MIGRATE", raising=False)
    migrations_dir = tmp_path / "migrations_pg"
    migrations_dir.mkdir()
    for name in [
        "001_a.sql",
        "002_b.sql",
        "003_c.sql",
        "004_d.sql",
        "005_e.sql",
    ]:
        _write_migration(migrations_dir, name)

    conn, cur = _fake_conn(applied_filenames=["001_a.sql", "002_b.sql"])

    with caplog.at_level(logging.INFO, logger="bench.db.migrations"):
        db_module.apply_migrations(conn, migrations_dir)

    messages = [r.getMessage() for r in caplog.records]
    # Summary line surfaces the (applied, pending) counts.
    assert any(
        "2 applied" in m and "3 pending" in m and "5 files" in m
        for m in messages
    ), messages
    # Each pending file is enumerated so the audit log doesn't have to
    # cross-reference filesystem state.
    assert any("pending: 003_c.sql" in m for m in messages)
    assert any("pending: 004_d.sql" in m for m in messages)
    assert any("pending: 005_e.sql" in m for m in messages)


def test_no_pending_logs_only_summary(monkeypatch, tmp_path, caplog):
    """All applied → summary line only, no per-file noise."""
    monkeypatch.delenv("LIS_DISABLE_AUTO_MIGRATE", raising=False)
    migrations_dir = tmp_path / "migrations_pg"
    migrations_dir.mkdir()
    _write_migration(migrations_dir, "001_a.sql")

    conn, cur = _fake_conn(applied_filenames=["001_a.sql"])

    with caplog.at_level(logging.INFO, logger="bench.db.migrations"):
        db_module.apply_migrations(conn, migrations_dir)

    messages = [r.getMessage() for r in caplog.records]
    assert any(
        "1 applied" in m and "0 pending" in m for m in messages
    ), messages
    # No "pending: …" per-file line when there's nothing pending.
    assert not any("pending: " in m for m in messages)


# ---------------------------------------------------------------------------
# Error surfacing on per-migration failure
# ---------------------------------------------------------------------------


def test_failing_migration_logs_and_reraises(monkeypatch, tmp_path, caplog):
    """A migration that errors must:
    - log an error line that names the file + error class + message
    - re-raise so the deploy fails loudly rather than silently dropping
    """
    monkeypatch.delenv("LIS_DISABLE_AUTO_MIGRATE", raising=False)
    migrations_dir = tmp_path / "migrations_pg"
    migrations_dir.mkdir()
    _write_migration(migrations_dir, "003_broken.sql", "DROP TABLE no_such;")

    conn = MagicMock(spec=psycopg.Connection)
    cursor_ctx = MagicMock()
    cur = MagicMock()
    cursor_ctx.__enter__.return_value = cur
    cursor_ctx.__exit__.return_value = None
    conn.cursor.return_value = cursor_ctx
    # First call (SELECT existing migrations): returns empty.
    # Second call (the broken migration's execute): raises.
    cur.fetchall.return_value = []

    call_count = {"n": 0}

    def execute_side_effect(*args, **kwargs):
        call_count["n"] += 1
        sql = args[0] if args else ""
        # Calls in order:
        # 1. CREATE TABLE IF NOT EXISTS schema_migrations
        # 2. SELECT filename FROM schema_migrations
        # 3. The broken migration's SQL ← raise here
        if "DROP TABLE" in sql:
            raise psycopg.errors.UndefinedTable('relation "no_such" does not exist')

    cur.execute.side_effect = execute_side_effect

    with caplog.at_level(logging.ERROR, logger="bench.db.migrations"):
        with pytest.raises(psycopg.errors.UndefinedTable):
            db_module.apply_migrations(conn, migrations_dir)

    messages = [r.getMessage() for r in caplog.records]
    assert any(
        "FAILED 003_broken.sql" in m and "UndefinedTable" in m
        for m in messages
    ), messages
