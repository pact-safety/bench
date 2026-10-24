"""Tests for the /decisions route + journal service (BEN-82, GH #212).

Post-PR-A of the chat_outcomes cutover: the service delegates to
ChatOutcomesRepository. Tests mock the repo (not settings) and
exercise the service + the routes end-to-end.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services import journal as journal_service


_USER = "11111111-1111-1111-1111-111111111111"


def _outcome(
    *,
    eid: str = "co_xxx",
    initiative: str = "bench",
    decisions: str = "Picked X.",
    next_actions: str = "Ship Y.",
    chat_url: str | None = None,
    created_at: datetime | None = None,
):
    """Build a ChatOutcome-shaped object for repo mocks."""
    from app.models import ChatOutcome
    return ChatOutcome(
        id=eid,
        user_id=_USER,
        initiative_slug=initiative,
        decisions=decisions,
        next_actions=next_actions,
        chat_url=chat_url,
        created_at=created_at or datetime(2026, 5, 25, 10, 0, 0, tzinfo=timezone.utc),
        source="mcp",
    )


def _mock_repo_with(outcomes_by_user: dict[str, list]):
    """Build a MagicMock repo with list_for_user / get / initiatives_with_counts
    side_effects driven by the operator's outcomes_by_user dict."""
    repo = MagicMock()

    def _list_for_user(uid, *, initiative_slug=None, limit=50):
        rows = outcomes_by_user.get(uid, [])
        if initiative_slug:
            rows = [r for r in rows if r.initiative_slug == initiative_slug]
        return sorted(rows, key=lambda r: r.created_at, reverse=True)[:limit]

    def _get(entry_id, *, user_id):
        for r in outcomes_by_user.get(user_id, []):
            if r.id == entry_id:
                return r
        return None

    def _initiatives_with_counts(uid):
        counts: dict[str, int] = {}
        for r in outcomes_by_user.get(uid, []):
            counts[r.initiative_slug] = counts.get(r.initiative_slug, 0) + 1
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))

    repo.list_for_user.side_effect = _list_for_user
    repo.get.side_effect = _get
    repo.initiatives_with_counts.side_effect = _initiatives_with_counts
    return repo


# ---------------------------------------------------------------------------
# Service: list_entries / get_entry / initiatives_with_counts
# ---------------------------------------------------------------------------


def test_list_entries_returns_reverse_chronological():
    repo = _mock_repo_with({_USER: [
        _outcome(eid="co_1", created_at=datetime(2026, 5, 20, tzinfo=timezone.utc)),
        _outcome(eid="co_2", created_at=datetime(2026, 5, 22, tzinfo=timezone.utc)),
        _outcome(eid="co_3", created_at=datetime(2026, 5, 21, tzinfo=timezone.utc)),
    ]})
    out = journal_service.list_entries(repo, _USER)
    assert [e.id for e in out] == ["co_2", "co_3", "co_1"]


def test_list_entries_filters_by_initiative():
    repo = _mock_repo_with({_USER: [
        _outcome(eid="co_1", initiative="bench"),
        _outcome(eid="co_2", initiative="capstone"),
        _outcome(eid="co_3", initiative="bench"),
    ]})
    out = journal_service.list_entries(repo, _USER, initiative="bench")
    assert {e.id for e in out} == {"co_1", "co_3"}
    assert all(e.initiative == "bench" for e in out)


def test_list_entries_respects_limit():
    repo = _mock_repo_with({_USER: [
        _outcome(eid=f"co_{i}", created_at=datetime(2026, 5, 25, 10, 0, i, tzinfo=timezone.utc))
        for i in range(5)
    ]})
    out = journal_service.list_entries(repo, _USER, limit=2)
    assert len(out) == 2


def test_list_entries_returns_empty_when_repo_empty():
    repo = _mock_repo_with({})
    assert journal_service.list_entries(repo, _USER) == []


def test_get_entry_returns_match():
    repo = _mock_repo_with({_USER: [
        _outcome(eid="target", decisions="Found me"),
        _outcome(eid="other"),
    ]})
    entry = journal_service.get_entry(repo, _USER, "target")
    assert entry is not None
    assert entry.decisions == "Found me"


def test_get_entry_returns_none_when_missing():
    repo = _mock_repo_with({_USER: [_outcome(eid="exists")]})
    assert journal_service.get_entry(repo, _USER, "nope") is None
    assert journal_service.get_entry(repo, _USER, "") is None


def test_initiatives_with_counts_sorted_by_count_desc_then_slug():
    repo = _mock_repo_with({_USER: [
        _outcome(eid="1", initiative="bench"),
        _outcome(eid="2", initiative="capstone"),
        _outcome(eid="3", initiative="bench"),
        _outcome(eid="4", initiative="anthropic-fellows"),
        _outcome(eid="5", initiative="bench"),
    ]})
    out = journal_service.initiatives_with_counts(repo, _USER)
    # bench=3 (highest), then capstone=1 / anthropic-fellows=1
    # tie broken alphabetically (anthropic-fellows < capstone)
    assert out == [("bench", 3), ("anthropic-fellows", 1), ("capstone", 1)]


def test_journal_entry_strips_blank_chat_url():
    """ChatOutcome with whitespace-only chat_url becomes None on the
    JournalEntry view-model (templates use chat_url is not None)."""
    repo = _mock_repo_with({_USER: [_outcome(eid="x", chat_url="   ")]})
    out = journal_service.list_entries(repo, _USER)
    assert out[0].chat_url is None


def test_journal_entry_preserves_non_blank_chat_url():
    repo = _mock_repo_with({_USER: [
        _outcome(eid="x", chat_url="https://claude.ai/chat/abc"),
    ]})
    out = journal_service.list_entries(repo, _USER)
    assert out[0].chat_url == "https://claude.ai/chat/abc"


# ---------------------------------------------------------------------------
# Route: GET /decisions
# ---------------------------------------------------------------------------


def _signed_in_client(monkeypatch):
    monkeypatch.setenv("LIS_ALLOWED_USER_IDS", _USER)
    monkeypatch.delenv("LIS_ADMIN_USER_IDS", raising=False)

    import app.main as m
    from app.auth import UserSession
    from fastapi.testclient import TestClient
    import app.auth as auth_module

    monkeypatch.setattr(m, "_user_settings", lambda _uid: {})
    monkeypatch.setattr(
        auth_module, "parse_access_token",
        lambda _tok: UserSession(
            user_id=_USER, email="op@example.com",
            expires_at=2**31 - 1, raw_access_token="x",
        ),
    )

    client = TestClient(m.app)
    client.cookies.set("sb-access-token", "x")
    return client, m


def test_decisions_index_renders_entries(monkeypatch):
    client, m = _signed_in_client(monkeypatch)
    outcomes = [
        _outcome(eid="co_1", initiative="bench", decisions="Picked /focus"),
        _outcome(eid="co_2", initiative="capstone", next_actions="Wire vLLM",
                 created_at=datetime(2026, 5, 23, tzinfo=timezone.utc)),
    ]
    fake_repo = _mock_repo_with({_USER: outcomes})
    monkeypatch.setattr(m, "chat_outcomes_repo", fake_repo)

    r = client.get("/decisions", follow_redirects=False)
    assert r.status_code == 200
    assert "Picked /focus" in r.text
    assert "Wire vLLM" in r.text
    assert "bench" in r.text
    assert "capstone" in r.text


def test_decisions_index_filter_via_query_param(monkeypatch):
    client, m = _signed_in_client(monkeypatch)
    outcomes = [
        _outcome(eid="co_1", initiative="bench", decisions="Bench decision"),
        _outcome(eid="co_2", initiative="capstone", decisions="Capstone decision"),
    ]
    monkeypatch.setattr(m, "chat_outcomes_repo", _mock_repo_with({_USER: outcomes}))

    r = client.get("/decisions?initiative=bench", follow_redirects=False)
    assert r.status_code == 200
    assert "Bench decision" in r.text
    assert "Capstone decision" not in r.text


def test_decisions_index_empty_state(monkeypatch):
    client, m = _signed_in_client(monkeypatch)
    monkeypatch.setattr(m, "chat_outcomes_repo", _mock_repo_with({}))

    r = client.get("/decisions", follow_redirects=False)
    assert r.status_code == 200
    assert "log_chat_outcome" in r.text
    assert "No journal entries yet" in r.text


def test_decisions_permalink_renders_single_entry(monkeypatch):
    client, m = _signed_in_client(monkeypatch)
    outcomes = [
        _outcome(eid="co_target", initiative="bench",
                 decisions="Single-entry view",
                 chat_url="https://claude.ai/chat/abc"),
    ]
    monkeypatch.setattr(m, "chat_outcomes_repo", _mock_repo_with({_USER: outcomes}))

    r = client.get("/decisions/co_target", follow_redirects=False)
    assert r.status_code == 200
    assert "Single-entry view" in r.text
    assert "https://claude.ai/chat/abc" in r.text


def test_decisions_permalink_404s_for_missing_entry(monkeypatch):
    client, m = _signed_in_client(monkeypatch)
    monkeypatch.setattr(m, "chat_outcomes_repo", _mock_repo_with({}))

    r = client.get("/decisions/no-such-entry", follow_redirects=False)
    assert r.status_code == 404


def test_decisions_nav_section_highlighted(monkeypatch):
    client, m = _signed_in_client(monkeypatch)
    monkeypatch.setattr(m, "chat_outcomes_repo", _mock_repo_with({}))

    r = client.get("/decisions", follow_redirects=False)
    assert r.status_code == 200
    # Nav link for Decisions
    assert 'href="/decisions">Decisions</a>' in r.text
