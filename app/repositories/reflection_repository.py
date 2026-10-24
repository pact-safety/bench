from __future__ import annotations

import json
from datetime import datetime

import psycopg

from ..models import Reflection
from ._pg import jsonb, naive_utc, uuid_str


def _row(r: dict) -> Reflection:
    return Reflection(
        id=r["id"],
        user_id=uuid_str(r["user_id"]),
        period_start=naive_utc(r["period_start"]),
        period_end=naive_utc(r["period_end"]),
        generated_at=naive_utc(r["generated_at"]),
        prompts=jsonb(r.get("prompts_json")) or [],
        response_md=r["response_md"],
        response_updated_at=naive_utc(r["response_updated_at"]),
        summary_md=r["summary_md"],
        method=r["method"],
        model_used=r["model_used"],
        calibration_json=jsonb(r.get("calibration_json")),
        # Migration 008 added this column with DEFAULT FALSE; pre-migration
        # rows simply won't have the key so `.get` returns None → False.
        pregenerated=bool(r.get("pregenerated", False)),
        # Migration 011: NULL on pre-migration rows.
        initiative_slug=r.get("initiative_slug"),
    )


class ReflectionRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def insert(self, r: Reflection) -> int:
        # Layered fallback. Try the newest column-set; on UndefinedColumn
        # fall back one layer at a time so the app survives DBs lagging
        # on migrations.
        try:
            return self._insert_with_initiative(r)
        except psycopg.errors.UndefinedColumn:
            self.conn.rollback()
            try:
                return self._insert_with_pregenerated(r)
            except psycopg.errors.UndefinedColumn:
                self.conn.rollback()
                return self._insert_legacy(r)

    def _insert_with_initiative(self, r: Reflection) -> int:
        """Migration-011 insert path: includes initiative_slug."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO reflections
                  (user_id, period_start, period_end, generated_at,
                   prompts_json, response_md, response_updated_at,
                   summary_md, method, model_used, pregenerated,
                   initiative_slug)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    r.user_id,
                    r.period_start,
                    r.period_end,
                    r.generated_at,
                    json.dumps(r.prompts),
                    r.response_md,
                    r.response_updated_at,
                    r.summary_md,
                    r.method,
                    r.model_used,
                    bool(r.pregenerated),
                    r.initiative_slug,
                ),
            )
            new_id = cur.fetchone()["id"]
        self.conn.commit()
        return new_id

    def _insert_with_pregenerated(self, r: Reflection) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO reflections
                  (user_id, period_start, period_end, generated_at,
                   prompts_json, response_md, response_updated_at,
                   summary_md, method, model_used, pregenerated)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    r.user_id,
                    r.period_start,
                    r.period_end,
                    r.generated_at,
                    json.dumps(r.prompts),
                    r.response_md,
                    r.response_updated_at,
                    r.summary_md,
                    r.method,
                    r.model_used,
                    bool(r.pregenerated),
                ),
            )
            new_id = cur.fetchone()["id"]
        self.conn.commit()
        return new_id

    def _insert_legacy(self, r: Reflection) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO reflections
                  (user_id, period_start, period_end, generated_at,
                   prompts_json, response_md, response_updated_at,
                   summary_md, method, model_used)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    r.user_id,
                    r.period_start,
                    r.period_end,
                    r.generated_at,
                    json.dumps(r.prompts),
                    r.response_md,
                    r.response_updated_at,
                    r.summary_md,
                    r.method,
                    r.model_used,
                ),
            )
            new_id = cur.fetchone()["id"]
        self.conn.commit()
        return new_id

    def latest_in_period(
        self,
        user_id: str,
        period_start: datetime,
        period_end: datetime,
    ) -> Reflection | None:
        """Return the most-recently-generated reflection covering this
        period, if any. The pre-generation cron uses this to skip users
        whose row for the current week already exists (operator-triggered
        OR an earlier cron run)."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM reflections
                 WHERE user_id = %s
                   AND period_start <= %s
                   AND period_end >= %s
                 ORDER BY generated_at DESC
                 LIMIT 1
                """,
                (user_id, period_end, period_start),
            )
            row = cur.fetchone()
        return _row(row) if row else None

    def get(self, refl_id: int) -> Reflection | None:
        with self.conn.cursor() as cur:
            cur.execute("SELECT * FROM reflections WHERE id = %s", (refl_id,))
            row = cur.fetchone()
        return _row(row) if row else None

    def list_for_user(self, user_id: str, limit: int = 50) -> list[Reflection]:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM reflections WHERE user_id = %s "
                "ORDER BY generated_at DESC LIMIT %s",
                (user_id, limit),
            )
            rows = cur.fetchall()
        return [_row(r) for r in rows]

    def list_for_user_since(self, user_id: str, since: datetime) -> list[Reflection]:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM reflections WHERE user_id = %s "
                "AND generated_at >= %s "
                "ORDER BY generated_at DESC",
                (user_id, since),
            )
            rows = cur.fetchall()
        return [_row(r) for r in rows]

    def save_response(
        self,
        refl_id: int,
        response_md: str | None,
        calibration_json: dict | None = None,
    ) -> None:
        try:
            if calibration_json is None:
                self._save_response_legacy(refl_id, response_md)
            else:
                self._save_response_with_calibration(
                    refl_id,
                    response_md,
                    calibration_json,
                )
        except psycopg.errors.UndefinedColumn:
            # Migration-safe fallback: older DBs may not have
            # `reflections.calibration_json` yet.
            self.conn.rollback()
            self._save_response_legacy(refl_id, response_md)
        self.conn.commit()

    def _save_response_legacy(self, refl_id: int, response_md: str | None) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE reflections
                   SET response_md = %s,
                       response_updated_at = NOW()
                 WHERE id = %s
                """,
                (response_md, refl_id),
            )

    def _save_response_with_calibration(
        self,
        refl_id: int,
        response_md: str | None,
        calibration_json: dict,
    ) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE reflections
                   SET response_md = %s,
                       calibration_json = %s,
                       response_updated_at = NOW()
                 WHERE id = %s
                """,
                (
                    response_md,
                    json.dumps(calibration_json),
                    refl_id,
                ),
            )
