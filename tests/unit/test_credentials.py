"""Tests for app.services.credentials — keyword/Claude parse + iac profile.

Focus on the surface that the JD detail page and gap-suggestion code
depend on: the analyzer's output shape, the iac_profile coercion,
and the fall-back behavior when Claude returns garbage.
"""

from __future__ import annotations

from app.services import credentials as cred


def test_keyword_analyzer_returns_axis_scores_and_no_iac():
    text = (
        "Built training pipelines and fine-tuned transformer models. "
        "Strong experience with optimizers and gradient accumulation."
    )
    out = cred.analyze_keyword(text)
    assert out["method"] == "keyword_fallback"
    assert out["axis_scores"]["training_mechanics"] > 0
    # Keyword fallback has no iac signal — leave it None so the UI
    # hides the block instead of fabricating a mix.
    assert out["iac_profile"] is None
    assert out["iac_evidence_md"] is None


def test_analyze_empty_text_short_circuits():
    out = cred.analyze("   ")
    assert out["method"] == "keyword_fallback"
    assert out["iac_profile"] is None


def test_analyze_with_claude_extracts_iac_profile(mock_anthropic):
    """The Claude path should surface iac_profile + iac_evidence_md
    from the model JSON and round-trip them through analyze()."""
    mock_anthropic.queue(
        '{"axis_scores": {"transformer_internals": 0.8}, '
        '"rationale": {"transformer_internals": "thesis on attention"}, '
        '"summary": "Strong applied transformer experience.", '
        '"iac_profile": {"iterator": 0.6, "amplifier": 0.3, "connector": 0.1}, '
        '"iac_evidence_md": "- PhD thesis iterating on attention variants"}'
    )
    out = cred.analyze("PhD on attention variants. Ran 100+ experiments.")
    assert out["method"] == "claude"
    iac = out["iac_profile"]
    assert iac == {"iterator": 0.6, "amplifier": 0.3, "connector": 0.1}
    assert "attention variants" in out["iac_evidence_md"]


def test_analyze_with_claude_falls_back_keeps_keys_present(mock_anthropic):
    """If Claude returns junk, analyze() falls back to keyword — and
    the keyword path also returns the iac_profile key (set to None)
    so downstream consumers don't KeyError."""
    mock_anthropic.queue("not JSON")
    out = cred.analyze("Training transformer models on the alignment team.")
    assert out["method"] == "keyword_fallback"
    # Key must exist; value is None.
    assert "iac_profile" in out
    assert out["iac_profile"] is None


def test_coerce_iac_profile_clamps_and_handles_garbage():
    assert cred._coerce_iac_profile(None) is None
    assert cred._coerce_iac_profile("nope") is None
    assert cred._coerce_iac_profile({"unrelated": 0.5}) is None
    # Out of range + non-numeric → clamped / zeroed.
    out = cred._coerce_iac_profile(
        {"iterator": 2.0, "amplifier": -1.0, "connector": "x"}
    )
    assert out == {"iterator": 1.0, "amplifier": 0.0, "connector": 0.0}
