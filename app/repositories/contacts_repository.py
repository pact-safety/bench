"""Repository for contacts + contact_interactions (migration 013).

Used by:
- ``app/services/connecting.py`` for warmth-decay scoring + view
  composition.
- ``app/main.py`` /connecting routes for read + add + archive + log
  interactions.

No SQL beyond direct CRUD — warmth and ordering happen in the service
layer because both depend on the per-contact interaction history, not
just the row's own columns.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg

from ..models import Contact, ContactInteraction
from ._pg import naive_utc, uuid_str


# Kinds the service writes to the DB. Free-form column at the schema
# level (no enum), but the service validates against this set so a
# typo in a form doesn't pollute the data. Add a new kind: extend the
# tuple, update the form, update the icon switch in the template.
_VALID_KINDS = ("sent", "received", "meeting", "call", "message", "note")
_VALID_DIRECTIONS = (None, "outbound", "inbound")


def _row_to_contact(r: dict) -> Contact:
    return Contact(
        id=r["id"],
        user_id=uuid_str(r["user_id"]) or "",
        name=r["name"],
        email=r.get("email"),
        handle=r.get("handle"),
        context=r.get("context"),
        cadence_days=int(r["cadence_days"]),
        archived=bool(r["archived"]),
        created_at=naive_utc(r["created_at"]),
        updated_at=naive_utc(r["updated_at"]),
    )


def _row_to_interaction(r: dict) -> ContactInteraction:
    return ContactInteraction(
        id=r["id"],
        contact_id=int(r["contact_id"]),
        user_id=uuid_str(r["user_id"]) or "",
        occurred_at=naive_utc(r["occurred_at"]),
        kind=r["kind"],
        direction=r.get("direction"),
        notes=r.get("notes"),
        created_at=naive_utc(r["created_at"]),
    )


class ContactsRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    # ----- contacts ------------------------------------------------

    def list_for_user(
        self,
        user_id: str,
        *,
        include_archived: bool = False,
    ) -> list[Contact]:
        """All contacts for this user, by-name order. Service layer
        re-sorts by warmth ascending for the /connecting list view."""
        clauses = ["user_id = %s"]
        params: list[Any] = [user_id]
        if not include_archived:
            clauses.append("archived = FALSE")
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT * FROM contacts WHERE {' AND '.join(clauses)} "
                f"ORDER BY LOWER(name)",
                tuple(params),
            )
            return [_row_to_contact(r) for r in cur.fetchall()]

    def get(self, contact_id: int, *, user_id: str) -> Contact | None:
        """Fetch one contact, scoped to the requesting user. user_id
        gate prevents the GET-by-id handler from leaking another
        tenant's row even though we're single-tenant today."""
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM contacts WHERE id = %s AND user_id = %s",
                (contact_id, user_id),
            )
            r = cur.fetchone()
        return _row_to_contact(r) if r else None

    def create(
        self,
        *,
        user_id: str,
        name: str,
        email: str | None = None,
        handle: str | None = None,
        context: str | None = None,
        cadence_days: int = 30,
    ) -> Contact:
        """Insert a contact. Returns the persisted row.

        Empty-string fields collapse to NULL so the templates can
        check `{% if contact.email %}` without checking-and-trimming
        in the template. The cadence_days CHECK constraint at the
        schema level catches absurd values (≤0 or > 10 years)."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO contacts
                  (user_id, name, email, handle, context, cadence_days)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    user_id,
                    name.strip(),
                    (email or "").strip() or None,
                    (handle or "").strip() or None,
                    (context or "").strip() or None,
                    int(cadence_days),
                ),
            )
            r = cur.fetchone()
        self.conn.commit()
        return _row_to_contact(r)

    def set_archived(self, contact_id: int, *, user_id: str, archived: bool) -> None:
        """Archive (or un-archive) a contact. Soft-delete; preserves
        history. user_id gates the update so it's safe to call from a
        POST handler without an extra ownership check."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE contacts
                   SET archived = %s, updated_at = NOW()
                 WHERE id = %s AND user_id = %s
                """,
                (bool(archived), contact_id, user_id),
            )
        self.conn.commit()

    # ----- interactions --------------------------------------------

    def list_interactions_for_contact(
        self,
        contact_id: int,
        *,
        user_id: str,
        limit: int = 50,
    ) -> list[ContactInteraction]:
        """Newest-first history. Bounded by `limit` because long-running
        contacts will accumulate; the detail page paginates if we ever
        need to."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM contact_interactions
                 WHERE contact_id = %s AND user_id = %s
                 ORDER BY occurred_at DESC, created_at DESC, id DESC
                 LIMIT %s
                """,
                (contact_id, user_id, limit),
            )
            return [_row_to_interaction(r) for r in cur.fetchall()]

    def latest_interaction_by_contact(
        self, user_id: str
    ) -> dict[int, ContactInteraction]:
        """Fetch the latest actual touch for each of the user's contacts.

        Private notes remain in history but do not reset warmth or reply
        state. One query avoids an N+1 over contacts on the list view.

        Uses Postgres DISTINCT ON for the per-group latest. Equivalent
        to a window function but cheaper here because we already have
        the (contact_id, occurred_at DESC) index."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (contact_id) *
                  FROM contact_interactions
                 WHERE user_id = %s AND kind <> 'note'
                 ORDER BY contact_id, occurred_at DESC, created_at DESC, id DESC
                """,
                (user_id,),
            )
            return {
                int(r["contact_id"]): _row_to_interaction(r)
                for r in cur.fetchall()
            }

    def latest_interaction_for_contact(
        self, contact_id: int, *, user_id: str
    ) -> ContactInteraction | None:
        """Latest actual touch, independent of the displayed history limit."""
        # A long run of private notes must not hide an older pending reply.
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM contact_interactions
                 WHERE contact_id = %s AND user_id = %s AND kind <> 'note'
                 ORDER BY occurred_at DESC, created_at DESC, id DESC
                 LIMIT 1
                """,
                (contact_id, user_id),
            )
            r = cur.fetchone()
        return _row_to_interaction(r) if r else None

    def add_interaction(
        self,
        *,
        contact_id: int,
        user_id: str,
        occurred_at: datetime,
        kind: str,
        direction: str | None = None,
        notes: str | None = None,
    ) -> ContactInteraction:
        """Append one interaction. Caller (the service) validates
        `kind` and `direction` against the known vocab so DB-level
        check constraints are a safety net, not the primary gate."""
        if kind not in _VALID_KINDS:
            raise ValueError(f"invalid interaction kind: {kind!r}")
        if direction not in _VALID_DIRECTIONS:
            raise ValueError(f"invalid interaction direction: {direction!r}")
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO contact_interactions
                  (contact_id, user_id, occurred_at, kind, direction, notes)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    contact_id,
                    user_id,
                    occurred_at,
                    kind,
                    direction,
                    (notes or "").strip() or None,
                ),
            )
            r = cur.fetchone()
        # Bump the parent contact's updated_at so the list view's
        # ordering tiebreaker reflects activity. Not strictly needed for
        # warmth (warmth is over occurred_at) but useful for "recently
        # touched" UI affordances later.
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE contacts SET updated_at = NOW() WHERE id = %s",
                (contact_id,),
            )
        self.conn.commit()
        return _row_to_interaction(r)
