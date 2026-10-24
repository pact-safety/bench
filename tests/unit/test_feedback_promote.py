"""Route tests for the feedback↔GH integration (LIS-301).

Covers:
  - POST /feedback by an admin → auto-promotes (mark_promoted called,
    response includes the gh link)
  - POST /feedback by an admin when GH call returns None → still saves
    the row, response explains uncertainty without promising another create
  - POST /feedback by a non-admin → never tries to create_gh_issue
  - GET /feedback/inbox by admin defaults to scope=all (cross-user)
  - GET /feedback/inbox by admin with ?scope=mine narrows to self
  - GET /feedback/inbox by non-admin always scopes to self
  - POST /feedback/{id}/promote requires admin
  - POST /feedback/{id}/promote on an already-promoted row redirects
    to the existing GH URL (idempotent)
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest


# Reusable admin user_id + a non-admin user_id. The admin UUID matches
# what each test points LIS_ADMIN_USER_IDS at.
_ADMIN_UUID = "11111111-1111-1111-1111-111111111111"
_USER_UUID = "22222222-2222-2222-2222-222222222222"


def _client(monkeypatch, *, admin_uuid: str = _ADMIN_UUID,
            session_uuid: str | None = None):
    """Build a TestClient with a mocked auth middleware so we can pin
    `request.state.user_session` to a chosen user_id without going
    through the OAuth flow."""
    monkeypatch.setenv("LIS_ADMIN_USER_IDS", admin_uuid)
    monkeypatch.delenv("LIS_ALLOWED_USER_IDS", raising=False)
    monkeypatch.delenv("LIS_ALLOWED_EMAILS", raising=False)

    import app.main as m
    from fastapi.testclient import TestClient

    # Stub `_user_settings` so the middleware path doesn't hit the
    # raw conn (the test runs against the no-DB sentinel).
    monkeypatch.setattr(m, "_user_settings", lambda uid: {})

    # Force the JWT-decode path to return a session with our chosen uid.
    from app.auth import UserSession
    fake_uid = session_uuid or admin_uuid
    monkeypatch.setattr(
        m.auth_module if hasattr(m, "auth_module") else __import__("app.auth", fromlist=["auth"]),
        "parse_access_token",
        lambda _tok: UserSession(
            user_id=fake_uid, email=f"{fake_uid[:6]}@example.com",
            expires_at=2**31 - 1, raw_access_token="x",
        ),
    )
    client = TestClient(m.app)
    client.cookies.set("sb-access-token", "x.y.z")
    return client, m


def _form(**kw):
    """Default form-data for a /feedback POST."""
    return {
        "url": "/problem/softmax",
        "body": "Hint Tier 3 leaks the answer.",
        "page_title": "Softmax",
        "theme": "dark",
        "viewport_width": "1440",
        **kw,
    }


def _feedback_row(
    *,
    fb_id: int,
    user_id: str,
    status: str = "open",
    gh_issue_url: str | None = None,
):
    from app.models import Feedback

    return Feedback(
        id=fb_id,
        user_id=user_id,
        url="/x",
        page_title=None,
        theme=None,
        viewport_width=None,
        body="feedback body",
        status=status,
        created_at=datetime(2026, 5, 15, 10, 0, 0),
        processed_at=None,
        processing_notes=None,
        gh_issue_url=gh_issue_url,
        gh_issue_number=5 if gh_issue_url else None,
        promoted_at=None,
        promoted_by=None,
    )


def _promotion_setup(monkeypatch, m, *, fb_id=77):
    from app.services import github_feedback
    monkeypatch.setenv("GITHUB_FEEDBACK_TOKEN", "test-only")
    monkeypatch.setenv("GITHUB_FEEDBACK_REPO", "test/repo")
    fb = _feedback_row(fb_id=fb_id, user_id=_ADMIN_UUID)
    monkeypatch.setattr(m.feedback_repo, "insert", MagicMock(return_value=fb_id))
    monkeypatch.setattr(m.feedback_repo, "get", MagicMock(return_value=fb))
    claim = MagicMock(return_value=True)
    mark = MagicMock(return_value=True)
    create = MagicMock(return_value=("https://github.com/test/repo/issues/9", 9))
    monkeypatch.setattr(m.feedback_repo, "claim_promotion", claim)
    monkeypatch.setattr(m.feedback_repo, "mark_promoted", mark)
    monkeypatch.setattr(m.feedback_inbox_service, "regenerate_inbox", MagicMock())
    monkeypatch.setattr(github_feedback, "create_gh_issue", create)
    return fb, claim, mark, create


def test_admin_submit_auto_promotes_and_marks_db(mock_anthropic, monkeypatch):
    client, m = _client(monkeypatch)
    _, claim, mark, create = _promotion_setup(monkeypatch, m)
    r = client.post("/feedback", data=_form())
    assert r.status_code == 200
    assert "gh#9" in r.text
    claim.assert_called_once_with(fb_id=77, promoted_by=_ADMIN_UUID)
    mark.assert_called_once_with(fb_id=77, gh_issue_url="https://github.com/test/repo/issues/9",
                                 gh_issue_number=9, promoted_by=_ADMIN_UUID)
    create.assert_called_once()


def test_admin_submit_preserves_saved_report_after_uncertain_promotion(mock_anthropic, monkeypatch):
    client, m = _client(monkeypatch)
    _, claim, mark, create = _promotion_setup(monkeypatch, m, fb_id=78)
    create.return_value = None
    r = client.post("/feedback", data=_form())
    assert r.status_code == 200
    assert "saved as feedback #78" in r.text
    assert "needs review" in r.text.lower()
    assert "/feedback/inbox" in r.text
    assert "will retry" not in r.text.lower()
    claim.assert_called_once()
    mark.assert_not_called()


def test_non_admin_submit_does_not_attempt_gh(mock_anthropic, monkeypatch):
    """Non-admin user submits → row saved, but create_gh_issue must
    NOT be called (the inbox is the alpha-user's review path)."""
    client, m = _client(
        monkeypatch,
        admin_uuid=_ADMIN_UUID,
        session_uuid=_USER_UUID,  # session is a different user
    )

    insert_mock = MagicMock(return_value=79)
    gh_mock = MagicMock()

    with patch.object(m.feedback_repo, "insert", insert_mock), \
         patch.object(m.feedback_inbox_service, "regenerate_inbox"):
        from app.services import github_feedback
        monkeypatch.setattr(github_feedback, "create_gh_issue", gh_mock)

        r = client.post("/feedback", data=_form())
        assert r.status_code == 200
        assert "#79" in r.text
        # Critical: alpha user submissions don't auto-fire GH calls.
        gh_mock.assert_not_called()


def test_archive_closes_linked_gh_issue(mock_anthropic, monkeypatch):
    client, m = _client(monkeypatch)
    fb = _feedback_row(
        fb_id=7,
        user_id=_ADMIN_UUID,
        gh_issue_url="https://github.com/test/repo/issues/5",
    )

    with patch.object(m.feedback_repo, "get", return_value=fb), \
         patch.object(m.feedback_repo, "set_status") as set_status_mock, \
         patch.object(m.feedback_inbox_service, "regenerate_inbox"):
        from app.services import github_feedback
        close_mock = MagicMock(return_value=True)
        monkeypatch.setattr(github_feedback, "close_gh_issue", close_mock)

        r = client.post("/feedback/7/archive", follow_redirects=False)
        assert r.status_code == 303
        # Post-2026-05-28 operator review: archive redirects to the
        # tab the form's `return_to` field carried. Test doesn't pass
        # one → defaults to "open" so the operator stays on the queue.
        assert r.headers["location"] == "/feedback/inbox?status=open"
        set_status_mock.assert_called_once_with(7, "archived", None)
        close_mock.assert_called_once_with(
            "https://github.com/test/repo/issues/5",
            state_reason="completed",
        )


def test_archive_skips_gh_close_when_feedback_has_no_link(mock_anthropic, monkeypatch):
    client, m = _client(monkeypatch)
    fb = _feedback_row(fb_id=8, user_id=_ADMIN_UUID, gh_issue_url=None)

    with patch.object(m.feedback_repo, "get", return_value=fb), \
         patch.object(m.feedback_repo, "set_status") as set_status_mock, \
         patch.object(m.feedback_inbox_service, "regenerate_inbox"):
        from app.services import github_feedback
        close_mock = MagicMock(return_value=True)
        monkeypatch.setattr(github_feedback, "close_gh_issue", close_mock)

        r = client.post("/feedback/8/archive", follow_redirects=False)
        assert r.status_code == 303
        set_status_mock.assert_called_once_with(8, "archived", None)
        close_mock.assert_not_called()


def test_archive_gh_failure_does_not_break_handler(mock_anthropic, monkeypatch):
    client, m = _client(monkeypatch)
    fb = _feedback_row(
        fb_id=9,
        user_id=_ADMIN_UUID,
        gh_issue_url="https://github.com/test/repo/issues/9",
    )

    with patch.object(m.feedback_repo, "get", return_value=fb), \
         patch.object(m.feedback_repo, "set_status") as set_status_mock, \
         patch.object(m.feedback_inbox_service, "regenerate_inbox"):
        from app.services import github_feedback
        monkeypatch.setattr(
            github_feedback,
            "close_gh_issue",
            MagicMock(side_effect=RuntimeError("boom")),
        )

        r = client.post("/feedback/9/archive", follow_redirects=False)
        assert r.status_code == 303
        # Same default-to-open semantic as test_archive_writes_*.
        assert r.headers["location"] == "/feedback/inbox?status=open"
        set_status_mock.assert_called_once_with(9, "archived", None)


def test_inbox_open_auto_archives_closed_linked_issues(mock_anthropic, monkeypatch):
    client, m = _client(monkeypatch, session_uuid=_USER_UUID)

    # The sync explicitly probes for GITHUB_FEEDBACK_TOKEN before
    # calling out to GitHub — short-circuits with a diagnostic when
    # missing. Provide a placeholder so the test exercises the call
    # path through fetch_closed_issue_urls (which is mocked).
    monkeypatch.setenv("GITHUB_FEEDBACK_TOKEN", "test-token")

    row_closed = _feedback_row(
        fb_id=11,
        user_id=_USER_UUID,
        gh_issue_url="https://github.com/test/repo/issues/11",
    )
    row_open = _feedback_row(
        fb_id=12,
        user_id=_USER_UUID,
        gh_issue_url="https://github.com/test/repo/issues/12",
    )

    list_for_user_mock = MagicMock(side_effect=[[row_closed, row_open], [row_open]])

    with patch.object(m.feedback_repo, "list_for_user", list_for_user_mock), \
         patch.object(m.feedback_repo, "set_status") as set_status_mock, \
         patch.object(m.feedback_repo, "attachments_meta", return_value={}), \
         patch.object(m, "_fb_counts", return_value={"open": 1, "backlog": 0, "closed": 1}):
        from app.services import github_feedback
        fetch_closed_mock = MagicMock(return_value={row_closed.gh_issue_url})
        monkeypatch.setattr(github_feedback, "fetch_closed_issue_urls", fetch_closed_mock)

        r = client.get("/feedback/inbox?status=open")
        assert r.status_code == 200
        fetch_closed_mock.assert_called_once_with([
            "https://github.com/test/repo/issues/11",
            "https://github.com/test/repo/issues/12",
        ])
        set_status_mock.assert_called_once_with(
            11,
            "archived",
            "Auto-closed: linked GitHub issue is closed.",
        )
        # Initial read + post-sync re-read.
        assert list_for_user_mock.call_count == 2


def test_admin_inbox_defaults_to_all_scope(mock_anthropic, monkeypatch):
    client, m = _client(monkeypatch)

    list_all_mock = MagicMock(return_value=[])
    list_for_user_mock = MagicMock(return_value=[])
    counts_all_mock = MagicMock(return_value={"open": 5, "backlog": 2, "closed": 3})

    with patch.object(m.feedback_repo, "list_all", list_all_mock), \
         patch.object(m.feedback_repo, "list_for_user", list_for_user_mock), \
         patch.object(m.feedback_repo, "counts_all", counts_all_mock):
        r = client.get("/feedback/inbox")
        assert r.status_code == 200
        # Admin default → list_all (cross-user). list_for_user untouched.
        list_all_mock.assert_called_once()
        list_for_user_mock.assert_not_called()
        # Toggle is visible — the "just mine" link is in the rendered HTML.
        assert "just mine" in r.text


def test_admin_inbox_scope_mine_narrows_to_self(mock_anthropic, monkeypatch):
    client, m = _client(monkeypatch)

    list_all_mock = MagicMock()
    list_for_user_mock = MagicMock(return_value=[])

    # The "mine" scope path calls the legacy `_fb_counts(uid)` helper
    # which uses a raw conn cursor — stub it so the test doesn't need
    # a real DB.
    with patch.object(m.feedback_repo, "list_all", list_all_mock), \
         patch.object(m.feedback_repo, "list_for_user", list_for_user_mock), \
         patch.object(m, "_fb_counts", return_value={"open": 0, "backlog": 0, "closed": 0}):
        r = client.get("/feedback/inbox?scope=mine")
        assert r.status_code == 200
        # Mine scope → list_for_user (self), list_all untouched.
        list_for_user_mock.assert_called_once()
        list_all_mock.assert_not_called()


def test_non_admin_inbox_always_self_scoped(mock_anthropic, monkeypatch):
    """Even with ?scope=all, a non-admin must NOT see other users' rows."""
    client, m = _client(monkeypatch, session_uuid=_USER_UUID)

    list_all_mock = MagicMock()
    list_for_user_mock = MagicMock(return_value=[])

    with patch.object(m.feedback_repo, "list_all", list_all_mock), \
         patch.object(m.feedback_repo, "list_for_user", list_for_user_mock), \
         patch.object(m, "_fb_counts", return_value={"open": 0, "backlog": 0, "closed": 0}):
        r = client.get("/feedback/inbox?scope=all")
        assert r.status_code == 200
        list_for_user_mock.assert_called_once()
        list_all_mock.assert_not_called()
        # Scope toggle hidden for non-admin.
        assert "just mine" not in r.text


def test_promote_endpoint_requires_admin(mock_anthropic, monkeypatch):
    client, m = _client(monkeypatch, session_uuid=_USER_UUID)
    r = client.post("/feedback/1/promote")
    assert r.status_code == 403


def test_promote_endpoint_idempotent_when_already_promoted(mock_anthropic, monkeypatch):
    """Re-promoting an already-promoted row redirects to the existing
    GH URL without making a second create_gh_issue call."""
    from app.models import Feedback

    client, m = _client(monkeypatch)
    existing = Feedback(
        id=1, user_id=_ADMIN_UUID, url="/x", page_title=None, theme=None,
        viewport_width=None, body="b", status="open",
        created_at=datetime(2026, 5, 15, 10, 0, 0),
        processed_at=None, processing_notes=None,
        gh_issue_url="https://github.com/test/repo/issues/5",
        gh_issue_number=5,
        promoted_at=datetime(2026, 5, 15, 10, 5, 0),
        promoted_by=_ADMIN_UUID,
    )
    gh_mock = MagicMock()

    with patch.object(m.feedback_repo, "get", return_value=existing):
        from app.services import github_feedback
        monkeypatch.setattr(github_feedback, "create_gh_issue", gh_mock)
        r = client.post("/feedback/1/promote", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "https://github.com/test/repo/issues/5"
        gh_mock.assert_not_called()


@pytest.mark.parametrize('automatic', [True, False])
def test_auto_and_manual_promotion_use_same_claimed_helper(monkeypatch, automatic):
    from app.services import github_feedback
    client, m = _client(monkeypatch)
    fb, claim, mark, create = _promotion_setup(monkeypatch, m)
    helper = MagicMock(wraps=github_feedback.promote_feedback)
    monkeypatch.setattr(github_feedback, 'promote_feedback', helper)
    response = client.post('/feedback' if automatic else '/feedback/77/promote',
                           data=_form() if automatic else {}, follow_redirects=False)
    assert response.status_code == (200 if automatic else 303)
    helper.assert_called_once()
    assert helper.call_args.args == (m.feedback_repo, fb)
    assert helper.call_args.kwargs['actor_id'] == _ADMIN_UUID
    assert helper.call_args.kwargs.get('auto_promoted', False) is automatic
    claim.assert_called_once()
    create.assert_called_once()


@pytest.mark.parametrize('status, expected', [('uncertain', 409), ('unconfigured', 503), ('unavailable', 503)])
def test_manual_promotion_failure_status_does_not_promise_retry(monkeypatch, status, expected):
    from app.services import github_feedback
    client, m = _client(monkeypatch)
    fb = _feedback_row(fb_id=7, user_id=_USER_UUID)
    monkeypatch.setattr(m.feedback_repo, 'get', MagicMock(return_value=fb))
    helper = MagicMock(return_value=github_feedback.PromotionResult(status))
    monkeypatch.setattr(github_feedback, 'promote_feedback', helper)
    response = client.post('/feedback/7/promote')
    assert response.status_code == expected
    assert 'will retry' not in response.text.lower()
    if status == 'uncertain':
        assert 'needs review' in response.text.lower()
        assert 'will not be created automatically' in response.text.lower()
        assert '/feedback/inbox' in response.text


def test_reconciliation_requires_admin_before_read_or_verification(monkeypatch):
    from app.services import github_feedback
    client, m = _client(monkeypatch, session_uuid=_USER_UUID)
    get, verify = MagicMock(), MagicMock()
    monkeypatch.setattr(m.feedback_repo, 'get', get)
    monkeypatch.setattr(github_feedback, 'reconcile_feedback', verify)
    response = client.post('/feedback/7/reconcile', data={'issue_url': 'https://github.com/test/repo/issues/9'})
    assert response.status_code == 403
    get.assert_not_called()
    verify.assert_not_called()


@pytest.mark.parametrize('status, expected', [('linked', 303), ('invalid', 400), ('uncertain', 409), ('unavailable', 503)])
def test_reconciliation_maps_verified_result_without_create(monkeypatch, status, expected):
    from app.services import github_feedback
    client, m = _client(monkeypatch)
    fb = _feedback_row(fb_id=7, user_id=_USER_UUID)
    fb.promoted_at = datetime(2026, 9, 25)
    monkeypatch.setattr(m.feedback_repo, 'get', MagicMock(return_value=fb))
    verify = MagicMock(return_value=github_feedback.PromotionResult(status))
    create = MagicMock(side_effect=AssertionError('reconciliation created issue'))
    monkeypatch.setattr(github_feedback, 'reconcile_feedback', verify)
    monkeypatch.setattr(github_feedback, 'create_gh_issue', create)
    url = 'https://github.com/test/repo/issues/9'
    response = client.post('/feedback/7/reconcile', data={'issue_url': url}, follow_redirects=False)
    assert response.status_code == expected
    verify.assert_called_once_with(m.feedback_repo, fb, issue_url=url, actor_id=_ADMIN_UUID)
    create.assert_not_called()
    if status == 'linked':
        assert response.headers['location'] == '/feedback/inbox'


def test_reconciliation_missing_feedback_does_not_verify(monkeypatch):
    from app.services import github_feedback
    client, m = _client(monkeypatch)
    monkeypatch.setattr(m.feedback_repo, 'get', MagicMock(return_value=None))
    verify = MagicMock()
    monkeypatch.setattr(github_feedback, 'reconcile_feedback', verify)
    response = client.post('/feedback/7/reconcile', data={'issue_url': 'https://github.com/test/repo/issues/9'})
    assert response.status_code == 404
    verify.assert_not_called()



def test_manual_retry_of_uncertain_claim_does_not_create_again(monkeypatch):
    client, m = _client(monkeypatch)
    fb, claim, mark, create = _promotion_setup(monkeypatch, m)
    fb.promoted_at = datetime(2026, 9, 25)
    response = client.post('/feedback/77/promote')
    assert response.status_code == 409
    claim.assert_not_called()
    create.assert_not_called()
    mark.assert_not_called()
