"""Real PostgreSQL boundary gate; only a disposable loopback E2E DB is accepted."""
from __future__ import annotations

import os
from datetime import datetime
from urllib.parse import urlsplit

import psycopg
from psycopg.rows import dict_row
import pytest

from app import cache
from app.repositories.content_repository import ContentRepository

pytestmark = pytest.mark.integration
A = "11111111-1111-1111-1111-111111111111"
B = "22222222-2222-2222-2222-222222222222"


@pytest.fixture
def repo():
    url = os.environ.get("E2E_DATABASE_URL", "")
    if not url:
        pytest.skip("E2E_DATABASE_URL is required; DATABASE_URL is never used")
    parsed = urlsplit(url)
    if parsed.scheme not in {"postgres", "postgresql"} or parsed.hostname not in {"localhost", "127.0.0.1", "::1"} or parsed.query:
        pytest.fail("E2E_DATABASE_URL must be loopback PostgreSQL without connection overrides")
    # TEMP tables shadow application tables; all writes disappear on close.
    # PostgreSQL's real UUID/JSONB types catch parameter inference bugs a
    # SQLite substitute cannot exercise.
    with psycopg.connect(url, autocommit=True, row_factory=dict_row) as conn:
        conn.execute("""
            CREATE TEMP TABLE content_items (
                id SERIAL PRIMARY KEY, slug TEXT UNIQUE NOT NULL,
                kind TEXT, title TEXT, source TEXT, url TEXT, duration_min INT,
                axes_json JSONB, prerequisites_json JSONB, content_md TEXT,
                authored_by TEXT, authored_date TEXT, version_int INT,
                source_kind TEXT, created_by_user_id UUID
            );
            CREATE TEMP TABLE content_progress (
                user_id UUID, content_id INT, status TEXT, checked_at TIMESTAMPTZ,
                notes_md TEXT, favorited_bool BOOLEAN DEFAULT FALSE,
                rating_1_to_5 INT, initiative_slug TEXT, recitation_state JSONB,
                last_recited_at TIMESTAMPTZ, paper_state JSONB,
                PRIMARY KEY (user_id, content_id)
            );
            CREATE TEMP TABLE tts_cache (
                user_id UUID, cache_key TEXT, content_id INT, chunk_ix INT,
                voice TEXT, mime TEXT, audio BYTEA,
                PRIMARY KEY (user_id, cache_key)
            )
        """)
        conn.execute("""INSERT INTO content_items
            (slug, kind, title, version_int, source_kind, axes_json, content_md)
            VALUES ('shared', 'reading', 'Shared', 1, 'authored', '[]', 'Shared notes')""")
        repository = ContentRepository(conn)
        for uid, slug in [(A, "owner-a"), (B, "owner-b")]:
            repository.insert_user_item(user_id=uid, slug=slug, kind="reading",
                title=slug, source="Personal", url=None, duration_min=5,
                axes=[slug], notes_md=f"private {slug}")
        cache.invalidate_prefix("content_items:")
        yield repository
        cache.invalidate_prefix("content_items:")


def test_postgres_two_account_lists_details_and_cache(repo):
    for uid, expected in [(A, ["shared", "owner-a"]), (B, ["shared", "owner-b"]),
                          (None, ["shared"]), (A, ["shared", "owner-a"])]:
        assert [item.slug for item in repo.all_by_kind("reading", user_id=uid)] == expected
        assert [item.slug for item in repo.all_by_kinds(["reading", "video"], user_id=uid)["reading"]] == expected
        for slug in ["shared", "owner-a", "owner-b"]:
            assert (repo.get_by_slug(slug, user_id=uid) is not None) == (slug in expected)
    private = repo.get_by_slug("owner-a", user_id=A)
    assert private.content_md == "private owner-a"
    assert repo.get_by_id(private.id, user_id=B) is None
    assert repo.get_by_id(private.id) is None


@pytest.mark.parametrize("method,args", [
    ("mark_completed", ()), ("mark_unread", ()), ("toggle_favorite", ()),
    ("set_rating", (5,)), ("save_reflection", ("reflection",)),
    ("save_recitation_state", ({"concept": {}},)), ("save_paper_state", ({"pass": 1},)),
])
def test_postgres_mutations_only_persist_visible_content(repo, method, args):
    cid = repo.get_by_slug("owner-a", user_id=A).id
    operation = getattr(repo, method)
    operation(B, cid, *args)
    assert repo.conn.execute("SELECT COUNT(*) AS n FROM content_progress").fetchone()["n"] == 0
    operation(A, cid, *args)
    operation(B, 1, *args)
    assert len(repo.progress_for_user(A)) == 1
    assert len(repo.progress_for_user(B)) == 1
    if method == "toggle_favorite":
        assert operation(A, cid) is False


def test_postgres_legacy_progress_and_audio_are_hidden(repo):
    cid = repo.get_by_slug("owner-a", user_id=A).id
    repo.conn.execute("""INSERT INTO content_progress
        (user_id, content_id, status, checked_at, favorited_bool, rating_1_to_5)
        VALUES (%s, %s, 'completed', NOW(), TRUE, 5)""", (B, cid))
    assert repo.progress_for_user(B) == {}
    assert repo.list_progress_since(B, datetime(2020, 1, 1)) == []
    assert repo.favorites_for_user(B) == []
    assert repo.axis_ratings_for_user(B) == {}
    repo.save_reflection(B, cid, "forbidden")
    assert repo.conn.execute("SELECT notes_md FROM content_progress").fetchone()["notes_md"] is None
    repo.put_tts_chunk(user_id=B, cache_key="foreign", content_id=cid, chunk_ix=0,
                      voice="test", mime="audio/mpeg", audio=b"foreign")
    assert repo.get_tts_chunk(B, "foreign") is None
    repo.conn.execute("INSERT INTO tts_cache (user_id, cache_key, content_id, mime, audio) VALUES (%s, 'legacy', %s, 'audio/mpeg', %s)", (B, cid, b"legacy"))
    assert repo.get_tts_chunk(B, "legacy") is None
    repo.put_tts_chunk(user_id=A, cache_key="owner", content_id=cid, chunk_ix=0,
                      voice="test", mime="audio/mpeg", audio=b"owner")
    assert bytes(repo.get_tts_chunk(A, "owner")["audio"]) == b"owner"
    assert repo.get_tts_chunk(B, "owner") is None
