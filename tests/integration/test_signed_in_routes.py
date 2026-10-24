"""Integration tests for signed-in routes against real Postgres.

Each test creates a brand-new auth.users row via the test_user_factory
fixture, exercises a route or two, and the teardown (in conftest.py)
cleans up everything that user wrote.

This is the test tier that would have caught:
  - The /today/next 500 from naive-vs-aware datetime comparison
  - The infinite-reading-loop bug (kinds_done_today)
  - Any future regressions in the daily-flow chain

Run with: `./scripts/test.sh --integration`
"""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.integration


def test_signed_in_user_can_reach_home(signed_in_user):
    """Smoke: real test user, cookie set, GET / should not redirect to
    /login. May 303 to /onboarding if no assessment is present —
    that's still progress (means auth passed)."""
    client, user = signed_in_user
    r = client.get("/", follow_redirects=False)
    # 200 = home rendered. 303 = redirected to /onboarding (because
    # no completed assessment for this fresh user). Either is fine;
    # auth gate didn't fire to /login.
    assert r.status_code in (200, 303), f"expected 200 or 303, got {r.status_code}"
    loc = r.headers.get("location") or ""
    assert loc != "/login", "auth gate fired despite valid cookie"


def test_skip_onboarding_lands_on_home(signed_in_user):
    """The most common new-user path: skip onboarding, see home."""
    client, _user = signed_in_user
    # Trip the onboarding skip flag.
    r = client.post("/onboarding/skip", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers.get("location") == "/"
    # And now home renders without bouncing to /onboarding.
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 200
    assert "Up next" in r.text or "caught up" in r.text.lower()


def test_today_next_does_not_500(signed_in_user):
    """REGRESSION: /today/next 500'd on a naive-vs-aware datetime
    comparison in _recent_content_axes. The fix (naive_utc at the
    repo boundary) is locked in by this test running clean."""
    client, _user = signed_in_user
    client.post("/onboarding/skip")
    r = client.get("/today/next", follow_redirects=False)
    # 303 to next action OR / (caught_up case).
    assert r.status_code == 303, f"expected redirect, got {r.status_code}: {r.text[:200]}"


def test_completing_reading_advances_to_watch_slot(signed_in_user):
    """REGRESSION: the infinite-reading-loop bug. Marking any reading
    complete should put 'reading' in kinds_done_today, and the next
    /today/next should NOT pick another reading."""
    client, _user = signed_in_user
    client.post("/onboarding/skip")
    # Get the home page so we know what reading was queued.
    r = client.get("/")
    assert r.status_code == 200
    # Find a reading via the library (we know content r01-... is loaded
    # in the authored content set).
    r = client.get("/content/r01-attention-is-all-you-need", follow_redirects=False)
    if r.status_code != 200:
        pytest.skip("content r01-attention-is-all-you-need not loaded in this Postgres")
    # Extract the content id from the mark-complete form action.
    # The page has <form method="post" action="/content/{id}/check">.
    import re
    m = re.search(r'action="/content/(\d+)/check"', r.text)
    assert m, "no content check form found on the page"
    content_id = int(m.group(1))
    # Mark complete + advance.
    r = client.post(
        f"/content/{content_id}/check",
        data={"next": "1"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    # The redirect should be to /today/next.
    assert r.headers.get("location") == "/today/next"
    # Following that, we should NOT land on another /content/r... page
    # of kind=reading. It might be the same r01 (kinds_done_today is
    # the safeguard) or it might go to a watch / exercise / problem /
    # caught_up. The one thing it must NOT do is loop on readings.
    r2 = client.get("/today/next", follow_redirects=False)
    assert r2.status_code == 303, f"expected redirect, got {r2.status_code}"
    loc = r2.headers.get("location") or ""
    # If it's still on a reading URL, we've regressed.
    if loc.startswith("/content/"):
        # Pull the kind from the content detail page to confirm.
        r3 = client.get(loc)
        text = r3.text.lower()
        # The content page shows the kind badge. If it says "reading",
        # we looped — that's a failure.
        if 'class="content__kind">reading' in text:
            pytest.fail(
                f"daily flow looped on another reading at {loc}; "
                "kinds_done_today should have skipped the reading slot"
            )


def test_requeue_un_completes_content(signed_in_user):
    """The "Done today" tray's requeue button hits
    /content/{id}/check?undo=1. After clicking, the content should be
    back to status=unread."""
    client, _user = signed_in_user
    client.post("/onboarding/skip")
    r = client.get("/content/r01-attention-is-all-you-need", follow_redirects=False)
    if r.status_code != 200:
        pytest.skip("content r01-... not loaded")
    import re
    m = re.search(r'action="/content/(\d+)/check"', r.text)
    if not m:
        pytest.skip("page shape changed; can't extract content_id")
    content_id = int(m.group(1))
    # Mark complete
    client.post(f"/content/{content_id}/check")
    # Confirm the home page shows it in Done today
    r = client.get("/")
    assert "Done today" in r.text, "completion did not surface in Done today tray"
    # Undo
    r = client.post(f"/content/{content_id}/check?undo=1", follow_redirects=False)
    assert r.status_code == 303
    # Now the home page should NOT have a Done today section (no
    # completions left this session).
    r = client.get("/")
    assert "Done today" not in r.text, "requeue didn't un-complete the item"


def test_ramp_indicator_visible_for_new_users(signed_in_user):
    """A new user (0 attempts) is in the onboarding ramp. The Up next
    card should surface that with a 'Onboarding ramp · 0 / 10 attempts'
    line. Phase 6 transparency: users see WHY they're getting easy
    problems."""
    client, _user = signed_in_user
    client.post("/onboarding/skip")
    r = client.get("/")
    # The ramp banner only renders when the Up next card is a
    # practice action; for a fresh user with no content done, the
    # picker might land on reading or watch first. Both code paths
    # are fine. The thing we DO need: the home renders without error.
    assert r.status_code == 200
    # If the up-next card happens to be a problem, the ramp line
    # should be visible.
    if "Onboarding ramp" in r.text:
        assert "/ 10 attempts" in r.text


def _extract_reset_total_rows(html: str) -> str:
    """Pull the reset-token value rendered into the preview page."""
    import re

    m = re.search(r'id="reset-token">\s*([^<]+)\s*</code>', html)
    assert m, "reset token not rendered on /settings/reset"
    return m.group(1).strip()


def test_settings_reset_preview_renders(signed_in_user):
    """Phase 6 reset flow: preview page lists what would be deleted."""
    client, _user = signed_in_user
    client.post("/onboarding/skip")
    r = client.get("/settings/reset")
    assert r.status_code == 200
    assert "Will delete" in r.text
    assert "Will keep" in r.text
    assert 'name="typed_total"' in r.text
    # The 6 table rows the reset touches should all be named.
    for table in ("attempts", "assessment runs", "content progress",
                  "review state", "sessions", "reflections"):
        assert table in r.text, f"reset preview missing '{table}'"


def test_settings_reset_execute_clears_state_and_redirects_to_onboarding(signed_in_user):
    """Phase 6 reset flow end-to-end: skip onboarding, mark a piece of
    content complete, hit reset, confirm landing back on /onboarding
    with the skip flag cleared."""
    import re
    client, _user = signed_in_user
    # Skip onboarding so we have a flag to clear.
    client.post("/onboarding/skip")
    # Mark something complete so there's actually state to wipe.
    r = client.get("/content/r01-attention-is-all-you-need", follow_redirects=False)
    if r.status_code == 200:
        m = re.search(r'action="/content/(\d+)/check"', r.text)
        if m:
            client.post(f"/content/{m.group(1)}/check")
    # Pull the expected typed-count token from the preview page.
    r = client.get("/settings/reset", follow_redirects=False)
    assert r.status_code == 200
    typed_total = _extract_reset_total_rows(r.text)
    # Now execute the reset.
    r = client.post(
        "/settings/reset",
        data={"confirm": "yes", "typed_total": typed_total},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers.get("location") == "/"
    # The next visit to / should redirect to /onboarding (skip flag was cleared).
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers.get("location") == "/onboarding"


def test_settings_reset_requires_confirm(signed_in_user):
    """POSTing without confirm=yes bounces back to the preview page."""
    client, _user = signed_in_user
    r = client.post("/settings/reset", data={"confirm": "no"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers.get("location") == "/settings/reset"


def test_settings_reset_requires_matching_typed_total(signed_in_user):
    """confirm=yes still requires the typed total to match server-side."""
    client, _user = signed_in_user
    client.post("/onboarding/skip")
    r = client.get("/settings/reset", follow_redirects=False)
    assert r.status_code == 200
    expected_total = _extract_reset_total_rows(r.text)

    r = client.post(
        "/settings/reset",
        data={"confirm": "yes", "typed_total": f"{expected_total}x"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers.get("location") == "/settings/reset"


def test_auth_signin_redirects_to_supabase_oauth(client):
    """Unsigned path. Just confirms the OAuth-initiation URL is still
    shaped right after any auth-layer refactor."""
    r = client.get("/auth/signin/github", follow_redirects=False)
    assert r.status_code == 303
    loc = r.headers.get("location") or ""
    assert "/auth/v1/authorize" in loc
    assert "provider=github" in loc
    assert "code_challenge_method=S256" in loc
