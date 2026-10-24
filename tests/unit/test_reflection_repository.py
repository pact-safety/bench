"""Tests for ReflectionRepository column-lag compatibility behavior."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import psycopg

from app.models import Reflection
from app.repositories.reflection_repository import ReflectionRepository, _row


def test_row_handles_missing_calibration_column():
    row = {
        "id": 4,
        "user_id": "00000000-0000-0000-0000-000000000001",
        "period_start": datetime(2026, 5, 10, 0, 0, 0),
        "period_end": datetime(2026, 5, 17, 0, 0, 0),
        "generated_at": datetime(2026, 5, 17, 9, 0, 0),
        "prompts_json": [{"label": "Calibration", "prompt": "predict vs actual"}],
        "response_md": None,
        "response_updated_at": None,
        "summary_md": None,
        "method": "keyword_fallback",
        "model_used": None,
    }

    reflection = _row(row)

    assert reflection.id == 4
    assert reflection.calibration_json is None


def test_save_response_retries_without_calibration_on_undefined_column(monkeypatch):
    conn = MagicMock()
    repo = ReflectionRepository(conn)

    save_calls: list[str] = []

    def fail_with_calibration(_refl_id, _response_md, _calibration_json):
        save_calls.append("with_calibration")
        raise psycopg.errors.UndefinedColumn("column calibration_json does not exist")

    def succeed_legacy(_refl_id, _response_md):
        save_calls.append("legacy")

    monkeypatch.setattr(repo, "_save_response_with_calibration", fail_with_calibration)
    monkeypatch.setattr(repo, "_save_response_legacy", succeed_legacy)

    repo.save_response(8, "hi", calibration_json={"predicted_pct": 70, "actual_pct": 50})

    assert save_calls == ["with_calibration", "legacy"]
    conn.rollback.assert_called_once()
    conn.commit.assert_called_once()


def _reflection() -> Reflection:
    return Reflection(
        id=None,
        user_id="00000000-0000-0000-0000-000000000001",
        period_start=datetime(2026, 5, 16, 0, 0, 0),
        period_end=datetime(2026, 5, 23, 0, 0, 0),
        generated_at=datetime(2026, 5, 23, 7, 0, 0),
        prompts=[{"label": "Hits", "prompt": "What worked?"}],
        response_md=None,
        response_updated_at=None,
        summary_md="ok",
        method="claude",
        model_used="claude-haiku-4-5",
        pregenerated=True,
        initiative_slug="bench",
    )


def test_insert_falls_back_through_layers_on_undefined_column(monkeypatch):
    """DB lagging on migration 011 (initiative_slug) AND on migration 008
    (pregenerated) → legacy insert wins."""
    conn = MagicMock()
    repo = ReflectionRepository(conn)
    r = _reflection()

    insert_calls: list[str] = []

    def fail_initiative(_r):
        insert_calls.append("with_initiative")
        raise psycopg.errors.UndefinedColumn("column initiative_slug does not exist")

    def fail_pregenerated(_r):
        insert_calls.append("with_pregenerated")
        raise psycopg.errors.UndefinedColumn("column pregenerated does not exist")

    def succeed_legacy(_r):
        insert_calls.append("legacy")
        return 55

    monkeypatch.setattr(repo, "_insert_with_initiative", fail_initiative)
    monkeypatch.setattr(repo, "_insert_with_pregenerated", fail_pregenerated)
    monkeypatch.setattr(repo, "_insert_legacy", succeed_legacy)

    new_id = repo.insert(r)

    assert new_id == 55
    assert insert_calls == ["with_initiative", "with_pregenerated", "legacy"]
    assert conn.rollback.call_count == 2


def test_insert_uses_initiative_layer_when_migration_011_present(monkeypatch):
    """Happy path: migration 011 applied → top layer succeeds, no fallback."""
    conn = MagicMock()
    repo = ReflectionRepository(conn)
    r = _reflection()

    insert_calls: list[str] = []

    def succeed_initiative(_r):
        insert_calls.append("with_initiative")
        return 66

    monkeypatch.setattr(repo, "_insert_with_initiative", succeed_initiative)

    new_id = repo.insert(r)

    assert new_id == 66
    assert insert_calls == ["with_initiative"]
    conn.rollback.assert_not_called()


def test_row_includes_initiative_slug_when_present():
    """Migration 011 column round-trips through the row mapper."""
    row = {
        "id": 7,
        "user_id": "00000000-0000-0000-0000-000000000001",
        "period_start": datetime(2026, 5, 10, 0, 0, 0),
        "period_end": datetime(2026, 5, 17, 0, 0, 0),
        "generated_at": datetime(2026, 5, 17, 9, 0, 0),
        "prompts_json": [],
        "response_md": None,
        "response_updated_at": None,
        "summary_md": None,
        "method": "claude",
        "model_used": "claude-haiku-4-5",
        "pregenerated": True,
        "initiative_slug": "capstone",
    }

    reflection = _row(row)

    assert reflection.initiative_slug == "capstone"


def test_row_returns_none_for_initiative_slug_when_column_missing():
    """Pre-migration row (column absent) → None, not KeyError."""
    row = {
        "id": 8,
        "user_id": "00000000-0000-0000-0000-000000000001",
        "period_start": datetime(2026, 5, 10, 0, 0, 0),
        "period_end": datetime(2026, 5, 17, 0, 0, 0),
        "generated_at": datetime(2026, 5, 17, 9, 0, 0),
        "prompts_json": [],
        "response_md": None,
        "response_updated_at": None,
        "summary_md": None,
        "method": "claude",
        "model_used": "claude-haiku-4-5",
        # no `initiative_slug` key
    }

    reflection = _row(row)

    assert reflection.initiative_slug is None
