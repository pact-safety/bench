from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from tests.unit.test_mira_routes import _signed_in_client


@pytest.mark.parametrize("action", ["archive", "backlog", "reopen", "dismiss"])
def test_admin_can_triage_other_learners_feedback(monkeypatch, action):
    client, m = _signed_in_client(monkeypatch)
    from app.services import access
    monkeypatch.setattr(access, "is_admin", lambda uid: True)
    monkeypatch.setattr(m.mira_repo, "list_sessions", lambda *a, **k: [])
    monkeypatch.setattr(m.feedback_repo, "get", lambda fid: SimpleNamespace(id=fid, user_id="another-learner", gh_issue_url=None))
    status = Mock()
    monkeypatch.setattr(m.feedback_repo, "set_status", status)
    monkeypatch.setattr(m.feedback_inbox_service, "regenerate_inbox", Mock())
    response = client.post(f"/feedback/2/{action}", follow_redirects=False)
    assert response.status_code == 303
    status.assert_called_once()


@pytest.mark.parametrize("action", ["archive", "backlog", "reopen", "dismiss"])
def test_nonadmin_cannot_triage_other_learners_feedback(monkeypatch, action):
    client, m = _signed_in_client(monkeypatch)
    from app.services import access
    monkeypatch.setattr(access, "is_admin", lambda uid: False)
    monkeypatch.setattr(m.feedback_repo, "get", lambda fid: SimpleNamespace(id=fid, user_id="another-learner", gh_issue_url=None))
    status = Mock()
    monkeypatch.setattr(m.feedback_repo, "set_status", status)
    assert client.post(f"/feedback/2/{action}", follow_redirects=False).status_code == 404
    status.assert_not_called()


@pytest.mark.parametrize("url", ["javascript:alert(1)", "data:text/html,boom", "//evil.example/path", "relative/path"])
def test_feedback_rejects_unsafe_context_before_saving(monkeypatch, url):
    from tests.unit.test_feedback_attachments import _client
    client, m = _client(monkeypatch)
    saved = Mock()
    monkeypatch.setattr(m.feedback_repo, "insert", saved)
    response = client.post("/feedback", data={"url": url, "body": "UI report"})
    assert response.status_code == 400
    saved.assert_not_called()


def test_feedback_context_omits_query_and_fragment(monkeypatch):
    from tests.unit.test_feedback_attachments import _client
    client, m = _client(monkeypatch)
    saved = Mock(return_value=1)
    monkeypatch.setattr(m.feedback_repo, "insert", saved)
    monkeypatch.setattr(m.feedback_inbox_service, "regenerate_inbox", Mock())
    response = client.post("/feedback", data={"url": "/problem/example?token=secret#private", "body": "UI report"})
    assert response.status_code == 200
    assert saved.call_args.kwargs["url"] == "/problem/example"
