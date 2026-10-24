"""Tests for app.auth — PKCE primitives + JWT payload extraction.

Pure functions; no network."""

from __future__ import annotations

import base64
import hashlib
import json

from app import auth


def test_generate_pkce_pair_is_well_formed():
    verifier, challenge = auth.generate_pkce_pair()
    # Verifier: 43-128 URL-safe chars per RFC-7636.
    assert 43 <= len(verifier) <= 128
    # Challenge: base64url(sha256(verifier)) without padding.
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    assert challenge == expected
    assert len(challenge) == 43  # sha256 → 32 bytes → 43 base64url chars w/o pad


def test_generate_pkce_pair_is_fresh_each_call():
    """The verifier must be entropic per call — otherwise concurrent
    sign-ins would conflict."""
    pairs = {auth.generate_pkce_pair()[0] for _ in range(10)}
    assert len(pairs) == 10


def test_build_oauth_authorize_url(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    url = auth.build_oauth_authorize_url(
        provider="github",
        redirect_to="http://localhost:8765/auth/callback",
        code_challenge="abc123",
    )
    assert url.startswith("https://test.supabase.co/auth/v1/authorize?")
    assert "provider=github" in url
    assert "code_challenge=abc123" in url
    assert "code_challenge_method=S256" in url
    assert "redirect_to=http" in url


def test_parse_access_token_extracts_sub_and_email():
    payload = {"sub": "abc-uuid", "email": "x@example.com", "exp": 9999999999}
    token = _make_jwt(payload)
    sess = auth.parse_access_token(token)
    assert sess.user_id == "abc-uuid"
    assert sess.email == "x@example.com"
    assert sess.expires_at == 9999999999
    assert sess.raw_access_token == token


def test_parse_access_token_returns_none_on_malformed():
    assert auth.parse_access_token("") is None
    assert auth.parse_access_token("not.a.jwt.with.too.many.parts") is None
    assert auth.parse_access_token("only-one-part") is None
    assert auth.parse_access_token("two.parts") is None


def test_parse_access_token_returns_none_when_no_sub():
    """A JWT without `sub` is invalid for our use — return None."""
    token = _make_jwt({"email": "x@example.com"})  # no sub
    assert auth.parse_access_token(token) is None


def test_current_user_reads_cookie():
    class _Req:
        cookies = {auth.ACCESS_TOKEN_COOKIE: _make_jwt({"sub": "u1"})}
    sess = auth.current_user(_Req())
    assert sess.user_id == "u1"


def test_current_user_none_when_cookie_absent():
    class _Req:
        cookies = {}
    assert auth.current_user(_Req()) is None


def _make_jwt(payload: dict) -> str:
    """Build a fake JWT for testing — we only ever decode the payload
    unverified, so the signature can be garbage."""
    hdr = base64.urlsafe_b64encode(b'{"alg":"HS256"}').rstrip(b"=").decode()
    pl = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    # Unverified decoding still requires canonical base64url JWT segments.
    sig = base64.urlsafe_b64encode(b"fake-signature").rstrip(b"=").decode()
    return f"{hdr}.{pl}.{sig}"
