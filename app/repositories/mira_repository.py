"""Repository for MIRA's chat sessions + turns (migration 014_mira).

One method per query, matching the ``_row_to_X`` + ``XRepository(conn)`` shape
the rest of ``app/repositories/`` uses (see ``chat_outcomes_repository.py``).

Why the cache here when ``chat_outcomes`` has none: a MIRA conversation
re-reads its whole history on *every* turn (load last-N turns → build the
prompt → stream → append the new turns), so the transcript is the hottest
read on the surface and changes only by append. We cache the per-session
turn list and drop it on append. The key is prefixed per session
(``mira_turns:{session_id}:...``) so one turn invalidates only that
conversation's history via ``cache.invalidate_prefix`` — not every session's.

JSONB columns (``tool_calls``/``citations``/``latency_ms``) are written as
``json.dumps(...)`` strings; Postgres casts the JSON text into JSONB on
insert, the same pattern the attempt/jd/content repos use.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID

import psycopg

from .. import cache as _cache
from ..models import MiraSession, MiraTurn
from ._pg import jsonb, naive_utc, uuid_str


@dataclass(frozen=True)
class CoachWriteResult:
    session_id: str | None
    status: str


# Local appends cannot invalidate another worker's transcript cache. Bound
# cross-worker convergence to the same 30 seconds used for user settings.
_TURNS_TTL_S = 30.0


def _turns_prefix(session_id: str) -> str:
    return f"mira_turns:{session_id}:"


def _row_to_session(r: dict) -> MiraSession:
    return MiraSession(
        id=uuid_str(r["id"]),
        user_id=uuid_str(r["user_id"]),
        modality=r["modality"],
        started_at=naive_utc(r["started_at"]),
        ended_at=naive_utc(r["ended_at"]),
        title=r["title"],
        meta=r.get("meta") or {},
    )


def _row_to_turn(r: dict) -> MiraTurn:
    return MiraTurn(
        id=uuid_str(r["id"]),
        session_id=uuid_str(r["session_id"]),
        role=r["role"],
        content=r["content"],
        created_at=naive_utc(r["created_at"]),
        tool_calls=jsonb(r["tool_calls"]),
        citations=jsonb(r["citations"]),
        provider_used=r["provider_used"],
        latency_ms=jsonb(r["latency_ms"]),
        interrupted=bool(r["interrupted"]),
    )


def _row_to_surface(r: dict) -> dict:
    """Generic row → template dict for the agenda/memory/evals surfaces:
    stringify UUID keys the templates touch, strip tz from timestamps
    (the naive-UTC convention — see ``_pg.naive_utc``)."""
    out = dict(r)
    out["id"] = uuid_str(out["id"])
    for k in ("created_at", "updated_at", "due_at"):
        if k in out:
            out[k] = naive_utc(out[k])
    return out


class MiraRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    # ---------- sessions ----------------------------------------------------

    def create_session(
        self,
        *,
        user_id: str,
        modality: str = "chat",
        title: str | None = None,
        persona_key: str | None = None,
        coach_context: dict | None = None,
    ) -> str:
        """Open a new conversation. Returns the new session's UUID.

        ``modality`` is constrained to 'chat'|'voice' by the table CHECK.
        ``coach_context`` marks a coach session, including when empty; the
        caller validates and authorizes any referenced exercise or track.
        """
        with self.conn.cursor() as cur:
            import json as _json
            meta = {"persona_key": persona_key} if persona_key else {}
            if coach_context is not None:
                meta.update(mode="coach", context=dict(coach_context))
            cur.execute(
                """
                INSERT INTO mira_sessions (user_id, modality, title, meta)
                VALUES (%s, %s, %s, %s::jsonb)
                RETURNING id
                """,
                (user_id, modality, title, _json.dumps(meta)),
            )
            new_id = cur.fetchone()["id"]
        self.conn.commit()
        return uuid_str(new_id)

    def get_session(
        self, session_id: str, *, user_id: str | None = None
    ) -> MiraSession | None:
        """Single-session lookup. When ``user_id`` is given, scope to it as
        defense-in-depth alongside the route's session check so one user can
        never resume another's conversation by guessing a UUID."""
        with self.conn.cursor() as cur:
            if user_id is not None:
                cur.execute(
                    "SELECT * FROM mira_sessions WHERE id = %s AND user_id = %s",
                    (session_id, user_id),
                )
            else:
                cur.execute(
                    "SELECT * FROM mira_sessions WHERE id = %s",
                    (session_id,),
                )
            row = cur.fetchone()
        return _row_to_session(row) if row else None

    def list_sessions(self, user_id: str, *, limit: int = 50) -> list[MiraSession]:
        """Reverse-chronological session list for the /mira landing rail.
        Capped for unbounded-list defense."""
        safe_limit = max(1, min(int(limit), 200))
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM mira_sessions
                 WHERE user_id = %s
                 ORDER BY started_at DESC
                 LIMIT %s
                """,
                (user_id, safe_limit),
            )
            rows = cur.fetchall()
        return [_row_to_session(r) for r in rows]

    # ---------- turns -------------------------------------------------------

    def append_coach_note(
        self, *, user_id: str, stage: str, content: str, coach_context: dict,
        session_id: str = "", request_token: str = "", force_new: bool = False,
    ) -> CoachWriteResult:
        """Atomically resolve an owned coaching session and save its next step."""
        from ..services.mira_coach import STAGES

        if stage not in STAGES or not content.strip() or len(content) > 6000:
            raise ValueError("Invalid coaching note.")
        if request_token:
            if len(request_token) != 36:
                raise ValueError("Invalid coaching request token.")
            request_token = str(UUID(request_token))
        if force_new and not session_id and not request_token:
            raise ValueError("New coaching sessions require a request token.")
        context_json = json.dumps(coach_context, sort_keys=True)
        with self.conn.transaction(), self.conn.cursor() as cur:
            token_matched = False
            row = None
            if session_id:
                cur.execute("SELECT id, meta FROM mira_sessions WHERE id = %s AND user_id = %s FOR UPDATE",
                            (session_id, user_id))
                row = cur.fetchone()
                if row is None:
                    return CoachWriteResult(None, "missing")
            else:
                # No session row exists for a first note. Lock the owner's
                # context until creation and append both commit, across workers.
                lock_key = json.dumps([user_id, coach_context], sort_keys=True)
                cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (lock_key,))
                if request_token:
                    cur.execute("SELECT id, meta FROM mira_sessions WHERE user_id = %s "
                                "AND (meta->>'coach_request_token' = %s OR meta->'coach_request_tokens' ? %s) "
                                "AND meta->'context' = %s::jsonb FOR UPDATE",
                                (user_id, request_token, request_token, context_json))
                    row = cur.fetchone()
                    token_matched = row is not None
                if row is None and not force_new:
                    cur.execute("SELECT id, meta FROM mira_sessions WHERE user_id = %s "
                                "AND meta->>'mode' = 'coach' AND meta->'context' = %s::jsonb "
                                "ORDER BY started_at DESC, id DESC LIMIT 1 FOR UPDATE", (user_id, context_json))
                    row = cur.fetchone()
            turns = []
            expected = STAGES[0]
            if row:
                if (row.get("meta") or {}).get("mode") != "coach":
                    return CoachWriteResult(uuid_str(row["id"]), "readonly")
                # Bypass the history cache while holding the session row lock;
                # the prior worker's committed stage determines this write.
                cur.execute("SELECT provider_used, content FROM mira_turns WHERE session_id = %s "
                            "AND role = 'user' ORDER BY created_at DESC, id DESC", (row["id"],))
                turns = cur.fetchall()
                for turn in turns:
                    source = turn["provider_used"] or ""
                    if source.startswith("coach:") and source[6:] in STAGES:
                        index = STAGES.index(source[6:]) + 1
                        expected = STAGES[index] if index < len(STAGES) else None
                        break
                if expected is None and not session_id and not token_matched:
                    row, turns, expected = None, [], STAGES[0]
            if stage != expected:
                duplicate = any(t["provider_used"] == f"coach:{stage}" and t["content"] == content for t in turns)
                if duplicate and stage == STAGES[0] and request_token and not session_id and not token_matched:
                    # Two first forms may converge on one saved note. Keep the
                    # accepted loser's identity so replay after reflection does
                    # not mistake it for a request to start another session.
                    cur.execute("UPDATE mira_sessions SET meta = jsonb_set(meta, '{coach_request_tokens}', "
                                "COALESCE(meta->'coach_request_tokens', '[]'::jsonb) || jsonb_build_array(%s::text)) "
                                "WHERE id = %s AND user_id = %s", (request_token, row["id"], user_id))
                return CoachWriteResult(uuid_str(row["id"]) if row else None, "duplicate" if duplicate else "stale")
            if row is None:
                meta = {"mode": "coach", "context": coach_context}
                if request_token:
                    meta["coach_request_token"] = request_token
                cur.execute("INSERT INTO mira_sessions (user_id, modality, title, meta, started_at) "
                            "VALUES (%s, 'chat', 'Practice coaching', %s::jsonb, clock_timestamp()) RETURNING id",
                            (user_id, json.dumps(meta)))
                row = cur.fetchone()
            saved_id = uuid_str(row["id"])
            # NOW() is the transaction start, which can precede a lock wait
            # and invert stages written by two concurrent transactions.
            cur.execute("INSERT INTO mira_turns (session_id, role, content, provider_used, created_at) "
                        "VALUES (%s, 'user', %s, %s, clock_timestamp())", (saved_id, content, f"coach:{stage}"))
        _cache.invalidate_prefix(_turns_prefix(saved_id))
        return CoachWriteResult(saved_id, "saved")

    def append_turn(
        self,
        *,
        session_id: str,
        role: str,
        content: str,
        tool_calls: object | None = None,
        citations: object | None = None,
        provider_used: str | None = None,
        latency_ms: object | None = None,
        interrupted: bool = False,
    ) -> str:
        """Append one turn to a conversation. Returns the new turn's UUID.

        Append-only: there is no update/delete path. Invalidates this
        session's cached history so the next ``list_turns`` reads fresh.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO mira_turns
                  (session_id, role, content, tool_calls, citations,
                   provider_used, latency_ms, interrupted)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    session_id,
                    role,
                    content,
                    json.dumps(tool_calls) if tool_calls is not None else None,
                    json.dumps(citations) if citations is not None else None,
                    provider_used,
                    json.dumps(latency_ms) if latency_ms is not None else None,
                    interrupted,
                ),
            )
            new_id = cur.fetchone()["id"]
        self.conn.commit()
        # Drop every cached history slice for this session (any limit).
        _cache.invalidate_prefix(_turns_prefix(session_id))
        return uuid_str(new_id)

    def list_turns(self, session_id: str, *, limit: int = 200, fresh: bool = False) -> list[MiraTurn]:
        """Chronological (oldest-first) turn list for a session — the order
        the chat transcript and the prompt-history builder both want.

        Read-through cached per (session, limit); invalidated on
        ``append_turn``. Select the newest window before restoring chronological
        order, so a long conversation keeps its recent context. The prompt
        builder applies its own tighter token budget on top.
        """
        safe_limit = max(1, min(int(limit), 1000))
        key = f"mira_turns:{session_id}:{safe_limit}"

        def _load() -> list[MiraTurn]:
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM (
                        SELECT * FROM mira_turns
                         WHERE session_id = %s
                         ORDER BY created_at DESC, id DESC
                         LIMIT %s
                    ) AS recent_turns
                    ORDER BY created_at ASC, id ASC
                    """,
                    (session_id, safe_limit),
                )
                rows = cur.fetchall()
            return [_row_to_turn(r) for r in rows]

        # Coaching stage transitions must see writes from other workers;
        # process-local invalidation only covers this worker's own appends.
        return _load() if fresh else _cache.get(key, loader=_load, ttl_s=_TURNS_TTL_S)

    # ---------- agenda / memory / evals (surfaces 6a/6b/6d) -----------------
    # Dict rows, not dataclasses: the only consumer is a template, so
    # per-table model classes would be ceremony — promote to models if the
    # agent loop starts reasoning over these. No cache either: occasional
    # page visits, unlike the per-turn transcript reads above.

    def _list_surface(self, table_where: str, params: tuple, limit: int) -> list[dict]:
        """Shared SELECT for the three list surfaces: user-scoped,
        newest-first, capped for unbounded-list defense."""
        safe_limit = max(1, min(int(limit), 500))
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT * FROM {table_where}"  # noqa: S608 — table_where is a literal from the three callers below, never user input
                " ORDER BY created_at DESC LIMIT %s",
                (*params, safe_limit),
            )
            rows = cur.fetchall()
        return [_row_to_surface(r) for r in rows]

    def list_agenda(self, user_id: str, *, limit: int = 100) -> list[dict]:
        return self._list_surface(
            "research_agenda WHERE user_id = %s", (user_id,), limit
        )

    def set_agenda_linear(
        self, user_id: str, agenda_id: str, *,
        issue_id: str, identifier: str, url: str,
    ) -> bool:
        """Record where an agenda item landed in Linear. Owner-scoped."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE research_agenda
                   SET linear_issue_id = %s, linear_issue_identifier = %s,
                       linear_issue_url = %s, updated_at = NOW()
                 WHERE id = %s AND user_id = %s
                """,
                (issue_id, identifier, url, agenda_id, user_id),
            )
            ok = cur.rowcount > 0
        self.conn.commit()
        return ok

    def agenda_linear_links(self, user_id: str) -> list[dict]:
        """(agenda_id, linear_issue_id, status) for linked items —
        the refresh pull's working set."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, linear_issue_id, status FROM research_agenda
                 WHERE user_id = %s AND linear_issue_id IS NOT NULL
                """,
                (user_id,),
            )
            rows = cur.fetchall()
        return [
            {"id": uuid_str(r["id"]), "linear_issue_id": r["linear_issue_id"],
             "status": r["status"]}
            for r in rows
        ]

    def set_agenda_status(self, user_id: str, agenda_id: str, status: str) -> None:
        # The CHECK constraint is the schema's guard; callers pass only
        # mapped values (linear_sync.STATE_TO_AGENDA_STATUS).
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE research_agenda SET status = %s, updated_at = NOW()
                 WHERE id = %s AND user_id = %s
                """,
                (status, agenda_id, user_id),
            )
        self.conn.commit()

    def list_memories(self, user_id: str, *, limit: int = 100) -> list[dict]:
        # superseded_by IS NULL matches the partial index in 014_mira.sql:
        # superseded rows stay out of the surface like they stay out of
        # Mira's prompt.
        return self._list_surface(
            "mira_memory WHERE user_id = %s AND superseded_by IS NULL",
            (user_id,),
            limit,
        )

    def list_proposed_evals(self, user_id: str, *, limit: int = 100) -> list[dict]:
        # Read surface. The agent loop's tool-use write path lands in a later
        # MIRA phase; today the only writer is the startup seed via
        # add_proposed_eval below.
        return self._list_surface(
            "proposed_evals WHERE user_id = %s", (user_id,), limit
        )

    def add_proposed_eval(
        self,
        *,
        user_id: str,
        hypothesis: str,
        falsifier: str | None = None,
        conditions: list | None = None,
        model_under_test: str | None = None,
        meta: dict | None = None,
    ) -> str:
        """Write a Mira-proposed eval. ``conditions`` is the design's A/B/C
        framing table [{"label", "framing"}]; ``meta`` carries presentational
        title + inspect_path. Returns the new row's UUID."""
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO proposed_evals"
                " (user_id, hypothesis, falsifier, conditions, model_under_test, meta)"
                " VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (
                    user_id,
                    hypothesis,
                    falsifier,
                    json.dumps(conditions or []),
                    model_under_test,
                    json.dumps(meta or {}),
                ),
            )
            new_id = cur.fetchone()["id"]
        self.conn.commit()
        return uuid_str(new_id)

    def add_agenda_item(
        self, *, user_id: str, kind: str, title: str, why: str | None = None
    ) -> str:
        """``kind`` must satisfy the table CHECK; the route whitelists
        before calling. Returns the new row's UUID."""
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO research_agenda (user_id, kind, title, why)"
                " VALUES (%s, %s, %s, %s) RETURNING id",
                (user_id, kind, title, why),
            )
            new_id = cur.fetchone()["id"]
        self.conn.commit()
        return uuid_str(new_id)

    def add_memory(self, *, user_id: str, category: str, content: str) -> str:
        """``category`` must satisfy the table CHECK; the route whitelists.
        Returns the new row's UUID."""
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO mira_memory (user_id, category, content)"
                " VALUES (%s, %s, %s) RETURNING id",
                (user_id, category, content),
            )
            new_id = cur.fetchone()["id"]
        self.conn.commit()
        return uuid_str(new_id)
