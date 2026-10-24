"""Optional exports must not expose identity metadata or fail saved reports."""
from datetime import datetime
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services import feedback_inbox, github_feedback


def test_public_issue_omits_identity_and_private_url_components():
    body = github_feedback.format_issue_body(
        feedback_id=4, body="The button does not respond.",
        url="https://user:password@example.com/problem/softmax?token=private-token#private-fragment",
        page_title="Softmax", theme="dark", viewport_width=800,
        submitter_email="private@example.com", submitter_user_id="private-user-uuid",
        auto_promoted=False,
    )
    assert "The button does not respond." in body
    assert "`/problem/softmax`" in body
    assert "feedback_id=4" in body
    for secret in ("private@example.com", "private-user-uuid", "private-token", "private-fragment", "password"):
        assert secret not in body


def test_empty_issue_title_does_not_copy_query_metadata():
    title = github_feedback.format_issue_title(body="", url="/library?token=private-token#private-fragment")
    assert "/library" in title
    assert "private-token" not in title
    assert "private-fragment" not in title


def test_markdown_mirror_failure_does_not_turn_saved_feedback_into_error(tmp_path, caplog):
    repo = SimpleNamespace(list_for_user=Mock(side_effect=RuntimeError("mirror read unavailable")))
    feedback_inbox.regenerate_inbox(repo, "user-id", tmp_path)
    assert "mirror" in caplog.text.lower()


def test_unwritable_mirror_destination_does_not_fail_saved_feedback(tmp_path, caplog):
    (tmp_path / "data").write_text("not a directory")
    repo = SimpleNamespace(list_for_user=Mock(return_value=[]))
    feedback_inbox.regenerate_inbox(repo, "user-id", tmp_path)
    assert "mirror" in caplog.text.lower()


def test_mirror_success_still_writes_both_files(tmp_path):
    repo = SimpleNamespace(list_for_user=Mock(return_value=[]))
    feedback_inbox.regenerate_inbox(repo, "user-id", tmp_path)
    export_dir = tmp_path / "data/feedback/users" / sha256(b"user-id").hexdigest()
    assert "Nothing open" in (export_dir / "inbox.md").read_text()
    assert "Empty" in (export_dir / "archive.md").read_text()


@pytest.mark.parametrize("url,linked", [
    ("javascript:alert(document.domain)", False), ("//evil.example/path", False),
    ("/problem/softmax", True), ("https://example.com/page", True),
])
def test_inbox_links_only_safe_page_urls(url, linked):
    from datetime import datetime
    from pathlib import Path
    from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, select_autoescape

    env = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": "{% block body %}{% endblock %}"}),
        FileSystemLoader(Path(__file__).resolve().parents[2] / "templates"),
    ]), autoescape=select_autoescape(["html"]))
    row = SimpleNamespace(id=4, status="open", created_at=datetime(2026, 9, 25),
        url=url, body="Report", theme=None, viewport_width=None, gh_issue_number=None,
        gh_issue_url=None, processing_notes=None)
    html = env.get_template("feedback_inbox.html").render(items=[row], active_status="open",
        tab_statuses=["open"], counts={"open": 1}, attachments_by_fb={}, is_admin=False, show_all=False)
    assert (f'href="{url}"' in html) is linked
    assert url in html


def test_submit_confirms_saved_row_when_optional_mirror_fails(monkeypatch, tmp_path):
    from tests.unit.test_feedback_attachments import _client, _form

    client, m = _client(monkeypatch)
    insert = Mock(return_value=83)
    monkeypatch.setattr(m, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(m.feedback_repo, "insert", insert)
    monkeypatch.setattr(m.feedback_repo, "list_for_user", Mock(side_effect=RuntimeError("mirror unavailable")))
    response = client.post("/feedback", data=_form())
    assert response.status_code == 200
    assert response.text.startswith("saved as feedback #83")
    insert.assert_called_once()


def test_markdown_exports_keep_users_separate_and_preserve_legacy_files(tmp_path):
    legacy = tmp_path / "data/feedback"
    legacy.mkdir(parents=True)
    (legacy / "inbox.md").write_text("legacy mirror")
    (legacy / "archive.md").write_text("legacy archive")

    def items(user_id, *, status, **kwargs):
        return [SimpleNamespace(id=1, created_at=datetime(2026, 9, 25),
            processed_at=None, body=f"Private {user_id} report", url="/problem/example",
            page_title="Example", theme=None, viewport_width=None, processing_notes=None)]

    repo = SimpleNamespace(list_for_user=Mock(side_effect=items))
    for user_id in ("alpha", "beta"):
        feedback_inbox.regenerate_inbox(repo, user_id, tmp_path)
    for user_id, other_id in (("alpha", "beta"), ("beta", "alpha")):
        export_dir = legacy / "users" / sha256(user_id.encode()).hexdigest()
        for filename in ("inbox.md", "archive.md"):
            body = (export_dir / filename).read_text()
            assert f"Private {user_id} report" in body
            assert f"Private {other_id} report" not in body
    assert (legacy / "inbox.md").read_text() == "legacy mirror"
    assert (legacy / "archive.md").read_text() == "legacy archive"
    assert [call.args[0] for call in repo.list_for_user.call_args_list] == ["alpha"] * 4 + ["beta"] * 4


@pytest.mark.parametrize("user_id", ["../../../outside", "/absolute/path", "用户\\notes"])
def test_markdown_export_directory_never_uses_raw_user_id(tmp_path, user_id):
    repo = SimpleNamespace(list_for_user=Mock(return_value=[]))
    feedback_inbox.regenerate_inbox(repo, user_id, tmp_path)
    digest = sha256(user_id.encode("utf-8")).hexdigest()
    assert sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*.md")) == [
        f"data/feedback/users/{digest}/archive.md",
        f"data/feedback/users/{digest}/inbox.md",
    ]
