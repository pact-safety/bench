"""Tests for the axis taxonomy.

The assessment AXES tuple is the contract surface for:
  - Scheduler weighting (problems' domain_tags must use these strings)
  - JD parse output (axis_weights keys must match)
  - Readiness math (only weights axes the user has scores on)
  - The /library/add axis-pick checkboxes

If an axis is added or renamed, downstream tagging needs to know.
These tests pin the current taxonomy + the AI-safety additions from
feedback #33 so renames produce a loud test failure rather than a
silent data drift.
"""

from __future__ import annotations

from app.services import assessment as assess
from app.services import jds


# --- Existing 10 engineering axes ---------------------------------------


def test_engineering_axes_present():
    """The original ML-engineering axes must remain — content + problem
    tagging across the repo references them by literal string."""
    for axis in (
        "transformer_internals", "training_mechanics", "sampling_decoding",
        "eval_design", "numerical_stability", "debugging",
        "tokenization", "data_pipeline", "algorithmic", "rust_fluency",
    ):
        assert axis in assess.AXES, f"missing required engineering axis: {axis}"


# --- AI-safety axes (feedback #33) --------------------------------------


def test_safety_axes_present():
    """Three safety axes added so BlueDot/AI-Safety-Fundamentals readings
    and interpretability/governance JDs have somewhere to land."""
    for axis in (
        "ai_safety_fundamentals",
        "mechanistic_interpretability",
        "ai_governance_strategy",
    ):
        assert axis in assess.AXES, f"missing safety axis: {axis}"


def test_all_axes_have_labels():
    """Every AXES entry must have a human label in AXIS_LABELS —
    the /library/add form + readiness page render the label, not the key."""
    for axis in assess.AXES:
        assert axis in assess.AXIS_LABELS, f"axis {axis} missing from AXIS_LABELS"
        assert assess.AXIS_LABELS[axis], f"axis {axis} has empty label"


# --- JD parse: keyword fallback covers the new axes --------------------


def test_jd_keyword_fallback_recognizes_safety_language():
    """A JD that explicitly names 'AI safety' + 'interpretability' should
    score on the new axes even without an Anthropic API key (i.e. the
    keyword-fallback path, which is what offline / CI tests use)."""
    text = (
        "Research Engineer, Interpretability. Build mechanistic interpretability "
        "tools using sparse autoencoders. Contribute to our AI safety research "
        "agenda on deceptive alignment and scalable oversight."
    )
    parsed = jds.parse_keyword(text)
    weights = parsed["axis_weights"]
    assert weights["mechanistic_interpretability"] > 0
    assert weights["ai_safety_fundamentals"] > 0
    # And the JD doesn't mention rust, so that axis stays 0.
    assert weights["rust_fluency"] == 0


def test_jd_keyword_fallback_recognizes_governance_language():
    text = (
        "Senior Policy Lead. Shape responsible scaling policy and compute "
        "governance frameworks. Cross-functional work on deployment policy."
    )
    parsed = jds.parse_keyword(text)
    weights = parsed["axis_weights"]
    assert weights["ai_governance_strategy"] > 0


def test_axes_count_is_stable():
    """The current count is 13 (10 engineering + 3 safety). If this
    fails, an axis was added or removed; update downstream consumers
    (template axis-pick lists, JD parse prompt, downstream tests)."""
    assert len(assess.AXES) == 13
