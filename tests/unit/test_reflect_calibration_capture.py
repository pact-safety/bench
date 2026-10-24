"""Route coverage for structured calibration capture on reflection save."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch


_USER_UUID = "11111111-1111-1111-1111-111111111111"


def _signed_in_client(monkeypatch):
    monkeypatch.setenv("LIS_ALLOWED_USER_IDS", _USER_UUID)
    monkeypatch.delenv("LIS_ADMIN_USER_IDS", raising=False)

    import app.main as m
    from app.auth import UserSession
    from fastapi.testclient import TestClient

    monkeypatch.setattr(m, "_user_settings", lambda _uid: {})
    monkeypatch.setattr(
        m.auth_module if hasattr(m, "auth_module") else __import__("app.auth", fromlist=["auth"]),
        "parse_access_token",
        lambda _tok: UserSession(
            user_id=_USER_UUID,
            email="test@example.com",
            expires_at=2**31 - 1,
            raw_access_token="x",
        ),
    )

    client = TestClient(m.app)
    client.cookies.set("sb-access-token", "x.y.z")
    return client, m


def _reflection_with_prompts(prompts):
    from app.models import Reflection

    return Reflection(
        id=9,
        user_id=_USER_UUID,
        period_start=datetime(2026, 5, 10, 0, 0, 0),
        period_end=datetime(2026, 5, 17, 0, 0, 0),
        generated_at=datetime(2026, 5, 17, 0, 0, 0),
        prompts=prompts,
        response_md=None,
        response_updated_at=None,
        summary_md=None,
        method="keyword_fallback",
        model_used=None,
    )


def test_reflect_save_persists_calibration_payload_when_prompt_present(monkeypatch):
    client, m = _signed_in_client(monkeypatch)
    reflection = _reflection_with_prompts(
        [
            {"label": "Avoiding", "prompt": "What are you avoiding?"},
            {"label": "Calibration", "prompt": "What did you predict vs what happened?"},
        ]
    )

    with patch.object(m.reflection_repo, "get", return_value=reflection), \
         patch.object(m.reflection_repo, "save_response") as save_mock:
        r = client.post(
            "/reflect/9/save",
            data={
                "response_md": "  Some free-text reflection.  ",
                "calibration_predicted_pct": "72",
                "calibration_actual_pct": "61",
                "calibration_gap_md": "Overestimated ease after peeking at hints.",
            },
            follow_redirects=False,
        )

    assert r.status_code == 303
    assert r.headers.get("location") == "/reflect/9"

    save_mock.assert_called_once()
    args, kwargs = save_mock.call_args
    assert args == (9, "Some free-text reflection.")
    assert kwargs["calibration_json"] == {
        "predicted_pct": 72,
        "actual_pct": 61,
        "gap_md": "Overestimated ease after peeking at hints.",
    }


def test_reflect_save_ignores_calibration_fields_when_prompt_absent(monkeypatch):
    client, m = _signed_in_client(monkeypatch)
    reflection = _reflection_with_prompts(
        [
            {"label": "Avoiding", "prompt": "What did you avoid this week?"},
            {"label": "Compounding", "prompt": "What compounded?"},
        ]
    )

    with patch.object(m.reflection_repo, "get", return_value=reflection), \
         patch.object(m.reflection_repo, "save_response") as save_mock:
        r = client.post(
            "/reflect/9/save",
            data={
                "response_md": "  Keep existing behavior.  ",
                "calibration_predicted_pct": "90",
                "calibration_actual_pct": "10",
                "calibration_gap_md": "Should not persist for non-calibration prompts.",
            },
            follow_redirects=False,
        )

    assert r.status_code == 303
    assert r.headers.get("location") == "/reflect/9"

    save_mock.assert_called_once()
    args, kwargs = save_mock.call_args
    assert args == (9, "Keep existing behavior.")
    assert kwargs["calibration_json"] is None
