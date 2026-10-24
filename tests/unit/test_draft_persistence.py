"""Saving a writing status also persists the submitted editor snapshot."""
from unittest.mock import patch
import pytest
from tests.unit.test_writings_delete import _signed_in_client, _writing, _USER_UUID, _OTHER_UUID


@pytest.mark.parametrize("status", ["published", "draft", "archived"])
def test_status_saves_submitted_title_and_body_atomically(monkeypatch, status):
    client, m = _signed_in_client(monkeypatch)
    with patch.object(m.writing_repo, "get", return_value=_writing(id_=7)), patch.object(m.writing_repo, "save_with_status", return_value=True) as save, patch.object(m.writing_repo, "set_status") as status_only:
        response = client.post("/writings/7/status", data={"editor_snapshot": "1", "status": status, "title": "unsaved title", "body_md": "unsaved body"}, follow_redirects=False)
    assert response.status_code == 303
    save.assert_called_once_with(7, user_id=_USER_UUID, title="unsaved title", body_md="unsaved body", status=status)
    status_only.assert_not_called()


def test_status_missing_editor_snapshot_does_not_discard_work(monkeypatch):
    client, m = _signed_in_client(monkeypatch)
    with patch.object(m.writing_repo, "get", return_value=_writing(id_=7)), patch.object(m.writing_repo, "save_with_status") as save, patch.object(m.writing_repo, "set_status") as status_only:
        response = client.post("/writings/7/status", data={"status": "published"}, follow_redirects=False)
    assert response.status_code == 422
    save.assert_not_called()
    status_only.assert_not_called()


def test_status_never_saves_another_users_editor(monkeypatch):
    client, m = _signed_in_client(monkeypatch)
    with patch.object(m.writing_repo, "get", return_value=_writing(id_=7, user_id=_OTHER_UUID)), patch.object(m.writing_repo, "save_with_status") as save:
        response = client.post("/writings/7/status", data={"editor_snapshot":"1", "status":"published", "title":"mine", "body_md":"mine"}, follow_redirects=False)
    assert response.status_code == 404
    save.assert_not_called()


def test_writing_title_is_data_in_delete_confirmation(monkeypatch):
    client, m = _signed_in_client(monkeypatch)
    title = """Li's "draft" <script>alert(1)</script>"""
    with patch.object(m.writing_repo, "list_for_user", return_value=[_writing(id_=7, title=title)]):
        response = client.get("/writings")
    assert 'data-confirm-delete=' in response.text
    assert 'onsubmit="return confirm(' not in response.text
    assert title not in response.text


def test_explicit_empty_editor_can_be_saved_with_status(monkeypatch):
    client, m = _signed_in_client(monkeypatch)
    with patch.object(m.writing_repo, "get", return_value=_writing(id_=7)), patch.object(m.writing_repo, "save_with_status", return_value=True) as save:
        response = client.post("/writings/7/status", data={"editor_snapshot":"1", "status":"archived", "title":"", "body_md":""}, follow_redirects=False)
    assert response.status_code == 303
    save.assert_called_once_with(7, user_id=_USER_UUID, status="archived", title="", body_md="")
