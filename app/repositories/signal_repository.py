"""Repositories for the Signal surface: evidence artifacts and the
opportunities they get spent on.

Owner-scoped by construction — every query filters on `user_id`, from
the first version, so the day a second user exists no query is
retroactively wrong (BEN-148 rule 3).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import psycopg

from ._pg import naive_utc


@dataclass(frozen=True)
class EvidenceArtifact:
    id: str
    criterion: str
    title: str
    url: str | None
    claim_md: str | None
    strength: str
    occurred_on: date | None
    created_at: datetime | None


def _row_to_artifact(r: dict) -> EvidenceArtifact:
    return EvidenceArtifact(
        id=str(r["id"]),
        criterion=r["criterion"],
        title=r["title"],
        url=r["url"],
        claim_md=r["claim_md"],
        strength=r["strength"],
        occurred_on=r["occurred_on"],
        created_at=naive_utc(r["created_at"]),
    )


class EvidenceRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def add(
        self,
        user_id: str,
        *,
        criterion: str,
        title: str,
        url: str | None,
        claim_md: str | None,
        strength: str,
        occurred_on: date | None = None,
    ) -> str:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO evidence_artifacts
                    (user_id, criterion, title, url, claim_md, strength, occurred_on)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (user_id, criterion, title, url, claim_md, strength, occurred_on),
            )
            new_id = str(cur.fetchone()["id"])
        self.conn.commit()
        return new_id

    def by_criterion(self, user_id: str) -> dict[str, list[EvidenceArtifact]]:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM evidence_artifacts
                 WHERE user_id = %s
                 ORDER BY created_at DESC
                """,
                (user_id,),
            )
            rows = cur.fetchall()
        out: dict[str, list[EvidenceArtifact]] = {}
        for r in rows:
            out.setdefault(r["criterion"], []).append(_row_to_artifact(r))
        return out

    def set_strength(self, user_id: str, artifact_id: str, strength: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE evidence_artifacts SET strength = %s, updated_at = NOW()
                 WHERE id = %s AND user_id = %s
                """,
                (strength, artifact_id, user_id),
            )
        self.conn.commit()

    def delete(self, user_id: str, artifact_id: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "DELETE FROM evidence_artifacts WHERE id = %s AND user_id = %s",
                (artifact_id, user_id),
            )
        self.conn.commit()


@dataclass(frozen=True)
class Opportunity:
    id: str
    kind: str
    org: str
    title: str
    url: str | None
    location: str
    deadline: date | None
    stage: str
    outcome: str | None
    feedback_md: str | None
    created_at: datetime | None


def _row_to_opp(r: dict) -> Opportunity:
    return Opportunity(
        id=str(r["id"]),
        kind=r["kind"],
        org=r["org"],
        title=r["title"],
        url=r["url"],
        location=r["location"],
        deadline=r["deadline"],
        stage=r["stage"],
        outcome=r["outcome"],
        feedback_md=r["feedback_md"],
        created_at=naive_utc(r["created_at"]),
    )


# Ordered: an application walks left to right. `closed` is terminal.
STAGES = ("watching", "selected", "drafting", "submitted", "interview", "decision", "closed")
KINDS = ("fellowship", "grant", "job", "program", "workshop")


class OpportunityRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def add(
        self,
        user_id: str,
        *,
        kind: str,
        org: str,
        title: str,
        url: str | None,
        location: str,
        deadline: date | None,
        stage: str = "watching",
    ) -> str:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO opportunities
                    (user_id, kind, org, title, url, location, deadline, stage, source)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'manual')
                RETURNING id
                """,
                (user_id, kind, org, title, url, location or "unspecified", deadline, stage),
            )
            new_id = str(cur.fetchone()["id"])
            cur.execute(
                """
                INSERT INTO opportunity_events (opportunity_id, user_id, kind, note)
                VALUES (%s, %s, 'created', %s)
                """,
                (new_id, user_id, f"tracked at stage {stage}"),
            )
        self.conn.commit()
        return new_id

    def list_for_user(self, user_id: str) -> list[Opportunity]:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM opportunities
                 WHERE user_id = %s
                 ORDER BY (deadline IS NULL), deadline ASC, created_at DESC
                """,
                (user_id,),
            )
            return [_row_to_opp(r) for r in cur.fetchall()]

    def advance(
        self,
        user_id: str,
        opp_id: str,
        *,
        stage: str,
        outcome: str | None = None,
        feedback_md: str | None = None,
    ) -> bool:
        """Move an application and leave a dated trail. Feedback is
        appended, never overwritten — the point is to keep it."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE opportunities
                   SET stage = %s,
                       outcome = COALESCE(%s, outcome),
                       feedback_md = CASE
                           WHEN %s IS NULL OR %s = '' THEN feedback_md
                           WHEN feedback_md IS NULL OR feedback_md = '' THEN %s
                           ELSE feedback_md || E'\\n\\n---\\n\\n' || %s
                       END,
                       updated_at = NOW()
                 WHERE id = %s AND user_id = %s
                """,
                (stage, outcome, feedback_md, feedback_md, feedback_md, feedback_md,
                 opp_id, user_id),
            )
            if cur.rowcount == 0:
                return False
            note = f"stage → {stage}" + (f" ({outcome})" if outcome else "")
            cur.execute(
                """
                INSERT INTO opportunity_events (opportunity_id, user_id, kind, note)
                VALUES (%s, %s, 'stage_change', %s)
                """,
                (opp_id, user_id, note),
            )
        self.conn.commit()
        return True

    def events_for(self, user_id: str, opp_id: str) -> list[dict]:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT at, kind, note FROM opportunity_events
                 WHERE opportunity_id = %s AND user_id = %s
                 ORDER BY at DESC
                """,
                (opp_id, user_id),
            )
            return [
                {"at": naive_utc(r["at"]), "kind": r["kind"], "note": r["note"]}
                for r in cur.fetchall()
            ]

    def outcome_stats(self, user_id: str) -> dict:
        """Where applications actually die. The thread's unrecorded
        dataset: 14 rejections is noise; 14 rejections of which 6 died
        at final interview is a diagnosis."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT stage, outcome, COUNT(*) AS n
                  FROM opportunities WHERE user_id = %s
                 GROUP BY stage, outcome
                """,
                (user_id,),
            )
            rows = cur.fetchall()
        by_stage: dict[str, int] = {}
        rejected_late = 0
        total = 0
        for r in rows:
            n = int(r["n"])
            total += n
            by_stage[r["stage"]] = by_stage.get(r["stage"], 0) + n
            if (r["outcome"] or "").lower() == "rejected" and r["stage"] in ("interview", "decision"):
                rejected_late += n
        return {"total": total, "by_stage": by_stage, "rejected_late": rejected_late}
