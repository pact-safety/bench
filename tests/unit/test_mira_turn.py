"""Unit tests for the MIRA Phase 1a chat loop (app/services/mira.py).

No DB, no network: the loop is exercised against a fake repository and
either the deterministic offline provider (no key) or a fake provider that
captures the prompt it was handed. These are the spec §10 chat-loop tests.
"""

from __future__ import annotations

import pytest
pytestmark = pytest.mark.skip(reason="MIRA stubbed as coming soon")


import asyncio
from types import SimpleNamespace

from app.services import mira


def _drain(agen) -> list[dict]:
    async def run() -> list[dict]:
        return [ev async for ev in agen]

    return asyncio.run(run())


class _FakeRepo:
    """In-memory stand-in for MiraRepository — records appended turns."""

    def __init__(self, turns=None):
        self._turns = turns or []
        self.appended: list[dict] = []

    def list_turns(self, session_id, *, limit=200):
        return list(self._turns)

    def append_turn(self, *, session_id, role, content, **kw):
        self.appended.append({"role": role, "content": content, **kw})
        return f"turn-{len(self.appended)}"


class _FakeProvider:
    """Captures the (system, messages) it's streamed and emits scripted
    events. `model` attr present so mira's model-override branch runs."""

    name = "anthropic"

    def __init__(self, events):
        self._events = events
        self.model = "placeholder"
        self.captured: dict = {}

    async def stream(self, system, messages, tools=None, max_tokens=1024,
                     cache_breakpoint=True):
        self.captured["system"] = system
        self.captured["messages"] = messages
        self.captured["max_tokens"] = max_tokens
        for ev in self._events:
            if isinstance(ev, Exception):
                raise ev
            yield ev


def _turn(role, content):
    return SimpleNamespace(role=role, content=content)


# ---------------------------------------------------------------------------
# Offline path — never 500s, persists both turns
# ---------------------------------------------------------------------------


def test_offline_streams_and_persists_both_turns(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    repo = _FakeRepo()
    events = _drain(mira.mira_turn("sess", "what should I ship?", repo=repo))

    assert [e["type"] for e in events] == ["text", "finish"]
    # User turn persisted before streaming, assistant turn after.
    roles = [a["role"] for a in repo.appended]
    assert roles == ["user", "assistant"]
    assert repo.appended[0]["content"] == "what should I ship?"
    assert repo.appended[1]["content"]  # canned offline text
    assert repo.appended[1]["provider_used"] == "offline"
    assert "total" in repo.appended[1]["latency_ms"]


def test_runs_without_repo(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    events = _drain(mira.mira_turn("sess", "hi", repo=None))
    assert [e["type"] for e in events] == ["text", "finish"]


# ---------------------------------------------------------------------------
# System prompt carries the full Mira persona + the honest Phase-1a footer
# ---------------------------------------------------------------------------


def test_system_prompt_has_mira_persona_and_phase1a_footer(monkeypatch):
    fake = _FakeProvider([
        {"type": "text", "delta": "hey Li"},
        {"type": "finish", "finish_reason": "end_turn",
         "usage": {"input_tokens": 10, "output_tokens": 5}},
    ])
    monkeypatch.setattr(mira.llm_provider, "get_provider", lambda pref="anthropic": fake)
    monkeypatch.setattr(mira.spend_cap, "over_cap_for", lambda uid, svc: False)

    _drain(mira.mira_turn("sess", "hi", user_id="u1", repo=_FakeRepo(), model="claude-test"))

    system = fake.captured["system"]
    assert "You are Mira" in system          # persona from voices.get("mira")
    assert "ANTI-SYCOPHANCY" in system        # persona rule 11
    assert "first principles" in system       # Phase-1a base footer
    # The configured model is applied to the provider.
    assert fake.model == "claude-test"


# ---------------------------------------------------------------------------
# History: prior turns replayed chronologically, current message last, bounded
# ---------------------------------------------------------------------------


def test_history_is_replayed_then_current_message(monkeypatch):
    fake = _FakeProvider([
        {"type": "finish", "finish_reason": "end_turn",
         "usage": {"input_tokens": 1, "output_tokens": 1}},
    ])
    monkeypatch.setattr(mira.llm_provider, "get_provider", lambda pref="anthropic": fake)
    monkeypatch.setattr(mira.spend_cap, "over_cap_for", lambda uid, svc: False)

    repo = _FakeRepo(turns=[
        _turn("user", "first question"),
        _turn("assistant", "first answer"),
    ])
    _drain(mira.mira_turn("sess", "second question", user_id="u1", repo=repo))

    msgs = fake.captured["messages"]
    assert [(m.role, m.content) for m in msgs] == [
        ("user", "first question"),
        ("assistant", "first answer"),
        ("user", "second question"),
    ]


def test_history_bounded_by_token_budget(monkeypatch):
    fake = _FakeProvider([
        {"type": "finish", "finish_reason": "end_turn",
         "usage": {"input_tokens": 1, "output_tokens": 1}},
    ])
    monkeypatch.setattr(mira.llm_provider, "get_provider", lambda pref="anthropic": fake)
    monkeypatch.setattr(mira.spend_cap, "over_cap_for", lambda uid, svc: False)

    # 10 turns of ~400 chars (~100 tokens each); a 150-token budget should
    # admit only the most-recent prior turn plus the current message.
    big = "x" * 400
    repo = _FakeRepo(turns=[_turn("user", big) for _ in range(10)])
    _drain(mira.mira_turn(
        "sess", "now", user_id="u1", repo=repo,
        history_max_turns=20, history_token_budget=150,
    ))

    msgs = fake.captured["messages"]
    # Far fewer than 11 — the budget trimmed history; current msg is last.
    assert len(msgs) < 11
    assert msgs[-1].content == "now"


def test_tool_role_turns_are_skipped_in_history(monkeypatch):
    fake = _FakeProvider([
        {"type": "finish", "finish_reason": "end_turn",
         "usage": {"input_tokens": 1, "output_tokens": 1}},
    ])
    monkeypatch.setattr(mira.llm_provider, "get_provider", lambda pref="anthropic": fake)
    monkeypatch.setattr(mira.spend_cap, "over_cap_for", lambda uid, svc: False)

    repo = _FakeRepo(turns=[
        _turn("user", "q"),
        _turn("tool", "{tool output}"),
        _turn("assistant", "a"),
    ])
    _drain(mira.mira_turn("sess", "next", user_id="u1", repo=repo))

    roles = [m.role for m in fake.captured["messages"]]
    assert "tool" not in roles


# ---------------------------------------------------------------------------
# Spend cap: over-cap bypasses the API entirely
# ---------------------------------------------------------------------------


def test_over_cap_uses_offline_and_never_calls_provider(monkeypatch):
    monkeypatch.setattr(mira.spend_cap, "over_cap_for", lambda uid, svc: True)

    def _boom(pref="anthropic"):
        raise AssertionError("get_provider must not be called when over cap")

    monkeypatch.setattr(mira.llm_provider, "get_provider", _boom)

    repo = _FakeRepo()
    events = _drain(mira.mira_turn("sess", "hi", user_id="u1", repo=repo))
    assert events[-1]["finish_reason"] == "offline"
    assert repo.appended[-1]["provider_used"] == "offline"


def test_spend_cap_recorded_from_finish_usage(monkeypatch):
    fake = _FakeProvider([
        {"type": "text", "delta": "ok"},
        {"type": "finish", "finish_reason": "end_turn",
         "usage": {"input_tokens": 123, "output_tokens": 45}},
    ])
    monkeypatch.setattr(mira.llm_provider, "get_provider", lambda pref="anthropic": fake)
    monkeypatch.setattr(mira.spend_cap, "over_cap_for", lambda uid, svc: False)

    captured = {}

    def _record(uid, resp):
        captured["uid"] = uid
        captured["in"] = resp.usage.input_tokens
        captured["out"] = resp.usage.output_tokens

    monkeypatch.setattr(mira.spend_cap, "record_usage_for", _record)

    _drain(mira.mira_turn("sess", "hi", user_id="u9", repo=_FakeRepo()))
    assert captured == {"uid": "u9", "in": 123, "out": 45}


# ---------------------------------------------------------------------------
# Provider failure degrades to offline rather than propagating
# ---------------------------------------------------------------------------


class _StatefulRepo:
    """In-memory repo that actually accumulates turns, so a multi-turn
    loop sees its own growing history — the Phase-1a exit criterion."""

    def __init__(self):
        self.turns: list = []

    def list_turns(self, session_id, *, limit=200):
        return list(self.turns[-limit:])

    def append_turn(self, *, session_id, role, content, **kw):
        self.turns.append(SimpleNamespace(role=role, content=content))
        return f"turn-{len(self.turns)}"


def test_twenty_turn_conversation_offline_never_raises(monkeypatch):
    # Exit criterion (spec): a 20-turn conversation works end-to-end and the
    # offline fallback never errors. Drive 20 user turns through the loop on
    # the deterministic offline provider; each must stream text+finish and
    # leave a clean user/assistant pair in history.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    repo = _StatefulRepo()
    for i in range(20):
        events = _drain(mira.mira_turn(
            "sess", f"turn {i}", user_id="u1", repo=repo,
            history_max_turns=20, history_token_budget=6000,
        ))
        assert [e["type"] for e in events] == ["text", "finish"]

    # 20 user + 20 assistant turns recorded, interleaved.
    assert len(repo.turns) == 40
    assert [t.role for t in repo.turns[:4]] == ["user", "assistant", "user", "assistant"]


def test_provider_failure_falls_back_offline(monkeypatch):
    fake = _FakeProvider([RuntimeError("anthropic exploded")])
    monkeypatch.setattr(mira.llm_provider, "get_provider", lambda pref="anthropic": fake)
    monkeypatch.setattr(mira.spend_cap, "over_cap_for", lambda uid, svc: False)

    repo = _FakeRepo()
    events = _drain(mira.mira_turn("sess", "hi", user_id="u1", repo=repo))
    # Still a usable turn, and the persisted assistant turn is the offline one.
    assert [e["type"] for e in events] == ["text", "finish"]
    assert events[-1]["finish_reason"] == "offline"
    assert repo.appended[-1]["role"] == "assistant"
    assert repo.appended[-1]["provider_used"] == "offline"
