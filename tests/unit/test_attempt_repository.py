"""Tests for AttemptRepository compatibility around user_tests_code."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import psycopg

from app.models import Attempt
from app.repositories.attempt_repository import AttemptRepository, _row_to_attempt


def _attempt() -> Attempt:
    return Attempt(
        id=None,
        user_id="00000000-0000-0000-0000-000000000001",
        problem_id=1,
        problem_version=1,
        started_at=datetime(2026, 5, 17, 11, 0, 0),
        ended_at=datetime(2026, 5, 17, 11, 5, 0),
        language_used="python",
        final_code="def f():\n    return 1\n",
        solved_without_lookup=True,
        confidence_1_to_5=4,
        time_to_first_edit_seconds=10,
        edit_count=2,
        looked_at_solution=False,
        looked_at_pitfalls=False,
        test_passed=True,
        test_output="ok",
        notes_md=None,
    )


def test_row_to_attempt_handles_missing_user_tests_column():
    row = {
        "id": 9,
        "user_id": "00000000-0000-0000-0000-000000000001",
        "problem_id": 1,
        "problem_version": 1,
        "started_at": datetime(2026, 5, 17, 11, 0, 0),
        "ended_at": datetime(2026, 5, 17, 11, 5, 0),
        "language_used": "python",
        "final_code": "x",
        "solved_without_lookup_bool": True,
        "confidence_1_to_5": 3,
        "time_to_first_edit_seconds": 5,
        "edit_count": 1,
        "looked_at_solution_bool": False,
        "looked_at_pitfalls_bool": False,
        "test_passed_bool": True,
        "test_output": "ok",
        "notes_md": None,
    }

    attempt = _row_to_attempt(row)

    assert attempt.id == 9
    assert attempt.user_tests_code is None


def test_insert_falls_back_through_all_layers_on_undefined_column(monkeypatch):
    """Full migration-lag chain. DB without migration 014 (phase budgets)
    AND without 011 (initiative_slug) AND without 006 (user_tests_code) →
    legacy insert wins. The four-layer cascade catches each missing
    column and steps down to the next."""
    conn = MagicMock()
    repo = AttemptRepository(conn)
    a = _attempt()

    insert_calls: list[str] = []

    def fail_phase_budgets(_attempt):
        insert_calls.append("with_phase_budgets")
        raise psycopg.errors.UndefinedColumn("column phase_budgets_json does not exist")

    def fail_initiative(_attempt):
        insert_calls.append("with_initiative")
        raise psycopg.errors.UndefinedColumn("column initiative_slug does not exist")

    def fail_user_tests(_attempt):
        insert_calls.append("with_user_tests")
        raise psycopg.errors.UndefinedColumn("column user_tests_code does not exist")

    def succeed_legacy(_attempt):
        insert_calls.append("legacy")
        return 77

    monkeypatch.setattr(repo, "_insert_with_phase_budgets", fail_phase_budgets)
    monkeypatch.setattr(repo, "_insert_with_initiative", fail_initiative)
    monkeypatch.setattr(repo, "_insert_with_user_tests", fail_user_tests)
    monkeypatch.setattr(repo, "_insert_legacy", succeed_legacy)

    new_id = repo.insert(a)

    assert new_id == 77
    assert insert_calls == ["with_phase_budgets", "with_initiative", "with_user_tests", "legacy"]
    assert conn.rollback.call_count == 3  # one per layer that errored
    conn.commit.assert_called_once()


def test_insert_uses_phase_budgets_layer_when_migration_014_present(monkeypatch):
    """Happy path: migration 014 applied → phase_budgets_json column
    exists → top layer succeeds, no fallback fires."""
    conn = MagicMock()
    repo = AttemptRepository(conn)
    a = _attempt()

    insert_calls: list[str] = []

    def succeed_phase_budgets(_attempt):
        insert_calls.append("with_phase_budgets")
        return 100

    monkeypatch.setattr(repo, "_insert_with_phase_budgets", succeed_phase_budgets)

    new_id = repo.insert(a)

    assert new_id == 100
    assert insert_calls == ["with_phase_budgets"]
    conn.rollback.assert_not_called()
    conn.commit.assert_called_once()


def test_insert_uses_initiative_layer_when_migration_014_missing(monkeypatch):
    """Migration 014 not yet applied but 011 is: skip the phase-budgets
    layer, succeed at the initiative-slug layer."""
    conn = MagicMock()
    repo = AttemptRepository(conn)
    a = _attempt()

    insert_calls: list[str] = []

    def fail_phase_budgets(_attempt):
        insert_calls.append("with_phase_budgets")
        raise psycopg.errors.UndefinedColumn("column phase_budgets_json does not exist")

    def succeed_initiative(_attempt):
        insert_calls.append("with_initiative")
        return 88

    monkeypatch.setattr(repo, "_insert_with_phase_budgets", fail_phase_budgets)
    monkeypatch.setattr(repo, "_insert_with_initiative", succeed_initiative)

    new_id = repo.insert(a)

    assert new_id == 88
    assert insert_calls == ["with_phase_budgets", "with_initiative"]
    conn.rollback.assert_called_once()
    conn.commit.assert_called_once()


def test_insert_retries_user_tests_when_011_and_014_missing(monkeypatch):
    """Migrations 014 + 011 both missing but 006 is: skip the top two,
    succeed at the user_tests layer."""
    conn = MagicMock()
    repo = AttemptRepository(conn)
    a = _attempt()

    insert_calls: list[str] = []

    def fail_phase_budgets(_attempt):
        insert_calls.append("with_phase_budgets")
        raise psycopg.errors.UndefinedColumn("column phase_budgets_json does not exist")

    def fail_initiative(_attempt):
        insert_calls.append("with_initiative")
        raise psycopg.errors.UndefinedColumn("column initiative_slug does not exist")

    def succeed_user_tests(_attempt):
        insert_calls.append("with_user_tests")
        return 99

    monkeypatch.setattr(repo, "_insert_with_phase_budgets", fail_phase_budgets)
    monkeypatch.setattr(repo, "_insert_with_initiative", fail_initiative)
    monkeypatch.setattr(repo, "_insert_with_user_tests", succeed_user_tests)

    new_id = repo.insert(a)

    assert new_id == 99
    assert insert_calls == ["with_phase_budgets", "with_initiative", "with_user_tests"]
    assert conn.rollback.call_count == 2
    conn.commit.assert_called_once()
