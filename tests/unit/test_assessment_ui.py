"""Assessment snapshots must distinguish missing evidence from measured zero."""
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace as N

import pytest

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, select_autoescape

from app.services import assessment, readiness, skill_stats


def render(name, **context):
    env = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": "{% block body %}{% endblock %}"}),
        FileSystemLoader(Path(__file__).resolve().parents[2] / "templates"),
    ]), autoescape=select_autoescape())
    env.filters.update(pentagon_geometry=skill_stats.pentagon_geometry,
                       jd_title=lambda value: value, markdown=lambda value: value)
    return env.get_template(name).render(**context)


def coverage():
    return {"measured_axes": ("debugging",),
            "unknown_axes": tuple(a for a in assessment.AXES if a != "debugging"),
            "assessed_at": datetime(2026, 9, 20)}


def test_chart_does_not_draw_unknown_stats_at_zero():
    html = render("_skill_chart.html", skill_scores={"debugging": 0.0})
    assert 'class="stat-pentagon__value"' not in html
    assert html.count('class="stat-pentagon__dot ') == 1
    assert "Not assessed" in html
    assert '0<tspan class="stat-badge__pct-unit">%</tspan>' in html
    assert "None" not in html


def test_aim_distinguishes_assessed_zero_from_unknown_axis():
    html = render("aim.html", latest_skill_run=N(completed_at=datetime(2026, 9, 20)),
                  skill_scores={"debugging": 0.0}, axis_labels=assessment.AXIS_LABELS,
                  axis_to_chart={}, calibration_chart={"points": []},
                  assessment_coverage=coverage())
    assert 'data-axis="debugging"' in html
    assert 'class="axis-row__pct">0%</span>' in html
    assert "Not assessed" in html
    assert html.count('class="axis-row__fill"') == 1
    assert "2026-09-20" in html
    assert "1 of 13 axes" in html


def test_result_describes_dated_partial_snapshot():
    html = render("assess_result.html", run=N(id=7), skill_scores={"debugging": 0.0},
                  axis_labels=assessment.AXIS_LABELS, assessment_coverage=coverage())
    assert "2026-09-20" in html
    assert "1 of 13 axes" in html
    assert "Not assessed" in html
    assert "does not automatically update" in html
    assert "re-measure as you go" not in html


def test_onboarding_has_no_unvalidated_time_or_adaptive_claim():
    html = render("onboarding.html")
    assert "~3 min" not in html
    assert "adaptive multiple-choice" not in html
    assert "coverage" in html


def test_readiness_labels_fixed_rate_as_illustrative():
    primary = readiness.snapshot_for_template(readiness.compute(
        user_scores={"debugging": 0.0}, jd_axis_weights={"debugging": 0.8},
        axes=assessment.AXES), assessment.AXIS_LABELS)
    html = render("readiness.html", primary=primary,
                  active_jd=N(id=1, title="Research Engineer", org=""),
                  assessment_coverage=coverage(), has_assessment=True,
                  axis_labels=assessment.AXIS_LABELS, other_jds=[{
                      "id": 2, "title": "Another role", "org": "",
                      "readiness_pct_rounded": 50, "total_hours_rounded": 36,
                      "unknown_axes_count": 2,
                  }])
    assert "50% on assessed axes" in html
    assert "2 JD axes not assessed" in html
    assert "Illustrative" in html
    assert "fixed assumption" in html
    assert "personalized prediction" in html
    assert "2026-09-20" in html
    assert "20 attempts" not in html
    assert "will refine" not in html
    assert 'aria-live="polite"' in html


def test_complete_chart_retains_all_measured_points():
    html = render("_skill_chart.html", skill_scores={a: 0.5 for a in assessment.AXES})
    assert 'class="stat-pentagon__value"' in html
    assert html.count('class="stat-pentagon__dot ') == 5
    assert "Not assessed" not in html


def test_readiness_without_overlapping_evidence_explains_missing_axes():
    html = render("readiness.html", primary={
        "has_data": False, "note": "No assessed axes overlap this JD.",
        "unknown_axes": [{"axis": "algorithmic", "label": "Algorithmic"}],
    }, active_jd=N(id=1), has_assessment=True, has_weighted_jd=True,
        assessment_coverage=coverage(), axis_labels=assessment.AXIS_LABELS)
    assert "JD axes not assessed, excluded from this scenario" in html
    assert "Algorithmic" in html
    assert 'href="/aim#stand"' in html
    assert 'href="/onboarding"' not in html
    assert 'href="/aim#aim"' not in html
    assert 'id="readiness-slider"' not in html


@pytest.mark.parametrize("name", ["assess_result.html", "aim.html"])
def test_fallback_suggestion_does_not_claim_it_is_the_lowest_assessed_axis(name):
    html = render(name, run=N(id=7), latest_skill_run=N(completed_at=datetime(2026, 9, 20)),
                  skill_scores={"debugging": 0.1, "algorithmic": 0.5},
                  axis_labels=assessment.AXIS_LABELS, axis_to_chart={},
                  calibration_chart={"points": []}, assessment_coverage=coverage(),
                  suggestion={"axis_label": "Algorithmic", "problem": N(
                      slug="available", problem_type="code_compose", difficulty="easy",
                      time_bucket=10, title="Available exercise")})
    assert "Suggested assessed focus" in html
    assert "Algorithmic" in html
    assert "lowest" not in html.lower()
    assert "weakest" not in html.lower()


@pytest.mark.parametrize("has_assessment,active_jd,has_weighted_jd,target", [
    (False, None, False, "/onboarding"),
    (True, N(id=1), False, "/aim/jd/1"),
    (True, None, False, "/aim#aim"),
    (True, N(id=1), True, "/aim#stand"),
])
def test_readiness_empty_state_links_to_the_missing_input(
        has_assessment, active_jd, has_weighted_jd, target):
    html = render("readiness.html", primary={"has_data": False, "note": "Missing input"},
                  has_assessment=has_assessment, active_jd=active_jd,
                  has_weighted_jd=has_weighted_jd)
    assert f'href="{target}"' in html
    if has_assessment:
        assert 'href="/onboarding"' not in html
