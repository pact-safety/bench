"""MATS drill launcher: /mira?persona= → session persona → drill notes.

The last piece of the MATS drill (task chain: persona + rep-trend helper
shipped earlier; this wires the launcher end to end).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services import mira as mira_service


_ADMIN_UUID = "11111111-1111-1111-1111-111111111111"


def _client(monkeypatch):
    monkeypatch.setenv("LIS_ADMIN_USER_IDS", _ADMIN_UUID)
    monkeypatch.delenv("LIS_ALLOWED_USER_IDS", raising=False)
    monkeypatch.delenv("LIS_ALLOWED_EMAILS", raising=False)

    import app.main as m
    import app.auth as auth_module
    from app.auth import UserSession
    from fastapi.testclient import TestClient

    monkeypatch.setattr(m, "_user_settings", lambda uid: {})
    monkeypatch.setattr(
        auth_module,
        "parse_access_token",
        lambda _tok: UserSession(
            user_id=_ADMIN_UUID, email="op@example.com",
            expires_at=2**31 - 1, raw_access_token="x",
        ),
    )
    client = TestClient(m.app)
    client.cookies.set("sb-access-token", "x.y.z")
    return client, m


# ---- route: ?persona= -------------------------------------------------------


def test_legacy_drill_query_cannot_start_unrestricted_generation(monkeypatch):
    client, m = _client(monkeypatch)
    create = MagicMock(return_value="s1")
    with patch.object(m.mira_repo, "create_session", create), \
         patch.object(m.mira_repo, "get_session", return_value=MagicMock(meta={})), \
         patch.object(m, "_mira_session_view", return_value=__import__("fastapi").responses.HTMLResponse("ok")), \
         patch.object(m.feedback_repo, "counts_all", return_value={"open": 0}):
        r = client.get("/mira?persona=mats-empirical-drill")
    assert r.status_code == 200
    create.assert_not_called()


def test_unknown_persona_query_does_not_create_session(monkeypatch):
    client, m = _client(monkeypatch)
    create = MagicMock(return_value="s1")
    with patch.object(m.mira_repo, "create_session", create), \
         patch.object(m.mira_repo, "get_session", return_value=MagicMock(meta={})), \
         patch.object(m, "_mira_session_view", return_value=__import__("fastapi").responses.HTMLResponse("ok")), \
         patch.object(m.feedback_repo, "counts_all", return_value={"open": 0}):
        client.get("/mira?persona=hamming")  # review lens, not a chat persona
    create.assert_not_called()


# ---- service: persona selection + drill system note ------------------------


def _turn(role: str, content: str, minutes_ago: int = 0):
    return SimpleNamespace(
        role=role, content=content,
        created_at=datetime.utcnow() - timedelta(minutes=minutes_ago),
    )


async def _collect(gen):
    return [e async for e in gen]


def test_drill_persona_used_and_note_injected(monkeypatch):
    """With persona_key=mats-empirical-drill, the system prompt carries
    the drill persona AND the elapsed/trend system note."""
    captured = {}

    class FakeProvider:
        name = "fake"
        async def stream(self, system, messages, max_tokens):
            captured["system"] = system
            yield {"type": "text", "delta": "ok"}
            yield {"type": "finish", "usage": None}

    repo = MagicMock()
    repo.list_turns.return_value = [
        _turn("assistant", "=== REP 1 · MODE A · target 20 min ===", 25),
        _turn("user", "(submission)", 22),
        _turn("assistant", "=== END REP 1 · elapsed 22 min ===\ncritique…", 18),
    ]
    monkeypatch.setattr(mira_service.llm_provider, "get_provider", lambda name: FakeProvider())
    monkeypatch.setattr(mira_service.spend_cap, "over_cap_for", lambda *a: False)

    import asyncio
    asyncio.run(_collect(mira_service.mira_turn(
        "sess", "next rep please", user_id=None, repo=repo,
        persona_key="mats-empirical-drill",
    )))

    system = captured["system"]
    assert "BENCH FORMAT" in system  # the drill persona's pinned block
    assert "<system_note>" in system
    assert "elapsed since your last message: 18m." in system
    assert "Rep 1: 22/20m (over)" in system  # trend from the markers


def test_default_persona_unchanged(monkeypatch):
    captured = {}

    class FakeProvider:
        name = "fake"
        async def stream(self, system, messages, max_tokens):
            captured["system"] = system
            yield {"type": "finish", "usage": None}

    monkeypatch.setattr(mira_service.llm_provider, "get_provider", lambda name: FakeProvider())
    monkeypatch.setattr(mira_service.spend_cap, "over_cap_for", lambda *a: False)

    import asyncio
    asyncio.run(_collect(mira_service.mira_turn("sess", "hi", user_id=None, repo=None)))

    assert "<system_note>" not in captured["system"]
    assert "BENCH FORMAT" not in captured["system"]


def test_review_lens_key_cannot_reach_chat(monkeypatch):
    """A review-voice key (voices.get would resolve it!) must fall back
    to the mentor — the whitelist is the boundary."""
    captured = {}

    class FakeProvider:
        name = "fake"
        async def stream(self, system, messages, max_tokens):
            captured["system"] = system
            yield {"type": "finish", "usage": None}

    monkeypatch.setattr(mira_service.llm_provider, "get_provider", lambda name: FakeProvider())
    monkeypatch.setattr(mira_service.spend_cap, "over_cap_for", lambda *a: False)

    import asyncio
    asyncio.run(_collect(mira_service.mira_turn(
        "sess", "hi", user_id=None, repo=None, persona_key="hamming",
    )))
    assert "BENCH FORMAT" not in captured["system"]


# ---- track renders the drill launcher --------------------------------------


def test_mats_track_loads_with_drill_kind():
    from pathlib import Path
    from app.services.tracks import load_all_tracks

    tracks = load_all_tracks(Path("content/tracks"))
    d = tracks if isinstance(tracks, dict) else {t.slug: t for t in tracks}
    sec = d["mats"].chapters[0].sections[0]
    assert sec.kind == "drill"
    assert sec.url == "/mira?persona=mats-empirical-drill"
