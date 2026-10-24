"""Track checkpoints gated on demonstrated application.

Before this, a checkpoint was self-attested: the route surfaced Socratic
questions and the second click recorded a pass, with nothing checked. A
learner who tabbed through a Colab could mark every section complete.

Now a section that names `cold_checkpoint` problems will not complete until
those problems have actually run green for this user. Mastery-learning
practice (Bloom; Keller's PSI) puts the gate at demonstrated performance with
unlimited, unpenalized retakes — which is what attempts already are.

Sections with no honest problem mapping keep the older understanding check,
and say so rather than pretending to a rigour they don't have.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services import tracks as tracks_service


_USER = "22222222-2222-2222-2222-222222222222"


def _section(cold=(), prep=()):
    return tracks_service.TrackSection(
        title="1.1 Transformers from Scratch",
        url="https://learn.arena.education/chapter1_transformer_interp/01_transformers/",
        kind="external_exercise",
        duration_min=480,
        domain_tags=(),
        axes=(),
        cold_checkpoint=tuple(cold),
        prep=tuple(prep),
    )


# ---------- gate resolution --------------------------------------------------


def test_no_cold_checkpoint_means_no_gate(mock_anthropic):
    import app.main as m

    assert m._track_gate_status(_section(), _USER) is None


def test_gate_reports_per_problem_pass_state(mock_anthropic):
    import app.main as m

    problems = {
        "a-slug": MagicMock(id=1, title="A"),
        "b-slug": MagicMock(id=2, title="B"),
    }
    with patch.object(m.problem_repo, "get_by_slug", side_effect=lambda s: problems.get(s)), \
         patch.object(m.attempt_repo, "has_passing_attempt", side_effect=lambda u, pid: pid == 1):
        gate = m._track_gate_status(_section(cold=["a-slug", "b-slug"]), _USER)

    assert gate["total"] == 2
    assert gate["passed_count"] == 1
    assert gate["passed"] is False
    assert [i["slug"] for i in gate["remaining"]] == ["b-slug"]


def test_gate_passes_only_when_every_problem_is_green(mock_anthropic):
    import app.main as m

    with patch.object(m.problem_repo, "get_by_slug", return_value=MagicMock(id=1, title="A")), \
         patch.object(m.attempt_repo, "has_passing_attempt", return_value=True):
        gate = m._track_gate_status(_section(cold=["a-slug", "b-slug"]), _USER)

    assert gate["passed"] is True
    assert gate["remaining"] == []


def test_gate_fails_closed_on_lookup_error(mock_anthropic):
    """A gate we cannot read must not strand a learner mid-track."""
    import app.main as m

    with patch.object(m.problem_repo, "get_by_slug", side_effect=RuntimeError("db down")):
        gate = m._track_gate_status(_section(cold=["a-slug"]), _USER)
        assert gate["passed"] is False
        assert gate["unavailable"] is True


def test_gate_fails_closed_for_missing_problem(mock_anthropic):
    """A stale slug should not silently become an unpassable gate."""
    import app.main as m

    with patch.object(m.problem_repo, "get_by_slug", return_value=None):
        gate = m._track_gate_status(_section(cold=["gone"]), _USER)
        assert gate["passed"] is False
        assert gate["total"] == 1
        assert gate["unavailable"] is True


# ---------- prep resolution --------------------------------------------------


def test_prep_items_resolve_and_drop_missing(mock_anthropic):
    import app.main as m

    known = {"e11-x": MagicMock(title="Rearrange", kind="exercise", duration_min=8)}
    with patch.object(m.content_repo, "get_by_slug", side_effect=lambda s: known.get(s)):
        items = m._track_prep_items(_section(prep=["e11-x", "does-not-exist"]))

    assert [i["slug"] for i in items] == ["e11-x"]
    assert items[0]["title"] == "Rearrange"


# ---------- the authored track ----------------------------------------------


def _arena():
    return tracks_service.load_all_tracks(Path("content/tracks"))["arena_3"]


def test_track_covers_all_five_chapters_on_the_live_host():
    """Exercises moved to learn.arena.education; the old streamlit apps are
    not where a learner should be sent."""
    track = _arena()
    assert len(track.chapters) == 5
    urls = [s.url for s in track.all_sections]
    assert all(u.startswith("https://learn.arena.education/") for u in urls)
    assert not any("streamlit.app" in u for u in urls)


def test_every_prep_slug_resolves_to_an_authored_exercise():
    """A prep link to a missing file is a 404 in the learner's face at
    exactly the moment they were told to prepare."""
    track = _arena()
    available = {p.stem for p in Path("content/exercises").glob("*.md")}
    for section in track.all_sections:
        for slug in section.prep:
            assert slug in available, f"{section.title!r} preps missing {slug!r}"


def test_the_first_three_weeks_are_gated():
    """A six-week cohort spends weeks 1-3 in chapters 0, 1 and 3 — the
    strongly-gated ones. If gating regressed there, the track's central
    claim is false."""
    track = _arena()
    gated = {s.title for s in track.all_sections if s.cold_checkpoint}
    assert "0.0 Prerequisites" in gated
    assert "1.1 Transformers from Scratch" in gated
    assert "1.2 Intro to Mech Interp" in gated
    assert "3.1 Intro to Evals" in gated


def test_prep_exists_for_every_gated_section_in_chapter_0_and_1():
    """Gating without prep is just a harder wall. Where we gate early, we
    also hand the learner the decomposition first."""
    track = _arena()
    for s in track.all_sections:
        if s.cold_checkpoint and (s.title.startswith("0.") or s.title.startswith("1.")):
            assert s.prep, f"{s.title!r} gates but offers no prep"
