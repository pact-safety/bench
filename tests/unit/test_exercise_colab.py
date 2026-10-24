from __future__ import annotations

import base64
import json
import time
from unittest.mock import patch


_USER_UUID = "11111111-1111-1111-1111-111111111111"


def _set_fake_session_cookie(client, *, user_id: str = _USER_UUID) -> None:
    header = base64.urlsafe_b64encode(b'{"alg":"HS256"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(
        json.dumps(
            {
                "sub": user_id,
                "email": "test@example.com",
                "exp": int(time.time()) + 3600,
            }
        ).encode()
    ).rstrip(b"=").decode()
    client.cookies.set("sb-access-token", f"{header}.{payload}.sig")


def _signed_in_client(monkeypatch):
    monkeypatch.setenv("LIS_ALLOWED_USER_IDS", _USER_UUID)
    monkeypatch.delenv("LIS_ADMIN_USER_IDS", raising=False)
    monkeypatch.delenv("LIS_ALLOWED_EMAILS", raising=False)

    import app.main as m
    from fastapi.testclient import TestClient

    monkeypatch.setattr(m, "_user_settings", lambda _uid: {"display_tz": "UTC", "display_name": "Li"})
    client = TestClient(m.app)
    _set_fake_session_cookie(client, user_id=_USER_UUID)
    return client, m


def _render_exercise_detail(monkeypatch, *, gpu_required: bool, colab_url: str | None):
    client, m = _signed_in_client(monkeypatch)

    from app.models import ContentItem

    item = ContentItem(
        id=21,
        slug="e08-training-loop-ordering",
        kind="exercise",
        title="Spot the training-loop ordering bug",
        content_md="Exercise body",
    )

    with patch.object(m.content_repo, "get_by_slug", return_value=item), \
         patch.object(m.content_repo, "progress_for_user", return_value={}), \
         patch.object(m.problem_repo, "all_core", return_value=[]), \
         patch.object(m.problem_repo, "all_warmups", return_value=[]), \
         patch.object(m.attempt_repo, "all_for_user", return_value=[]), \
         patch.object(m.crosslink_service, "attempts_following_content", return_value=[]), \
         patch.object(m.content_service, "exercise_frontmatter", return_value=(gpu_required, colab_url)):
        return client.get("/content/e08-training-loop-ordering", follow_redirects=False)


def test_exercise_detail_renders_colab_button_when_colab_url_is_set(monkeypatch):
    colab_url = (
        "https://colab.research.google.com/github/LiBearden/"
        "research-engineer-interview-prep/blob/main/notebooks/exercises/e08-training-loop-ordering.ipynb"
    )
    r = _render_exercise_detail(monkeypatch, gpu_required=True, colab_url=colab_url)

    assert r.status_code == 200
    assert "Open in Colab" in r.text
    assert f'href="{colab_url}"' in r.text
    assert "target=\"_blank\"" in r.text
    assert "GPU recommended — bring your own" not in r.text


def test_exercise_detail_renders_gpu_note_without_colab_url(monkeypatch):
    r = _render_exercise_detail(monkeypatch, gpu_required=True, colab_url=None)

    assert r.status_code == 200
    assert "Open in Colab" not in r.text
    assert "GPU recommended — bring your own (Colab, Modal, local CUDA)." in r.text


def test_exercise_detail_regression_safe_when_no_gpu_or_colab(monkeypatch):
    r = _render_exercise_detail(monkeypatch, gpu_required=False, colab_url=None)

    assert r.status_code == 200
    assert "Open in Colab" not in r.text
    assert "GPU recommended — bring your own" not in r.text
    assert "Mark complete + next" in r.text
