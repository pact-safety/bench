"""GitHub OAuth via Supabase Auth, session management — PKCE flow.

Phase 3 of the multi-user migration.

Flow shape (modern Supabase enforces PKCE; implicit flow is deprecated):

  /auth/signin/github
    └─ Server generates a (code_verifier, code_challenge) pair.
       Verifier saved in a short-lived HTTP-only cookie. Challenge is
       embedded in the OAuth URL. User is 303'd to Supabase.

  Supabase → GitHub → Supabase → /auth/callback?code=<auth_code>
    └─ Server reads `code` from the query string and the verifier
       from the cookie, then POSTs to Supabase's /auth/v1/token
       endpoint (grant_type=pkce) to exchange the pair for an access
       + refresh token. Verifier cookie is cleared. Session cookies
       are set.

  Subsequent requests
    └─ Middleware reads `sb-access-token` cookie and decodes the JWT
       payload to populate `request.state.user_session`.

Security notes:

- Cookies are HTTP-only + SameSite=Lax + `secure` when served over
  HTTPS (controlled by SENTRY_ENVIRONMENT).
- The code_verifier cookie has a 10-minute max-age and is cleared on
  callback success. It's the only piece of OAuth state that lives
  outside the access_token, so we keep its lifetime tight.
- JWT signature verification is **deferred to Phase 7**. Right now
  we decode the payload to read `sub` (user_id) and `email` without
  verifying. That's acceptable on localhost (HTTP-only cookie, same-
  origin) but NOT on the public internet. The deploy checklist
  (LIS-280) tracks the fix.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from dataclasses import dataclass
from typing import Any


ACCESS_TOKEN_COOKIE = "sb-access-token"
REFRESH_TOKEN_COOKIE = "sb-refresh-token"
PKCE_VERIFIER_COOKIE = "sb-pkce-verifier"


@dataclass
class UserSession:
    user_id: str
    email: str | None
    expires_at: int
    raw_access_token: str


# ---------- PKCE primitives -------------------------------------------------

def generate_pkce_pair() -> tuple[str, str]:
    """Return `(verifier, challenge)` for a fresh PKCE handshake.

    Verifier: 43-128 chars, URL-safe. Challenge: base64url-encoded
    SHA-256 of the verifier. Method is `S256` (the only one Supabase
    accepts; `plain` is not supported)."""
    # `token_urlsafe(64)` gives 86 url-safe chars — well above the
    # RFC-7636 minimum of 43 and below the maximum of 128.
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def build_oauth_authorize_url(*, provider: str, redirect_to: str, code_challenge: str) -> str:
    """Build the Supabase /auth/v1/authorize URL with PKCE params.

    We construct manually because supabase-py's `sign_in_with_oauth`
    keeps the code_verifier in its in-memory storage, which doesn't
    survive across the two HTTP requests on a server-rendered app."""
    from urllib.parse import urlencode

    supabase_url = os.environ.get("SUPABASE_URL", "").strip()
    if not supabase_url:
        raise RuntimeError("SUPABASE_URL not set in .env.local")
    params = urlencode({
        "provider": provider,
        "redirect_to": redirect_to,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    })
    return f"{supabase_url}/auth/v1/authorize?{params}"


def exchange_code_for_session(auth_code: str, code_verifier: str) -> dict[str, Any]:
    """POST to Supabase's token endpoint to swap (code + verifier) for
    a session. Returns the parsed token bundle, raising on any failure.

    Doc: https://supabase.com/docs/reference/api/auth/v1/token
    Endpoint: POST /auth/v1/token?grant_type=pkce
    Body: {"auth_code": "...", "code_verifier": "..."}
    """
    import httpx

    supabase_url = os.environ.get("SUPABASE_URL", "").strip()
    anon_key = os.environ.get("SUPABASE_ANON_KEY", "").strip()
    if not (supabase_url and anon_key):
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_ANON_KEY must be set in .env.local"
        )

    with httpx.Client(timeout=10.0) as client:
        resp = client.post(
            f"{supabase_url}/auth/v1/token?grant_type=pkce",
            headers={
                "apikey": anon_key,
                "Content-Type": "application/json",
                # Some Supabase deployments require Authorization too,
                # set to the same anon key. Cheap to include.
                "Authorization": f"Bearer {anon_key}",
            },
            json={"auth_code": auth_code, "code_verifier": code_verifier},
        )
    if resp.status_code >= 400:
        # Surface the GoTrue error message — usually descriptive.
        try:
            err = resp.json()
        except Exception:
            err = {"raw": resp.text[:400]}
        raise RuntimeError(
            f"Supabase token exchange failed ({resp.status_code}): {err}"
        )
    return resp.json()


# ---------- Cookie / session helpers ----------------------------------------

def _cookie_secure() -> bool:
    """`secure=True` only when served over HTTPS — proxied here by
    SENTRY_ENVIRONMENT being `prod`. Local dev (HTTP) leaves it off
    so the cookie sticks."""
    return os.environ.get("SENTRY_ENVIRONMENT", "local").lower() in ("prod", "production")


def _decode_jwt_payload_unverified(token: str) -> dict[str, Any]:
    """Last-resort fallback: decode payload without verification.

    Only fires when SUPABASE_JWT_SECRET is unset AND we're in local
    dev (allow_unverified_jwt() returns True). Logs a warning every
    time it's used so we notice if it's ever invoked in production.
    """
    try:
        _hdr, payload_b64, _sig = token.split(".", 2)
    except ValueError as e:
        raise ValueError(f"malformed JWT (expected 3 parts): {e}")
    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
    return json.loads(decoded.decode("utf-8"))


def _is_prod() -> bool:
    return os.environ.get("SENTRY_ENVIRONMENT", "local").lower() in ("prod", "production")


def allow_unverified_jwt() -> bool:
    """Local dev escape hatch: if the JWT secret isn't set and we're
    NOT in production, allow the unverified decode path with a loud
    warning. In production, missing the secret is a hard error.

    LIS-280 deploy hardening: before this PR every request decoded
    JWTs without verifying signatures — anyone could craft a token
    and impersonate any user. Now we verify with the Supabase JWT
    secret (HS256). The unverified path remains only for local dev
    where the secret may not be set; production fails closed."""
    return os.environ.get("SUPABASE_JWT_SECRET") is None and not _is_prod()


_JWKS_CLIENT_CACHE: dict[str, Any] = {}


def _jwks_client_for(supabase_url: str):
    """One PyJWKClient per project URL, cached process-wide. PyJWKClient
    keeps its own LRU of fetched keys, so this gives us both connection
    reuse and key caching across requests."""
    import jwt as _jwt
    if supabase_url not in _JWKS_CLIENT_CACHE:
        jwks_url = supabase_url.rstrip("/") + "/auth/v1/.well-known/jwks.json"
        _JWKS_CLIENT_CACHE[supabase_url] = _jwt.PyJWKClient(jwks_url, cache_keys=True)
    return _JWKS_CLIENT_CACHE[supabase_url]


def _decode_jwt_verified(token: str) -> dict[str, Any]:
    """Verify the JWT signature and return its payload. Raises on any
    failure — callers translate that to a signed-out session.

    Modern Supabase projects sign access tokens with **ES256** (P-256
    EC keypair); the public keys are served via JWKS at
    `/auth/v1/.well-known/jwks.json`. Older projects still sign with
    **HS256** using a shared `SUPABASE_JWT_SECRET`. We dispatch on the
    token header's `alg`:

    - `ES256` / `RS256` → fetch the matching key by `kid` from JWKS
      (PyJWKClient caches keys; one HTTP hit per key rotation).
    - `HS256` → verify with `SUPABASE_JWT_SECRET` (legacy path).

    The legacy path is kept because (a) tokens issued just before a
    project's key rotation are still valid until their `exp`, and
    (b) self-hosted Supabase deployments may still be on HS256."""
    import jwt as _jwt

    try:
        header = _jwt.get_unverified_header(token)
    except Exception as e:
        raise ValueError(f"malformed JWT header: {e}")
    alg = header.get("alg", "HS256")

    # Common decode options. `aud` for Supabase access tokens is
    # "authenticated"; we don't enforce `iss` because issuers vary.
    decode_kwargs: dict[str, Any] = {
        "algorithms": [alg],
        "audience": "authenticated",
        "options": {"require": ["exp", "sub"]},
    }

    if alg in ("ES256", "ES384", "ES512", "RS256", "RS384", "RS512"):
        # Asymmetric: pull the public key from the project's JWKS.
        supabase_url = os.environ.get("SUPABASE_URL")
        if not supabase_url:
            raise RuntimeError(
                "SUPABASE_URL is required to verify ES256/RS256 access tokens "
                "(needed to fetch the project's JWKS)."
            )
        jwks = _jwks_client_for(supabase_url)
        signing_key = jwks.get_signing_key_from_jwt(token).key
        return _jwt.decode(token, signing_key, **decode_kwargs)

    # HS256 (legacy shared-secret) path.
    secret = os.environ.get("SUPABASE_JWT_SECRET")
    if not secret:
        if allow_unverified_jwt():
            import logging
            logging.warning(
                "SUPABASE_JWT_SECRET unset; falling back to UNVERIFIED JWT decode "
                "(local dev only). Set the secret before deploying."
            )
            return _decode_jwt_payload_unverified(token)
        raise RuntimeError(
            "SUPABASE_JWT_SECRET is required to verify HS256 tokens. "
            "If your Supabase project has migrated to ES256 signing keys, "
            "this code path should not be hit — check the token header's `alg`."
        )
    return _jwt.decode(token, secret, **decode_kwargs)


def parse_access_token(token: str) -> UserSession | None:
    if not token:
        return None
    try:
        payload = _decode_jwt_verified(token)
    except Exception:
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    return UserSession(
        user_id=str(user_id),
        email=payload.get("email"),
        expires_at=int(payload.get("exp", 0)),
        raw_access_token=token,
    )


def current_user(request) -> UserSession | None:
    token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    if not token:
        return None
    return parse_access_token(token)


def set_pkce_verifier_cookie(response, verifier: str) -> None:
    """Short-lived; only needs to survive the round-trip through GitHub.
    10 minutes is generous."""
    response.set_cookie(
        key=PKCE_VERIFIER_COOKIE,
        value=verifier,
        max_age=600,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        path="/",
    )


def clear_pkce_verifier_cookie(response) -> None:
    response.delete_cookie(PKCE_VERIFIER_COOKIE, path="/")


def set_session_cookies(response, access_token: str, refresh_token: str | None) -> None:
    secure = _cookie_secure()
    response.set_cookie(
        key=ACCESS_TOKEN_COOKIE,
        value=access_token,
        max_age=3600,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    if refresh_token:
        response.set_cookie(
            key=REFRESH_TOKEN_COOKIE,
            value=refresh_token,
            max_age=60 * 60 * 24 * 30,
            httponly=True,
            secure=secure,
            samesite="lax",
            path="/",
        )


def clear_session_cookies(response) -> None:
    response.delete_cookie(ACCESS_TOKEN_COOKIE, path="/")
    response.delete_cookie(REFRESH_TOKEN_COOKIE, path="/")
