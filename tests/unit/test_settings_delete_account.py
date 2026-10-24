"""Tests for /settings/delete-account — the wider destructive sibling
of /settings/reset.

Distinct from reset:
- Deletes user-authored content too (writings, JDs, feedback, etc.)
- Clears the public.users row
- Signs out (cookie clear) and redirects to /login?deleted=1
- Server-side gate: requires literal phrase "DELETE MY ACCOUNT"
"""

from __future__ import annotations

from unittest.mock import patch


_USER_UUID = "11111111-1111-1111-1111-111111111111"


def _signed_in_client(monkeypatch):
    monkeypatch.setenv("LIS_ALLOWED_USER_IDS", _USER_UUID)
    monkeypatch.delenv("LIS_ADMIN_USER_IDS", raising=False)

    import app.main as m
    import app.auth as auth_module
    from app.auth import UserSession
    from fastapi.testclient import TestClient

    monkeypatch.setattr(m, "_user_settings", lambda _uid: {})
    monkeypatch.setattr(
        auth_module,
        "parse_access_token",
        lambda _tok: UserSession(
            user_id=_USER_UUID,
            email="op@example.com",
            expires_at=2**31 - 1,
            raw_access_token="x",
        ),
    )

    client = TestClient(m.app)
    client.cookies.set("sb-access-token", "x")
    return client, m


# ---------------------------------------------------------------------------
# /settings landing page surfaces the Danger zone affordances
# ---------------------------------------------------------------------------


def test_settings_page_renders_danger_zone_with_both_actions(monkeypatch):
    """The settings landing must show a Danger zone panel with links
    to both /settings/reset and /settings/delete-account."""
    client, m = _signed_in_client(monkeypatch)

    with patch.object(m.assessment_repo, "latest_completed", return_value=None):
        r = client.get("/settings")

    assert r.status_code == 200
    assert "Danger zone" in r.text
    assert 'href="/settings/reset"' in r.text
    assert 'href="/settings/delete-account"' in r.text


# ---------------------------------------------------------------------------
# GET /settings/delete-account — preview, no mutation
# ---------------------------------------------------------------------------


def test_get_delete_account_renders_preview_with_counts(monkeypatch):
    client, m = _signed_in_client(monkeypatch)

    fake_counts = {
        "reflections": 3,
        "sessions": 0,
        "review_state": 5,
        "attempts": 12,
        "assessment_runs": 1,
        "content_progress": 7,
        "writings": 2,
        "jds": 1,
        "feedback": 0,
        "credential_runs": 0,
        "chat_outcomes": 4,
    }
    with patch.object(m, "_delete_account_counts", return_value=fake_counts):
        r = client.get("/settings/delete-account")

    assert r.status_code == 200
    # Page renders with the phrase-confirmation gate visible.
    assert "DELETE MY ACCOUNT" in r.text
    # Per-table count rows present.
    for table, n in fake_counts.items():
        assert table.replace("_", " ") in r.text
    # Total surfaced.
    assert str(sum(fake_counts.values())) in r.text


def test_get_delete_account_handles_empty_account(monkeypatch):
    """No data on file → renders "No data on file" copy instead of
    the row list."""
    client, m = _signed_in_client(monkeypatch)

    empty_counts = {t: 0 for t in m._DELETE_ACCOUNT_TABLES_ORDER}
    with patch.object(m, "_delete_account_counts", return_value=empty_counts):
        r = client.get("/settings/delete-account")

    assert r.status_code == 200
    assert "No data on file" in r.text


# ---------------------------------------------------------------------------
# POST /settings/delete-account — server-side gate
# ---------------------------------------------------------------------------


def test_post_without_typed_phrase_redirects_back_no_mutation(monkeypatch):
    """Missing the typed phrase → bounce back to the preview page,
    no deletion happens."""
    client, m = _signed_in_client(monkeypatch)

    with patch.object(m, "conn") as fake_conn:
        r = client.post(
            "/settings/delete-account",
            data={"confirm": "yes", "typed_phrase": ""},
            follow_redirects=False,
        )

    assert r.status_code == 303
    assert r.headers["location"] == "/settings/delete-account"
    fake_conn.transaction.assert_not_called()


def test_post_with_wrong_phrase_redirects_back_no_mutation(monkeypatch):
    """Typed phrase that doesn't match exactly → bounce back, no mutation.
    Defends against case-mismatch or partial entry slipping through a
    JS-only gate that didn't enforce the same check server-side."""
    client, m = _signed_in_client(monkeypatch)

    with patch.object(m, "conn") as fake_conn:
        for phrase in ["delete my account", "DELETE", "DELETE MY ACCOUNT NOW", ""]:
            r = client.post(
                "/settings/delete-account",
                data={"confirm": "yes", "typed_phrase": phrase},
                follow_redirects=False,
            )
            assert r.status_code == 303
            assert r.headers["location"] == "/settings/delete-account"
        fake_conn.transaction.assert_not_called()


def test_post_without_confirm_field_redirects_back(monkeypatch):
    """Even with the correct phrase, missing `confirm=yes` blocks the
    deletion (defense-in-depth)."""
    client, m = _signed_in_client(monkeypatch)

    with patch.object(m, "conn") as fake_conn:
        r = client.post(
            "/settings/delete-account",
            data={"confirm": "", "typed_phrase": "DELETE MY ACCOUNT"},
            follow_redirects=False,
        )

    assert r.status_code == 303
    assert r.headers["location"] == "/settings/delete-account"
    fake_conn.transaction.assert_not_called()


def test_post_with_correct_phrase_executes_deletion_and_signs_out(monkeypatch):
    """Happy path: typed phrase matches → DELETEs across all tables in
    the configured order + DELETEs from public.users → redirect to
    /login?deleted=1 with session cookies cleared."""
    client, m = _signed_in_client(monkeypatch)

    deletes: list[tuple[str, str]] = []

    class _FakeCursor:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return None
        def execute(self, sql, params=None):
            deletes.append((sql.strip(), params[0] if params else None))

    class _FakeTxn:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return None

    class _FakeConn:
        def transaction(self):
            return _FakeTxn()
        def cursor(self):
            return _FakeCursor()

    from unittest.mock import MagicMock

    delete_llm = MagicMock()
    delete_linear = MagicMock()
    with patch.object(m, "conn", _FakeConn()), \
         patch.object(m.llm_config_repo, "delete_for", delete_llm), \
         patch.object(m.linear_config_repo, "delete_for", delete_linear), \
         patch.object(m.vault_sync_repo, "delete_for", MagicMock()):
        r = client.post(
            "/settings/delete-account",
            data={"confirm": "yes", "typed_phrase": "DELETE MY ACCOUNT"},
            follow_redirects=False,
        )
    # BYO-key cleanup runs (vault secret can't be reached by the
    # generic table sweep).
    delete_llm.assert_called_once_with(_USER_UUID)

    assert r.status_code == 303
    assert r.headers["location"] == "/login?deleted=1"

    # All configured tables were DELETEd against this user.
    for table in m._DELETE_ACCOUNT_TABLES_ORDER:
        assert any(table in sql for sql, _uid in deletes), f"missing DELETE for {table}"
    # plus public.users at the end.
    assert any("public.users" in sql for sql, _uid in deletes)
    # Every delete carried the user_id.
    for _sql, uid in deletes:
        assert uid == _USER_UUID

    # Session cookies cleared (set-cookie with Max-Age=0 or expires past).
    set_cookie_headers = r.headers.get_list("set-cookie") if hasattr(r.headers, "get_list") else r.headers.raw  # noqa: SLF001
    # FastAPI's TestClient surfaces deleted cookies via response.cookies/headers.
    # Loose check: confirm at least the access token cookie was cleared.
    deleted_cookies = str(r.headers).lower()
    assert "sb-access-token" in deleted_cookies


def test_post_with_whitespace_around_phrase_still_works(monkeypatch):
    """Server strips whitespace before comparing — pasting the phrase
    with a trailing newline or leading space still validates."""
    client, m = _signed_in_client(monkeypatch)

    class _Noop:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return None
        def execute(self, *a, **k):
            return None
        def transaction(self):
            return self
        def cursor(self):
            return self

    from unittest.mock import MagicMock

    with patch.object(m, "conn", _Noop()), \
         patch.object(m.llm_config_repo, "delete_for", MagicMock()), \
         patch.object(m.linear_config_repo, "delete_for", MagicMock()), \
         patch.object(m.vault_sync_repo, "delete_for", MagicMock()):
        r = client.post(
            "/settings/delete-account",
            data={"confirm": "yes", "typed_phrase": "  DELETE MY ACCOUNT\n"},
            follow_redirects=False,
        )

    # Whitespace-stripped match → proceeds to the redirect, not back to preview.
    assert r.status_code == 303
    assert r.headers["location"] == "/login?deleted=1"
