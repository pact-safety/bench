"""Integration smoke — basic route shape against real Postgres.

These run only when DATABASE_URL is set (see conftest auto-skip).
They confirm:
  - The auth gate redirects unauthenticated requests
  - Public paths stay public
  - Static assets serve
  - The login page renders

They don't currently exercise the signed-in routes against the live
Postgres because that requires inserting a real auth.users row first
(which the synthetic fake-JWT path can't trigger via Supabase). Phase
5 (test-user separation) will land a fixture that does that cleanly."""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.integration


def test_unauthenticated_root_redirects_to_login(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers.get("location") == "/login"


def test_login_page_renders(client):
    r = client.get("/login")
    assert r.status_code == 200
    assert "Continue with GitHub" in r.text


def test_auth_callback_without_code_redirects_with_error(client):
    r = client.get("/auth/callback", follow_redirects=False)
    assert r.status_code == 303
    assert "error" in (r.headers.get("location") or "")


def test_static_asset_serves(client):
    r = client.get("/static/css/main.css")
    assert r.status_code == 200
    assert "text/css" in r.headers.get("content-type", "")


def test_auth_signin_redirects_to_supabase(client):
    """The OAuth-initiation route should 303 to a Supabase /authorize
    URL with a code_challenge in the query string."""
    r = client.get("/auth/signin/github", follow_redirects=False)
    assert r.status_code == 303
    loc = r.headers.get("location") or ""
    assert "/auth/v1/authorize" in loc
    assert "code_challenge=" in loc
    assert "code_challenge_method=S256" in loc
    # Verifier cookie should have been set so /auth/callback can use it.
    cookies = "".join(r.headers.get_list("set-cookie"))
    assert "sb-pkce-verifier" in cookies
