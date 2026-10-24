"""BEN-135 recitation grader + recite route.

The load-bearing test here is `test_grade_output_has_no_score_field` — the
whole feature's constraint is that grading never produces a number, even if
the model tries to emit one.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services import recitation


_SCORE_KEYS = {
    "score", "overall_score", "grade", "percent", "percentage",
    "points", "correct", "total", "rating", "mark", "pct",
}


def _flat_keys(obj) -> set[str]:
    keys: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            keys.add(str(k).lower())
            keys |= _flat_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            keys |= _flat_keys(v)
    return keys


# ---- the grading constraint ------------------------------------------------


def test_grade_output_has_no_score_field():
    """Even when the model sneaks a score/grade into its JSON, the sanitiser
    drops it — no numeric summary can ever reach the UI."""
    sneaky = {
        "covered": ["softmax"],
        "missing": [{"concept": "attention mask", "where": "§2", "prompt": "when?"}],
        "misstated": [],
        "open_question": "why pre-softmax?",
        # the model tried to grade him anyway:
        "score": 62, "overall_score": 0.62, "grade": "B-", "percentage": 62,
    }
    out = recitation._sanitize(sneaky)
    assert _flat_keys(out) & _SCORE_KEYS == set()
    # the real content survives
    assert out["covered"] == ["softmax"]
    assert out["missing"][0]["concept"] == "attention mask"
    assert out["open_question"] == "why pre-softmax?"


def test_grade_skipped_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = recitation.grade("source", "transcript")
    assert out["method"] == "skipped"
    assert out["covered"] == [] and out["missing"] == []
    assert _flat_keys(out) & _SCORE_KEYS == set()


def test_sanitize_shape_is_stable():
    out = recitation._sanitize({})
    assert set(out) == {"method", "covered", "missing", "misstated",
                        "open_question", "error_text"}


# ---- recite route ----------------------------------------------------------

_ADMIN = "11111111-1111-1111-1111-111111111111"


def _client(monkeypatch):
    monkeypatch.setenv("LIS_ADMIN_USER_IDS", _ADMIN)
    import app.main as m
    import app.auth as auth_module
    from app.auth import UserSession
    from fastapi.testclient import TestClient

    monkeypatch.setattr(m, "_user_settings", lambda _u: {})
    monkeypatch.setattr(
        auth_module, "parse_access_token",
        lambda _t: UserSession(user_id=_ADMIN, email="op@x.com",
                               expires_at=2**31 - 1, raw_access_token="x"),
    )
    c = TestClient(m.app)
    c.cookies.set("sb-access-token", "x.y.z")
    return c, m


def test_recite_route_grades_and_schedules(monkeypatch):
    c, m = _client(monkeypatch)
    item = MagicMock(version=1, content_md="The attention mask is applied before the softmax.")
    graded = {
        "method": "claude",
        "covered": ["softmax"],
        "missing": [{"concept": "attention mask", "where": "§2", "prompt": "when applied?"}],
        "misstated": [],
        "open_question": "why before, not after?",
        "error_text": None,
    }
    with patch.object(m.content_repo, "get_by_id", return_value=item), \
         patch.object(m.content_repo, "progress_for_user", return_value={}), \
         patch.object(m.content_repo, "save_recitation_state") as save, \
         patch("app.services.transcription.transcribe",
               return_value={"text": "um, softmax happens", "duration_seconds": 3.0}), \
         patch("app.services.recitation.grade", return_value=graded):
        r = c.post(
            "/content/1/recite",
            data={"mode": "review"},
            files={"audio": ("r.webm", b"AUDIODATA", "audio/webm")},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["missing"][0]["concept"] == "attention mask"
    assert _flat_keys(body) & _SCORE_KEYS == set()   # no score in the response
    save.assert_called_once()                        # schedule was persisted
