"""Unit tests for `app.services.transcription`.

Covers the upstream-call shape (mocking httpx), error translation,
and the daily-seconds spend cap.

No live Groq calls — all upstream interactions are mocked.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import httpx
import pytest

import app.services.transcription as t


@pytest.fixture(autouse=True)
def _clear_openai_key(monkeypatch):
    """These tests exercise the Groq-compatible request path via GROQ_API_KEY.
    OPENAI_API_KEY is now the preferred key, so clear it here to keep the
    fallback deterministic regardless of the CI environment."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


# --- transcribe() upstream-call shape ----------------------------------------


def _ok_response(*, text: str = "hello world", duration: float = 3.5) -> MagicMock:
    """Build a fake httpx.Response matching Groq's verbose_json shape."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "task": "transcribe",
        "language": "english",
        "duration": duration,
        "text": text,
    }
    return resp


def _err_response(*, status: int, body: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    if body is not None:
        resp.json.return_value = body
        resp.text = ""
    else:
        resp.json.side_effect = ValueError("not json")
        resp.text = "<html>upstream error page</html>"
    return resp


@pytest.fixture
def fake_client():
    """Patch httpx.Client to a MagicMock with a context-manager shape."""
    with patch.object(t.httpx, "Client") as ctor:
        client = MagicMock()
        ctor.return_value.__enter__.return_value = client
        yield client


def test_transcribe_success_returns_text_and_duration(monkeypatch, fake_client):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    fake_client.post.return_value = _ok_response(text="hello, world.", duration=2.7)

    result = t.transcribe(
        audio_bytes=b"\x00\x01\x02" * 200,
        filename="audio.webm",
        content_type="audio/webm",
    )

    assert result == {"text": "hello, world.", "duration_seconds": 2.7}
    # Verify the upstream call was shaped correctly.
    args, kwargs = fake_client.post.call_args
    assert args[0] == t._TRANSCRIBE_URL
    assert kwargs["headers"] == {"Authorization": "Bearer gsk_test"}
    assert kwargs["data"]["model"] == t._TRANSCRIBE_MODEL
    assert kwargs["data"]["response_format"] == "verbose_json"
    # Multipart file field present.
    assert "file" in kwargs["files"]


def test_transcribe_strips_whitespace_and_clamps_negative_duration(monkeypatch, fake_client):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"text": "   spaced out   ", "duration": -1.0}
    fake_client.post.return_value = resp

    result = t.transcribe(
        audio_bytes=b"x" * 100,
        filename="a.webm",
        content_type="audio/webm",
    )
    assert result["text"] == "spaced out"
    assert result["duration_seconds"] == 0.0


def test_transcribe_missing_duration_field_treated_as_zero(monkeypatch, fake_client):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"text": "ok"}  # no duration key
    fake_client.post.return_value = resp

    result = t.transcribe(
        audio_bytes=b"x" * 100, filename="a.webm", content_type="audio/webm"
    )
    assert result["duration_seconds"] == 0.0


def test_transcribe_rejects_empty_payload():
    with pytest.raises(t.TranscriptionError, match="empty"):
        t.transcribe(audio_bytes=b"", filename="a.webm", content_type="audio/webm")


def test_transcribe_rejects_oversized_payload(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    too_big = b"\x00" * (t.MAX_AUDIO_BYTES + 1)
    with pytest.raises(t.TranscriptionError, match="exceeds"):
        t.transcribe(audio_bytes=too_big, filename="big.webm", content_type="audio/webm")


def test_transcribe_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(t.TranscriptionError, match="OPENAI_API_KEY"):
        t.transcribe(
            audio_bytes=b"x" * 100, filename="a.webm", content_type="audio/webm"
        )


def test_transcribe_translates_upstream_4xx_to_TranscriptionError(monkeypatch, fake_client):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    fake_client.post.return_value = _err_response(
        status=413, body={"error": {"message": "file too large"}}
    )
    with pytest.raises(t.TranscriptionError, match="HTTP 413"):
        t.transcribe(
            audio_bytes=b"x" * 100, filename="a.webm", content_type="audio/webm"
        )


def test_transcribe_translates_upstream_5xx_to_TranscriptionError(monkeypatch, fake_client):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    fake_client.post.return_value = _err_response(status=503, body=None)
    with pytest.raises(t.TranscriptionError, match="HTTP 503"):
        t.transcribe(
            audio_bytes=b"x" * 100, filename="a.webm", content_type="audio/webm"
        )


def test_transcribe_translates_httpx_error_to_TranscriptionError(monkeypatch, fake_client):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    fake_client.post.side_effect = httpx.ConnectError("dns lookup failed")
    with pytest.raises(t.TranscriptionError, match="upstream connection failed"):
        t.transcribe(
            audio_bytes=b"x" * 100, filename="a.webm", content_type="audio/webm"
        )


def test_transcribe_handles_non_json_response(monkeypatch, fake_client):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    resp = MagicMock()
    resp.status_code = 200
    resp.json.side_effect = ValueError("expecting value")
    fake_client.post.return_value = resp
    with pytest.raises(t.TranscriptionError, match="non-JSON"):
        t.transcribe(
            audio_bytes=b"x" * 100, filename="a.webm", content_type="audio/webm"
        )


# --- Spend cap (transcription_today counter) ---------------------------------


def _settings(*, used_today: int = 0, used_yesterday: int = 0) -> dict:
    """Build a `user_settings` dict with the given transcription state."""
    state = {}
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    if used_today:
        state = {"date": today, "seconds": used_today}
    elif used_yesterday:
        state = {"date": yesterday, "seconds": used_yesterday}
    if state:
        return {"transcription_today": state}
    return {}


def test_get_today_seconds_returns_zero_when_no_state():
    assert t._get_today_seconds({}) == 0


def test_get_today_seconds_returns_zero_on_day_rollover():
    """Yesterday's count must NOT count toward today's cap."""
    settings = _settings(used_yesterday=999999)
    assert t._get_today_seconds(settings) == 0


def test_get_today_seconds_returns_today_count():
    settings = _settings(used_today=500)
    assert t._get_today_seconds(settings) == 500


def test_over_cap_for_no_user_id_returns_false():
    """user_id=None means background job; never blocked."""
    assert t.over_cap_for(None) is False


def test_over_cap_for_under_budget_returns_false(monkeypatch):
    settings = _settings(used_today=100)
    monkeypatch.setattr(t, "_try_load_settings", lambda uid: settings)
    assert t.over_cap_for("u1") is False


def test_over_cap_for_at_budget_returns_true(monkeypatch):
    settings = _settings(used_today=t.DEFAULT_DAILY_TRANSCRIBE_SECONDS)
    monkeypatch.setattr(t, "_try_load_settings", lambda uid: settings)
    assert t.over_cap_for("u1") is True


def test_over_cap_for_settings_load_failure_fails_open(monkeypatch):
    """Transient DB issue must not block dictation."""
    monkeypatch.setattr(t, "_try_load_settings", lambda uid: None)
    assert t.over_cap_for("u1") is False


def test_over_cap_for_honors_custom_cap(monkeypatch):
    settings = _settings(used_today=50)
    monkeypatch.setattr(t, "_try_load_settings", lambda uid: settings)
    assert t.over_cap_for("u1", cap=30) is True
    assert t.over_cap_for("u1", cap=1000) is False


def test_record_seconds_for_no_user_id_is_noop():
    # No exception; nothing happens.
    t.record_seconds_for(None, 5)
    t.record_seconds_for("", 5)


def test_record_seconds_for_zero_seconds_is_noop(monkeypatch):
    """Sub-second blobs (durations < 0.5 round to 0) shouldn't write."""
    write_mock = MagicMock()
    monkeypatch.setattr(t, "_try_load_settings", lambda uid: {})
    monkeypatch.setattr(t, "_try_save_settings", write_mock)
    t.record_seconds_for("u1", 0.0)
    t.record_seconds_for("u1", 0.3)  # rounds to 0
    assert write_mock.call_count == 0


def test_record_seconds_for_accumulates_across_calls(monkeypatch):
    """Two calls in the same day should sum, not overwrite."""
    store = {"transcription_today": {"date": date.today().isoformat(), "seconds": 100}}
    monkeypatch.setattr(t, "_try_load_settings", lambda uid: store)
    monkeypatch.setattr(t, "_try_save_settings", lambda uid, s: None)
    t.record_seconds_for("u1", 30)
    assert store["transcription_today"]["seconds"] == 130
    t.record_seconds_for("u1", 70)
    assert store["transcription_today"]["seconds"] == 200


def test_record_seconds_for_resets_on_day_rollover(monkeypatch):
    """If the stored counter is from yesterday, today starts fresh."""
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    store = {"transcription_today": {"date": yesterday, "seconds": 1800}}
    monkeypatch.setattr(t, "_try_load_settings", lambda uid: store)
    monkeypatch.setattr(t, "_try_save_settings", lambda uid, s: None)
    t.record_seconds_for("u1", 25)
    assert store["transcription_today"]["date"] == date.today().isoformat()
    assert store["transcription_today"]["seconds"] == 25
