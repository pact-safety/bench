from __future__ import annotations

import json

import psycopg

from ..models import Session
from ._pg import jsonb, naive_utc, uuid_str


def _row_to_session(r: dict) -> Session:
    return Session(
        id=r["id"],
        user_id=uuid_str(r["user_id"]),
        started_at=naive_utc(r["started_at"]),
        ended_at=naive_utc(r["ended_at"]),
        strategy_name=r["strategy_name"],
        time_limit_seconds=r["time_limit_seconds"],
        problems=jsonb(r["problems_json"]) or [],
    )


class SessionRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def insert(self, s: Session) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO sessions (user_id, started_at, ended_at, strategy_name,
                                      time_limit_seconds, problems_json)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (s.user_id, s.started_at, s.ended_at, s.strategy_name,
                 s.time_limit_seconds, json.dumps(s.problems)),
            )
            new_id = cur.fetchone()["id"]
        self.conn.commit()
        return new_id

    def latest_for_user(self, user_id: str) -> Session | None:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM sessions WHERE user_id = %s ORDER BY started_at DESC LIMIT 1",
                (user_id,),
            )
            r = cur.fetchone()
        return _row_to_session(r) if r else None
