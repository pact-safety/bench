"""Tests for WritingRepository column-lag compatibility (migration 011)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import psycopg

from app.repositories.writing_repository import WritingRepository, _row_to_writing


_UID = "00000000-0000-0000-0000-000000000001"


def test_insert_uses_initiative_layer_when_migration_011_present(monkeypatch):
    """Happy path: top layer succeeds, no fallback."""
    conn = MagicMock()
    repo = WritingRepository(conn)

    insert_calls: list[str] = []

    def succeed_initiative(**kwargs):
        insert_calls.append("with_initiative")
        assert kwargs["initiative_slug"] == "capstone"
        return 11

    monkeypatch.setattr(repo, "_insert_with_initiative", succeed_initiative)

    new_id = repo.insert(_UID, "Title", "body", initiative_slug="capstone")

    assert new_id == 11
    assert insert_calls == ["with_initiative"]
    conn.rollback.assert_not_called()


def test_insert_falls_back_to_legacy_when_column_missing(monkeypatch):
    """DB lagging migration 011 → falls back to insert without
    initiative_slug. The slug is silently dropped — acceptable for a
    pre-migration DB; the next insert after migration applies the column."""
    conn = MagicMock()
    repo = WritingRepository(conn)

    insert_calls: list[str] = []

    def fail_initiative(**kwargs):
        insert_calls.append("with_initiative")
        raise psycopg.errors.UndefinedColumn(
            "column initiative_slug does not exist"
        )

    def succeed_legacy(**kwargs):
        insert_calls.append("legacy")
        # legacy path doesn't accept initiative_slug kwarg
        assert "initiative_slug" not in kwargs
        return 22

    monkeypatch.setattr(repo, "_insert_with_initiative", fail_initiative)
    monkeypatch.setattr(repo, "_insert_legacy", succeed_legacy)

    new_id = repo.insert(_UID, "Title", "body", initiative_slug="capstone")

    assert new_id == 22
    assert insert_calls == ["with_initiative", "legacy"]
    conn.rollback.assert_called_once()


def test_insert_legacy_callers_without_initiative_slug_still_work(monkeypatch):
    """Pre-existing callers that don't pass initiative_slug must continue
    to work without modification."""
    conn = MagicMock()
    repo = WritingRepository(conn)

    insert_calls: list[str] = []

    def succeed_initiative(**kwargs):
        insert_calls.append("with_initiative")
        # Default None when caller doesn't pass it.
        assert kwargs.get("initiative_slug") is None
        return 33

    monkeypatch.setattr(repo, "_insert_with_initiative", succeed_initiative)

    new_id = repo.insert(_UID, "Title", "body")

    assert new_id == 33
    assert insert_calls == ["with_initiative"]


def test_row_includes_initiative_slug_when_present():
    """Migration 011 column round-trips through the row mapper."""
    row = {
        "id": 7,
        "user_id": _UID,
        "title": "Test",
        "body_md": "hello",
        "source_refs_json": [],
        "status": "draft",
        "word_count": 1,
        "created_at": datetime(2026, 5, 17, 9, 0, 0),
        "updated_at": datetime(2026, 5, 17, 9, 0, 0),
        "published_at": None,
        "initiative_slug": "anthropic-fellows",
    }

    writing = _row_to_writing(row)

    assert writing.initiative_slug == "anthropic-fellows"


def test_row_returns_none_for_initiative_slug_when_column_missing():
    """Pre-migration row → None, not KeyError."""
    row = {
        "id": 8,
        "user_id": _UID,
        "title": "Test",
        "body_md": "hello",
        "source_refs_json": [],
        "status": "draft",
        "word_count": 1,
        "created_at": datetime(2026, 5, 17, 9, 0, 0),
        "updated_at": datetime(2026, 5, 17, 9, 0, 0),
        "published_at": None,
        # no `initiative_slug` key
    }

    writing = _row_to_writing(row)

    assert writing.initiative_slug is None


def test_status_and_unsaved_content_are_one_owned_update():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.rowcount = 1
    repo = WritingRepository(conn)
    assert repo.save_with_status(7, user_id=_UID, title="unsaved title", body_md="two words", status="published")
    cur.execute.assert_called_once()
    query, params = cur.execute.call_args.args
    assert "title = %s" in query and "body_md = %s" in query
    assert "status = %s" in query and "user_id = %s" in query
    assert "COALESCE(published_at, NOW())" in query
    assert params == ("unsaved title", "two words", 2, "published", "published", 7, _UID)
    conn.commit.assert_called_once()


def test_status_and_content_update_reports_missing_owner():
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.rowcount = 0
    assert not WritingRepository(conn).save_with_status(7, user_id=_UID, title="", body_md="", status="archived")
