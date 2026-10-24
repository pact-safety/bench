"""Route tests for /news (rss-news-feed Phase 1)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
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


def _item(
    *,
    id_: int,
    source: str = "anthropic",
    title: str = "Some news",
    url: str = "https://example.test/x",
    is_pinned: bool = False,
    is_dismissed: bool = False,
    summary: str | None = "A short summary.",
):
    return SimpleNamespace(
        id=id_,
        source=source,
        title=title,
        url=url,
        summary=summary,
        published_at=datetime(2026, 5, 27, 10, 0, 0),
        fetched_at=datetime(2026, 5, 27, 10, 5, 0),
        axes_json=[],
        is_pinned=is_pinned,
        is_dismissed=is_dismissed,
    )


# ---------------------------------------------------------------------------
# GET /news
# ---------------------------------------------------------------------------


def test_news_renders_items_with_titles_and_links(monkeypatch):
    client, m = _signed_in_client(monkeypatch)

    items = [
        _item(id_=1, source="anthropic", title="Claude 4.7 announcement",
              url="https://www.anthropic.com/news/claude-4-7"),
        _item(id_=2, source="metr", title="New evals released",
              url="https://metr.org/blog/evals"),
    ]
    with patch.object(m.news_repo, "list_recent", return_value=items), \
         patch.object(m.news_repo, "list_sources_present", return_value=["anthropic", "metr"]):
        r = client.get("/news")

    assert r.status_code == 200
    assert "Claude 4.7 announcement" in r.text
    assert 'href="https://www.anthropic.com/news/claude-4-7"' in r.text
    assert "New evals released" in r.text


def test_news_empty_state_when_no_items(monkeypatch):
    client, m = _signed_in_client(monkeypatch)

    with patch.object(m.news_repo, "list_recent", return_value=[]), \
         patch.object(m.news_repo, "list_sources_present", return_value=[]):
        r = client.get("/news")

    assert r.status_code == 200
    assert "No items yet" in r.text
    # Empty state mentions the feed registry path so the operator knows
    # where to add new sources.
    assert "news_feeds.toml" in r.text


def test_news_source_filter_param_is_passed_to_repo(monkeypatch):
    client, m = _signed_in_client(monkeypatch)
    captured: dict = {}

    def fake_list_recent(*, limit, source, include_dismissed):
        captured["source"] = source
        captured["include_dismissed"] = include_dismissed
        return []

    with patch.object(m.news_repo, "list_recent", side_effect=fake_list_recent), \
         patch.object(m.news_repo, "list_sources_present", return_value=["anthropic", "metr"]):
        r = client.get("/news?source=metr")

    assert r.status_code == 200
    assert captured["source"] == "metr"
    assert captured["include_dismissed"] is False


def test_news_show_dismissed_query_param_propagates(monkeypatch):
    client, m = _signed_in_client(monkeypatch)
    captured: dict = {}

    def fake_list_recent(*, limit, source, include_dismissed):
        captured["include_dismissed"] = include_dismissed
        return []

    with patch.object(m.news_repo, "list_recent", side_effect=fake_list_recent), \
         patch.object(m.news_repo, "list_sources_present", return_value=[]):
        client.get("/news?show_dismissed=1")

    assert captured["include_dismissed"] is True


def test_news_filter_chips_use_feed_display_names(monkeypatch):
    """The chip label is the feed's `name` from news_feeds.toml, not
    the bare slug. Slugs are sometimes ugly ("ai-snake-oil"); names
    are human ("AI Snake Oil")."""
    client, m = _signed_in_client(monkeypatch)

    with patch.object(m.news_repo, "list_recent", return_value=[]), \
         patch.object(m.news_repo, "list_sources_present", return_value=["anthropic", "metr"]):
        r = client.get("/news")

    # The shipped news_feeds.toml has Anthropic and METR with these names.
    assert "Anthropic News" in r.text
    assert "METR" in r.text


# ---------------------------------------------------------------------------
# Pin / dismiss actions
# ---------------------------------------------------------------------------


def test_pin_action_marks_pinned_and_redirects(monkeypatch):
    client, m = _signed_in_client(monkeypatch)

    captured: dict = {}

    def fake_set_pinned(item_id, pinned):
        captured["item_id"] = item_id
        captured["pinned"] = pinned

    with patch.object(m.news_repo, "get", return_value=_item(id_=42)), \
         patch.object(m.news_repo, "set_pinned", side_effect=fake_set_pinned):
        r = client.post("/news/42/pin", follow_redirects=False)

    assert r.status_code == 303
    assert r.headers["location"] == "/news"
    assert captured == {"item_id": 42, "pinned": True}


def test_unpin_action_clears_pin(monkeypatch):
    client, m = _signed_in_client(monkeypatch)
    captured: dict = {}

    def fake_set_pinned(item_id, pinned):
        captured["pinned"] = pinned

    with patch.object(m.news_repo, "get", return_value=_item(id_=42, is_pinned=True)), \
         patch.object(m.news_repo, "set_pinned", side_effect=fake_set_pinned):
        client.post("/news/42/pin", data={"unpin": "1"}, follow_redirects=False)

    assert captured["pinned"] is False


def test_dismiss_action_marks_dismissed(monkeypatch):
    client, m = _signed_in_client(monkeypatch)
    captured: dict = {}

    def fake_set_dismissed(item_id, dismissed):
        captured["dismissed"] = dismissed

    with patch.object(m.news_repo, "get", return_value=_item(id_=42)), \
         patch.object(m.news_repo, "set_dismissed", side_effect=fake_set_dismissed):
        client.post("/news/42/dismiss", follow_redirects=False)

    assert captured["dismissed"] is True


def test_pin_on_missing_item_returns_404(monkeypatch):
    client, m = _signed_in_client(monkeypatch)
    with patch.object(m.news_repo, "get", return_value=None), \
         patch.object(m.news_repo, "set_pinned") as fake_set:
        r = client.post("/news/9999/pin", follow_redirects=False)
    assert r.status_code == 404
    fake_set.assert_not_called()


# ---------------------------------------------------------------------------
# Auth gate
# ---------------------------------------------------------------------------


def test_get_news_requires_auth():
    import app.main as m
    from fastapi.testclient import TestClient

    client = TestClient(m.app)
    r = client.get("/news", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"
