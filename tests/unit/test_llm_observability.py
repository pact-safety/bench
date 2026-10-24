"""BEN-145 — LLM attribution in Sentry.

These helpers run on every LLM call and inside request middleware, so the
property that matters most is that they cannot break anything. Every test
here is really asking "does this stay out of the way when it fails?"
"""

from __future__ import annotations

import pytest

from app.observability import note_llm_fallback, note_llm_usage, set_request_user


class _Usage:
    def __init__(self, i, o):
        self.input_tokens = i
        self.output_tokens = o


class _Resp:
    def __init__(self, model="claude-sonnet-4-5", i=100, o=200):
        self.model = model
        self.usage = _Usage(i, o)


def test_note_llm_usage_is_silent_without_sentry():
    """No DSN configured is the normal case in dev and in CI."""
    note_llm_usage(_Resp())


def test_note_llm_usage_tolerates_a_response_with_no_usage():
    """Mock responses in tests, and streamed responses, may not carry it."""

    class _Bare:
        pass

    note_llm_usage(_Bare())


def test_note_llm_usage_tolerates_garbage():
    """It is handed whatever the provider SDK returned. It must never be the
    reason a user's hint fails to render."""
    for junk in (None, 0, "", [], object()):
        note_llm_usage(junk)


def test_note_llm_usage_survives_a_raising_response():
    """A property that raises on access is the nastiest realistic case."""

    class _Exploding:
        @property
        def usage(self):
            raise RuntimeError("boom")

    note_llm_usage(_Exploding())


def test_note_llm_fallback_is_safe():
    note_llm_fallback("hint", "over_cap")
    note_llm_fallback("", "")


def test_set_request_user_accepts_none():
    """Anonymous requests hit this on every page of the landing page."""
    set_request_user(None)
    set_request_user("00000000-0000-4000-8000-000000000001")


def test_set_request_user_does_not_forward_email():
    """send_default_pii=False is deliberate; this signature must not be the
    thing that quietly undoes it."""
    import inspect

    sig = inspect.signature(set_request_user)
    assert "email" in sig.parameters, "signature kept for call-site clarity"
    src = inspect.getsource(set_request_user)
    body = src.split('"""', 2)[-1]
    assert "email" not in body, (
        "set_request_user must not pass email to Sentry — "
        "send_default_pii=False exists on purpose"
    )


def test_init_sentry_no_longer_hardcodes_the_operator(monkeypatch):
    """REGRESSION: init_sentry used to stamp every event with a fixed
    operator identity, filing alpha users' errors under the operator.

    Asserted behaviourally — an earlier version of this test scraped the
    source for "set_user(", which trips over the comment that explains the
    bug. Comments are not behaviour."""
    import sys
    import types

    from app import observability

    calls = []
    fake = types.ModuleType("sentry_sdk")
    fake.init = lambda **kw: calls.append(("init", kw))
    fake.set_user = lambda v: calls.append(("set_user", v))
    fake.integrations = types.ModuleType("sentry_sdk.integrations")

    class _Stub:  # the real integrations take kwargs
        def __init__(self, **kw):
            self.kw = kw

    for name, attrs in (
        ("sentry_sdk.integrations.fastapi", {"FastApiIntegration": _Stub}),
        ("sentry_sdk.integrations.starlette", {"StarletteIntegration": _Stub}),
    ):
        mod = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(mod, k, v)
        monkeypatch.setitem(sys.modules, name, mod)
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake)
    monkeypatch.setenv("SENTRY_DSN", "https://example@example.ingest.sentry.io/1")

    assert observability.init_sentry() is True
    assert any(c[0] == "init" for c in calls), "Sentry should still be initialised"
    assert not any(c[0] == "set_user" for c in calls), (
        "init_sentry must not stamp a global user — scoping belongs in the "
        "request path, or every alpha user's errors file under the operator"
    )
