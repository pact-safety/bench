"""BEN-135 audio-out: TTS caching, graceful degradation, owner-only serving."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services import tts


# ---- graceful degradation + chunking ---------------------------------------


def test_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert tts.available() is False
    assert tts.synthesize("hello") is None  # no key → None, never raises


def test_manifest_none_without_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    repo = MagicMock()
    assert tts.manifest(repo, user_id="u", content_id=1, version=1, text="x") is None


def test_chunk_text_splits_on_paragraphs_preserving_order():
    text = "First para.\n\nSecond para.\n\nThird para."
    chunks = tts.chunk_text(text, max_chars=20)
    assert chunks == ["First para.", "Second para.", "Third para."]


def test_chunk_text_hard_splits_oversized_paragraph():
    chunks = tts.chunk_text("x" * 50, max_chars=20)
    assert len(chunks) == 3 and "".join(chunks) == "x" * 50


def test_cache_key_version_sensitive():
    a = tts.cache_key(1, 1, "V", 0)
    b = tts.cache_key(1, 2, "V", 0)  # different version → different key
    assert a != b and len(a) == 64


# ---- cache hit / miss ------------------------------------------------------


def test_render_chunk_cache_hit_skips_synthesis(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    repo = MagicMock()
    repo.get_tts_chunk.return_value = {"mime": "audio/wav", "audio": b"cached"}
    with patch.object(tts, "synthesize") as synth:
        ok = tts.render_chunk(
            repo, user_id="u", content_id=1, version=1, chunk_ix=0, text="hi"
        )
    assert ok is True
    synth.assert_not_called()        # cache hit → no API call
    repo.put_tts_chunk.assert_not_called()


def test_render_chunk_cache_miss_synthesizes_and_stores(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    repo = MagicMock()
    repo.get_tts_chunk.return_value = None  # miss
    with patch.object(tts, "synthesize", return_value=(b"WAVDATA", "audio/wav")):
        ok = tts.render_chunk(
            repo, user_id="u", content_id=7, version=2, chunk_ix=3, text="hello"
        )
    assert ok is True
    repo.put_tts_chunk.assert_called_once()
    kw = repo.put_tts_chunk.call_args.kwargs
    assert kw["audio"] == b"WAVDATA" and kw["content_id"] == 7 and kw["user_id"] == "u"


# ---- owner-only serving (route) --------------------------------------------

_ADMIN = "11111111-1111-1111-1111-111111111111"
_OTHER = "22222222-2222-2222-2222-222222222222"


def _client(monkeypatch, uid):
    monkeypatch.setenv("LIS_ADMIN_USER_IDS", _ADMIN)
    import app.main as m
    import app.auth as auth_module
    from app.auth import UserSession
    from fastapi.testclient import TestClient

    monkeypatch.setattr(m, "_user_settings", lambda _u: {})
    monkeypatch.setattr(
        auth_module, "parse_access_token",
        lambda _t: UserSession(user_id=uid, email="u@x.com",
                               expires_at=2**31 - 1, raw_access_token="x"),
    )
    c = TestClient(m.app)
    c.cookies.set("sb-access-token", "x.y.z")
    return c, m


def test_audio_chunk_unauthenticated_is_denied(monkeypatch):
    """No session → the middleware bounces to /login before the handler; the
    audio never reaches an anonymous caller."""
    import app.main as m
    from fastapi.testclient import TestClient

    c = TestClient(m.app, follow_redirects=False)  # no cookie
    r = c.get("/content/1/audio/0")
    assert r.status_code in (302, 303, 401, 403)
    assert r.status_code != 200


def test_audio_chunk_owner_only_other_user_gets_404(monkeypatch):
    """User B requesting content only User A rendered gets 404 — the cache read
    is scoped WHERE user_id = requester, so B never sees A's audio."""
    c, m = _client(monkeypatch, _OTHER)
    item = MagicMock(version=1)
    with patch.object(m.content_repo, "get_by_id", return_value=item), \
         patch.object(m.content_repo, "get_tts_chunk", return_value=None) as g:
        r = c.get("/content/1/audio/0")
    assert r.status_code == 404
    # the lookup was scoped to the requesting (other) user
    assert g.call_args.args[0] == _OTHER


def test_audio_chunk_owner_gets_bytes(monkeypatch):
    c, m = _client(monkeypatch, _ADMIN)
    item = MagicMock(version=1)
    with patch.object(m.content_repo, "get_by_id", return_value=item), \
         patch.object(m.content_repo, "get_tts_chunk",
                      return_value={"mime": "audio/wav", "audio": b"WAVDATA"}):
        r = c.get("/content/1/audio/0")
    assert r.status_code == 200
    assert r.content == b"WAVDATA"
    assert "private" in r.headers.get("cache-control", "")
