"""Signal — the evidence half of readiness.

Motivating report (cohort thread): an applicant at 14 rejections, several
at final stage, told repeatedly to do things he had already done; and the
observation that a fellowship returns one bit of feedback, months late.

What this pins:
  - criteria load from FILES and validate (a bad bar file fails loudly)
  - coverage counts `weak` as NOT covered — the whole point is separating
    "I did that" from "a reviewer can see I did that well"
  - next_actions ranks by published emphasis, then cheapness
  - the page never claims a score or a guarantee
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import criteria as C


def _c(slug, weight=3, hours=10, track="all"):
    return C.Criterion(
        slug=slug, title=slug, track=track, weight=weight,
        effort_hours=hours, axes=(), body_md="",
    )


def _art(strength):
    return SimpleNamespace(strength=strength)


# ---------- loading ----------------------------------------------------------


def test_authored_criteria_all_load():
    loaded = C.load_all(Path("content/criteria"))
    assert len(loaded) >= 11
    for slug, crit in loaded.items():
        assert crit.slug == slug
        assert crit.track in C.TRACKS
        assert 1 <= crit.weight <= 5
        assert crit.body_md, f"{slug} has no body"


def test_every_criterion_states_what_weak_looks_like():
    """The strong/weak split is the feature. A criterion missing it is
    just another checklist item, which is the thing that failed."""
    for path in Path("content/criteria").glob("*.md"):
        body = path.read_text().lower()
        assert "what strong looks like" in body, path.name
        assert "what weak looks like" in body, path.name


def test_slug_must_match_filename(tmp_path):
    f = tmp_path / "c99-x.md"
    f.write_text("---\nslug: mismatched\ntitle: x\n---\nbody\n")
    with pytest.raises(ValueError, match="must match the filename"):
        C.load_all(tmp_path)


def test_bad_track_is_rejected(tmp_path):
    f = tmp_path / "c99-x.md"
    f.write_text("---\nslug: c99-x\ntitle: x\ntrack: nonsense\n---\nbody\n")
    with pytest.raises(ValueError, match="track must be one of"):
        C.load_all(tmp_path)


def test_missing_dir_is_empty_not_an_error():
    assert C.load_all(Path("content/does-not-exist")) == {}


# ---------- the gap read -----------------------------------------------------


def test_weak_evidence_does_not_count_as_covered():
    statuses = C.status_for((_c("a"),), {"a": [_art("weak")]})
    assert statuses[0].best_strength == "weak"
    assert statuses[0].covered is False


def test_partial_and_strong_both_cover():
    for s in ("partial", "strong"):
        statuses = C.status_for((_c("a"),), {"a": [_art(s)]})
        assert statuses[0].covered is True, s


def test_best_of_several_artifacts_wins():
    statuses = C.status_for((_c("a"),), {"a": [_art("weak"), _art("strong")]})
    assert statuses[0].best_strength == "strong"


def test_coverage_separates_weak_only_from_empty():
    statuses = C.status_for(
        (_c("a"), _c("b"), _c("c")),
        {"a": [_art("strong")], "b": [_art("weak")]},
    )
    cov = C.coverage(statuses)
    assert cov == {"total": 3, "covered": 1, "weak_only": 1, "empty": 1, "pct": 33}


def test_next_actions_prefer_heavier_then_cheaper():
    statuses = C.status_for(
        (
            _c("heavy-expensive", weight=5, hours=200),
            _c("heavy-cheap", weight=5, hours=15),
            _c("light-cheap", weight=2, hours=5),
        ),
        {},
    )
    picks = [s.criterion.slug for s in C.next_actions(statuses, limit=3)]
    assert picks == ["heavy-cheap", "heavy-expensive", "light-cheap"]


def test_next_actions_keep_weak_only_criteria():
    """'I already did that' usually means the weak version — so a weak
    artifact must not remove the criterion from the work list."""
    statuses = C.status_for((_c("a"), _c("b")), {"a": [_art("weak")], "b": [_art("strong")]})
    picks = [s.criterion.slug for s in C.next_actions(statuses)]
    assert picks == ["a"]


def test_covered_criteria_drop_out_of_next_actions():
    statuses = C.status_for((_c("a"),), {"a": [_art("strong")]})
    assert C.next_actions(statuses) == []


# ---------- the promise the page makes --------------------------------------


def test_no_criterion_promises_selection():
    """Acceptance is capacity-bound and single-digit-percent. Content that
    implies otherwise would be both false and cruel to the audience that
    prompted this surface."""
    # Affirmative promises only — a disclaimer ("none of this guarantees
    # anything") is the behaviour we want, not a violation.
    banned = (
        "will get you in",
        "ensures acceptance",
        "guarantees acceptance",
        "guarantees a place",
        "you will be accepted",
    )
    for path in Path("content/criteria").glob("*.md"):
        body = path.read_text().lower()
        for phrase in banned:
            assert phrase not in body, f"{path.name} contains {phrase!r}"


def test_the_hardest_criteria_say_out_loud_that_they_are_not_sufficient():
    """At least some of the heaviest items must carry the disclaimer. The
    audience for this surface is people already at 14 rejections."""
    hedged = 0
    for path in Path("content/criteria").glob("*.md"):
        body = path.read_text().lower()
        if "guarantee" in body or "not a differentiator" in body or "capacity" in body:
            hedged += 1
    assert hedged >= 3, "criteria should be explicit about what they do not buy"
