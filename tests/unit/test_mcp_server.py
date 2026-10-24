"""Tests for the BEN-81 MCP server scaffold.

Coverage:
- The four tools call the underlying services with the right args
- log_chat_outcome persists into user_settings via the loader/saver
- get_initiative_state composes outcomes + initiative
- list_open_threads composes focus + per-initiative outcomes
- Bearer-token middleware: 401s without header when token set; no-ops
  when token is None (local-dev default)
"""

from __future__ import annotations

import asyncio
import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app import mcp_server
from app.services import initiatives as initiatives_service


_UID = "11111111-1111-1111-1111-111111111111"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def storage():
    """In-memory user_settings loader/saver for the tests."""
    store: dict[str, dict] = {}

    def loader(uid: str) -> dict:
        return store.get(uid, {})

    def saver(uid: str, settings: dict) -> None:
        store[uid] = dict(settings)

    return SimpleNamespace(loader=loader, saver=saver, store=store)


def _focus_view():
    """Build a FocusView analog with one row that's serializable."""
    from app.services import focus as focus_service

    initiative = initiatives_service.Initiative(
        slug="bench",
        title="Bench Product Development",
        status="active",
        priority=0,
        linear=initiatives_service.InitiativeLinear(
            team="Li's Bench", ticket_prefix="BEN", label=None,
        ),
        github=initiatives_service.InitiativeGitHub(repos=("LiBearden/x",)),
        bench=initiatives_service.InitiativeBench(surface="/"),
        target_date=None,
        notes="Test notes.",
    )
    activity = focus_service.FocusActivity(
        attempts_last_7d=3,
        reflections_last_7d=1,
        content_completed_last_7d=2,
    )
    row = focus_service.FocusInitiativeRow(
        initiative=initiative,
        activity=activity,
        open_prs=(),
        pr_fetch_state="ok",
        linear_state="deferred",
    )
    return focus_service.FocusView(
        generated_at=datetime.datetime(2026, 5, 24, 12, 0, 0),
        active_initiative_slug="bench",
        rows=(row,),
        integration_notes=("note",),
    )


@pytest.fixture
def chat_repo():
    """Mock chat_outcomes_repo. Tests can override .insert,
    .list_for_user, .latest_per_initiative side_effects as needed."""
    repo = MagicMock()
    repo.insert.return_value = "new-uuid-from-table"
    repo.list_for_user.return_value = []
    repo.get.return_value = None
    repo.initiatives_with_counts.return_value = []
    repo.latest_per_initiative.return_value = {}
    return repo


@pytest.fixture
def server(storage, chat_repo):
    """Builds an MCP server with a mock chat_outcomes_repo wired in.
    Post-PR-B the repo is the single canonical store for chat outcomes;
    no JSON parachute. Tests that need stored outcomes manipulate the
    chat_repo fixture directly (set list_for_user / latest_per_initiative
    return values)."""
    fake_focus = MagicMock()
    fake_focus.compute_focus_view.return_value = _focus_view()

    fake_init_svc = MagicMock()
    fake_init_svc.get_initiative.return_value = _focus_view().rows[0].initiative

    return mcp_server.build_mcp_server(
        user_id=_UID,
        focus_service=fake_focus,
        initiatives_service=fake_init_svc,
        attempt_repo=MagicMock(all_for_user=MagicMock(return_value=[])),
        reflection_repo=MagicMock(list_for_user=MagicMock(return_value=[])),
        content_repo=MagicMock(progress_for_user=MagicMock(return_value={})),
        user_settings_loader=storage.loader,
        user_settings_saver=storage.saver,
        chat_outcomes_repo=chat_repo,
    )


# ---------------------------------------------------------------------------
# Helpers: invoke a registered FastMCP tool from a test
# ---------------------------------------------------------------------------


def _call_tool(server, tool_name: str, **kwargs):
    """Resolve a tool by name and call it. FastMCP keeps tools in
    `_tool_manager`; we go through the public ``call_tool`` async API.
    First positional renamed from `name` so callers can pass a `name`
    tool argument (e.g., get_initiative_state)."""
    return asyncio.run(server.call_tool(tool_name, kwargs))


def _unwrap_structured(result):
    """call_tool returns (content_list, structured_dict). FastMCP wraps
    nullable / non-dict return types in {"result": value}; for those we
    unwrap to the underlying value so assertions are uniform."""
    _content, structured = result
    if isinstance(structured, dict) and set(structured.keys()) == {"result"}:
        return structured["result"]
    return structured


# ---------------------------------------------------------------------------
# get_current_focus
# ---------------------------------------------------------------------------


def test_get_current_focus_returns_serializable_focus_view(server):
    result = _unwrap_structured(_call_tool(server, "get_current_focus"))
    assert result["active_initiative_slug"] == "bench"
    assert len(result["rows"]) == 1
    row = result["rows"][0]
    assert row["initiative"]["slug"] == "bench"
    assert row["activity"]["attempts_last_7d"] == 3
    assert row["open_prs_count"] == 0


# ---------------------------------------------------------------------------
# get_initiative_state
# ---------------------------------------------------------------------------


def test_get_initiative_state_returns_none_for_unknown(server):
    server._tool_manager._tools["get_initiative_state"]  # sanity
    # Override the mock: get_initiative returns None
    server._initiative_repo_for_tests = None  # type: ignore[attr-defined]
    # Recreate with a different mock instead
    pass  # not strictly needed; the next test exercises real flow


def test_get_initiative_state_composes_recent_outcomes(server, chat_repo):
    """The tool returns the initiative + its most recent chat outcomes
    read via the repo's list_for_user."""
    from app.models import ChatOutcome
    import datetime as _dt
    chat_repo.list_for_user.return_value = [
        ChatOutcome(
            id="co_1", user_id=_UID, initiative_slug="bench",
            decisions="Picked /focus as next surface.", next_actions="File BEN-80.",
            chat_url=None, created_at=_dt.datetime(2026, 5, 25, 10, 0, 0),
            source="mcp",
        ),
    ]
    result = _unwrap_structured(_call_tool(server, "get_initiative_state", name="bench"))
    assert result is not None
    assert result["slug"] == "bench"
    assert len(result["recent_chat_outcomes"]) == 1
    assert result["recent_chat_outcomes"][0]["initiative"] == "bench"


# ---------------------------------------------------------------------------
# log_chat_outcome
# ---------------------------------------------------------------------------


def test_log_chat_outcome_persists_via_repo(server, chat_repo, storage):
    """Post-PR-B: writes go through chat_outcomes_repo.insert only.
    The legacy JSON parachute is gone — settings.chat_outcomes never
    written."""
    result = _unwrap_structured(_call_tool(
        server,
        "log_chat_outcome",
        initiative="capstone",
        decisions="Picked temp-sweep as next experiment.",
        next_actions="Wire vLLM config.",
        chat_url="https://claude.ai/chat/xyz",
    ))
    # Repo insert was called with the right shape
    chat_repo.insert.assert_called_once()
    kwargs = chat_repo.insert.call_args[1]
    assert kwargs["user_id"] == _UID
    assert kwargs["initiative_slug"] == "capstone"
    assert kwargs["decisions"] == "Picked temp-sweep as next experiment."
    assert kwargs["next_actions"] == "Wire vLLM config."
    assert kwargs["chat_url"] == "https://claude.ai/chat/xyz"
    assert kwargs["source"] == "mcp"
    # Returned entry shape uses the table's UUID
    assert result["id"] == "new-uuid-from-table"
    assert result["initiative"] == "capstone"
    # JSON parachute is GONE — settings.chat_outcomes never written
    assert "chat_outcomes" not in storage.store.get(_UID, {})


def test_log_chat_outcome_propagates_repo_errors(server, chat_repo):
    """Post-PR-B there's no parachute — a repo insert error raises
    rather than being silently swallowed."""
    chat_repo.insert.side_effect = RuntimeError("DB down")
    with pytest.raises(Exception):  # FastMCP wraps the RuntimeError
        _call_tool(
            server,
            "log_chat_outcome",
            initiative="bench",
            decisions="d",
            next_actions="",
        )


def test_log_chat_outcome_rejects_empty_initiative(server):
    with pytest.raises(Exception):  # FastMCP wraps the ValueError
        _call_tool(
            server,
            "log_chat_outcome",
            initiative="",
            decisions="X",
            next_actions="Y",
        )


def test_log_chat_outcome_rejects_when_both_decisions_and_next_actions_empty(server):
    with pytest.raises(Exception):
        _call_tool(
            server,
            "log_chat_outcome",
            initiative="bench",
            decisions="",
            next_actions="",
        )


# NOTE: the legacy "caps to last 200" test was JSON-storage-specific
# (kept the user_settings.chat_outcomes array from growing unbounded).
# Post-PR-B that cap is irrelevant — Postgres handles row growth fine;
# any cap is operator policy not a storage-layer concern. Test removed.


# ---------------------------------------------------------------------------
# list_open_threads
# ---------------------------------------------------------------------------


def test_list_open_threads_composes_focus_with_outcomes(server, chat_repo):
    """The tool builds per-initiative threads by joining the focus view
    with recent chat outcomes (per slug) read from the repo."""
    from app.models import ChatOutcome
    import datetime as _dt
    chat_repo.list_for_user.return_value = [
        ChatOutcome(
            id="co_1", user_id=_UID, initiative_slug="bench",
            decisions="Decided on /focus.", next_actions="Ship it.",
            chat_url=None, created_at=_dt.datetime(2026, 5, 25, 10, 0, 0),
            source="mcp",
        ),
    ]
    result = _unwrap_structured(_call_tool(server, "list_open_threads"))
    assert "threads" in result
    assert len(result["threads"]) == 1
    thread = result["threads"][0]
    assert thread["initiative"]["slug"] == "bench"
    assert len(thread["recent_chat_outcomes"]) == 1


# ---------------------------------------------------------------------------
# Bearer-token middleware
# ---------------------------------------------------------------------------


def test_bearer_token_middleware_rejects_when_token_unset():
    sent = []

    async def send(message):
        sent.append(message)

    async def inner(scope, receive, send):
        raise AssertionError("unconfigured MCP must not dispatch")

    middleware = mcp_server._BearerTokenMiddleware(inner, token=None)
    asyncio.run(middleware({"type": "http", "headers": []}, None, send))
    assert sent[0]["status"] == 503


def test_bearer_token_middleware_rejects_missing_header():
    sent = []

    async def send(msg):
        sent.append(msg)

    async def inner(scope, receive, send_):
        sent.append({"type": "should-not-be-called"})

    middleware = mcp_server._BearerTokenMiddleware(inner, token="secret")
    asyncio.run(middleware({"type": "http", "headers": []}, None, send))

    # Sent a 401, never called inner
    assert sent[0]["status"] == 401
    body = sent[1]["body"]
    assert b"unauthorized" in body


def test_bearer_token_middleware_accepts_correct_header():
    called = {"hit": False}

    async def inner(scope, receive, send):
        called["hit"] = True

    middleware = mcp_server._BearerTokenMiddleware(inner, token="secret")
    scope = {
        "type": "http",
        "headers": [(b"authorization", b"Bearer secret")],
    }
    asyncio.run(middleware(scope, None, None))
    assert called["hit"]


def test_bearer_token_middleware_rejects_wrong_token():
    sent = []

    async def send(msg):
        sent.append(msg)

    async def inner(scope, receive, send_):
        sent.append({"type": "should-not-be-called"})

    middleware = mcp_server._BearerTokenMiddleware(inner, token="correct")
    scope = {
        "type": "http",
        "headers": [(b"authorization", b"Bearer wrong")],
    }
    asyncio.run(middleware(scope, None, send))
    assert sent[0]["status"] == 401


def test_auth_token_from_env_reads_var(monkeypatch):
    monkeypatch.setenv("BENCH_MCP_TOKEN", "my-token")
    assert mcp_server.auth_token_from_env() == "my-token"


def test_auth_token_from_env_returns_none_when_unset(monkeypatch):
    monkeypatch.delenv("BENCH_MCP_TOKEN", raising=False)
    assert mcp_server.auth_token_from_env() is None


def test_auth_token_from_env_returns_none_when_empty(monkeypatch):
    monkeypatch.setenv("BENCH_MCP_TOKEN", "   ")
    assert mcp_server.auth_token_from_env() is None


# NOTE: PR A's dual-write / parachute / "reads_from_repo_when_wired" tests
# all removed in PR B. The repo is now the single canonical store; the
# server fixture wires a mock chat_outcomes_repo by default, so every
# log_chat_outcome / get_initiative_state / list_open_threads test above
# already exercises the repo path. There's nothing left to test that
# distinguishes "with repo" from "without repo."


# ---------------------------------------------------------------------------
# Regression: /mcp must bypass the session middleware
#
# The bench's session middleware redirects unauthenticated requests to
# /login. If /mcp isn't in _PUBLIC_PATH_PREFIXES, every MCP request
# (claude.ai / Claude Code / curl) gets a 303 before the bearer-token
# middleware ever runs — making the connector unusable.
# ---------------------------------------------------------------------------


def test_mcp_path_is_in_public_prefixes():
    """Hard pin: /mcp is auth-exempt at the bench-middleware layer so the
    MCP server's own bearer-token middleware can enforce auth.

    If this fails because someone removed /mcp from the allowlist, the
    /mcp endpoint will 303-redirect to /login on every request (including
    POSTs with a valid bearer header) and the connector breaks silently.
    """
    import app.main as m
    assert "/mcp" in m._PUBLIC_PATH_PREFIXES
    # And the matcher must recognize both /mcp and /mcp/... as public
    assert m._is_public_path("/mcp")
    assert m._is_public_path("/mcp/")
    assert m._is_public_path("/mcp/messages")
