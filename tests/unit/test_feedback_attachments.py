"""Route tests for feedback image attachments (migration 015) and the
auto-diagnostics widget contract.

Server side only: validation caps (type / size / count), attachment
persistence alongside the feedback row, and the owner-or-admin gate on
the serve route. The JS capture path is exercised manually.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


_ADMIN_UUID = "11111111-1111-1111-1111-111111111111"
_USER_UUID = "22222222-2222-2222-2222-222222222222"


def _client(monkeypatch, *, session_uuid: str = _USER_UUID):
    """Non-admin by default so POSTs skip the GH auto-promotion path."""
    monkeypatch.setenv("LIS_ADMIN_USER_IDS", _ADMIN_UUID)
    monkeypatch.delenv("LIS_ALLOWED_USER_IDS", raising=False)
    monkeypatch.delenv("LIS_ALLOWED_EMAILS", raising=False)

    import app.main as m
    import app.auth as auth_module
    from app.auth import UserSession
    from fastapi.testclient import TestClient

    monkeypatch.setattr(m, "_user_settings", lambda uid: {})
    monkeypatch.setattr(
        auth_module,
        "parse_access_token",
        lambda _tok: UserSession(
            user_id=session_uuid,
            email="fb@example.com",
            expires_at=2**31 - 1,
            raw_access_token="x",
        ),
    )
    client = TestClient(m.app)
    client.cookies.set("sb-access-token", "x.y.z")
    return client, m


def _form(**kw):
    return {
        "url": "/problem/softmax",
        "body": "the mask renders wrong",
        "page_title": "Softmax",
        "theme": "dark",
        "viewport_width": "1440",
        **kw,
    }


_PNG = ("shot.png", b"\x89PNG fake bytes", "image/png")


# ---------------------------------------------------------------------------
# POST /feedback with images
# ---------------------------------------------------------------------------


def test_valid_image_is_persisted_with_feedback(monkeypatch):
    client, m = _client(monkeypatch)
    insert = MagicMock(return_value=77)
    att = MagicMock(return_value=1)

    with patch.object(m.feedback_repo, "insert", insert), \
         patch.object(m.feedback_repo, "insert_attachment", att), \
         patch.object(m.feedback_inbox_service, "regenerate_inbox"):
        r = client.post("/feedback", data=_form(), files=[("images", _PNG)])

    assert r.status_code == 200
    att.assert_called_once()
    kw = att.call_args.kwargs
    assert kw["feedback_id"] == 77
    assert kw["content_type"] == "image/png"
    assert kw["data"] == _PNG[1]


def test_no_images_still_works(monkeypatch):
    """The widget always posts multipart now — zero files must behave
    exactly like the old text-only path."""
    client, m = _client(monkeypatch)
    att = MagicMock()

    with patch.object(m.feedback_repo, "insert", MagicMock(return_value=1)), \
         patch.object(m.feedback_repo, "insert_attachment", att), \
         patch.object(m.feedback_inbox_service, "regenerate_inbox"):
        r = client.post("/feedback", data=_form())

    assert r.status_code == 200
    att.assert_not_called()


def test_wrong_type_rejected_before_insert(monkeypatch):
    client, m = _client(monkeypatch)
    insert = MagicMock()

    with patch.object(m.feedback_repo, "insert", insert):
        r = client.post(
            "/feedback",
            data=_form(),
            files=[("images", ("evil.svg", b"<svg/>", "image/svg+xml"))],
        )

    assert r.status_code == 400
    insert.assert_not_called()  # nothing half-saved


def test_oversize_image_rejected(monkeypatch):
    client, m = _client(monkeypatch)
    big = b"x" * (2 * 1024 * 1024 + 1)

    with patch.object(m.feedback_repo, "insert", MagicMock()) as insert:
        r = client.post(
            "/feedback",
            data=_form(),
            files=[("images", ("big.png", big, "image/png"))],
        )

    assert r.status_code == 400
    insert.assert_not_called()


def test_more_than_three_images_rejected(monkeypatch):
    client, m = _client(monkeypatch)
    files = [("images", (f"s{i}.png", b"data", "image/png")) for i in range(4)]

    with patch.object(m.feedback_repo, "insert", MagicMock()) as insert:
        r = client.post("/feedback", data=_form(), files=files)

    assert r.status_code == 400
    insert.assert_not_called()


# ---------------------------------------------------------------------------
# GET /feedback/attachment/{id} — owner-or-admin
# ---------------------------------------------------------------------------


def _att_row(owner: str) -> dict:
    return {
        "id": 5,
        "feedback_id": 9,
        "user_id": owner,
        "filename": "shot.png",
        "content_type": "image/png",
        "byte_size": 4,
        "bytes": b"data",
    }


def test_owner_can_fetch_attachment(monkeypatch):
    client, m = _client(monkeypatch, session_uuid=_USER_UUID)
    with patch.object(m.feedback_repo, "get_attachment", return_value=_att_row(_USER_UUID)):
        r = client.get("/feedback/attachment/5")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/png")
    assert r.content == b"data"


def test_other_user_gets_404(monkeypatch):
    client, m = _client(monkeypatch, session_uuid=_USER_UUID)
    with patch.object(m.feedback_repo, "get_attachment", return_value=_att_row("someone-else")):
        r = client.get("/feedback/attachment/5")
    assert r.status_code == 404


def test_admin_can_fetch_any_attachment(monkeypatch):
    client, m = _client(monkeypatch, session_uuid=_ADMIN_UUID)
    with patch.object(m.feedback_repo, "get_attachment", return_value=_att_row(_USER_UUID)):
        r = client.get("/feedback/attachment/5")
    assert r.status_code == 200


def test_missing_attachment_404(monkeypatch):
    client, m = _client(monkeypatch)
    with patch.object(m.feedback_repo, "get_attachment", return_value=None):
        r = client.get("/feedback/attachment/999")
    assert r.status_code == 404
