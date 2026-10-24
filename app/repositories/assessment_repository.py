from __future__ import annotations

import json
from datetime import datetime

import psycopg

from ..models import AssessmentResponse, AssessmentRun
from ..services import assessment
from ._pg import jsonb, naive_utc, uuid_str


def _row_to_run(r: dict) -> AssessmentRun:
    return AssessmentRun(
        id=r["id"],
        user_id=uuid_str(r["user_id"]),
        started_at=naive_utc(r["started_at"]),
        completed_at=naive_utc(r["completed_at"]),
        final_scores=jsonb(r["final_scores_json"]) or {},
    )


def _row_to_response(r: dict) -> AssessmentResponse:
    return AssessmentResponse(
        id=r["id"],
        run_id=r["run_id"],
        question_id=r["question_id"],
        answer_index=r["answer_index"],
        axis_scores=jsonb(r["axis_scores_json"]) or {},
        answered_at=naive_utc(r["answered_at"]),
    )


class AssessmentRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def start_run(self, user_id: str) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO assessment_runs (user_id, started_at) "
                "VALUES (%s, NOW()) RETURNING id",
                (user_id,),
            )
            new_id = cur.fetchone()["id"]
        self.conn.commit()
        return new_id

    def complete_run(self, run_id: int, *, user_id: str) -> bool:
        # Serialize completion with answer writes; never overwrite a saved result.
        with self.conn.transaction():
            run = self.get_run(run_id, user_id=user_id, for_update=True)
            if run is None or run.completed_at is not None:
                return False
            responses = self.responses_for_run(run_id, user_id=user_id)
            if assessment.pick_next([r.question_id for r in responses]) is not None:
                return False
            scores = assessment.aggregate_scores(responses)
            with self.conn.cursor() as cur:
                cur.execute(
                    "UPDATE assessment_runs SET completed_at = NOW(), "
                    "final_scores_json = %s WHERE id = %s AND user_id = %s "
                    "AND completed_at IS NULL",
                    (json.dumps(scores), run_id, user_id),
                )
        return True

    def get_run(
        self, run_id: int, *, user_id: str, for_update: bool = False,
    ) -> AssessmentRun | None:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM assessment_runs WHERE id = %s AND user_id = %s"
                + (" FOR UPDATE" if for_update else ""),
                (run_id, user_id),
            )
            r = cur.fetchone()
        return _row_to_run(r) if r else None

    def latest_completed(self, user_id: str) -> AssessmentRun | None:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM assessment_runs WHERE user_id = %s "
                "AND completed_at IS NOT NULL ORDER BY completed_at DESC LIMIT 1",
                (user_id,),
            )
            r = cur.fetchone()
        return _row_to_run(r) if r else None

    def completed_since(self, user_id: str, since: datetime) -> list[AssessmentRun]:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM assessment_runs WHERE user_id = %s "
                "AND completed_at IS NOT NULL "
                "AND completed_at >= %s "
                "ORDER BY completed_at DESC",
                (user_id, since),
            )
            rows = cur.fetchall()
        return [_row_to_run(r) for r in rows]

    def has_completed(self, user_id: str) -> bool:
        return self.latest_completed(user_id) is not None

    def record_response(
        self, run_id: int, question_id: str, answer_index: int, *, user_id: str,
    ) -> int | None:
        # All writers lock the parent row before reading progress, so concurrent
        # submissions cannot both accept the same currently displayed question.
        with self.conn.transaction():
            run = self.get_run(run_id, user_id=user_id, for_update=True)
            if run is None or run.completed_at is not None:
                return None
            responses = self.responses_for_run(run_id, user_id=user_id)
            question = assessment.pick_next([r.question_id for r in responses])
            if (question is None or question.id != question_id
                    or not 0 <= answer_index < len(question.options)):
                raise ValueError("Answer does not match the current question.")
            scores = dict(question.options[answer_index].scores)
            with self.conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO assessment_responses "
                    "(run_id, question_id, answer_index, axis_scores_json) "
                    "SELECT id, %s, %s, %s FROM assessment_runs "
                    "WHERE id = %s AND user_id = %s AND completed_at IS NULL "
                    "RETURNING id",
                    (question_id, answer_index, json.dumps(scores), run_id, user_id),
                )
                new_id = cur.fetchone()["id"]
        return new_id

    def responses_for_run(
        self, run_id: int, *, user_id: str,
    ) -> list[AssessmentResponse]:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT response.* FROM assessment_responses AS response "
                "JOIN assessment_runs AS run ON run.id = response.run_id "
                "WHERE response.run_id = %s AND run.user_id = %s ORDER BY response.id",
                (run_id, user_id),
            )
            rows = cur.fetchall()
        # Old duplicate submissions must not affect progress or later summaries.
        seen: set[str] = set()
        responses = []
        for row in rows:
            if row["question_id"] not in seen:
                seen.add(row["question_id"])
                responses.append(_row_to_response(row))
        return responses
