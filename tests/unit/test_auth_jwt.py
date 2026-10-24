"""Tests for app.auth JWT verification (LIS-280).

The critical contract: in production (SENTRY_ENVIRONMENT=prod), the
app must REFUSE to decode JWTs when SUPABASE_JWT_SECRET is missing.
Pre-PR every request decoded JWTs without signature verification —
anyone could forge a token. This regression would re-introduce that.
"""

from __future__ import annotations

import time

import pytest

from app import auth


def _make_token(secret: str, payload: dict) -> str:
    """Helper: produce a Supabase-style HS256 JWT for testing."""
    import jwt
    return jwt.encode(payload, secret, algorithm="HS256")


def test_verified_path_with_secret(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-secret-12345")
    token = _make_token("test-secret-12345", {
        "sub": "00000000-0000-0000-0000-000000000001",
        "email": "test@example.com",
        "exp": int(time.time()) + 3600,
        "aud": "authenticated",
    })
    session = auth.parse_access_token(token)
    assert session is not None
    assert session.user_id == "00000000-0000-0000-0000-000000000001"
    assert session.email == "test@example.com"


def test_rejects_wrong_signature(monkeypatch):
    """Token signed with secret X must not validate against secret Y."""
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "expected-secret")
    forged = _make_token("attacker-secret", {
        "sub": "11111111-1111-1111-1111-111111111111",
        "email": "attacker@evil.com",
        "exp": int(time.time()) + 3600,
        "aud": "authenticated",
    })
    assert auth.parse_access_token(forged) is None


def test_rejects_expired(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-secret")
    expired = _make_token("test-secret", {
        "sub": "00000000-0000-0000-0000-000000000001",
        "email": "test@example.com",
        "exp": int(time.time()) - 60,  # 60 seconds ago
        "aud": "authenticated",
    })
    assert auth.parse_access_token(expired) is None


def test_rejects_missing_required_fields(monkeypatch):
    """The decoder asserts exp + sub are present. A token without exp
    is malformed and must be rejected (otherwise we'd accept
    never-expiring tokens)."""
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-secret")
    no_exp = _make_token("test-secret", {
        "sub": "00000000-0000-0000-0000-000000000001",
        "email": "test@example.com",
        "aud": "authenticated",
    })
    assert auth.parse_access_token(no_exp) is None


def test_allow_unverified_only_in_local(monkeypatch):
    """Without SUPABASE_JWT_SECRET, local dev gets the unverified
    fallback; production must NOT."""
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "local")
    assert auth.allow_unverified_jwt() is True

    monkeypatch.setenv("SENTRY_ENVIRONMENT", "prod")
    assert auth.allow_unverified_jwt() is False


def test_prod_without_secret_raises_at_decode(monkeypatch):
    """Production safety net: if a HS256 token arrives in prod with no
    SUPABASE_JWT_SECRET set, decode must raise. This blocks accidental
    deploys where the secret didn't make it into the env."""
    import jwt as _jwt
    # Mint a *well-formed* HS256 token (signed with a throwaway secret)
    # so the header parses cleanly and we exercise the alg dispatch,
    # not the malformed-header branch.
    hs_token = _jwt.encode(
        {"sub": "u", "aud": "authenticated", "exp": 9999999999},
        "throwaway", algorithm="HS256",
    )
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "prod")
    with pytest.raises(RuntimeError):
        auth._decode_jwt_verified(hs_token)
    # And parse_access_token returns None (no session) in this state.
    assert auth.parse_access_token(hs_token) is None


def test_es256_path_uses_jwks(monkeypatch):
    """Modern Supabase projects sign with ES256 (P-256 ECC) and publish
    public keys at /auth/v1/.well-known/jwks.json. The verifier must
    pull the right key by `kid` and verify with the asymmetric alg —
    not fall through to the HS256 shared-secret path.

    This is the regression guard for the prod redirect loop we hit
    after Supabase auto-migrated the project to ES256."""
    from cryptography.hazmat.primitives.asymmetric import ec
    import jwt as _jwt

    # Generate a P-256 keypair and a matching ES256 token. The token's
    # `kid` header points at the JWK we'll inject into PyJWKClient.
    private_key = ec.generate_private_key(ec.SECP256R1())
    kid = "test-kid-1"
    token = _jwt.encode(
        {"sub": "u-1", "email": "t@x.com",
         "aud": "authenticated", "exp": int(time.time()) + 3600},
        private_key,
        algorithm="ES256",
        headers={"kid": kid},
    )

    # Stand in for PyJWKClient.get_signing_key_from_jwt: return an
    # object whose `.key` is the public half of the keypair.
    class _FakeJWK:
        key = private_key.public_key()
    monkeypatch.setattr(
        auth, "_jwks_client_for",
        lambda _url: type("J", (), {"get_signing_key_from_jwt": staticmethod(lambda _t: _FakeJWK())})(),
    )

    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "prod")

    payload = auth._decode_jwt_verified(token)
    assert payload["sub"] == "u-1"
    assert payload["email"] == "t@x.com"


def test_es256_rejects_wrong_key(monkeypatch):
    """A token signed by key A must NOT verify against key B's public
    half. PyJWKClient would normally serve only matching `kid`s; this
    guards the lower-level decode call."""
    from cryptography.hazmat.primitives.asymmetric import ec
    import jwt as _jwt

    signing = ec.generate_private_key(ec.SECP256R1())
    other = ec.generate_private_key(ec.SECP256R1())
    token = _jwt.encode(
        {"sub": "u", "aud": "authenticated", "exp": int(time.time()) + 3600},
        signing, algorithm="ES256", headers={"kid": "k"},
    )

    class _WrongJWK:
        key = other.public_key()
    monkeypatch.setattr(
        auth, "_jwks_client_for",
        lambda _url: type("J", (), {"get_signing_key_from_jwt": staticmethod(lambda _t: _WrongJWK())})(),
    )
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "prod")

    with pytest.raises(Exception):
        auth._decode_jwt_verified(token)
    assert auth.parse_access_token(token) is None
