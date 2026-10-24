"""Unit tests for app.services.spend_cap.

Covers the wiring between the pure helpers in `security.py` (PR #32)
and the LLM-touching services. We don't re-test the helpers here —
that's `test_security.py`'s job; we test that `over_cap_for` returns
True/False from the right inputs and that `record_usage_for` actually
calls `record_usage` + persists.

The shim does a late import of `app.main._user_settings` /
`_save_user_settings` to avoid circular dependency. Tests monkeypatch
those module-level functions so we don't need a running app."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services import spend_cap, security


def _future_iso(hours: int = 6) -> str:
    """An open budget window closes this many hours out (UTC instant)."""
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


@pytest.fixture
def _isolate_settings(monkeypatch):
    """Wire `_try_load_settings` / `_try_save_settings` to a dict
    instead of `app.main`. Returns the dict so tests can assert on
    what got persisted."""
    state: dict[str, dict] = {}

    def fake_load(uid: str) -> dict:
        return state.setdefault(uid, {})

    def fake_save(uid: str, settings: dict) -> None:
        state[uid] = settings

    monkeypatch.setattr(spend_cap, "_try_load_settings", fake_load)
    monkeypatch.setattr(spend_cap, "_try_save_settings", fake_save)
    return state


# ---------- over_cap_for ----------------------------------------------------


def test_over_cap_no_user_id_is_no_cap(_isolate_settings):
    """`user_id=None` is the contract for "no cap, don't record" —
    used by tests, background jobs, anything not on a user's behalf."""
    assert spend_cap.over_cap_for(None, "hint") is False


def test_over_cap_empty_settings_returns_false(_isolate_settings):
    """A fresh user has no usage; not over cap."""
    assert spend_cap.over_cap_for("user-a", "hint") is False


def test_over_cap_true_when_settings_at_cap(_isolate_settings):
    """When today's usage equals the cap, `over_cap_for` returns True
    and the service-level caller is supposed to use the offline fallback."""
    _isolate_settings["user-a"] = {
        "anthropic_today": {"resets_at": _future_iso(),
                            "tokens": security.DEFAULT_DAILY_TOKEN_CAP},
    }
    assert spend_cap.over_cap_for("user-a", "hint") is True


def test_over_cap_resets_on_day_rollover(_isolate_settings):
    """Yesterday's tokens don't carry over — once a budget window has
    closed, the security helpers read it as empty. `over_cap_for` must
    reflect that."""
    _isolate_settings["user-a"] = {
        "anthropic_today": {"resets_at": _future_iso(-1),  # window already closed
                            "tokens": security.DEFAULT_DAILY_TOKEN_CAP * 10},
    }
    assert spend_cap.over_cap_for("user-a", "hint") is False


def test_over_cap_fails_open_when_settings_unloadable(monkeypatch):
    """A transient DB issue must NOT turn every hint into an over-cap
    response — the cap is a circuit breaker, not a fence."""
    monkeypatch.setattr(spend_cap, "_try_load_settings", lambda _uid: None)
    assert spend_cap.over_cap_for("user-a", "hint") is False


# ---------- record_usage_for ------------------------------------------------


def test_record_usage_no_user_id_is_noop(_isolate_settings):
    """`user_id=None` → bookkeeping is skipped (tests / background)."""
    resp = SimpleNamespace(usage=SimpleNamespace(input_tokens=100, output_tokens=200))
    spend_cap.record_usage_for(None, resp)
    assert _isolate_settings == {}


def test_record_usage_no_usage_attr_is_silent(_isolate_settings):
    """Some Anthropic mocks / old responses don't have `.usage` —
    silently return without raising."""
    resp = SimpleNamespace(content=[])  # no `usage`
    spend_cap.record_usage_for("user-a", resp)
    # Even if a new user dict was created, no anthropic_today key on it.
    assert "anthropic_today" not in _isolate_settings.get("user-a", {})


def test_record_usage_bumps_counter(_isolate_settings):
    resp = SimpleNamespace(usage=SimpleNamespace(input_tokens=100, output_tokens=200))
    spend_cap.record_usage_for("user-a", resp)
    stored = _isolate_settings["user-a"]["anthropic_today"]
    assert datetime.fromisoformat(stored["resets_at"]) > datetime.now(timezone.utc)
    assert stored["tokens"] == 300


def test_record_usage_accumulates_across_calls(_isolate_settings):
    """Two calls in the same day → counter is the sum."""
    resp1 = SimpleNamespace(usage=SimpleNamespace(input_tokens=50, output_tokens=100))
    resp2 = SimpleNamespace(usage=SimpleNamespace(input_tokens=80, output_tokens=120))
    spend_cap.record_usage_for("user-a", resp1)
    spend_cap.record_usage_for("user-a", resp2)
    assert _isolate_settings["user-a"]["anthropic_today"]["tokens"] == 350


def test_record_usage_handles_missing_token_fields(_isolate_settings):
    """If `.usage` exists but has 0 / None token counts, no row update."""
    resp = SimpleNamespace(usage=SimpleNamespace(input_tokens=0, output_tokens=0))
    spend_cap.record_usage_for("user-a", resp)
    assert "anthropic_today" not in _isolate_settings.get("user-a", {})


def test_record_usage_swallows_exceptions(monkeypatch):
    """Persistence failure mustn't break the user's response. Recording
    is bookkeeping, not critical-path."""
    monkeypatch.setattr(spend_cap, "_try_load_settings", lambda _uid: {"x": "y"})
    def _boom(_uid, _settings):
        raise RuntimeError("simulated DB outage")
    monkeypatch.setattr(spend_cap, "_try_save_settings", _boom)
    resp = SimpleNamespace(usage=SimpleNamespace(input_tokens=100, output_tokens=200))
    # Must not raise.
    spend_cap.record_usage_for("user-a", resp)


# ---------- service-integration smoke ---------------------------------------


def test_hint_service_uses_cap_check(mock_anthropic, monkeypatch, _isolate_settings):
    """End-to-end: when a user is over cap, `hints.get_hint` returns
    the deterministic fallback instead of calling the (mocked) API.
    Regression guard against losing the cap-check wiring at the
    `if not over_cap_for(...)` site in `hints.py`."""
    from app.services import hints
    from app.models import Problem

    _isolate_settings["user-a"] = {
        "anthropic_today": {"resets_at": _future_iso(),
                            "tokens": security.DEFAULT_DAILY_TOKEN_CAP + 1},
    }
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    p = Problem(
        id=1, slug="x", title="x", difficulty="easy", time_bucket=30,
        problem_type="code_compose", is_warmup=False,
        content_md="...", version=1, em_mode="full", em_prompts={},
        references=[],
    )
    result = hints.get_hint(
        p, phase="plan", current_notes="", code=None,
        count_so_far=0, user_id="user-a",
    )
    # Over-cap path → method=="fallback", no API hit. Tier label may
    # vary (depends on count_so_far) so we don't assert on that.
    assert result["method"] == "fallback"
    # Critically: the Anthropic mock recorded zero calls — we didn't
    # spend budget on a user already past their cap.
    assert mock_anthropic.calls == []


def test_hint_service_records_usage_on_success(mock_anthropic, monkeypatch, _isolate_settings):
    """End-to-end: a successful hint call records tokens against the
    user's counter."""
    from app.services import hints
    from app.models import Problem

    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    mock_anthropic.queue('{"hint": "subtract max(x) before exp"}')

    p = Problem(
        id=1, slug="x", title="x", difficulty="easy", time_bucket=30,
        problem_type="code_compose", is_warmup=False,
        content_md="...", version=1, em_mode="full", em_prompts={},
        references=[],
    )
    result = hints.get_hint(
        p, phase="plan", current_notes="", code=None,
        count_so_far=0, user_id="user-a",
    )
    assert result["method"] == "claude"
    # FakeAnthropicClient's _FakeResponse defaults to 100+200=300 tokens.
    assert _isolate_settings["user-a"]["anthropic_today"]["tokens"] == 300


# ---------------------------------------------------------------------------
# BEN-144 follow-up: the custody ledger fires from record_usage_for
# ---------------------------------------------------------------------------


def _resp(in_tokens=100, out_tokens=40, model="claude-sonnet-x"):
    return SimpleNamespace(
        usage=SimpleNamespace(input_tokens=in_tokens, output_tokens=out_tokens),
        model=model,
    )


def test_record_usage_with_service_writes_ledger_line(_isolate_settings, monkeypatch):
    from app.services import audit_log, llm_keys

    lines = []
    monkeypatch.setattr(audit_log, "record", lambda **kw: lines.append(kw))
    monkeypatch.setattr(llm_keys, "has_user_key", lambda uid: False)

    spend_cap.record_usage_for("uid-1", _resp(), service="hint")

    assert len(lines) == 1
    entry = lines[0]
    assert entry["capability"] == "hint"
    assert entry["model"] == "claude-sonnet-x"
    assert entry["payload"] == {"wallet": "house"}
    assert entry["usage"] == {"input_tokens": 100, "output_tokens": 40}


def test_record_usage_ledger_marks_byo_wallet(_isolate_settings, monkeypatch):
    from app.services import audit_log, llm_keys

    lines = []
    monkeypatch.setattr(audit_log, "record", lambda **kw: lines.append(kw))
    monkeypatch.setattr(llm_keys, "has_user_key", lambda uid: True)

    spend_cap.record_usage_for("uid-1", _resp(), service="review")

    assert lines[0]["payload"] == {"wallet": "user"}


def test_record_usage_without_service_writes_no_ledger_line(_isolate_settings, monkeypatch):
    """service=None = the caller owns its own custody line (mira's
    _audit_turn). No line here, or mira turns would double-ledger."""
    from app.services import audit_log

    lines = []
    monkeypatch.setattr(audit_log, "record", lambda **kw: lines.append(kw))

    spend_cap.record_usage_for("uid-1", _resp())

    assert lines == []


def test_record_usage_ledgers_zero_token_calls(_isolate_settings, monkeypatch):
    """Zero-token responses bail out of counter bumping but MUST still
    reach the ledger — they're exactly what an audit should surface."""
    from app.services import audit_log, llm_keys

    lines = []
    monkeypatch.setattr(audit_log, "record", lambda **kw: lines.append(kw))
    monkeypatch.setattr(llm_keys, "has_user_key", lambda uid: False)

    spend_cap.record_usage_for("uid-1", _resp(0, 0), service="hint")

    assert len(lines) == 1
    assert lines[0]["usage"] == {"input_tokens": 0, "output_tokens": 0}


def test_record_usage_survives_ledger_failure(_isolate_settings, monkeypatch):
    """A broken ledger must not break bookkeeping or the response."""
    from app.services import audit_log

    def _boom(**kw):
        raise OSError("disk full")

    monkeypatch.setattr(audit_log, "record", _boom)
    spend_cap.record_usage_for("uid-1", _resp(), service="hint")  # no raise
    # Counter still bumped despite the ledger failure.
    assert security.get_today_usage(_isolate_settings["uid-1"]) == 140


def test_every_llm_service_passes_service_to_the_ledger():
    """Grep-level hygiene: any record_usage_for call site outside
    spend_cap/mira must pass service= (mira owns its own custody
    line). Catches the next service added without ledger wiring."""
    import re
    from pathlib import Path

    services_dir = Path(spend_cap.__file__).parent
    offenders = []
    for f in services_dir.glob("*.py"):
        if f.name in ("spend_cap.py", "mira.py"):
            continue
        for i, line in enumerate(f.read_text().splitlines(), 1):
            if "record_usage_for(" in line and "service=" not in line and not line.strip().startswith("#"):
                offenders.append(f"{f.name}:{i}")
    assert not offenders, f"record_usage_for without service=: {offenders}"
