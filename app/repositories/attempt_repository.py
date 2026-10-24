from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import psycopg

from ..models import Attempt
from ._pg import jsonb, naive_utc, uuid_str


# Alias for backwards-compat with the local name `_naive_utc` used
# throughout this file. The implementation now lives in `._pg`.
_naive_utc = naive_utc


def _row_to_attempt(r: dict) -> Attempt:
    return Attempt(
        id=r["id"],
        user_id=uuid_str(r["user_id"]),
        problem_id=r["problem_id"],
        problem_version=r["problem_version"],
        started_at=_naive_utc(r["started_at"]),
        ended_at=_naive_utc(r["ended_at"]),
        language_used=r["language_used"],
        final_code=r["final_code"],
        solved_without_lookup=r["solved_without_lookup_bool"],
        confidence_1_to_5=r["confidence_1_to_5"],
        time_to_first_edit_seconds=r["time_to_first_edit_seconds"],
        edit_count=r["edit_count"],
        looked_at_solution=bool(r["looked_at_solution_bool"]),
        looked_at_pitfalls=bool(r["looked_at_pitfalls_bool"]),
        test_passed=r["test_passed_bool"],
        test_output=r["test_output"],
        notes_md=r["notes_md"],
        explore_notes=r.get("explore_notes"),
        brainstorm_notes=r.get("brainstorm_notes"),
        plan_notes=r.get("plan_notes"),
        verify_notes=r.get("verify_notes"),
        time_per_phase=jsonb(r.get("time_per_phase_json")),
        interview_mode=bool(r.get("interview_mode_bool", False)),
        hints_used=jsonb(r.get("hints_used_json")),
        user_tests_code=r.get("user_tests_code"),
        # Migration 011: NULL on pre-migration rows and on
        # operator-unassigned attempts.
        initiative_slug=r.get("initiative_slug"),
        # Migration 014 (interview-mode v1): per-attempt snapshot of
        # the problem's phase budgets at submit time + cutoff flag +
        # forward-compat coach preference. NULL/False on pre-migration
        # rows.
        phase_budgets=jsonb(r.get("phase_budgets_json")),
        cutoff=bool(r.get("cutoff_bool", False)),
        interview_mode_preference=r.get("interview_mode_preference"),
    )


class AttemptRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def insert(self, a: Attempt) -> int:
        # Layered fallback. Each layer tries one more column-set than the
        # previous; on UndefinedColumn we roll back and try the next.
        # That way a fresh DB gets the full insert, and a DB lagging on
        # migrations still works with whatever columns it has.
        try:
            new_id = self._insert_with_phase_budgets(a)
        except psycopg.errors.UndefinedColumn:
            self.conn.rollback()
            try:
                new_id = self._insert_with_initiative(a)
            except psycopg.errors.UndefinedColumn:
                self.conn.rollback()
                try:
                    new_id = self._insert_with_user_tests(a)
                except psycopg.errors.UndefinedColumn:
                    # Backwards-compat while migrations lag app deploys.
                    self.conn.rollback()
                    new_id = self._insert_legacy(a)
        self.conn.commit()
        return new_id

    def _insert_with_phase_budgets(self, a: Attempt) -> int:
        """Migration-014 insert path: includes phase_budgets_json +
        cutoff_bool + interview_mode_preference. Top of the fallback
        chain since these are the newest columns."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO attempts (
                    user_id, problem_id, problem_version, started_at, ended_at,
                    language_used, final_code, solved_without_lookup_bool,
                    confidence_1_to_5, time_to_first_edit_seconds, edit_count,
                    looked_at_solution_bool, looked_at_pitfalls_bool,
                    test_passed_bool, test_output, notes_md,
                    explore_notes, brainstorm_notes, plan_notes, verify_notes,
                    time_per_phase_json, interview_mode_bool, hints_used_json,
                    user_tests_code, initiative_slug,
                    phase_budgets_json, cutoff_bool, interview_mode_preference
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    a.user_id,
                    a.problem_id,
                    a.problem_version,
                    a.started_at,
                    a.ended_at,
                    a.language_used,
                    a.final_code,
                    a.solved_without_lookup,
                    a.confidence_1_to_5,
                    a.time_to_first_edit_seconds,
                    a.edit_count,
                    bool(a.looked_at_solution),
                    bool(a.looked_at_pitfalls),
                    a.test_passed,
                    a.test_output,
                    a.notes_md,
                    a.explore_notes,
                    a.brainstorm_notes,
                    a.plan_notes,
                    a.verify_notes,
                    json.dumps(a.time_per_phase) if a.time_per_phase else None,
                    bool(a.interview_mode),
                    json.dumps(a.hints_used) if a.hints_used else None,
                    a.user_tests_code,
                    a.initiative_slug,
                    json.dumps(a.phase_budgets) if a.phase_budgets else None,
                    bool(a.cutoff),
                    a.interview_mode_preference,
                ),
            )
            return cur.fetchone()["id"]

    def _insert_with_initiative(self, a: Attempt) -> int:
        """Migration-011 insert path: includes the new initiative_slug column."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO attempts (
                    user_id, problem_id, problem_version, started_at, ended_at,
                    language_used, final_code, solved_without_lookup_bool,
                    confidence_1_to_5, time_to_first_edit_seconds, edit_count,
                    looked_at_solution_bool, looked_at_pitfalls_bool,
                    test_passed_bool, test_output, notes_md,
                    explore_notes, brainstorm_notes, plan_notes, verify_notes,
                    time_per_phase_json, interview_mode_bool, hints_used_json,
                    user_tests_code, initiative_slug
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    a.user_id,
                    a.problem_id,
                    a.problem_version,
                    a.started_at,
                    a.ended_at,
                    a.language_used,
                    a.final_code,
                    a.solved_without_lookup,
                    a.confidence_1_to_5,
                    a.time_to_first_edit_seconds,
                    a.edit_count,
                    bool(a.looked_at_solution),
                    bool(a.looked_at_pitfalls),
                    a.test_passed,
                    a.test_output,
                    a.notes_md,
                    a.explore_notes,
                    a.brainstorm_notes,
                    a.plan_notes,
                    a.verify_notes,
                    json.dumps(a.time_per_phase) if a.time_per_phase else None,
                    bool(a.interview_mode),
                    json.dumps(a.hints_used) if a.hints_used else None,
                    a.user_tests_code,
                    a.initiative_slug,
                ),
            )
            return cur.fetchone()["id"]

    def _insert_with_user_tests(self, a: Attempt) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO attempts (
                    user_id, problem_id, problem_version, started_at, ended_at,
                    language_used, final_code, solved_without_lookup_bool,
                    confidence_1_to_5, time_to_first_edit_seconds, edit_count,
                    looked_at_solution_bool, looked_at_pitfalls_bool,
                    test_passed_bool, test_output, notes_md,
                    explore_notes, brainstorm_notes, plan_notes, verify_notes,
                    time_per_phase_json, interview_mode_bool, hints_used_json,
                    user_tests_code
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    a.user_id,
                    a.problem_id,
                    a.problem_version,
                    a.started_at,
                    a.ended_at,
                    a.language_used,
                    a.final_code,
                    a.solved_without_lookup,
                    a.confidence_1_to_5,
                    a.time_to_first_edit_seconds,
                    a.edit_count,
                    bool(a.looked_at_solution),
                    bool(a.looked_at_pitfalls),
                    a.test_passed,
                    a.test_output,
                    a.notes_md,
                    a.explore_notes,
                    a.brainstorm_notes,
                    a.plan_notes,
                    a.verify_notes,
                    json.dumps(a.time_per_phase) if a.time_per_phase else None,
                    bool(a.interview_mode),
                    json.dumps(a.hints_used) if a.hints_used else None,
                    a.user_tests_code,
                ),
            )
            return cur.fetchone()["id"]

    def _insert_legacy(self, a: Attempt) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO attempts (
                    user_id, problem_id, problem_version, started_at, ended_at,
                    language_used, final_code, solved_without_lookup_bool,
                    confidence_1_to_5, time_to_first_edit_seconds, edit_count,
                    looked_at_solution_bool, looked_at_pitfalls_bool,
                    test_passed_bool, test_output, notes_md,
                    explore_notes, brainstorm_notes, plan_notes, verify_notes,
                    time_per_phase_json, interview_mode_bool, hints_used_json
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    a.user_id,
                    a.problem_id,
                    a.problem_version,
                    a.started_at,
                    a.ended_at,
                    a.language_used,
                    a.final_code,
                    a.solved_without_lookup,
                    a.confidence_1_to_5,
                    a.time_to_first_edit_seconds,
                    a.edit_count,
                    bool(a.looked_at_solution),
                    bool(a.looked_at_pitfalls),
                    a.test_passed,
                    a.test_output,
                    a.notes_md,
                    a.explore_notes,
                    a.brainstorm_notes,
                    a.plan_notes,
                    a.verify_notes,
                    json.dumps(a.time_per_phase) if a.time_per_phase else None,
                    bool(a.interview_mode),
                    json.dumps(a.hints_used) if a.hints_used else None,
                ),
            )
            return cur.fetchone()["id"]

    def last_for_problem(self, user_id: str, problem_id: int) -> Attempt | None:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM attempts WHERE user_id = %s AND problem_id = %s "
                "ORDER BY started_at DESC LIMIT 1",
                (user_id, problem_id),
            )
            r = cur.fetchone()
        return _row_to_attempt(r) if r else None

    def all_for_user(self, user_id: str) -> list[Attempt]:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM attempts WHERE user_id = %s ORDER BY started_at DESC",
                (user_id,),
            )
            rows = cur.fetchall()
        return [_row_to_attempt(r) for r in rows]

    def list_for_user_since(self, user_id: str, since: datetime) -> list[Attempt]:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM attempts "
                "WHERE user_id = %s AND started_at >= %s "
                "ORDER BY started_at DESC",
                (user_id, since),
            )
            rows = cur.fetchall()
        return [_row_to_attempt(r) for r in rows]

    def has_passing_attempt(self, user_id: str, problem_id: int) -> bool:
        """True when this user has ever passed this problem's tests.

        The track checkpoint gate reads this: a section is only completable
        once its paired problem has actually run green, so "checkpoint
        passed" means demonstrated application, not self-report.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1 FROM attempts
                 WHERE user_id = %s AND problem_id = %s AND test_passed IS TRUE
                 LIMIT 1
                """,
                (user_id, problem_id),
            )
            return cur.fetchone() is not None

    def count_for_problem(self, user_id: str, problem_id: int) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS c FROM attempts WHERE user_id = %s AND problem_id = %s",
                (user_id, problem_id),
            )
            return int(cur.fetchone()["c"])
