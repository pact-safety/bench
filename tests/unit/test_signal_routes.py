"""/signal routes — evidence ledger and application tracking."""

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
    from pathlib import Path
    from app.services import criteria as C

    C.set_criteria(C.load_all(Path("content/criteria")))
    monkeypatch.setattr(m, "_user_settings", lambda _uid: {})
    monkeypatch.setattr(
        auth_module, "parse_access_token",
        lambda _tok: UserSession(user_id=_USER, email="u@example.com",
                                 expires_at=2**31 - 1, raw_access_token="x"),
    )
    client = TestClient(m.app)
    client.cookies.set("sb-access-token", "x.y.z")
    return client, m


def _artifact(criterion="c01-shipped-eval-artifact", strength="weak"):
    return SimpleNamespace(
        id="a1", criterion=criterion, title="An eval", url="https://example.com",
        claim_md="Measures refusal consistency.", strength=strength,
        occurred_on=None, created_at=None,
    )


def test_signal_page_renders_coverage_and_next_actions(mock_anthropic, monkeypatch):
    client, m = _client(monkeypatch)
    with patch.object(m.evidence_repo, "by_criterion", return_value={}), \
         patch.object(m.opportunity_repo, "list_for_user", return_value=[]), \
         patch.object(m.opportunity_repo, "outcome_stats",
                      return_value={"total": 0, "by_stage": {}, "rejected_late": 0}):
        r = client.get("/signal")
    assert r.status_code == 200
    assert "Signal" in r.text
    assert "covered" in r.text
    # The honesty line must be on the page, not just in the content files.
    assert "capacity-bound" in r.text


def test_weak_evidence_shows_as_weak_only(mock_anthropic, monkeypatch):
    client, m = _client(monkeypatch)
    with patch.object(m.evidence_repo, "by_criterion",
                      return_value={"c01-shipped-eval-artifact": [_artifact()]}), \
         patch.object(m.opportunity_repo, "list_for_user", return_value=[]), \
         patch.object(m.opportunity_repo, "outcome_stats",
                      return_value={"total": 0, "by_stage": {}, "rejected_late": 0}):
        r = client.get("/signal")
    assert r.status_code == 200
    assert "weak-only" in r.text or "weak only" in r.text


def test_page_survives_a_cold_database(mock_anthropic, monkeypatch):
    """A reporting surface must not 500 because the DB blinked."""
    client, m = _client(monkeypatch)
    with patch.object(m.evidence_repo, "by_criterion", side_effect=RuntimeError("db down")), \
         patch.object(m.opportunity_repo, "list_for_user", side_effect=RuntimeError("db down")), \
         patch.object(m.opportunity_repo, "outcome_stats", side_effect=RuntimeError("db down")):
        r = client.get("/signal")
    assert r.status_code == 200


def test_criterion_detail_renders_strong_and_weak(mock_anthropic, monkeypatch):
    client, m = _client(monkeypatch)
    with patch.object(m.evidence_repo, "by_criterion", return_value={}):
        r = client.get("/signal/criterion/c01-shipped-eval-artifact")
    assert r.status_code == 200
    assert "What strong looks like" in r.text
    assert "What weak looks like" in r.text


def test_unknown_criterion_404s(mock_anthropic, monkeypatch):
    client, _m = _client(monkeypatch)
    assert client.get("/signal/criterion/nope").status_code == 404


def test_add_evidence_requires_a_known_criterion(mock_anthropic, monkeypatch):
    client, m = _client(monkeypatch)
    add = MagicMock()
    with patch.object(m.evidence_repo, "add", add):
        r = client.post("/signal/evidence", data={"criterion": "nope", "title": "x"})
    assert r.status_code == 400
    add.assert_not_called()


def test_add_evidence_persists_and_redirects(mock_anthropic, monkeypatch):
    client, m = _client(monkeypatch)
    add = MagicMock(return_value="new-id")
    with patch.object(m.evidence_repo, "add", add):
        r = client.post(
            "/signal/evidence",
            data={"criterion": "c08-mentor-specific-engagement", "title": " Ran their repo ",
                  "url": "https://example.com", "claim_md": "Found a bug in their eval.",
                  "strength": "partial"},
            follow_redirects=False,
        )
    assert r.status_code == 303
    assert r.headers["location"] == "/signal/criterion/c08-mentor-specific-engagement"
    kw = add.call_args.kwargs
    assert kw["title"] == "Ran their repo"
    assert kw["strength"] == "partial"


def test_add_evidence_rejects_empty_title(mock_anthropic, monkeypatch):
    client, m = _client(monkeypatch)
    add = MagicMock()
    with patch.object(m.evidence_repo, "add", add):
        r = client.post("/signal/evidence",
                        data={"criterion": "c08-mentor-specific-engagement", "title": "  "})
    assert r.status_code == 400
    add.assert_not_called()


def test_track_an_application(mock_anthropic, monkeypatch):
    client, m = _client(monkeypatch)
    add = MagicMock(return_value="opp-1")
    with patch.object(m.opportunity_repo, "add", add):
        r = client.post(
            "/signal/opportunity",
            data={"kind": "fellowship", "org": "PIBBSS", "title": "Summer Fellowship",
                  "location": "remote", "deadline": "2027-01-15", "stage": "submitted"},
            follow_redirects=False,
        )
    assert r.status_code == 303
    kw = add.call_args.kwargs
    assert kw["org"] == "PIBBSS"
    assert kw["location"] == "remote"
    assert str(kw["deadline"]) == "2027-01-15"


def test_application_rejects_a_bad_deadline(mock_anthropic, monkeypatch):
    client, m = _client(monkeypatch)
    add = MagicMock()
    with patch.object(m.opportunity_repo, "add", add):
        r = client.post("/signal/opportunity",
                        data={"kind": "fellowship", "org": "X", "title": "Y",
                              "deadline": "next tuesday"})
    assert r.status_code == 400
    add.assert_not_called()


def test_advancing_keeps_the_feedback(mock_anthropic, monkeypatch):
    """The one durable artifact of a rejection is what they actually said."""
    client, m = _client(monkeypatch)
    advance = MagicMock(return_value=True)
    with patch.object(m.opportunity_repo, "advance", advance):
        r = client.post(
            "/signal/opportunity/opp-1/advance",
            data={"stage": "decision", "outcome": "rejected",
                  "feedback_md": "Strong on engineering, thin on research taste."},
            follow_redirects=False,
        )
    assert r.status_code == 303
    kw = advance.call_args.kwargs
    assert kw["stage"] == "decision"
    assert kw["outcome"] == "rejected"
    assert "research taste" in kw["feedback_md"]


def test_advance_rejects_an_unknown_stage(mock_anthropic, monkeypatch):
    client, m = _client(monkeypatch)
    advance = MagicMock()
    with patch.object(m.opportunity_repo, "advance", advance):
        r = client.post("/signal/opportunity/opp-1/advance", data={"stage": "vibes"})
    assert r.status_code == 400
    advance.assert_not_called()
