from __future__ import annotations

import json

import psycopg

from ..models import JD
from ._pg import jsonb, naive_utc, uuid_str


def _row_to_jd(r: dict) -> JD:
    parsed = jsonb(r.get("parsed_json")) or {}
    iac_raw = parsed.get("iac_profile")
    iac_profile = iac_raw if isinstance(iac_raw, dict) else None
    return JD(
        id=r["id"],
        user_id=uuid_str(r["user_id"]),
        title=r["title"],
        org=r["org"],
        source_text=r["source_text"],
        axis_weights=parsed.get("axis_weights", {}),
        signal_tags=parsed.get("signal_tags", []),
        summary=parsed.get("summary"),
        method=parsed.get("method", "keyword_fallback"),
        model_used=parsed.get("model_used"),
        parsed_at=naive_utc(r["parsed_at"]),
        created_at=naive_utc(r["created_at"]),
        archived_at=naive_utc(r["archived_at"]),
        iac_profile=iac_profile,
        iac_evidence_md=parsed.get("iac_evidence_md"),
        iac_fit_md=parsed.get("iac_fit_md"),
    )


class JdRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def insert(self, jd: JD) -> int:
        parsed = {
            "axis_weights": jd.axis_weights,
            "signal_tags": jd.signal_tags,
            "summary": jd.summary,
            "method": jd.method,
            "model_used": jd.model_used,
            "iac_profile": jd.iac_profile,
            "iac_evidence_md": jd.iac_evidence_md,
            "iac_fit_md": jd.iac_fit_md,
        }
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO jds (user_id, title, org, source_text, parsed_json, parsed_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    jd.user_id,
                    jd.title,
                    jd.org,
                    jd.source_text,
                    json.dumps(parsed),
                    jd.parsed_at,
                ),
            )
            new_id = cur.fetchone()["id"]
        self.conn.commit()
        return new_id

    def get(self, jd_id: int) -> JD | None:
        with self.conn.cursor() as cur:
            cur.execute("SELECT * FROM jds WHERE id = %s", (jd_id,))
            r = cur.fetchone()
        return _row_to_jd(r) if r else None

    def list_for_user(self, user_id: str, include_archived: bool = False) -> list[JD]:
        with self.conn.cursor() as cur:
            if include_archived:
                cur.execute(
                    "SELECT * FROM jds WHERE user_id = %s ORDER BY id DESC",
                    (user_id,),
                )
            else:
                cur.execute(
                    "SELECT * FROM jds WHERE user_id = %s AND archived_at IS NULL "
                    "ORDER BY id DESC",
                    (user_id,),
                )
            rows = cur.fetchall()
        return [_row_to_jd(r) for r in rows]

    def set_iac_fit(self, jd_id: int, fit_md: str) -> None:
        """Merge a cached `iac_fit_md` string into the JD's parsed_json.
        Uses Postgres's jsonb concat so we don't have to re-serialize
        the whole blob from a stale dataclass."""
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE jds SET parsed_json = "
                "COALESCE(parsed_json, '{}'::jsonb) || %s::jsonb "
                "WHERE id = %s",
                (json.dumps({"iac_fit_md": fit_md}), jd_id),
            )
        self.conn.commit()

    def archive(self, jd_id: int) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE jds SET archived_at = NOW() WHERE id = %s",
                (jd_id,),
            )
        self.conn.commit()
