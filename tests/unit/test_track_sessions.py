"""Track work can be resumed and checkpoint evidence survives interruption."""
from copy import deepcopy
from types import SimpleNamespace
import sys

import pytest

from tests.unit.test_tracks_routes import _signed_in_client, _check_version


@pytest.fixture
def flow(monkeypatch):
    settings = {"active_track": {"slug": "graph", "checkpoint_passed_sections": [0]}}
    client = _signed_in_client(monkeypatch, settings)
    import app.main as m
    feedback = SimpleNamespace(review_checkpoint=lambda **kw: {
        "summary": "Check the boundary case.", "next_action": "Try an empty input.",
        "questions": ["What changes?"], "source": "offline",
    })
    monkeypatch.setitem(sys.modules, "app.services.track_feedback", feedback)
    return client, settings, feedback


def test_session_focus_and_answers_survive_pause_resume(flow):
    client, settings, _ = flow
    base = "/tracks/graph/sections/2"
    assert client.post(base + "/session", data={"stopping_point": "Cell 4", "next_action": "Trace batch", "artifact_url": "https://colab.research.google.com/my-work"}, follow_redirects=False).status_code == 303
    assert client.post(base + "/focus", follow_redirects=False).status_code == 303
    assert client.post(base + "/feedback", data={"check_version": _check_version("graph", 2), "answers": "I can trace the batch.", "confidence": "uncertain"}, follow_redirects=False).status_code == 303
    client.post("/tracks/clear-active", follow_redirects=False)
    client.post("/tracks/graph/activate", follow_redirects=False)
    state = settings["active_track"]
    assert state["preferred_section"] == 2
    assert state["cursor"] == 2
    assert state["session_per_section"]["2"]["stopping_point"] == "Cell 4"
    assert state["checkpoint_response_per_section"]["2"]["answers"] == "I can trace the batch."
    html = client.get("/tracks/graph").text
    assert 'id="section-2"' in html and "Cell 4" in html
    assert "Try an empty input." in client.get(base).text


@pytest.mark.parametrize("suffix,data", [
    ("session", {"stopping_point": "x" * 2001}),
    ("session", {"next_action": "x" * 501}),
    ("session", {"artifact_url": "javascript:alert(1)"}),
    ("session", {"artifact_url": "https://"}),
    ("feedback", {"answers": " ", "confidence": "clear"}),
    ("feedback", {"answers": "x" * 6001, "confidence": "clear"}),
    ("feedback", {"answers": "answer", "confidence": "certain"}),
    ("feedback", {"answers": "answer", "confidence": "clear", "artifact_url": "file:///tmp/x"}),
])
def test_invalid_input_does_not_overwrite(flow, suffix, data):
    client, settings, _ = flow
    before = deepcopy(settings)
    r = client.post(f"/tracks/graph/sections/1/{suffix}", data=data, follow_redirects=False)
    assert r.status_code == 400
    assert settings == before


@pytest.mark.parametrize("suffix,data", [("session", {"stopping_point": "cell"}), ("focus", {}), ("feedback", {"answers": "answer", "confidence": "clear"})])
def test_locked_or_other_track_rejects_mutations(flow, suffix, data):
    client, settings, _ = flow
    settings["active_track"] = {"slug": "graph", "cursor": 0}
    before = deepcopy(settings)
    for track, idx in [("graph", 1), ("prework", 0), ("graph", -1)]:
        r = client.post(f"/tracks/{track}/sections/{idx}/{suffix}", data=data, follow_redirects=False)
        assert r.status_code == 400
        assert settings == before


def test_feedback_failure_preserves_answers_without_passing(flow):
    client, settings, service = flow
    def fail(**kwargs):
        raise RuntimeError("provider failed")
    service.review_checkpoint = fail
    r = client.post("/tracks/graph/sections/1/feedback", data={"check_version": _check_version("graph", 1), "answers": "My explanation", "confidence": "stuck"}, follow_redirects=False)
    assert r.status_code == 303
    state = settings["active_track"]
    response = state["checkpoint_response_per_section"]["1"]
    assert response["answers"] == "My explanation"
    assert response["feedback"]["source"] == "unavailable"
    assert state["checkpoint_passed_sections"] == [0]


def test_completion_requires_saved_clear_answer_and_preserves_it(flow):
    client, settings, _ = flow
    base = "/tracks/graph/sections/1"
    client.post(base + "/complete", follow_redirects=False)
    assert client.post(base + "/complete", data={"checkpoint_pass": 1}, follow_redirects=False).status_code == 400
    client.post(base + "/feedback", data={"check_version": _check_version("graph", 1), "answers": "I am unsure", "confidence": "uncertain"}, follow_redirects=False)
    assert client.post(base + "/complete", data={"checkpoint_pass": 1}, follow_redirects=False).status_code == 400
    client.post(base + "/feedback", data={"check_version": _check_version("graph", 1), "answers": "I traced the result.", "confidence": "clear"}, follow_redirects=False)
    assert client.post(base + "/complete", data={"checkpoint_pass": 1}, follow_redirects=False).status_code == 303
    state = settings["active_track"]
    assert 1 in state["checkpoint_passed_sections"]
    assert state["checkpoint_response_per_section"]["1"]["answers"] == "I traced the result."
    assert "I traced the result." in client.get(base).text


def test_feedback_preserves_newer_answers_and_usage(flow):
    client, settings, service = flow
    def concurrent(**kwargs):
        assert kwargs["request_ai"] is False
        settings["anthropic_today"] = {"tokens": 37}
        record = settings["active_track"]["checkpoint_response_per_section"]["1"]
        record.update(answers="Newer answer", updated_at="newer", feedback={"summary": "Newer guidance"})
        return {"summary": "Old guidance", "source": "self_review"}
    service.review_checkpoint = concurrent
    client.post("/tracks/graph/sections/1/feedback", data={"check_version": _check_version("graph", 1), "answers": "Old answer", "confidence": "clear"}, follow_redirects=False)
    assert settings["anthropic_today"] == {"tokens": 37}
    record = settings["active_track"]["checkpoint_response_per_section"]["1"]
    assert record["answers"] == "Newer answer"
    assert record["feedback"]["summary"] == "Newer guidance"


def test_feedback_does_not_reactivate_track_switched_during_review(flow):
    client, settings, service = flow
    def switch(**kwargs):
        settings["paused_tracks"] = {"graph": deepcopy(settings["active_track"])}
        settings["active_track"] = {"slug": "prework", "cursor": 0}
        settings["anthropic_today"] = {"tokens": 37}
        return {"summary": "Saved with paused track", "source": "self_review"}
    service.review_checkpoint = switch
    client.post("/tracks/graph/sections/1/feedback", data={"check_version": _check_version("graph", 1), "answers": "Answer", "confidence": "clear"}, follow_redirects=False)
    assert settings["active_track"]["slug"] == "prework"
    assert settings["anthropic_today"] == {"tokens": 37}
    assert settings["paused_tracks"]["graph"]["checkpoint_response_per_section"]["1"]["feedback"]["summary"] == "Saved with paused track"


def test_completed_section_cannot_be_overwritten(flow):
    client, settings, _ = flow
    before = deepcopy(settings)
    for suffix, data in [("session", {"stopping_point": "new"}), ("focus", {}), ("feedback", {"answers": "new", "confidence": "clear"})]:
        assert client.post(f"/tracks/graph/sections/0/{suffix}", data=data, follow_redirects=False).status_code == 400
        assert settings == before


def test_saved_clear_answer_cannot_bypass_practical_gate(flow, monkeypatch):
    client, settings, _ = flow
    import app.main as m
    monkeypatch.setattr(m, "_track_gate_status", lambda *_: {"passed": False, "remaining": [{"slug": "needs-retry"}]})
    state = settings["active_track"]
    state["checkpoint_questions_per_section"] = {"1": ["Explain your result."]}
    state["checkpoint_response_per_section"] = {"1": {"answers": "Clear explanation", "confidence": "clear", "check_version": _check_version("graph", 1)}}
    r = client.post("/tracks/graph/sections/1/complete", data={"checkpoint_pass": 1}, follow_redirects=False)
    assert r.status_code == 303
    assert "gate_blocked=needs-retry" in r.headers["location"]
    assert settings["active_track"]["checkpoint_passed_sections"] == [0]


def test_authored_checks_are_available_without_spending_tokens(flow, monkeypatch):
    client, settings, _ = flow
    import app.main as m
    from app.services.track_checks import questions_for_section
    settings["anthropic_today"] = {"tokens": 53}
    def forbidden_review(*args, **kwargs):
        raise AssertionError("Authored checks must not call the exercise reviewer")
    monkeypatch.setattr(m.review_service, "review_attempt", forbidden_review)
    expected = questions_for_section(m.get_track("graph"), 1)
    html = client.get("/tracks/graph/sections/1").text
    assert expected[0] in html
    r = client.post("/tracks/graph/sections/1/complete", follow_redirects=False)
    assert r.status_code == 303
    assert settings["anthropic_today"] == {"tokens": 53}
    assert settings["active_track"]["checkpoint_questions_per_section"]["1"] == expected
