"""Text-to-speech for the recitation loop's audio-out (BEN-135 Part 1).

Renders a content item's text to speech so the operator can listen while
walking. Mirrors transcription.py's shape (same OPENAI_API_KEY, same httpx
call, same graceful-degradation contract): if the key is absent, every
entry point returns ``None`` and the UI hides the player — exactly like
review.py returns "skipped" without ANTHROPIC_API_KEY.

Audio is cached aggressively in Postgres (tts_cache, migration 018), keyed
on a hash of (content_id, version, voice, chunk_ix), so a chapter is
synthesised once. A chapter is well beyond a single TTS call, so text is
chunked at natural boundaries (headings/blank lines) and served as an
ordered playlist.

Access is OWNER-ONLY and enforced at the serve route: cache rows carry
user_id and are read WHERE user_id = <requester>. This module never serves;
it only renders + caches.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..repositories.content_repository import ContentRepository

_log = logging.getLogger(__name__)

# OpenAI's TTS endpoint (Groq proved unreliable). Everything is env-overridable
# so repointing at Groq or any OpenAI-compatible host is a pure env change
# (TTS_URL + TTS_MODEL + TTS_VOICE + the API key).
_TTS_URL = os.environ.get("TTS_URL", "https://api.openai.com/v1/audio/speech")
_TTS_MODEL = os.environ.get("TTS_MODEL", "gpt-4o-mini-tts")
DEFAULT_VOICE = os.environ.get("TTS_VOICE", "alloy")
_MIME = "audio/wav"
_HTTP_TIMEOUT_SECONDS = 60.0

# Conservative per-chunk ceiling — well under the provider's input limit, and
# small enough that a cache-miss on playback synthesises quickly.
_MAX_CHUNK_CHARS = 1800


def _api_key() -> str | None:
    # Prefer OPENAI_API_KEY (the default provider); fall back to GROQ_API_KEY
    # so a Groq-configured deployment keeps working if TTS_URL is repointed.
    return (
        os.environ.get("OPENAI_API_KEY", "").strip()
        or os.environ.get("GROQ_API_KEY", "").strip()
        or None
    )


def available() -> bool:
    """True if TTS can run at all (key present). The UI uses this to decide
    whether to show the audio player."""
    return _api_key() is not None


def cache_key(content_id: int, version: int, voice: str, chunk_ix: int) -> str:
    """Stable per-(content, version, voice, chunk) identity. Version is in the
    key so re-imported content re-renders instead of serving stale audio."""
    raw = f"{content_id}:{version}:{voice}:{chunk_ix}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def chunk_text(text: str, *, max_chars: int = _MAX_CHUNK_CHARS) -> list[str]:
    """Split text into TTS-sized chunks at natural boundaries.

    Prefers blank-line/paragraph breaks; only hard-splits a single oversized
    paragraph. Order is preserved so the playlist reads top-to-bottom.
    """
    text = (text or "").strip()
    if not text:
        return []
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    buf = ""
    for para in paras:
        if len(para) > max_chars:
            if buf:
                chunks.append(buf)
                buf = ""
            # Hard-split the oversized paragraph on sentence-ish boundaries.
            start = 0
            while start < len(para):
                chunks.append(para[start : start + max_chars])
                start += max_chars
            continue
        if buf and len(buf) + 2 + len(para) > max_chars:
            chunks.append(buf)
            buf = para
        else:
            buf = f"{buf}\n\n{para}" if buf else para
    if buf:
        chunks.append(buf)
    return chunks


def synthesize(text: str, voice: str = DEFAULT_VOICE) -> tuple[bytes, str] | None:
    """Render one chunk to audio bytes. Returns (bytes, mime) or None if the
    key is absent or the provider errors — callers degrade to "no audio",
    never raise into a request."""
    key = _api_key()
    if not key or not (text or "").strip():
        return None
    try:
        with httpx.Client(timeout=_HTTP_TIMEOUT_SECONDS) as client:
            resp = client.post(
                _TTS_URL,
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": _TTS_MODEL,
                    "voice": voice,
                    "input": text,
                    "response_format": "wav",
                },
            )
    except httpx.HTTPError as e:
        _log.warning("tts.http_failure exc=%s msg=%r", type(e).__name__, str(e)[:120])
        return None
    if resp.status_code >= 400:
        _log.warning("tts.upstream_error status=%d body=%r", resp.status_code, resp.text[:200])
        return None
    return resp.content, _MIME


def render_chunk(
    repo: "ContentRepository",
    *,
    user_id: str,
    content_id: int,
    version: int,
    chunk_ix: int,
    text: str,
    voice: str = DEFAULT_VOICE,
) -> bool:
    """Ensure one chunk is cached for this user. Cache hit → True immediately;
    miss → synthesise, store, True; unavailable/error → False. Idempotent."""
    key = cache_key(content_id, version, voice, chunk_ix)
    if repo.get_tts_chunk(user_id, key) is not None:
        return True
    rendered = synthesize(text, voice)
    if rendered is None:
        return False
    audio, mime = rendered
    repo.put_tts_chunk(
        user_id=user_id,
        cache_key=key,
        content_id=content_id,
        chunk_ix=chunk_ix,
        voice=voice,
        mime=mime,
        audio=audio,
    )
    return True


def manifest(
    repo: "ContentRepository",
    *,
    user_id: str,
    content_id: int,
    version: int,
    text: str,
    voice: str = DEFAULT_VOICE,
) -> dict | None:
    """Render (cache-aware) every chunk and return an ordered playlist the UI
    plays sequentially. None when TTS is unavailable — the player hides."""
    if not available():
        return None
    chunks = chunk_text(text)
    ready = 0
    for ix, chunk in enumerate(chunks):
        if render_chunk(
            repo,
            user_id=user_id,
            content_id=content_id,
            version=version,
            chunk_ix=ix,
            text=chunk,
            voice=voice,
        ):
            ready += 1
    if ready == 0:
        return None
    return {
        "voice": voice,
        "count": ready,
        "chunks": [
            {"ix": ix, "url": f"/content/{content_id}/audio/{ix}"}
            for ix in range(ready)
        ],
    }
