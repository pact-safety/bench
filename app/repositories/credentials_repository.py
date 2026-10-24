from __future__ import annotations

import json
from datetime import datetime

import psycopg

from ..models import CredentialAssessment, CredentialFile, CredentialRun
from ._pg import jsonb, naive_utc, uuid_str


def _row_to_run(r: dict) -> CredentialRun:
    return CredentialRun(
        id=r["id"],
        user_id=uuid_str(r["user_id"]),
        started_at=naive_utc(r["started_at"]),
        completed_at=naive_utc(r["completed_at"]),
        status_text=r["status_text"],
    )


def _row_to_file(r: dict) -> CredentialFile:
    return CredentialFile(
        id=r["id"],
        run_id=r["run_id"],
        filename=r["filename"],
        content_type=r["content_type"],
        byte_size=r["byte_size"],
        sha256=r["sha256"],
        extracted_text=r["extracted_text"],
        uploaded_at=naive_utc(r["uploaded_at"]),
    )


def _row_to_assessment(r: dict) -> CredentialAssessment:
    return CredentialAssessment(
        id=r["id"],
        run_id=r["run_id"],
        inferred_axis_scores=jsonb(r["inferred_axis_scores_json"]) or {},
        summary_md=r["summary_md"],
        rationale=jsonb(r.get("rationale_json")) or {},
        method=r["method"],
        model_used=r["model_used"],
        created_at=naive_utc(r["created_at"]),
    )


class CredentialsRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def start_run(self, user_id: str) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO credential_runs (user_id, started_at) "
                "VALUES (%s, NOW()) RETURNING id",
                (user_id,),
            )
            new_id = cur.fetchone()["id"]
        self.conn.commit()
        return new_id

    def complete_run(self, run_id: int, status: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE credential_runs SET completed_at = NOW(), "
                "status_text = %s WHERE id = %s",
                (status, run_id),
            )
        self.conn.commit()

    def get_run(self, run_id: int) -> CredentialRun | None:
        with self.conn.cursor() as cur:
            cur.execute("SELECT * FROM credential_runs WHERE id = %s", (run_id,))
            r = cur.fetchone()
        return _row_to_run(r) if r else None

    def latest_completed(self, user_id: str) -> CredentialRun | None:
        runs = self.list_completed_for_user(user_id, limit=1)
        return runs[0] if runs else None

    def list_completed_for_user(self, user_id: str, limit: int = 10) -> list[CredentialRun]:
        safe_limit = max(1, min(int(limit), 100))
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM credential_runs WHERE user_id = %s "
                "AND completed_at IS NOT NULL "
                "ORDER BY completed_at DESC, id DESC LIMIT %s",
                (user_id, safe_limit),
            )
            rows = cur.fetchall()
        return [_row_to_run(r) for r in rows]

    def completed_since(self, user_id: str, since: datetime) -> list[CredentialRun]:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM credential_runs WHERE user_id = %s "
                "AND completed_at IS NOT NULL "
                "AND completed_at >= %s "
                "ORDER BY completed_at DESC, id DESC",
                (user_id, since),
            )
            rows = cur.fetchall()
        return [_row_to_run(r) for r in rows]

    def record_file(
        self,
        run_id: int,
        filename: str,
        content_type: str | None,
        byte_size: int,
        sha256: str | None,
        extracted_text: str | None,
    ) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO credential_files
                    (run_id, filename, content_type, byte_size, sha256, extracted_text)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (run_id, filename, content_type, byte_size, sha256, extracted_text),
            )
            new_id = cur.fetchone()["id"]
        self.conn.commit()
        return new_id

    def files_for_run(self, run_id: int) -> list[CredentialFile]:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM credential_files WHERE run_id = %s ORDER BY id",
                (run_id,),
            )
            rows = cur.fetchall()
        return [_row_to_file(r) for r in rows]

    def first_files_by_run(self, run_ids: list[int]) -> dict[int, CredentialFile]:
        """Return a {run_id -> first uploaded file} map in ONE round-trip.

        Replaces N calls to ``files_for_run`` when callers only need the
        primary filename per run (the /aim "evidence" list does this).
        """
        if not run_ids:
            return {}
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (run_id) *
                FROM credential_files
                WHERE run_id = ANY(%s)
                ORDER BY run_id, id
                """,
                (run_ids,),
            )
            rows = cur.fetchall()
        return {int(r["run_id"]): _row_to_file(r) for r in rows}

    def latest_assessments_by_run(self, run_ids: list[int]) -> dict[int, CredentialAssessment]:
        """Return a {run_id -> latest assessment} map in ONE round-trip.

        Replaces N calls to ``latest_assessment``.
        """
        if not run_ids:
            return {}
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (run_id) *
                FROM credential_assessments
                WHERE run_id = ANY(%s)
                ORDER BY run_id, id DESC
                """,
                (run_ids,),
            )
            rows = cur.fetchall()
        return {int(r["run_id"]): _row_to_assessment(r) for r in rows}

    def save_assessment(
        self,
        run_id: int,
        inferred_axis_scores: dict[str, float],
        summary_md: str | None,
        rationale: dict[str, str],
        method: str,
        model_used: str | None,
    ) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO credential_assessments
                    (run_id, inferred_axis_scores_json, summary_md,
                     rationale_json, method, model_used)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    run_id,
                    json.dumps(inferred_axis_scores),
                    summary_md,
                    json.dumps(rationale),
                    method,
                    model_used,
                ),
            )
            new_id = cur.fetchone()["id"]
        self.conn.commit()
        return new_id

    def latest_assessment(self, run_id: int) -> CredentialAssessment | None:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM credential_assessments WHERE run_id = %s "
                "ORDER BY id DESC LIMIT 1",
                (run_id,),
            )
            r = cur.fetchone()
        return _row_to_assessment(r) if r else None
