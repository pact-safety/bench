"""Account boundaries exercised against SQL, with no external database."""
import sqlite3
from datetime import datetime

import pytest

from app.repositories.content_repository import ContentRepository

A = "11111111-1111-1111-1111-111111111111"
B = "22222222-2222-2222-2222-222222222222"


class Cursor:
    def __init__(self, db):
        self.cursor = db.cursor()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.cursor.close()

    def execute(self, sql, params=()):
        self.cursor.execute(sql.replace("%s", "?"), params)

    def fetchone(self):
        row = self.cursor.fetchone()
        return dict(row) if row else None

    def fetchall(self):
        return [dict(row) for row in self.cursor.fetchall()]


class Connection:
    def __init__(self):
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.create_function("NOW", 0, lambda: "2026-09-24 12:00:00")

    def cursor(self):
        return Cursor(self.db)

    def commit(self):
        self.db.commit()


@pytest.fixture
def repo():
    conn = Connection()
    conn.db.executescript("""
        CREATE TABLE content_items (
          id INTEGER PRIMARY KEY, slug TEXT, kind TEXT, title TEXT,
          source TEXT, url TEXT, duration_min INTEGER, axes_json TEXT, prerequisites_json TEXT,
          content_md TEXT, authored_by TEXT, authored_date TEXT,
          version_int INTEGER, source_kind TEXT, created_by_user_id TEXT);
        CREATE TABLE content_progress (
          user_id TEXT, content_id INTEGER, status TEXT, checked_at TEXT,
          notes_md TEXT, favorited_bool INTEGER DEFAULT 0, rating_1_to_5 INTEGER,
          initiative_slug TEXT, recitation_state TEXT, last_recited_at TEXT,
          paper_state TEXT, PRIMARY KEY (user_id, content_id));
        CREATE TABLE tts_cache (
          user_id TEXT, cache_key TEXT, content_id INTEGER, chunk_ix INTEGER,
          voice TEXT, mime TEXT, audio BLOB, PRIMARY KEY (user_id, cache_key));
    """)
    for cid, owner, source_kind in [(1, None, "authored"), (2, A, "user"),
                                     (3, B, "user"), (4, None, "user")]:
        conn.db.execute("""INSERT INTO content_items
          (id, slug, kind, title, axes_json, content_md, version_int,
           source_kind, created_by_user_id) VALUES (?, ?, 'reading', ?, '[]', ?, 1, ?, ?)""",
          (cid, f"item-{cid}", f"Title {cid}", f"Private notes {cid}", source_kind, owner))
    yield ContentRepository(conn)
    conn.db.close()


def test_lists_and_cache_are_account_scoped(repo):
    for uid, expected in [(A, [1, 2]), (B, [1, 3]), (None, [1]), (A, [1, 2])]:
        assert [x.id for x in repo.all_by_kind("reading", user_id=uid)] == expected
        assert [x.id for x in repo.all_by_kinds(["reading", "video"], user_id=uid)["reading"]] == expected


@pytest.mark.parametrize("uid,visible", [(A, {1, 2}), (B, {1, 3}), (None, {1})])
def test_details_require_owner_or_authored_content(repo, uid, visible):
    for cid in range(1, 5):
        assert (repo.get_by_id(cid, user_id=uid) is not None) == (cid in visible)
        assert (repo.get_by_slug(f"item-{cid}", user_id=uid) is not None) == (cid in visible)


@pytest.mark.parametrize("method,args", [
    ("mark_completed", ()), ("mark_unread", ()), ("toggle_favorite", ()),
    ("set_rating", (5,)), ("save_reflection", ("private note",)),
    ("save_recitation_state", ({"concept": {}},)), ("save_paper_state", ({"pass": 1},)),
])
def test_progress_mutations_cannot_attach_foreign_content(repo, method, args):
    operation = getattr(repo, method)
    operation(B, 2, *args)
    assert repo.conn.db.execute("SELECT * FROM content_progress").fetchall() == []
    operation(A, 2, *args)
    operation(B, 1, *args)
    assert repo.conn.db.execute("SELECT count(*) FROM content_progress").fetchone()[0] == 2


def test_legacy_foreign_progress_is_hidden_from_derived_reads(repo):
    for cid in [1, 2, 3]:
        repo.conn.db.execute("""INSERT INTO content_progress
          (user_id, content_id, status, notes_md, favorited_bool, rating_1_to_5)
          VALUES (?, ?, 'completed', 'legacy', 1, 5)""", (B, cid))
    # Keep checked_at NULL so the production datetime adapter is not needed.
    assert set(repo.progress_for_user(B)) == {1, 3}
    assert [p.content_id for p in repo.favorites_for_user(B)] == [1, 3]
    repo.conn.db.execute("UPDATE content_items SET axes_json = '[\"foreign_axis\"]' WHERE id = 2")
    assert repo.axis_ratings_for_user(B) == {}


def test_tts_cache_rejects_foreign_content_and_legacy_audio(repo):
    repo.put_tts_chunk(user_id=B, cache_key="foreign", content_id=2,
                      chunk_ix=0, voice="test", mime="audio/mpeg", audio=b"foreign")
    assert repo.conn.db.execute("SELECT * FROM tts_cache").fetchall() == []
    repo.conn.db.execute("INSERT INTO tts_cache VALUES (?, 'legacy', 2, 0, 'test', 'audio/mpeg', ?)", (B, b"legacy"))
    assert repo.get_tts_chunk(B, "legacy") is None
    repo.put_tts_chunk(user_id=A, cache_key="own", content_id=2,
                      chunk_ix=0, voice="test", mime="audio/mpeg", audio=b"own")
    assert repo.get_tts_chunk(A, "own")["audio"] == b"own"
    assert repo.get_tts_chunk(B, "own") is None


def request_for(uid):
    from types import SimpleNamespace
    from starlette.requests import Request
    request = Request({"type": "http", "method": "POST", "path": "/content/item-2",
                       "headers": [], "query_string": b""})
    request.state.user_session = SimpleNamespace(user_id=uid)
    request.state.user_settings = {}
    return request


@pytest.fixture
def routes(repo, monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "content_repo", repo)
    monkeypatch.setattr(main.problem_repo, "all_core", lambda: [])
    monkeypatch.setattr(main.problem_repo, "all_warmups", lambda: [])
    monkeypatch.setattr(main.attempt_repo, "all_for_user", lambda uid: [])
    monkeypatch.setattr(main, "_bubbles_for", lambda *args: [])
    monkeypatch.setattr(main, "_active_track_materials", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "_daily_chain_step", lambda *args, **kwargs: None)
    monkeypatch.setattr(main.templates, "TemplateResponse", lambda request, name, context: context)
    return main


def test_library_and_detail_routes_preserve_owner_access(routes):
    for uid, expected in [(A, [1, 2]), (B, [1, 3]), (A, [1, 2])]:
        req = request_for(uid)
        assert [i.id for i in routes.library_page(req)["all_content"]] == expected
        for cid in expected:
            assert routes.view_content(req, f"item-{cid}")["item"].id == cid
    assert routes.view_content(request_for(B), "item-2").status_code == 404


@pytest.mark.parametrize("route,kwargs", [
    ("check_content", {"next": 0, "initiative_slug": ""}),
    ("check_content", {"undo": 1, "next": 0}),
    ("toggle_favorite", {}), ("rate_content", {"rating": 5}),
    ("reflect_content", {"notes_md": "foreign"}),
    ("content_audio_manifest", {}), ("content_audio_chunk", {"chunk_ix": 0}),
])
def test_id_routes_deny_foreign_content_before_mutation_or_tts(routes, repo, monkeypatch, route, kwargs):
    from app.services import tts
    def unexpected(*args, **kwargs):
        pytest.fail("foreign content reached the TTS provider")
    monkeypatch.setattr(tts, "manifest", unexpected)
    response = getattr(routes, route)(request_for(B), 2, **kwargs)
    assert response.status_code == 404
    assert repo.conn.db.execute("SELECT * FROM content_progress").fetchall() == []


def test_recitation_denies_foreign_content_before_reading_audio(routes):
    import asyncio
    from unittest.mock import AsyncMock
    audio = AsyncMock()
    response = asyncio.run(routes.recite_content(request_for(B), 2, audio=audio, mode="review"))
    assert response.status_code == 404
    audio.read.assert_not_called()


def test_paper_pass_denies_foreign_content(routes, repo):
    import asyncio
    response = asyncio.run(routes.content_advance_pass(request_for(B), 2))
    assert response.status_code == 404
    assert repo.conn.db.execute("SELECT * FROM content_progress").fetchall() == []


def test_completion_history_excludes_legacy_foreign_content(repo):
    for cid in [1, 2, 3]:
        repo.conn.db.execute("""INSERT INTO content_progress
          (user_id, content_id, status, checked_at) VALUES (?, ?, 'completed', '2026-09-24 12:00:00')""", (B, cid))
    assert [p.content_id for p in repo.list_progress_since(B, datetime(2026, 9, 1))] == [1, 3]


def test_inaccessible_existing_progress_cannot_be_modified(repo):
    repo.conn.db.execute("INSERT INTO content_progress (user_id, content_id, status, notes_md) VALUES (?, 2, 'unread', 'before')", (B,))
    repo.save_reflection(B, 2, "after")
    assert repo.conn.db.execute("SELECT notes_md FROM content_progress").fetchone()[0] == "before"


def test_owner_favorite_remains_toggleable(repo):
    assert repo.toggle_favorite(A, 2) is True
    assert repo.toggle_favorite(A, 2) is False


def test_create_then_owner_read_preserves_original_notes_and_invalidates_lists(routes, repo):
    # Warm both account caches before adding a private item.
    assert [i.id for i in repo.all_by_kind("reading", user_id=A)] == [1, 2]
    assert [i.id for i in repo.all_by_kind("reading", user_id=B)] == [1, 3]
    response = routes.create_external_content(
        request_for(A), title="New private note", kind="reading", source="Personal",
        source_other="", url="", duration_min="", axes_csv="", notes_md="original private notes",
    )
    assert response.status_code == 303
    slug = response.headers["location"].rsplit("/", 1)[-1]
    item = routes.view_content(request_for(A), slug)["item"]
    assert item.created_by_user_id == A
    assert item.content_md == "original private notes"
    assert item.id in [i.id for i in routes.library_page(request_for(A))["all_content"]]
    assert item.id not in [i.id for i in routes.library_page(request_for(B))["all_content"]]
    assert routes.view_content(request_for(B), slug).status_code == 404
    assert routes.reflect_content(request_for(B), item.id, notes_md="overwrite").status_code == 404
    assert routes.content_audio_manifest(request_for(B), item.id).status_code == 404
    assert repo.get_by_id(item.id, user_id=A).content_md == "original private notes"


def test_track_item_ratings_and_reflections_are_independent_per_item_and_learner(repo):
    # Track resources reuse shared authored IDs, while feedback belongs to the
    # learner. Updating one resource must not overwrite another or another user.
    repo.conn.db.execute("UPDATE content_items SET source_kind = 'authored', created_by_user_id = NULL WHERE id = 2")
    repo.set_rating(A, 1, 5)
    repo.save_reflection(A, 1, "Atlas: scaling evidence has limits.")
    repo.set_rating(A, 2, 3)
    repo.save_reflection(A, 2, "Tensor video: revisit axis order.")
    repo.set_rating(B, 1, 2)
    repo.save_reflection(B, 1, "Another learner's reflection.")
    repo.set_rating(A, 1, 4)
    a = repo.progress_for_user(A)
    b = repo.progress_for_user(B)
    assert (a[1].rating_1_to_5, a[1].notes_md) == (4, "Atlas: scaling evidence has limits.")
    assert (a[2].rating_1_to_5, a[2].notes_md) == (3, "Tensor video: revisit axis order.")
    assert (b[1].rating_1_to_5, b[1].notes_md) == (2, "Another learner's reflection.")
    assert 2 not in b
