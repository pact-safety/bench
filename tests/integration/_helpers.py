"""Lifecycle helpers for integration test users.

Phase 5: build real `auth.users` rows so integration tests can
exercise signed-in flows against real Postgres without touching
production accounts. Uses the Supabase Admin API (service_role key
required) to create + delete users; the on_auth_user_created
trigger we set up in migrations_pg/001 takes care of mirroring the
row into `public.users`.

Every test user has:
  - email: test+<short-random>@local.lisbench.test
  - is_test: TRUE in public.users (so production filters can exclude)
  - email_confirm: TRUE (skip the email-verification step)

The Admin API lives in supabase-py via `supabase.auth.admin`. Needs
the SERVICE_ROLE key (not the anon/publishable key) — keep it
server-side, never near the browser.
"""

from __future__ import annotations

import os
import secrets
from typing import Any


_TEST_EMAIL_DOMAIN = "local.lisbench.test"


def _admin_client():
    """Build a Supabase client authenticated with the service_role key.

    Raises immediately if the key isn't configured — Phase 5 tests
    need it. The error message points at the .env.local location."""
    from supabase import create_client
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not (url and key):
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in "
            ".env.local for integration tests that create real users. "
            "The service_role key is the `sb_secret_...` value on "
            "Supabase Project Settings → API Keys (not the publishable key)."
        )
    return create_client(url, key)


def _pg_conn():
    """Direct Postgres connection for the is_test flag update + cleanup
    fallback. The Admin API doesn't expose `public.users` so we touch
    it via psycopg."""
    import psycopg
    from psycopg.rows import dict_row
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL not set for test-user cleanup")
    return psycopg.connect(url, row_factory=dict_row, autocommit=True)


def create_test_user() -> dict[str, Any]:
    """Create a fresh test user. Returns `{user_id, email, password}`.

    The password is generated and discarded — we won't use it (tests
    sign in via cookie-mint rather than the magic-link flow), but
    Supabase Admin requires *something*. Worth knowing if you ever
    need to manually log in as a test user via the Supabase dashboard.
    """
    suffix = secrets.token_hex(4)  # 8 chars
    email = f"test+{suffix}@{_TEST_EMAIL_DOMAIN}"
    password = secrets.token_urlsafe(24)
    client = _admin_client()
    resp = client.auth.admin.create_user({
        "email": email,
        "password": password,
        "email_confirm": True,  # skip the verification step
    })
    user_id = resp.user.id

    # Flip the is_test flag so production filters can exclude.
    # The on_auth_user_created trigger already inserted public.users
    # with default is_test=FALSE; we update.
    pg = _pg_conn()
    try:
        with pg.cursor() as cur:
            cur.execute(
                "UPDATE public.users SET is_test = TRUE WHERE id = %s",
                (user_id,),
            )
    finally:
        pg.close()

    return {"user_id": user_id, "email": email, "password": password}


def delete_test_user(user_id: str) -> None:
    """Delete an auth.users row. The FK cascade on public.users (and
    transitively on attempts, content_progress, feedback, ...) cleans
    up every row owned by this user."""
    client = _admin_client()
    try:
        client.auth.admin.delete_user(user_id)
    except Exception:
        # If the admin API call fails (e.g. user already gone), fall
        # back to direct DELETE on public.users which cascades.
        pg = _pg_conn()
        try:
            with pg.cursor() as cur:
                cur.execute("DELETE FROM public.users WHERE id = %s", (user_id,))
        finally:
            pg.close()


def cleanup_all_test_users() -> int:
    """Sweep every is_test=TRUE row + their auth.users counterparts.
    Useful when test runs crash mid-fixture and leave orphans.
    Returns the count deleted."""
    pg = _pg_conn()
    try:
        with pg.cursor() as cur:
            cur.execute("SELECT id FROM public.users WHERE is_test = TRUE")
            test_ids = [r["id"] for r in cur.fetchall()]
    finally:
        pg.close()
    n = 0
    for uid in test_ids:
        try:
            delete_test_user(str(uid))
            n += 1
        except Exception:
            pass
    return n


def mint_test_jwt(user_id: str, email: str) -> str:
    """Build a JWT-shaped cookie value for an existing test user.

    The middleware decodes JWT payloads unverified (see auth.py and
    LIS-280 for the production-deploy hardening plan), so a hand-
    minted token with `sub` = user_id is accepted as a valid session.

    This lets us test signed-in routes without round-tripping through
    GitHub OAuth. The user_id MUST be a real public.users.id (created
    via create_test_user above) so the FK references resolve.
    """
    import base64
    import json
    import time
    hdr = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').rstrip(b"=").decode()
    pl = base64.urlsafe_b64encode(json.dumps({
        "sub": user_id,
        "email": email,
        "exp": int(time.time()) + 3600,
    }).encode()).rstrip(b"=").decode()
    # Unverified decoding still requires canonical base64url JWT segments.
    sig = base64.urlsafe_b64encode(b"fake-signature").rstrip(b"=").decode()
    return f"{hdr}.{pl}.{sig}"
