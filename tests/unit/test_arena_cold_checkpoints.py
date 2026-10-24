"""BEN-143 — cold checkpoints in tracks.

ARENA's Colab default autocomplete lets a learner tab through exercises
without retrieving anything. The section's own "understanding check" is warm
— you just read the material and self-assess — so it cannot tell the
difference. A cold checkpoint asks for the same capability later, in Compose,
with no completions and a real test run.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services import daily_flow, tracks as tracks_service


def _arena():
    tracks = tracks_service.load_all_tracks(Path("content/tracks"))
    t = tracks.get("arena_3")
    assert t is not None, "arena_3 track should load"
    return t


def _idx_of(track, title):
    for i, s in enumerate(track.all_sections):
        if s.title == title:
            return i
    raise AssertionError(f"section {title!r} not found")


# --- the track file -------------------------------------------------------

def test_cold_checkpoints_parse_off_the_track_file():
    track = _arena()
    idx = _idx_of(track, "1.1 Transformers from Scratch")
    slugs = tracks_service.cold_checkpoint_slugs(track, idx)
    assert "01-scaled-dot-product-attention" in slugs
    assert "03-layernorm-from-scratch" in slugs


def test_every_referenced_problem_actually_exists():
    """A checkpoint pointing at a missing slug sends the learner to a 404 —
    worse than having no checkpoint."""
    available = {p.stem for p in Path("content/problems").glob("*.md")}
    assert available, "no problems found; fixture path wrong"
    track = _arena()
    for i, section in enumerate(track.all_sections):
        for slug in section.cold_checkpoint:
            assert slug in available, (
                f"section {section.title!r} points at problem {slug!r}, "
                f"which does not exist in content/problems/"
            )


def test_sections_without_an_honest_mapping_have_none():
    """Bench's problem set is transformer-shaped. Ray tracing, CNNs and
    generative models have no counterpart, and a loose mapping would make the
    checkpoint a formality."""
    track = _arena()
    for title in ("0.1 Ray Tracing", "0.2 CNNs & ResNets", "0.5 VAEs & GANs"):
        assert tracks_service.cold_checkpoint_slugs(track, _idx_of(track, title)) == ()


def test_a_section_with_no_key_defaults_to_empty_not_error():
    """2.5 has no gate: the bench has RL prep exercises but no runnable RL
    checkpoint problem for MCTS."""
    track = _arena()
    assert tracks_service.cold_checkpoint_slugs(track, _idx_of(track, "2.5 MCTS & AlphaZero")) == ()


def test_prereqs_section_gates_on_the_einsum_problem():
    """0.0 IS einops/einsum/tensor-manipulation — `15-einsum-batched-matmul`
    is a direct capability match, not a loose one, so this section gates."""
    track = _arena()
    slugs = tracks_service.cold_checkpoint_slugs(track, _idx_of(track, "0.0 Prerequisites"))
    assert slugs == ("15-einsum-batched-matmul",)


# --- the daily-flow interleave --------------------------------------------

def test_checkpoint_surfaces_before_the_next_section():
    """The whole point is interleaving. A checkpoint offered only at the end
    of the track is a page you have to remember to visit."""
    track = _arena()
    idx = _idx_of(track, "1.1 Transformers from Scratch")
    action = daily_flow._cold_checkpoint_action(track, idx, set())
    assert action is not None
    assert action.kind == "track_checkpoint"
    assert action.verb == "Prove it cold"
    assert action.url == "/problem/01-scaled-dot-product-attention"
    assert "no autocomplete" in action.why


def test_passed_checkpoints_stop_surfacing():
    track = _arena()
    idx = _idx_of(track, "1.1 Transformers from Scratch")
    slugs = set(tracks_service.cold_checkpoint_slugs(track, idx))
    assert daily_flow._cold_checkpoint_action(track, idx, slugs) is None


def test_it_walks_to_the_next_unpassed_one():
    track = _arena()
    idx = _idx_of(track, "1.1 Transformers from Scratch")
    slugs = list(tracks_service.cold_checkpoint_slugs(track, idx))
    action = daily_flow._cold_checkpoint_action(track, idx, {slugs[0]})
    assert action is not None and action.url == f"/problem/{slugs[1]}"


def test_gate_requires_a_passing_slug():
    track = _arena()
    idx = _idx_of(track, "1.1 Transformers from Scratch")
    first = tracks_service.cold_checkpoint_slugs(track, idx)[0]
    action = daily_flow._cold_checkpoint_action(track, idx, passing_problem_slugs=set())
    assert action.url == f"/problem/{first}"


def test_a_section_without_checkpoints_does_not_block_the_flow():
    track = _arena()
    idx = _idx_of(track, "0.1 Ray Tracing")
    assert daily_flow._cold_checkpoint_action(track, idx, set()) is None
