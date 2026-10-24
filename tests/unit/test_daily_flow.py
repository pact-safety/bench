"""Tests for app.services.daily_flow — the "Up next" priority order
on Today. Pure function; no DB."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pytest

from app.services import daily_flow
from app.services import tracks as tracks_service
from app.services.track_content import item_slug


@dataclass
class _C:
    """Stand-in for ContentItem — just the attrs daily_flow reads."""
    id: int
    slug: str
    title: str
    kind: str
    duration_min: int | None = None


@dataclass
class _S:
    """Stand-in for a scheduler Scored result — daily_flow only reads
    .problem.id, .problem.slug, .problem.title, .problem.time_bucket,
    .problem.problem_type."""
    problem: object


@dataclass
class _P:
    id: int
    slug: str
    title: str
    time_bucket: int = 30
    problem_type: str = "code_compose"


@dataclass
class _Prog:
    status: str
    checked_at: datetime | None


@pytest.fixture(autouse=True)
def _clear_track_cache():
    tracks_service.set_tracks({})
    yield
    tracks_service.set_tracks({})


def _track_with_sections(*sections: tracks_service.TrackSection) -> tracks_service.Track:
    return tracks_service.Track(
        slug="arena_3",
        title="ARENA 3.0",
        description="",
        source_url="",
        chapters=(tracks_service.TrackChapter(title="Chapter 0", sections=tuple(sections)),),
        body_md="",
    )


def test_empty_queue_with_no_history_suggests_reflect():
    """No content + no attempts + no past reflection → suggest setting
    up the first weekly reflection."""
    nxt = daily_flow.compute_next(today=date.today())
    assert nxt.kind == "reflect"
    assert nxt.url == "/reflect"


def test_empty_queue_with_recent_reflection_is_caught_up():
    nxt = daily_flow.compute_next(
        today=date.today(),
        last_reflection_at=datetime.now() - timedelta(days=1),
    )
    assert nxt.kind == "caught_up"


def test_reading_first_priority():
    reading = _C(id=1, slug="r1", title="The BPE paper", kind="reading", duration_min=30)
    nxt = daily_flow.compute_next(today=date.today(), daily_reading=reading)
    assert nxt.kind == "reading"
    assert nxt.verb == "Read"
    assert nxt.url == "/content/r1"
    assert nxt.duration_min == 30


def test_completed_reading_falls_through_to_watch():
    """A reading completed today should be skipped; the next undone
    surface (video) becomes the next action."""
    reading = _C(id=1, slug="r1", title="r", kind="reading")
    watch = _C(id=2, slug="v1", title="makemore", kind="video")
    done_today = _Prog(status="completed", checked_at=datetime.now())
    nxt = daily_flow.compute_next(
        today=date.today(),
        daily_reading=reading,
        daily_watch=watch,
        progress_by_content_id={1: done_today},
        kinds_done_today={"reading"},
    )
    assert nxt.kind == "watch"
    assert nxt.verb == "Watch"


def test_reading_loop_advances_when_different_unread_reading_picked():
    """REGRESSION: pick_daily excludes completed items, so after the
    user marks reading A complete, the next visit's daily_reading is
    a DIFFERENT (unread) reading B. The old logic checked B's status
    only — B was unread → infinite reading loop. The kinds_done_today
    set fixes this: 'reading' is in the set, so the slot is skipped
    regardless of which unread reading happens to be picked."""
    reading_a = _C(id=1, slug="r1", title="reading A", kind="reading")
    reading_b = _C(id=2, slug="r2", title="reading B (still unread)", kind="reading")
    watch = _C(id=3, slug="v1", title="watch", kind="video")
    # Reading A is the one done today; pick_daily next visit returns B.
    done_today = _Prog(status="completed", checked_at=datetime.now())
    nxt = daily_flow.compute_next(
        today=date.today(),
        daily_reading=reading_b,  # the NEWLY-picked unread reading
        daily_watch=watch,
        progress_by_content_id={1: done_today},  # only A is marked
        kinds_done_today={"reading"},  # but the kind has been done
    )
    assert nxt.kind == "watch", "should advance, not loop on another reading"


def test_watch_and_listen_share_a_slot():
    """Video OR podcast counts — completing either fills the
    watch/listen slot for today."""
    podcast = _C(id=1, slug="p1", title="cool pod", kind="podcast")
    exercise = _C(id=2, slug="e1", title="exercise", kind="exercise")
    # User completed a video today (not the podcast); the picked watch
    # is a podcast (because video already done & filtered out).
    nxt = daily_flow.compute_next(
        today=date.today(),
        daily_watch=podcast,
        daily_exercise=exercise,
        kinds_done_today={"video"},  # video was completed; watch slot done
    )
    assert nxt.kind == "exercise", "watch slot done; should advance to exercise"


def test_watch_slot_not_done_when_no_watch_progress_today():
    """REGRESSION: if no video/podcast progress exists for today,
    we should not treat the watch slot as done just because no watch
    pick is available."""
    reading = _C(id=1, slug="r1", title="r", kind="reading")
    exercise = _C(id=2, slug="e1", title="exercise", kind="exercise")
    done_today = _Prog(status="completed", checked_at=datetime.now())

    nxt = daily_flow.compute_next(
        today=date.today(),
        daily_reading=reading,
        daily_watch=None,
        daily_exercise=exercise,
        progress_by_content_id={1: done_today},
        kinds_done_today={"reading"},
    )

    assert nxt.kind == "watch"
    assert nxt.url == "/library"


def test_video_uses_watch_verb_podcast_uses_listen():
    podcast = _C(id=2, slug="p1", title="cool pod", kind="podcast")
    nxt = daily_flow.compute_next(today=date.today(), daily_watch=podcast)
    assert nxt.verb == "Listen to"
    video = _C(id=2, slug="v1", title="vid", kind="video")
    nxt = daily_flow.compute_next(today=date.today(), daily_watch=video)
    assert nxt.verb == "Watch"


def test_active_track_cursor_zero_yields_track_section_before_axis_fit():
    reading = _C(id=1, slug="r1", title="Fallback reading", kind="reading", duration_min=25)
    track = _track_with_sections(
        tracks_service.TrackSection(
            title="0.1 Prerequisites",
            url="https://example.com/arena/0.1",
            kind="external_reading",
            duration_min=60,
            domain_tags=(),
            axes=(),
        )
    )
    tracks_service.set_tracks({track.slug: track})

    nxt = daily_flow.compute_next(
        today=date.today(),
        user_settings={"active_track": {"slug": track.slug, "cursor": 0}},
        daily_reading=reading,
    )

    assert nxt.kind == "track_section"
    assert nxt.title == "0.1 Prerequisites"
    assert nxt.url == f"/content/{item_slug(track.slug, track.all_sections[0].url)}"
    assert nxt.verb == "Work through"


def test_active_track_cursor_past_end_falls_through_to_axis_fit():
    reading = _C(id=1, slug="r1", title="Fallback reading", kind="reading")
    track = _track_with_sections(
        tracks_service.TrackSection(
            title="0.1",
            url="https://example.com/arena/0.1",
            kind="external_reading",
            duration_min=60,
            domain_tags=(),
            axes=(),
        )
    )
    tracks_service.set_tracks({track.slug: track})

    nxt = daily_flow.compute_next(
        today=date.today(),
        user_settings={"active_track": {"slug": track.slug, "cursor": 99}},
        daily_reading=reading,
    )

    assert nxt.kind == "reading"
    assert nxt.title == "Fallback reading"


def test_active_track_uses_checkpoint_passed_sections_and_dependencies_over_cursor():
    track = _track_with_sections(
        tracks_service.TrackSection(
            title="0.1",
            url="https://example.com/arena/0.1",
            kind="external_reading",
            duration_min=60,
            domain_tags=(),
            axes=(),
        ),
        tracks_service.TrackSection(
            title="0.2",
            url="https://example.com/arena/0.2",
            kind="external_exercise",
            duration_min=45,
            domain_tags=(),
            axes=(),
            depends_on=(0,),
        ),
        tracks_service.TrackSection(
            title="0.3",
            url="https://example.com/arena/0.3",
            kind="external_exercise",
            duration_min=45,
            domain_tags=(),
            axes=(),
            depends_on=(0,),
        ),
    )
    tracks_service.set_tracks({track.slug: track})

    nxt = daily_flow.compute_next(
        today=date.today(),
        user_settings={
            "active_track": {
                "slug": track.slug,
                "cursor": 99,
                "checkpoint_passed_sections": [0],
            }
        },
    )

    assert nxt.kind == "track_section"
    assert nxt.title == "0.2"
    assert nxt.why == "ARENA 3.0 — section 2 of 3"


def test_active_track_with_no_unlocked_sections_falls_through_to_axis_fit():
    reading = _C(id=1, slug="r1", title="Fallback reading", kind="reading")
    track = _track_with_sections(
        tracks_service.TrackSection(
            title="0.1",
            url="https://example.com/arena/0.1",
            kind="external_reading",
            duration_min=60,
            domain_tags=(),
            axes=(),
            depends_on=(1,),
        ),
        tracks_service.TrackSection(
            title="0.2",
            url="https://example.com/arena/0.2",
            kind="external_reading",
            duration_min=60,
            domain_tags=(),
            axes=(),
            depends_on=(0,),
        ),
    )
    tracks_service.set_tracks({track.slug: track})

    nxt = daily_flow.compute_next(
        today=date.today(),
        user_settings={
            "active_track": {
                "slug": track.slug,
                "checkpoint_passed_sections": [],
            }
        },
        daily_reading=reading,
    )

    assert nxt.kind == "reading"
    assert nxt.title == "Fallback reading"


def test_active_track_with_missing_slug_falls_through_and_logs_warning(caplog):
    reading = _C(id=1, slug="r1", title="Fallback reading", kind="reading")

    with caplog.at_level("WARNING"):
        nxt = daily_flow.compute_next(
            today=date.today(),
            user_settings={"active_track": {"slug": "missing_slug", "cursor": 0}},
            daily_reading=reading,
        )

    assert nxt.kind == "reading"
    assert "active track slug 'missing_slug' was not found" in caplog.text


def test_no_active_track_keeps_existing_axis_fit_behavior():
    reading = _C(id=1, slug="r1", title="Fallback reading", kind="reading")

    nxt = daily_flow.compute_next(
        today=date.today(),
        user_settings={},
        daily_reading=reading,
    )

    assert nxt.kind == "reading"
    assert nxt.title == "Fallback reading"


@pytest.mark.parametrize(
    ("section_kind", "expected_verb"),
    [
        ("external_reading", "Work through"),
        ("external_exercise", "Work through"),
        ("problem", "Attempt"),
        ("reflect_weekly", "Reflect on"),
    ],
)
def test_track_section_field_mapping_by_kind(section_kind: str, expected_verb: str):
    section_title = f"Section for {section_kind}"
    section_url = f"https://example.com/{section_kind}"
    track = _track_with_sections(
        tracks_service.TrackSection(
            title=section_title,
            url=section_url,
            kind=section_kind,
            duration_min=45,
            domain_tags=("tag",),
            axes=("axis",),
        )
    )
    tracks_service.set_tracks({track.slug: track})

    nxt = daily_flow.compute_next(
        today=date.today(),
        user_settings={"active_track": {"slug": track.slug, "cursor": 0}},
    )

    assert nxt.kind == "track_section"
    assert nxt.verb == expected_verb
    assert nxt.title == section_title
    assert nxt.url == f"/content/{item_slug(track.slug, track.all_sections[0].url)}"
    assert nxt.why == "ARENA 3.0 — section 1 of 1"
    assert nxt.duration_min == 45
    assert nxt.badge == section_kind


def test_practice_problem_after_content_done():
    """All content done, problem unattempted → practice surface fires."""
    reading = _C(id=1, slug="r", title="r", kind="reading")
    watch = _C(id=2, slug="v", title="v", kind="video")
    exercise = _C(id=3, slug="e", title="e", kind="exercise")
    done_today = _Prog(status="completed", checked_at=datetime.now())
    problem = _S(problem=_P(id=10, slug="softmax", title="Softmax", time_bucket=30))
    nxt = daily_flow.compute_next(
        today=date.today(),
        daily_reading=reading,
        daily_watch=watch,
        daily_exercise=exercise,
        progress_by_content_id={1: done_today, 2: done_today, 3: done_today},
        scored_problems=[problem],
    )
    assert nxt.kind == "practice"
    assert nxt.verb == "Attempt"
    assert nxt.url == "/problem/softmax"


def test_practice_advances_to_reflection_after_any_attempt_today():
    """REGRESSION: once any practice problem is attempted today, the
    practice slot is done for the day and flow should advance."""
    problem_a = _S(problem=_P(id=10, slug="a", title="A"))
    problem_b = _S(problem=_P(id=11, slug="b", title="B"))
    nxt = daily_flow.compute_next(
        today=date.today(),
        scored_problems=[problem_a, problem_b],
        attempts_today_problem_ids={10},
    )
    assert nxt.kind != "practice"
    assert nxt.kind == "reflect"


def test_practice_still_surfaces_when_attempts_today_is_empty():
    """Empty attempts preserves existing behavior: surface a practice
    action from scored problems."""
    problem = _S(problem=_P(id=12, slug="c", title="C"))
    nxt = daily_flow.compute_next(
        today=date.today(),
        scored_problems=[problem],
        attempts_today_problem_ids=set(),
    )
    assert nxt.kind == "practice"
    assert nxt.url == "/problem/c"


def test_reflect_nudge_after_7_days():
    """Last reflection was 8 days ago → suggest a new one."""
    nxt = daily_flow.compute_next(
        today=date.today(),
        last_reflection_at=datetime.now() - timedelta(days=8),
    )
    assert nxt.kind == "reflect"


def test_reflect_not_nudged_if_recent():
    """Last reflection 1 day ago → don't nudge."""
    nxt = daily_flow.compute_next(
        today=date.today(),
        last_reflection_at=datetime.now() - timedelta(days=1),
    )
    assert nxt.kind == "caught_up"
