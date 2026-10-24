"""Linear integration (v2.1 slice 6): the GraphQL client and the
settings/agenda routes.

Custody + degradation contract: the key is sent bare in Authorization
with an explicit User-Agent (Cloudflare rule), never logged or echoed;
every failure becomes a redirect with a renderable message — the local
agenda keeps working with a broken or absent connection.
"""

from __future__ import annotations

import io
import json
from unittest.mock import MagicMock, patch

import pytest

from app.services import linear_sync


class _FakeHTTPResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _urlopen_returning(payload: dict, capture: dict):
    def _fake(req, timeout=None):
        capture["url"] = req.full_url
        capture["headers"] = dict(req.header_items())
        capture["body"] = json.loads(req.data.decode())
        return _FakeHTTPResponse(json.dumps(payload).encode())

    return _fake


def test_gql_sends_bare_key_and_user_agent(monkeypatch):
    capture: dict = {}
    monkeypatch.setattr(
        linear_sync.urllib.request, "urlopen",
        _urlopen_returning({"data": {"viewer": {"name": "Li"},
                                     "teams": {"nodes": [{"id": "t1", "name": "Bench", "key": "BEN"}]}}},
                           capture),
    )
    info = linear_sync.verify_key("lin_api_secret123")
    assert info["account_label"] == "Li"
    assert info["teams"][0]["key"] == "BEN"
    headers = {k.lower(): v for k, v in capture["headers"].items()}
    assert headers["authorization"] == "lin_api_secret123"  # bare, no Bearer
    assert "lis-bench" in headers["user-agent"]  # CF 1010 rule


def test_verify_key_requires_a_visible_team(monkeypatch):
    monkeypatch.setattr(
        linear_sync.urllib.request, "urlopen",
        _urlopen_returning({"data": {"viewer": {"name": "Li"}, "teams": {"nodes": []}}}, {}),
    )
    with pytest.raises(linear_sync.LinearSyncError, match="no teams"):
        linear_sync.verify_key("k")


def test_graphql_errors_become_renderable_messages(monkeypatch):
    monkeypatch.setattr(
        linear_sync.urllib.request, "urlopen",
        _urlopen_returning({"errors": [{"message": "rate limited"}]}, {}),
    )
    with pytest.raises(linear_sync.LinearSyncError, match="rate limited"):
        linear_sync.verify_key("k")


def test_create_issue_returns_identifier_and_url(monkeypatch):
    capture: dict = {}
    monkeypatch.setattr(
        linear_sync.urllib.request, "urlopen",
        _urlopen_returning(
            {"data": {"issueCreate": {"success": True,
                                      "issue": {"id": "i1", "identifier": "BEN-9", "url": "https://linear.app/x/BEN-9"}}}},
            capture,
        ),
    )
    issue = linear_sync.create_issue("k", "t1", "Title", "Desc")
    assert issue["identifier"] == "BEN-9"
    assert capture["body"]["variables"]["input"]["teamId"] == "t1"


def test_fetch_issue_states_maps_by_id(monkeypatch):
    monkeypatch.setattr(
        linear_sync.urllib.request, "urlopen",
        _urlopen_returning(
            {"data": {"issues": {"nodes": [
                {"id": "i1", "state": {"type": "completed"}},
                {"id": "i2", "state": {"type": "started"}},
            ]}}},
            {},
        ),
    )
    states = linear_sync.fetch_issue_states("k", ["i1", "i2"])
    assert states == {"i1": "completed", "i2": "started"}
    assert linear_sync.STATE_TO_AGENDA_STATUS["completed"] == "done"


def test_fetch_issue_states_empty_input_makes_no_call(monkeypatch):
    boom = MagicMock(side_effect=AssertionError("no network expected"))
    monkeypatch.setattr(linear_sync.urllib.request, "urlopen", boom)
    assert linear_sync.fetch_issue_states("k", []) == {}


# ---------- routes -----------------------------------------------------------

_ADMIN_UUID = "11111111-1111-1111-1111-111111111111"


def _client(monkeypatch):
    monkeypatch.setenv("LIS_ADMIN_USER_IDS", _ADMIN_UUID)
    monkeypatch.delenv("LIS_ALLOWED_USER_IDS", raising=False)
    monkeypatch.delenv("LIS_ALLOWED_EMAILS", raising=False)
    monkeypatch.delenv("LIS_MIRA_ADMIN_ONLY", raising=False)

    import app.main as m
    import app.auth as auth_module
    from app.auth import UserSession
    from fastapi.testclient import TestClient

    monkeypatch.setattr(m, "_user_settings", lambda uid: {})
    monkeypatch.setattr(
        auth_module,
        "parse_access_token",
        lambda _tok: UserSession(
            user_id=_ADMIN_UUID, email="u@example.com",
            expires_at=2**31 - 1, raw_access_token="x",
        ),
    )
    client = TestClient(m.app)
    client.cookies.set("sb-access-token", "x.y.z")
    return client, m


def test_settings_connect_resolves_team_by_key(monkeypatch):
    client, m = _client(monkeypatch)
    info = {"account_label": "Li",
            "teams": [{"id": "t1", "name": "Bench", "key": "BEN"},
                      {"id": "t2", "name": "Ops", "key": "OPS"}]}
    set_config = MagicMock()
    with patch.object(linear_sync, "verify_key", return_value=info), \
         patch.object(m.linear_config_repo, "set_config", set_config):
        r = client.post(
            "/settings/linear",
            data={"linear_api_key": "lin_api_x", "linear_team_key": "ben"},
            follow_redirects=False,
        )
    assert r.status_code == 303
    assert r.headers["location"] == "/settings"
    kw = set_config.call_args.kwargs
    assert kw["team_id"] == "t1"
    assert kw["api_key"] == "lin_api_x"
    assert "BEN" in kw["team_name"]


def test_settings_connect_multi_team_without_key_bounces(monkeypatch):
    client, m = _client(monkeypatch)
    info = {"account_label": "Li",
            "teams": [{"id": "t1", "name": "Bench", "key": "BEN"},
                      {"id": "t2", "name": "Ops", "key": "OPS"}]}
    set_config = MagicMock()
    with patch.object(linear_sync, "verify_key", return_value=info), \
         patch.object(m.linear_config_repo, "set_config", set_config):
        r = client.post(
            "/settings/linear",
            data={"linear_api_key": "lin_api_x"},
            follow_redirects=False,
        )
    assert r.status_code == 303
    assert "linear_error=" in r.headers["location"]
    set_config.assert_not_called()


def test_settings_disconnect_removes_key(monkeypatch):
    client, m = _client(monkeypatch)
    delete_for = MagicMock()
    with patch.object(m.linear_config_repo, "delete_for", delete_for):
        r = client.post("/settings/linear/disconnect", follow_redirects=False)
    assert r.status_code == 303
    delete_for.assert_called_once_with(_ADMIN_UUID)


def _connected_cfg():
    cfg = MagicMock()
    cfg.vault_secret_id = "sid"
    cfg.team_id = "t1"
    return cfg


def test_agenda_push_creates_issue_and_records_link(monkeypatch):
    client, m = _client(monkeypatch)
    item = {"id": "a1", "title": "Reproduce fig 3", "kind": "experiment",
            "why": "core claim", "notes_md": None, "linear_issue_id": None}
    issue = {"id": "i9", "identifier": "BEN-77", "url": "https://linear.app/x/BEN-77"}
    set_link = MagicMock(return_value=True)
    with patch.object(m.linear_config_repo, "get", return_value=_connected_cfg()), \
         patch.object(m.linear_config_repo, "api_key_for", return_value="k"), \
         patch.object(m.mira_repo, "list_agenda", return_value=[item]), \
         patch.object(m.mira_repo, "set_agenda_linear", set_link), \
         patch.object(linear_sync, "create_issue", return_value=issue) as create:
        r = client.post("/mira/agenda/a1/linear", follow_redirects=False)
    assert r.status_code == 303
    assert create.call_args.args[:2] == ("k", "t1")
    assert create.call_args.args[2] == "Reproduce fig 3"
    assert "core claim" in create.call_args.args[3]
    set_link.assert_called_once_with(
        _ADMIN_UUID, "a1", issue_id="i9", identifier="BEN-77",
        url="https://linear.app/x/BEN-77",
    )


def test_agenda_push_without_connection_bounces(monkeypatch):
    client, m = _client(monkeypatch)
    with patch.object(m.linear_config_repo, "get", return_value=None), \
         patch.object(linear_sync, "create_issue") as create:
        r = client.post("/mira/agenda/a1/linear", follow_redirects=False)
    assert r.status_code == 303
    assert "linear_error=" in r.headers["location"]
    create.assert_not_called()


def test_agenda_refresh_maps_states_to_statuses(monkeypatch):
    client, m = _client(monkeypatch)
    links = [
        {"id": "a1", "linear_issue_id": "i1", "status": "open"},
        {"id": "a2", "linear_issue_id": "i2", "status": "done"},
    ]
    set_status = MagicMock()
    with patch.object(m.linear_config_repo, "api_key_for", return_value="k"), \
         patch.object(m.mira_repo, "agenda_linear_links", return_value=links), \
         patch.object(m.mira_repo, "set_agenda_status", set_status), \
         patch.object(linear_sync, "fetch_issue_states",
                      return_value={"i1": "completed", "i2": "completed"}):
        r = client.post("/mira/agenda/linear-refresh", follow_redirects=False)
    assert r.status_code == 303
    # a1 open→done updates; a2 already done stays untouched.
    set_status.assert_called_once_with(_ADMIN_UUID, "a1", "done")
