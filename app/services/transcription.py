"""Server-side audio transcription via Groq's Whisper-Large-v3-Turbo.

Why this exists
  Chrome's Web Speech API ("client-side" recognition) actually streams
  audio to `speech.googleapis.com`, which is unreachable in many
  privacy-extension / DNS-filtered browser environments. Operator's
  2026-05-17 trace (issue #80 → #88 → #90) showed deterministic
  `error: network` failures despite mic capture working. The fix is
  architectural: capture audio locally with MediaRecorder, ship the
  blob to OUR backend, transcribe via a server-side API. Audio never
  touches Google.

Provider
  Groq's Whisper-Large-v3-Turbo at the OpenAI-compatible endpoint
  `/openai/v1/audio/transcriptions`. ~200-400ms per utterance, ~$0.001
  per minute. The API shape is OpenAI's, so a future fallback to
  OpenAI is a base-URL change (set TRANSCRIBE_URL=
  https://api.openai.com/v1/audio/transcriptions and provide
  OPENAI_API_KEY in place of GROQ_API_KEY).

Spend cap
  Per-user daily seconds counter in `user_settings.transcription_today`.
  Parallel to the Anthropic token counter (`anthropic_today`) but in
  units of audio-seconds, not tokens. Default ceiling: 1800 seconds
  (30 min) per user per day. The cap is a circuit breaker against a
  runaway loop, not a hard cost ceiling — at $0.001/min, the worst
  case daily spend per user is ~$0.03 anyway.

Limits
  - Max audio payload: 25 MB (matches Whisper API's documented file
    size limit).
  - HTTP timeout: 30 seconds.
"""

from __future__ import annotations

import logging
import os
from datetime import date
from typing import Any

import httpx


_log = logging.getLogger(__name__)


# Endpoint URL is env-overridable so swapping providers (or pointing
# at a mock server in integration tests) requires zero code change.
# Default is OpenAI (Groq proved unreliable); both are OpenAI-compatible, so
# repointing at Groq or any compatible host is a pure env change. whisper-1
# is used because — unlike gpt-4o-transcribe — it supports
# response_format=verbose_json, which this module relies on for `duration`.
_TRANSCRIBE_URL = os.environ.get(
    "TRANSCRIBE_URL",
    "https://api.openai.com/v1/audio/transcriptions",
)
_TRANSCRIBE_MODEL = os.environ.get(
    "TRANSCRIBE_MODEL",
    "whisper-1",
)
# Whisper API's documented per-file ceiling; we enforce client-side
# too via the MediaRecorder's max session length, but defense in depth.
MAX_AUDIO_BYTES = 25 * 1024 * 1024  # 25 MB
HTTP_TIMEOUT_SECONDS = 30.0

# Daily per-user transcription seconds cap. 1800s = 30 min, generous
# for legitimate dictation but tight enough to catch a runaway loop.
DEFAULT_DAILY_TRANSCRIBE_SECONDS = int(
    os.environ.get("TRANSCRIBE_DAILY_SECONDS_CAP", "1800")
)


class TranscriptionError(Exception):
    """Raised on any transcription failure. Callers translate to a
    user-facing 4xx/5xx and log full details server-side."""


def _api_key() -> str:
    # Prefer OPENAI_API_KEY (the new default provider); fall back to
    # GROQ_API_KEY so a Groq-configured deployment keeps working if someone
    # repoints TRANSCRIBE_URL back.
    key = (
        os.environ.get("OPENAI_API_KEY", "").strip()
        or os.environ.get("GROQ_API_KEY", "").strip()
    )
    if not key:
        raise TranscriptionError("no audio API key set (OPENAI_API_KEY) on server")
    return key


def transcribe(
    *,
    audio_bytes: bytes,
    filename: str,
    content_type: str,
) -> dict[str, Any]:
    """POST `audio_bytes` to the configured transcription endpoint and
    return `{"text": "...", "duration_seconds": <float>}`.

    Uses `response_format=verbose_json` so the upstream's authoritative
    `duration` field comes back; we record that into the spend cap
    rather than trusting client-supplied timing.

    Raises `TranscriptionError` on any failure path."""
    if len(audio_bytes) == 0:
        raise TranscriptionError("empty audio payload")
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise TranscriptionError(
            f"audio payload exceeds {MAX_AUDIO_BYTES // (1024 * 1024)} MB limit "
            f"(got {len(audio_bytes)} bytes)"
        )
    key = _api_key()

    try:
        with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as client:
            resp = client.post(
                _TRANSCRIBE_URL,
                headers={"Authorization": f"Bearer {key}"},
                files={"file": (filename, audio_bytes, content_type)},
                data={
                    "model": _TRANSCRIBE_MODEL,
                    "response_format": "verbose_json",
                },
            )
    except httpx.HTTPError as e:
        _log.warning(
            "transcribe.http_failure exc_type=%s msg=%r",
            type(e).__name__,
            str(e)[:120],
        )
        raise TranscriptionError(f"upstream connection failed: {e}") from e

    if resp.status_code >= 400:
        try:
            body = resp.json()
        except Exception:
            body = {"raw": resp.text[:240]}
        _log.warning(
            "transcribe.upstream_error status=%d body=%r",
            resp.status_code,
            body,
        )
        raise TranscriptionError(
            f"upstream returned HTTP {resp.status_code}: {body}"
        )

    try:
        data = resp.json()
    except Exception as e:
        raise TranscriptionError(f"upstream returned non-JSON: {e}") from e

    text = (data.get("text") or "").strip()
    # `duration` is present on verbose_json responses; clamp negative
    # values defensively (shouldn't happen but parsing upstream output).
    duration_raw = data.get("duration")
    try:
        duration_seconds = max(0.0, float(duration_raw)) if duration_raw is not None else 0.0
    except (TypeError, ValueError):
        duration_seconds = 0.0

    _log.info(
        "transcribe.success bytes=%d text_len=%d duration_s=%.2f",
        len(audio_bytes),
        len(text),
        duration_seconds,
    )
    return {"text": text, "duration_seconds": duration_seconds}


# --- Spend cap (parallel to spend_cap.py's Anthropic counter) ----------------


def _today_iso() -> str:
    return date.today().isoformat()


def _get_today_seconds(settings: dict[str, Any]) -> int:
    """Today's accumulated transcription seconds from user settings.
    Returns 0 if the stored counter is from a previous day."""
    state = (settings or {}).get("transcription_today") or {}
    if state.get("date") != _today_iso():
        return 0
    try:
        return int(state.get("seconds", 0))
    except (TypeError, ValueError):
        return 0


def over_cap_for(
    user_id: str | None,
    *,
    cap: int | None = None,
) -> bool:
    """Pre-call gate. True if the user is already at/over today's
    transcription-seconds budget; routes should return 429 in that case.

    Fails open: a transient settings-load failure must not block
    legitimate dictation, so we return False if the read fails."""
    if not user_id:
        return False
    settings = _try_load_settings(user_id)
    if settings is None:
        return False
    limit = cap if cap is not None else DEFAULT_DAILY_TRANSCRIBE_SECONDS
    used = _get_today_seconds(settings)
    return used >= limit


def record_seconds_for(user_id: str | None, seconds: float | int) -> None:
    """Post-call bookkeeping. Adds `seconds` to today's counter.

    Wrapped: bookkeeping failures must not break the user's response."""
    if not user_id:
        return
    try:
        add = max(0, int(round(float(seconds))))
    except (TypeError, ValueError):
        return
    if add == 0:
        return
    try:
        settings = _try_load_settings(user_id)
        if settings is None:
            return
        cur = _get_today_seconds(settings)
        settings["transcription_today"] = {
            "date": _today_iso(),
            "seconds": cur + add,
        }
        _try_save_settings(user_id, settings)
    except Exception as e:
        _log.warning("transcription cap record failed: %s", e)


# Late-imported settings accessors — same pattern as spend_cap.py to
# avoid the circular import with app.main.


def _try_load_settings(user_id: str) -> dict | None:
    try:
        from ..main import _user_settings  # type: ignore[attr-defined]
        return _user_settings(user_id)
    except Exception as e:
        _log.warning(
            "transcription cap: could not load settings for %s: %s",
            user_id,
            e,
        )
        return None


def _try_save_settings(user_id: str, settings: dict) -> None:
    try:
        from ..main import _save_user_settings  # type: ignore[attr-defined]
        _save_user_settings(user_id, settings)
    except Exception as e:
        _log.warning(
            "transcription cap: could not save settings for %s: %s",
            user_id,
            e,
        )
