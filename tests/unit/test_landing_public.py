"""The landing page made "/" reachable without a session.

That is a change to the auth boundary, so it gets tests that assert the
boundary did not move anywhere else. The dangerous version of this change is
adding "/" to `_PUBLIC_PATH_PREFIXES`: entries there ending in "/" are
prefix-matched, so it would match every path in the app and silently
unauthenticate everything.
"""

from __future__ import annotations

import pytest

from app.main import _is_public_path, _PUBLIC_EXACT_PATHS


def test_root_is_public():
    assert _is_public_path("/") is True


@pytest.mark.parametrize(
    "path",
    [
        "/aim",
        "/mira",
        "/mira/memory",
        "/settings",
        "/skills",
        "/focus",
        "/news",
        "/readiness",
        "/decisions",
        "/writings",
        "/tracks",
        "/voices",
        "/warmup",
        "/reflect",
        "/connecting",
        "/credentials",
        "/jds",
        "/today/next",
        "/onboarding",
        "/admin/access-requests",
        "/feedback/inbox",
        "/problem/softmax",
        "/content/some-slug",
        "/journal/2026-08-10",
    ],
)
def test_protected_routes_are_still_protected(path):
    """REGRESSION: the whole risk of this change is over-matching."""
    assert _is_public_path(path) is False, (
        f"{path} became public — the auth boundary moved further than "
        f"intended and every signed-out visitor can now reach it"
    )


def test_exact_set_holds_only_root():
    """A second entry here should be a deliberate, reviewed decision."""
    assert _PUBLIC_EXACT_PATHS == frozenset({"/"})


def test_root_match_is_equality_not_prefix():
    """If "/" were prefix-matched, every one of these would be public."""
    for path in ("/aim", "/settings", "/anything", "/a"):
        assert _is_public_path(path) is False


def test_known_public_paths_still_public():
    """The change must not have narrowed the boundary either."""
    for path in ("/login", "/request-access", "/static/css/main.css", "/__health"):
        assert _is_public_path(path) is True
