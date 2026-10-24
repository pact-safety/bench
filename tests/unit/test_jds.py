"""Tests for app.services.jds — URL detection + page-content extraction.

The URL-paste happy path is mostly network-dependent, but the
pure-function helpers (HTML stripping, title/org heuristics) cover
the regression surface. The earlier `og:title` cleanup and the
known-board (Greenhouse / Lever) host map are the things most likely
to break silently."""

from __future__ import annotations

from app.services import jds


def test_looks_like_url_accepts_bare_url():
    assert jds.looks_like_url("https://example.com/jobs/1") == "https://example.com/jobs/1"
    assert jds.looks_like_url("  https://example.com  ") == "https://example.com"


def test_looks_like_url_rejects_free_form_text():
    assert jds.looks_like_url("Research Engineer at Acme") is None
    assert jds.looks_like_url("paste text\nhttps://x") is None
    assert jds.looks_like_url("") is None
    assert jds.looks_like_url("just words") is None


def test_strip_tags_extracts_meta_and_title():
    html = (
        '<title>Research Engineer, Interpretability — Anthropic</title>'
        '<meta property="og:site_name" content="Anthropic">'
        '<meta property="og:title" content="Research Engineer, Interpretability">'
        '<style>.a{}</style>'
        '<p>build evals and run experiments on transformer internals</p>'
    )
    body, meta, page_title = jds._strip_tags_to_text(html)
    assert "transformer internals" in body
    assert meta.get("og:site_name") == "Anthropic"
    assert meta.get("og:title") == "Research Engineer, Interpretability"
    assert "Anthropic" in page_title


def test_title_prefers_og_title():
    meta = {"og:title": "Research Engineer", "og:site_name": "Anthropic"}
    page_title = "Research Engineer — Anthropic"
    assert jds._title_from_meta(meta, page_title) == "Research Engineer"


def test_title_strips_separator_suffix_from_page_title():
    """If only <title> is set, strip trailing ` — Org` / ` - Org`."""
    assert jds._title_from_meta({}, "Research Engineer — Anthropic") == "Research Engineer"
    assert jds._title_from_meta({}, "Backprop · DeepLearning.ai") == "Backprop"
    assert jds._title_from_meta({}, "Just a title") == "Just a title"


# --- title_from_url + is_url_title (URL-slug fallback when fetch fails) ----


def test_title_from_url_extracts_anthropic_jobs_slug():
    """The exact case from in-app feedback #24: home page renders
    'Focused on <raw URL>' because fetch failed and we kept the URL
    as the title. The slug fallback should produce 'Research Engineer
    Interpretability' from this URL shape."""
    out = jds.title_from_url(
        "https://www.anthropic.com/jobs/4569028008-research-engineer-interpretability"
    )
    assert out == "Research Engineer Interpretability"


def test_title_from_url_strips_chrome_words():
    """'jobs', 'careers', etc. shouldn't appear as the first word of
    the derived title. Acronyms (AI, ML, etc.) render upper-case, not
    Capitalize-d — see test_title_from_url_uppercases_known_acronyms."""
    assert jds.title_from_url("https://example.com/jobs/senior-engineer-ai-safety") == "Senior Engineer AI Safety"
    assert jds.title_from_url("https://example.com/careers/research-engineer") == "Research Engineer"


def test_title_from_url_uppercases_known_acronyms():
    """Operator screenshot 2026-06-18: home page rendered 'Focused on
    Software Engineer Ai Safety San Francisco' because the title
    extractor used .capitalize() which produces 'Ai' from 'ai'.
    Known short acronyms (AI, ML, RL, LLM, NLP, etc.) should render
    upper-case instead."""
    assert jds.title_from_url("https://example.com/jobs/software-engineer-ai-safety-san-francisco") == "Software Engineer AI Safety San Francisco"
    assert jds.title_from_url("https://example.com/jobs/ml-platform-engineer") == "ML Platform Engineer"
    assert jds.title_from_url("https://example.com/jobs/rl-research-scientist") == "RL Research Scientist"
    assert jds.title_from_url("https://example.com/jobs/llm-eval-engineer") == "LLM Eval Engineer"
    # Non-acronyms still title-case normally.
    assert jds.title_from_url("https://example.com/jobs/research-engineer-interpretability") == "Research Engineer Interpretability"


def test_title_from_url_handles_numeric_only_segments():
    """If the last segment is pure digits, fall back to the previous
    non-numeric segment."""
    out = jds.title_from_url("https://example.com/jobs/12345/")
    assert out != "12345"
    # /jobs/12345 -> the "12345" segment is numeric → falls back to "jobs"
    # which is then chrome-stripped → empty → "Untitled JD".
    # Either "Untitled JD" or "Jobs" is acceptable but never "12345".
    assert "12345" not in out


def test_title_from_url_underscore_slug():
    assert jds.title_from_url("https://example.com/positions/research_engineer_alignment") == "Research Engineer Alignment"


def test_title_from_url_no_path_returns_untitled():
    """The callsite (jds_create) only invokes this after looks_like_url
    confirms a URL shape, so 'no path' is the only realistic edge case
    inside the function's contract."""
    assert jds.title_from_url("https://example.com") == "Untitled JD"
    assert jds.title_from_url("https://example.com/") == "Untitled JD"


def test_is_url_title_recognizes_http_titles():
    assert jds.is_url_title("https://example.com/jobs/1")
    assert jds.is_url_title("  http://example.com  ")
    assert not jds.is_url_title("Research Engineer, Interpretability")
    assert not jds.is_url_title("")
    assert not jds.is_url_title(None)


def test_org_from_og_site_name():
    assert jds._org_from_url_and_meta(
        "https://www.anthropic.com/jobs/1",
        {"og:site_name": "Anthropic"},
        "Research Engineer — Anthropic",
    ) == "Anthropic"


def test_org_greenhouse_host_parses_from_page_title():
    """Known-board: Greenhouse → org comes from the title separator."""
    org = jds._org_from_url_and_meta(
        "https://boards.greenhouse.io/metr/jobs/1",
        {},
        "Research Engineer · METR",
    )
    assert org == "METR"


def test_org_first_party_host_capitalizes_known_brands():
    org = jds._org_from_url_and_meta(
        "https://www.anthropic.com/jobs/123", {}, "",
    )
    assert org == "Anthropic"
    org = jds._org_from_url_and_meta(
        "https://www.openai.com/careers/x", {}, "",
    )
    assert org == "OpenAI"


def test_keyword_parse_extracts_axes_and_signals():
    """No-API-key path: regex-based axis/signal detection from text."""
    jd_text = (
        "We're hiring engineers to scale our interpretability research. "
        "You'll build evaluation tooling, work with transformer internals, "
        "and handle the data pipeline for training runs. Rust experience a plus."
    )
    parsed = jds.parse_keyword(jd_text)
    assert parsed["method"] == "keyword_fallback"
    # Should pick up several axes
    weights = parsed["axis_weights"]
    assert weights.get("transformer_internals", 0) > 0
    assert weights.get("data_pipeline", 0) > 0
    assert weights.get("eval_design", 0) > 0
    assert weights.get("rust_fluency", 0) > 0
    # And signal tags
    assert "interpretability" in parsed["signal_tags"]
    assert "evals" in parsed["signal_tags"]


def test_parse_with_no_api_key_uses_fallback(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    parsed = jds.parse("Research Engineer on the alignment team. Work on RLHF.")
    assert parsed["method"] == "keyword_fallback"


def test_parse_with_claude_returns_claude_method(mock_anthropic):
    """When the API key is set and Claude succeeds, method=claude."""
    mock_anthropic.queue('{"axis_weights": {"transformer_internals": 1.0}, "signal_tags": ["interpretability"], "summary": "Interp role."}')
    parsed = jds.parse("any jd text")
    assert parsed["method"] == "claude"
    assert parsed["axis_weights"].get("transformer_internals") == 1.0
    assert "interpretability" in parsed["signal_tags"]


def test_parse_with_claude_failure_falls_back(mock_anthropic):
    """If Claude returns garbage, parse() falls back to keyword."""
    mock_anthropic.queue("not JSON at all")
    parsed = jds.parse("Research Engineer working on transformers.")
    assert parsed["method"] == "keyword_fallback"


# --- Iterator / Amplifier / Connector ----------------------------------------


def test_parse_with_claude_extracts_iac_profile(mock_anthropic):
    """The Claude path picks up iac_profile + iac_evidence_md and
    clamps the values to [0, 1]."""
    mock_anthropic.queue(
        '{"axis_weights": {"eval_design": 0.8}, '
        '"signal_tags": ["evals"], '
        '"summary": "Eval infra role.", '
        '"iac_profile": {"iterator": 0.2, "amplifier": 0.7, "connector": 0.1}, '
        '"iac_evidence_md": "- build internal eval infra\\n- support researchers"}'
    )
    parsed = jds.parse("Build internal eval infrastructure for our research team.")
    assert parsed["method"] == "claude"
    iac = parsed["iac_profile"]
    assert iac is not None
    assert iac["iterator"] == 0.2
    assert iac["amplifier"] == 0.7
    assert iac["connector"] == 0.1
    assert "eval infra" in parsed["iac_evidence_md"]


def test_parse_with_claude_clamps_out_of_range_iac_values(mock_anthropic):
    """Out-of-range / garbage iac values are clamped to [0, 1] without
    raising."""
    mock_anthropic.queue(
        '{"axis_weights": {}, "signal_tags": [], "summary": "", '
        '"iac_profile": {"iterator": 1.5, "amplifier": -0.3, "connector": "junk"}}'
    )
    parsed = jds.parse("any text")
    iac = parsed["iac_profile"]
    assert iac == {"iterator": 1.0, "amplifier": 0.0, "connector": 0.0}


def test_keyword_parse_omits_iac_profile():
    """The keyword fallback has no iac signal; it should leave the
    field as None so the UI hides the block instead of fabricating a
    mix."""
    parsed = jds.parse_keyword("Research Engineer on the alignment team.")
    assert parsed["iac_profile"] is None
    assert parsed["iac_evidence_md"] is None


def test_coerce_iac_profile_returns_none_on_garbage():
    assert jds._coerce_iac_profile(None) is None
    assert jds._coerce_iac_profile("not a dict") is None
    # Dict with no recognized keys → None (so callers can default).
    assert jds._coerce_iac_profile({"unrelated": 1.0}) is None
