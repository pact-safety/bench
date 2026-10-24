from __future__ import annotations

import json

import psycopg

from ..models import AttemptReview
from ._pg import jsonb, naive_utc


def _row_to_review(r: dict) -> AttemptReview:
    return AttemptReview(
        id=r["id"],
        attempt_id=r["attempt_id"],
        method=r["method"],
        model_used=r["model_used"],
        summary_md=r["summary_md"],
        per_phase=jsonb(r.get("per_phase_json")) or {},
        overall_score=r["overall_score"],
        error_text=r["error_text"],
        created_at=naive_utc(r["created_at"]),
        rubric_signals=jsonb(r.get("rubric_signals_json")),
    )


class AttemptReviewRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def insert(self, review: AttemptReview) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO attempt_reviews
                    (attempt_id, method, model_used, summary_md, per_phase_json,
                     overall_score, error_text, rubric_signals_json)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    review.attempt_id,
                    review.method,
                    review.model_used,
                    review.summary_md,
                    json.dumps(review.per_phase),
                    review.overall_score,
                    review.error_text,
                    json.dumps(review.rubric_signals) if review.rubric_signals else None,
                ),
            )
            new_id = cur.fetchone()["id"]
        self.conn.commit()
        return new_id

    def latest_for_attempt(self, attempt_id: int) -> AttemptReview | None:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM attempt_reviews WHERE attempt_id = %s "
                "ORDER BY id DESC LIMIT 1",
                (attempt_id,),
            )
            r = cur.fetchone()
        return _row_to_review(r) if r else None
