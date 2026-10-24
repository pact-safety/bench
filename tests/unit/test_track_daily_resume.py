"""Track continuation and retention remain visible without crediting failed runs."""
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, select_autoescape

from app.services import daily_flow, tracks
from app.services.track_content import item_slug

TODAY = date(2026, 9, 25)


@pytest.fixture
def track(monkeypatch):
    monkeypatch.setattr(tracks, 'is_available_track', lambda slug: slug == 'fork')
    sections = tuple(tracks.TrackSection(
        title=f"Section {idx}", url=f"https://example.com/{idx}", kind="external_exercise",
        duration_min=30, domain_tags=(), axes=(), depends_on=deps,
        cold_checkpoint=("checkpoint",) if idx == 1 else (),
    ) for idx, deps in enumerate(((), (), (0,))))
    value = tracks.Track("fork", "Forked track", "", "", (tracks.TrackChapter("Work", sections),), "")
    tracks.set_tracks({value.slug: value})
    yield value
    tracks.set_tracks({})


@pytest.mark.parametrize("preferred,completed,expected", [
    ("1", set(), 1), (1, set(), 1), (2, set(), 0), (2, {0}, 2),
    (1, {1}, 0), (-1, set(), 0), (999, set(), 0), (None, set(), 0),
    (True, set(), 0), (1.9, set(), 0), ("bad", set(), 0),
    ([], set(), 0), (0, {0, 1, 2}, None),
])
def test_preferred_section_is_validated_against_dependencies(track, preferred, completed, expected):
    assert tracks.next_section_index(track, completed, preferred) == expected


def test_failed_checkpoint_stays_next_until_a_passing_run(track):
    kwargs = dict(today=TODAY, user_settings={"active_track": {"slug": "fork", "preferred_section": 1,
                               "checkpoint_passed_sections": [0]}},
                  attempted_problem_slugs={"checkpoint"})
    assert daily_flow.compute_next(**kwargs).kind == "track_checkpoint"
    assert daily_flow.compute_next(**kwargs, passing_problem_slugs={"checkpoint"}).kind == "track_section"


def test_missing_catalogue_checkpoint_does_not_create_dead_link(track):
    action = daily_flow.compute_next(
        today=TODAY, user_settings={"active_track": {"slug": "fork", "preferred_section": 1}},
        available_problem_slugs=set(),
    )
    assert action.kind == "track_section"


def test_saved_next_action_resumes_selected_resource(track):
    state = {"slug": "fork", "preferred_section": 1,
             "session_per_section": {"1": {"stopping_point": "Read two cells",
                 "artifact_url": "https://example.com/notebook", "next_action": "Trace the mask shapes"}}}
    action = daily_flow.compute_next(today=TODAY, user_settings={"active_track": state},
                                     passing_problem_slugs={"checkpoint"})
    assert action.kind == "track_section"
    assert action.verb == "Resume"
    assert action.url == f"/content/{item_slug(track.slug, track.all_sections[1].url)}"
    assert "Trace the mask shapes" in action.why
    assert "Section 1" == action.title


def test_failed_checkpoint_precedes_saved_resume(track):
    state = {"slug": "fork", "preferred_section": 1,
             "session_per_section": {"1": {"next_action": "Continue"}}}
    action = daily_flow.compute_next(today=TODAY, user_settings={"active_track": state})
    assert action.url == "/problem/checkpoint"
    assert action.verb == "Prove it cold"
    assert action.asdict()["resume_url"] == "/tracks/fork/sections/1"
    assert action.asdict()["resume_note"] == "Continue"


def review_inputs():
    return dict(today=TODAY, user_settings={"problem_schedule": {"7": {"due_at": "2026-09-24T12:00:00+00:00"}}},
        problems_by_id={7: SimpleNamespace(title="Softmax", slug="softmax", time_bucket=30)},
        progress_by_content_id={5: SimpleNamespace(recitation_state={"mask": {"due_at": "2026-09-24T12:00:00+00:00"}})},
        content_by_id={5: SimpleNamespace(title="Attention", slug="attention")})


def test_shared_due_review_keeps_recitation_then_problem_priority():
    kwargs = review_inputs()
    action = daily_flow.compute_due_review(**kwargs)
    assert action.kind == "recite"
    assert daily_flow.compute_next(**kwargs) == action
    kwargs["progress_by_content_id"] = {}
    action = daily_flow.compute_due_review(**kwargs)
    assert action.url == "/problem/softmax"
    assert "due again" in action.why
    assert daily_flow.compute_next(**kwargs) == action
    kwargs["problems_by_id"] = {}
    assert daily_flow.compute_due_review(**kwargs) is None


def test_due_review_is_available_independently_of_track_hero(track):
    kwargs = review_inputs()
    kwargs["user_settings"]["active_track"] = {"slug": "fork"}
    assert daily_flow.compute_next(**kwargs).kind == "track_section"
    assert daily_flow.compute_due_review(**kwargs).kind == "recite"


@pytest.mark.parametrize("hero_kind,has_due,visible", [
    ("track_section", True, True), ("track_checkpoint", True, True),
    ("track_section", False, False), ("practice", True, False),
])
def test_home_due_companion_is_accessible_and_only_shown_alongside_track(hero_kind, has_due, visible):
    env = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": "{% block body %}{% endblock %}"}),
        FileSystemLoader(Path(__file__).resolve().parents[2] / "templates"),
    ]), autoescape=select_autoescape(["html"]))
    due = dict(kind="practice", title="Return <problem>", url="/problem/softmax",
               why="This problem is due again.", verb="Attempt") if has_due else None
    html = env.get_template("home.html").render(
        next_action=dict(kind=hero_kind, title="Track hero", url="/tracks/fork", verb="Resume"),
        due_review=due, home_rail={}, progress_by_id={}, scored=[], has_assessment=True,
    )
    assert ('aria-labelledby="due-review-heading"' in html) is visible
    assert "Track hero" in html
    if visible:
        assert 'href="/problem/softmax"' in html
        assert "Return &lt;problem&gt;" in html
        assert "This problem is due again." in html


@pytest.mark.parametrize("progress_key", ["checkpoint_passed_sections", "completed_sections"])
def test_explicit_empty_progress_does_not_credit_sections_before_preferred_cursor(track, progress_key):
    state = {"slug": "fork", "preferred_section": 1, "cursor": 1, progress_key: []}
    assert daily_flow._track_checkpoint_passed_sections(track, state) == set()
    # Choosing an independent branch must not unlock a section that needs 0.
    state["preferred_section"] = 2
    action = daily_flow.compute_next(today=TODAY, user_settings={"active_track": state})
    assert action.url == f"/content/{item_slug(track.slug, track.all_sections[0].url)}"
    assert action.title == "Section 0"


def test_legacy_cursor_without_progress_lists_still_credits_previous_sections(track):
    assert daily_flow._track_checkpoint_passed_sections(track, {"cursor": 1}) == {0}


def test_next_action_wrapper_keeps_explicit_empty_progress_with_later_selection(track, monkeypatch):
    import app.main as m

    captured = {}
    original = daily_flow.compute_next

    def compute_next(**kwargs):
        captured.update(kwargs["user_settings"]["active_track"])
        return original(**kwargs)

    monkeypatch.setattr(m.daily_flow_service, "compute_next", compute_next)
    monkeypatch.setattr(m.problem_repo, "all_core", lambda: [])
    monkeypatch.setattr(m.problem_repo, "all_warmups", lambda: [])
    monkeypatch.setattr(m.reflection_repo, "list_for_user", lambda *args, **kwargs: [])
    monkeypatch.setattr(m.writing_repo, "active_draft_today", lambda *args: None)
    m._compute_next_action("u", scored=[], daily_reading=None, daily_watch=None,
        daily_exercise=None, progress_by_id={}, attempts=[], user_settings={"active_track": {
            "slug": "fork", "preferred_section": 1, "cursor": 1,
            "checkpoint_passed_sections": [], "completed_sections": [],
        }})
    assert captured["checkpoint_passed_sections"] == []
    assert captured["preferred_section"] == 1
    assert daily_flow._track_checkpoint_passed_sections(track, captured) == set()


def test_home_checkpoint_keeps_primary_action_and_shows_saved_resume(track):
    state = {"slug": "fork", "preferred_section": 1,
             "session_per_section": {"1": {"next_action": "Inspect <tensor> shapes"}}}
    action = daily_flow.compute_next(today=TODAY, user_settings={"active_track": state})
    env = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": "{% block body %}{% endblock %}"}),
        FileSystemLoader(Path(__file__).resolve().parents[2] / "templates"),
    ]), autoescape=select_autoescape(["html"]))
    html = env.get_template("home.html").render(
        next_action=action.asdict(), home_rail={}, progress_by_id={}, scored=[], has_assessment=True,
    )
    assert 'class="primary-link" href="/problem/checkpoint"' in html
    assert 'href="/tracks/fork/sections/1">Resume section' in html
    assert "Inspect &lt;tensor&gt; shapes" in html


def test_fresh_atlas_reading_opens_individual_content_page(monkeypatch):
    from pathlib import Path
    catalog = tracks.load_all_tracks(Path("content/tracks"))
    monkeypatch.setattr(tracks, "_tracks_by_slug", catalog)
    monkeypatch.setattr(tracks, "AVAILABLE_TRACK_SLUGS", ("ml4good-prework-fall-2026",))
    action = daily_flow.compute_next(today=TODAY, user_settings={"active_track": {
        "slug": "ml4good-prework-fall-2026", "checkpoint_passed_sections": []}})
    track = catalog["ml4good-prework-fall-2026"]
    assert action.url == f"/content/{item_slug(track.slug, track.all_sections[5].url)}"
    assert action.kind == "track_section"


def test_saved_stopping_point_keeps_context_without_next_action(track):
    state = {"slug": "fork", "preferred_section": 0,
             "session_per_section": {"0": {"stopping_point": "Read two cells"}}}
    action = daily_flow.compute_next(today=TODAY, user_settings={"active_track": state})
    assert action.verb == "Resume"
    assert "Read two cells" in action.why


def test_checkpoint_resume_uses_stopping_point_without_next_action(track):
    state = {"slug": "fork", "preferred_section": 1,
             "session_per_section": {"1": {"stopping_point": "Read two cells"}}}
    action = daily_flow.compute_next(today=TODAY, user_settings={"active_track": state})
    assert action.url == "/problem/checkpoint"
    assert action.resume_url == "/tracks/fork/sections/1"
    assert action.resume_note == "Read two cells"
