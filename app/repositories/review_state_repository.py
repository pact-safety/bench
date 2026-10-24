from __future__ import annotations

import psycopg

from ..models import ReviewState
from ._pg import naive_utc, uuid_str


def _row_to_state(r: dict) -> ReviewState:
    return ReviewState(
        user_id=uuid_str(r["user_id"]),
        problem_id=r["problem_id"],
        last_attempt_id=r["last_attempt_id"],
        last_due_score=float(r["last_due_score"]),
        next_due_at=naive_utc(r["next_due_at"]),
        lapses=int(r["lapses"]),
        ease_factor=float(r["ease_factor"]) if r["ease_factor"] is not None else None,
    )


class ReviewStateRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def upsert(self, s: ReviewState) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO review_state (
                    user_id, problem_id, last_attempt_id, last_due_score,
                    next_due_at, lapses, ease_factor
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, problem_id) DO UPDATE SET
                    last_attempt_id = EXCLUDED.last_attempt_id,
                    last_due_score  = EXCLUDED.last_due_score,
                    next_due_at     = EXCLUDED.next_due_at,
                    lapses          = EXCLUDED.lapses,
                    ease_factor     = EXCLUDED.ease_factor
                """,
                (
                    s.user_id, s.problem_id, s.last_attempt_id, s.last_due_score,
                    s.next_due_at, s.lapses, s.ease_factor,
                ),
            )
        self.conn.commit()

    def get(self, user_id: str, problem_id: int) -> ReviewState | None:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM review_state WHERE user_id = %s AND problem_id = %s",
                (user_id, problem_id),
            )
            r = cur.fetchone()
        return _row_to_state(r) if r else None

    def all_for_user(self, user_id: str) -> list[ReviewState]:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM review_state WHERE user_id = %s ORDER BY problem_id",
                (user_id,),
            )
            rows = cur.fetchall()
        return [_row_to_state(r) for r in rows]
