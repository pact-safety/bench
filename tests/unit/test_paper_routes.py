"""/content/<slug> pass ladder and the /papers corpus view."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

_USER = "22222222-2222-2222-2222-222222222222"


def _client(monkeypatch):
    monkeypatch.setenv("LIS_ALLOWED_USER_IDS", _USER)
    monkeypatch.delenv("LIS_ADMIN_USER_IDS", raising=False)

    import app.main as m
    import app.auth as auth_module
    from app.auth import UserSession
    from fastapi.testclient import TestClient

    monkeypatch.setattr(m, "_user_settings", lambda _uid: {})
    monkeypatch.setattr(
        auth_module, "parse_access_token",
        lambda _tok: UserSession(user_id=_USER, email="u@example.com",
                                 expires_at=2**31 - 1, raw_access_token="x"),
    )
    client = TestClient(m.app)
    client.cookies.set("sb-access-token", "x.y.z")
    return client, m


def _item(slug="r01-attention", url="https://arxiv.org/abs/1706.03762", kind="reading"):
    return SimpleNamespace(
        id=1, slug=slug, title="Attention Is All You Need", kind=kind,
        url=url, source="Vaswani et al., 2017", content_md="body",
        duration_min=12, axes=["transformer_internals"], domain_tags=[],
        source_kind="authored", gpu_required=False, colab_url=None,
    )


def _progress(paper_state=None):
    return SimpleNamespace(
        notes_md=None, favorited=False, rating_1_to_5=None, status="in_progress",
        checked_at=None, recitation_state={}, last_recited_at=None,
        paper_state=paper_state or {}, initiative_slug=None,
    )


def _view_patches(m, item, progress):
    return (
        patch.object(m.content_repo, "get_by_slug", return_value=item),
        patch.object(m.content_repo, "progress_for_user", return_value={1: progress}),
        patch.object(m.problem_repo, "all_core", return_value=[]),
        patch.object(m.problem_repo, "all_warmups", return_value=[]),
        patch.object(m.attempt_repo, "all_for_user", return_value=[]),
    )


def test_paper_gets_the_ladder(mock_anthropic, monkeypatch):
    client, m = _client(monkeypatch)
    ps = _view_patches(m, _item(), _progress())
    with ps[0], ps[1], ps[2], ps[3], ps[4]:
        r = client.get("/content/r01-attention")
    assert r.status_code == 200
    assert "Reading passes" in r.text
    assert "Title, abstract, figures" in r.text
    # Pass 3 questions must not be visible before pass 1 is done.
    assert "Which step of the derivation" not in r.text


def test_book_chapter_gets_no_ladder(mock_anthropic, monkeypatch):
    client, m = _client(monkeypatch)
    item = _item(slug="r02-rust", url="https://doc.rust-lang.org/book/ch04.html")
    ps = _view_patches(m, item, _progress())
    with ps[0], ps[1], ps[2], ps[3], ps[4]:
        r = client.get("/content/r02-rust")
    assert r.status_code == 200
    assert "Reading passes" not in r.text
    # The plain reflection survives for non-papers.
    assert "Reflection" in r.text


def test_later_passes_open_as_you_advance(mock_anthropic, monkeypatch):
    client, m = _client(monkeypatch)
    ps = _view_patches(m, _item(), _progress({"pass": 2, "passes": {"1": "x", "2": "y"}}))
    with ps[0], ps[1], ps[2], ps[3], ps[4]:
        r = client.get("/content/r01-attention")
    assert "What is the actual measurement" in r.text


def test_advancing_persists_answers_and_verdict(mock_anthropic, monkeypatch):
    client, m = _client(monkeypatch)
    save = MagicMock()
    with patch.object(m.content_repo, "get_by_id", return_value=_item()), \
         patch.object(m.content_repo, "progress_for_user", return_value={1: _progress()}), \
         patch.object(m.content_repo, "save_paper_state", save):
        r = client.post(
            "/content/1/pass",
            data={"to_pass": "1", "verdict": "park",
                  "q_content.predict": "Probably claims attention alone suffices."},
            follow_redirects=False,
        )
    assert r.status_code == 303
    state = save.call_args.args[2]
    assert state["pass"] == 1
    assert state["verdict"] == "park"
    assert "attention alone" in state["answers"]["content.predict"]


def test_bad_verdict_is_rejected(mock_anthropic, monkeypatch):
    client, m = _client(monkeypatch)
    save = MagicMock()
    with patch.object(m.content_repo, "save_paper_state", save):
        r = client.post("/content/1/pass", data={"to_pass": "1", "verdict": "vibes"})
    assert r.status_code == 400
    save.assert_not_called()


def test_pass_on_unknown_content_404s(mock_anthropic, monkeypatch):
    client, m = _client(monkeypatch)
    with patch.object(m.content_repo, "get_by_id", return_value=None):
        r = client.post("/content/999/pass", data={"to_pass": "1"})
    assert r.status_code == 404


def test_corpus_lists_papers_only(mock_anthropic, monkeypatch):
    client, m = _client(monkeypatch)
    items = [
        _item(),
        _item(slug="r02-rust", url="https://doc.rust-lang.org/book/ch04.html"),
    ]
    items[1].title = "The Rust Book, ch. 4"
    with patch.object(m.content_repo, "all_by_kind", return_value=items), \
         patch.object(m.content_repo, "progress_for_user", return_value={}):
        r = client.get("/papers")
    assert r.status_code == 200
    assert "Attention Is All You Need" in r.text
    assert "The Rust Book" not in r.text


def test_corpus_shows_no_percentage(mock_anthropic, monkeypatch):
    """The table is counts and passes. A completion percentage here would
    be the graded-progress failure BEN-135 exists to prevent."""
    client, m = _client(monkeypatch)
    with patch.object(m.content_repo, "all_by_kind", return_value=[_item()]), \
         patch.object(m.content_repo, "progress_for_user",
                      return_value={1: _progress({"pass": 3})}):
        r = client.get("/papers")
    assert r.status_code == 200
    assert "pass 3 of 4" in r.text
    assert "%" not in r.text
