"""Connect state regressions against an explicit disposable loopback Postgres DB."""
from datetime import datetime, timedelta
import os
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
import pytest

from app.repositories.contacts_repository import ContactsRepository
from app.services import connecting

pytestmark = pytest.mark.integration
A = "11111111-1111-1111-1111-111111111111"
B = "22222222-2222-2222-2222-222222222222"
NOW = datetime(2026, 9, 24, 12)


@pytest.fixture
def repo():
    dsn = os.environ.get("E2E_DATABASE_URL", "")
    if not dsn:
        pytest.skip("Set E2E_DATABASE_URL to disposable local Postgres; DATABASE_URL is never used")
    parsed = urlsplit(dsn)
    if (parsed.scheme not in {"postgres", "postgresql"}
            or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            or parsed.query):
        pytest.fail("E2E_DATABASE_URL must be loopback PostgreSQL without connection overrides")
    schema = "connect_test_" + uuid4().hex
    with psycopg.connect(dsn, autocommit=True, row_factory=dict_row,
                         connect_timeout=5) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            # Excluding public prevents a missing fixture table from reaching app data.
            conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
            conn.execute("SET TIME ZONE 'UTC'")
            conn.execute("""
                CREATE TABLE contacts (
                    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    user_id UUID NOT NULL, name TEXT NOT NULL,
                    email TEXT, handle TEXT, context TEXT,
                    cadence_days INTEGER NOT NULL DEFAULT 30
                        CHECK (cadence_days BETWEEN 1 AND 3650),
                    archived BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE TABLE contact_interactions (
                    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    contact_id BIGINT NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
                    user_id UUID NOT NULL, occurred_at TIMESTAMPTZ NOT NULL,
                    kind TEXT NOT NULL,
                    direction TEXT CHECK (direction IS NULL OR direction IN ('outbound', 'inbound')),
                    notes TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            yield ContactsRepository(conn)
        finally:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def add(repo, contact, *, days=0, kind="message", direction=None, notes=None):
    return repo.add_interaction(
        contact_id=contact.id, user_id=contact.user_id,
        occurred_at=NOW - timedelta(days=days), kind=kind,
        direction=direction, notes=notes,
    )


def row_for(repo, contact):
    return connecting.compose_view(
        contacts=[contact],
        latest_by_contact=repo.latest_interaction_by_contact(contact.user_id),
        now=NOW,
    ).rows[0]


def test_private_notes_preserve_actual_touch_and_history(repo):
    contact = repo.create(user_id=A, name="Ada", cadence_days=30)
    touch = add(repo, contact, days=45, direction="inbound")
    before = row_for(repo, contact)
    note = add(repo, contact, kind="note", notes="Private reminder")

    assert repo.latest_interaction_by_contact(A)[contact.id].id == touch.id
    assert repo.latest_interaction_for_contact(contact.id, user_id=A).id == touch.id
    after = row_for(repo, contact)
    assert (after.warmth, after.tier, after.days_since, after.their_move) == (
        before.warmth, before.tier, before.days_since, before.their_move,
    )
    history = repo.list_interactions_for_contact(contact.id, user_id=A)
    assert [item.id for item in history] == [note.id, touch.id]
    assert history[0].notes == "Private reminder"


def test_only_private_notes_mean_no_actual_touch(repo):
    contact = repo.create(user_id=A, name="Grace")
    note = add(repo, contact, kind="note", direction="inbound", notes="Private context")

    assert contact.id not in repo.latest_interaction_by_contact(A)
    assert repo.latest_interaction_for_contact(contact.id, user_id=A) is None
    row = row_for(repo, contact)
    assert row.latest is None
    assert (row.warmth, row.tier, row.days_since, row.their_move) == (0.0, "never", None, False)
    assert [item.id for item in repo.list_interactions_for_contact(contact.id, user_id=A)] == [note.id]


@pytest.mark.parametrize("tie", ["created_at", "id"])
@pytest.mark.parametrize("latest_direction", ["inbound", "outbound"])
def test_same_date_touches_use_created_at_then_id(repo, tie, latest_direction):
    contact = repo.create(user_id=A, name="Katherine")
    other_direction = "outbound" if latest_direction == "inbound" else "inbound"
    # The created_at case deliberately makes the smaller ID win, proving
    # timestamp ordering takes priority over insertion order.
    first = add(repo, contact, direction=latest_direction if tie == "created_at" else other_direction)
    second = add(repo, contact, direction=other_direction if tie == "created_at" else latest_direction)
    repo.conn.execute("UPDATE contact_interactions SET created_at = %s", (NOW,))
    if tie == "created_at":
        repo.conn.execute("UPDATE contact_interactions SET created_at = %s WHERE id = %s",
                          (NOW + timedelta(seconds=1), first.id))
    expected, earlier = (first, second) if tie == "created_at" else (second, first)

    assert repo.latest_interaction_by_contact(A)[contact.id].id == expected.id
    assert repo.latest_interaction_for_contact(contact.id, user_id=A).id == expected.id
    assert [item.id for item in repo.list_interactions_for_contact(contact.id, user_id=A)] == [expected.id, earlier.id]
    assert row_for(repo, contact).their_move is (latest_direction == "inbound")


def test_fifty_recent_notes_do_not_hide_actual_touch(repo):
    contact = repo.create(user_id=A, name="Margaret")
    touch = add(repo, contact, days=45, direction="inbound")
    for index in range(50):
        add(repo, contact, kind="note", notes=f"Private note {index}")

    history = repo.list_interactions_for_contact(contact.id, user_id=A)
    assert len(history) == 50
    assert all(item.kind == "note" for item in history)
    assert repo.latest_interaction_by_contact(A)[contact.id].id == touch.id
    assert repo.latest_interaction_for_contact(contact.id, user_id=A).id == touch.id
    row = row_for(repo, contact)
    assert (row.days_since, row.tier, row.their_move) == (45, "cold", True)


def test_actual_touch_and_history_are_scoped_to_each_owner(repo):
    alice = repo.create(user_id=A, name="Same name")
    bob = repo.create(user_id=B, name="Same name")
    a_touch = add(repo, alice, days=4, direction="inbound")
    a_note = add(repo, alice, kind="note", notes="A private note")
    b_touch = add(repo, bob, days=2, direction="outbound")
    b_note = add(repo, bob, kind="note", notes="B private note")

    for owner, own, foreign, touch, note in [
        (A, alice, bob, a_touch, a_note), (B, bob, alice, b_touch, b_note),
    ]:
        assert [contact.id for contact in repo.list_for_user(owner)] == [own.id]
        latest = repo.latest_interaction_by_contact(owner)
        assert set(latest) == {own.id}
        assert latest[own.id].id == touch.id
        assert repo.latest_interaction_for_contact(own.id, user_id=owner).id == touch.id
        assert repo.latest_interaction_for_contact(foreign.id, user_id=owner) is None
        assert repo.list_interactions_for_contact(foreign.id, user_id=owner) == []
        assert [item.id for item in repo.list_interactions_for_contact(own.id, user_id=owner)] == [note.id, touch.id]
