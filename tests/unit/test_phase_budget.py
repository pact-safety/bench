"""Unit coverage for app/services/phase_budget.py.

Pure functions over per-attempt time tracking; no DB, no I/O. Tests
the four moving parts:

  - default_budgets(): proportional split + sum invariant
  - validate_budgets(): catches missing/extra phases, negative
    values, sum mismatch
  - phase_status(): soft warn at 80%, over at 100%
  - compose_review_breakdown(): per-phase rows with under/on_budget/
    over status

Interview-mode v1 spec: docs/proposals/interview-mode-v2.md
"""

from __future__ import annotations

from app.services import phase_budget as svc


# ─── default_budgets ─────────────────────────────────────────────

def test_default_budgets_for_code_compose_sums_to_time_bucket():
    """The default proportional split sums exactly to time_bucket * 60
    seconds. Rounding error is absorbed by implement (the biggest
    slice) so the total stays correct."""
    budgets = svc.default_budgets(time_bucket_minutes=20, problem_type="code_compose")
    assert set(budgets.keys()) == set(svc.PHASES)
    assert sum(budgets.values()) == 20 * 60
    # implement is the biggest slice for code_compose
    assert budgets["implement"] == max(budgets.values())


def test_default_budgets_falls_back_to_code_compose_for_unknown_type():
    """A problem with an unrecognized problem_type still gets a
    sensible default — the bench's most common shape."""
    unknown = svc.default_budgets(time_bucket_minutes=15, problem_type="future_type_42")
    fallback = svc.default_budgets(time_bucket_minutes=15, problem_type="code_compose")
    assert unknown == fallback


def test_default_budgets_for_code_read_weights_explore():
    """Read problems should put most of the budget into explore +
    brainstorm — the proportions table reflects 'understand existing
    code' rather than 'write new code'."""
    budgets = svc.default_budgets(time_bucket_minutes=20, problem_type="code_read")
    assert budgets["explore"] > budgets["implement"]


def test_default_budgets_for_design_only_collapses_implement_and_verify():
    """Design problems don't ship code, so implement + verify get
    tiny slices."""
    budgets = svc.default_budgets(time_bucket_minutes=30, problem_type="design_only")
    assert budgets["implement"] + budgets["verify"] < budgets["plan"]


def test_default_budgets_zero_time_bucket_returns_zero_everywhere():
    """Pathological input — 0-minute problem — doesn't crash; just
    returns all-zero budgets so the soft-warn / cutoff math never
    blows up on a divide-by-zero."""
    budgets = svc.default_budgets(time_bucket_minutes=0, problem_type="code_compose")
    assert all(v == 0 for v in budgets.values())


# ─── validate_budgets ────────────────────────────────────────────

def test_validate_passes_on_canonical_budget():
    budgets = svc.default_budgets(time_bucket_minutes=20, problem_type="code_compose")
    ok, reason = svc.validate_budgets(budgets, time_bucket_minutes=20)
    assert ok, reason
    assert reason == ""


def test_validate_catches_missing_phase():
    bad = {p: 60 for p in svc.PHASES if p != "verify"}
    ok, reason = svc.validate_budgets(bad, time_bucket_minutes=5)
    assert not ok
    assert "verify" in reason.lower() or "missing" in reason.lower()


def test_validate_catches_extra_phase():
    bad = {p: 60 for p in svc.PHASES}
    bad["meditate"] = 60
    ok, reason = svc.validate_budgets(bad, time_bucket_minutes=6)
    assert not ok
    assert "meditate" in reason.lower() or "unknown" in reason.lower()


def test_validate_catches_negative_budget():
    bad = svc.default_budgets(time_bucket_minutes=20, problem_type="code_compose")
    bad["explore"] = -10
    ok, reason = svc.validate_budgets(bad, time_bucket_minutes=20)
    assert not ok
    assert "explore" in reason


def test_validate_catches_sum_mismatch():
    """If the operator authors budgets whose sum is wildly off
    time_bucket, we reject — guards against typos that would let the
    cutoff fire at the wrong instant."""
    bad = {p: 60 for p in svc.PHASES}  # total = 300s = 5min
    ok, reason = svc.validate_budgets(bad, time_bucket_minutes=20)  # expects 1200s
    assert not ok
    assert "sum" in reason.lower() or "1200" in reason or "300" in reason


def test_validate_tolerates_small_rounding_drift():
    """±10s drift is OK so operator-authored TOMLs don't fail
    validation over rounding."""
    near = {p: 60 for p in svc.PHASES}  # total = 300s
    near["implement"] += 5  # total = 305s
    ok, _ = svc.validate_budgets(near, time_bucket_minutes=5)  # expects 300s
    assert ok


# ─── phase_status ────────────────────────────────────────────────

def test_phase_status_returns_ok_below_soft_threshold():
    """Under 80% of the budget → 'ok'."""
    assert svc.phase_status(elapsed_seconds=100, budget_seconds=200) == "ok"


def test_phase_status_returns_soft_warn_at_threshold():
    """At exactly 80% → 'soft_warn' (the operator sees the toast)."""
    assert svc.phase_status(elapsed_seconds=160, budget_seconds=200) == "soft_warn"


def test_phase_status_returns_over_at_100_percent():
    """At or past 100% → 'over' (operator should have moved on)."""
    assert svc.phase_status(elapsed_seconds=200, budget_seconds=200) == "over"
    assert svc.phase_status(elapsed_seconds=999, budget_seconds=200) == "over"


def test_phase_status_handles_zero_budget_gracefully():
    """Zero or negative budget → 'ok' (we don't want a divide-by-zero
    or a phantom 'over' on a phase the operator opted out of)."""
    assert svc.phase_status(elapsed_seconds=50, budget_seconds=0) == "ok"
    assert svc.phase_status(elapsed_seconds=50, budget_seconds=-10) == "ok"


# ─── total_budget_seconds ────────────────────────────────────────

def test_total_budget_seconds_sums_canonical_budget():
    budgets = svc.default_budgets(time_bucket_minutes=20, problem_type="code_compose")
    assert svc.total_budget_seconds(budgets) == 20 * 60


def test_total_budget_seconds_defends_against_garbage():
    """If a row has corrupted JSON (string values, missing keys),
    we still return a usable number rather than raising — the
    middleware that reads this won't crash on a bad attempt row."""
    assert svc.total_budget_seconds(None) == 0
    assert svc.total_budget_seconds({}) == 0
    assert svc.total_budget_seconds({"explore": "not_a_number"}) == 0
    assert svc.total_budget_seconds({"explore": 100, "junk": 5000}) == 100


# ─── compose_review_breakdown ────────────────────────────────────

def test_review_breakdown_marks_on_budget_within_tolerance():
    """When elapsed % roughly tracks budget %, status = 'on_budget'.
    The ±5pp tolerance avoids flagging healthy jitter as a problem."""
    elapsed = {"explore": 180, "brainstorm": 240, "plan": 180, "implement": 480, "verify": 120}
    budgets = elapsed.copy()  # exact match
    rows = svc.compose_review_breakdown(elapsed, budgets)
    assert len(rows) == 5
    for r in rows:
        assert r["status"] == "on_budget"


def test_review_breakdown_marks_over_when_phase_runs_long():
    elapsed = {"explore": 100, "brainstorm": 100, "plan": 100, "implement": 800, "verify": 100}
    budgets = {"explore": 180, "brainstorm": 240, "plan": 180, "implement": 480, "verify": 120}
    rows = svc.compose_review_breakdown(elapsed, budgets)
    impl = next(r for r in rows if r["phase"] == "implement")
    assert impl["status"] == "over"


def test_review_breakdown_returns_empty_when_no_data():
    """Legacy attempts (no phase_time_seconds OR no phase_budgets)
    skip the breakdown — the template hides the section."""
    assert svc.compose_review_breakdown(None, {"explore": 100}) == []
    assert svc.compose_review_breakdown({"explore": 100}, None) == []
    assert svc.compose_review_breakdown({}, {}) == []


def test_review_breakdown_handles_partial_phase_times():
    """If the operator only worked some phases (e.g., didn't reach
    verify), the missing phases default to 0 elapsed but are still
    in the rendered row list."""
    elapsed = {"explore": 180, "brainstorm": 240, "plan": 180, "implement": 600}
    budgets = svc.default_budgets(time_bucket_minutes=20, problem_type="code_compose")
    rows = svc.compose_review_breakdown(elapsed, budgets)
    verify = next(r for r in rows if r["phase"] == "verify")
    assert verify["elapsed"] == 0


# ─── fmt_seconds ─────────────────────────────────────────────────

def test_fmt_seconds_renders_minutes_and_seconds():
    assert svc.fmt_seconds(0) == "0s"
    assert svc.fmt_seconds(45) == "45s"
    assert svc.fmt_seconds(60) == "1m"
    assert svc.fmt_seconds(90) == "1m 30s"
    assert svc.fmt_seconds(3600) == "1h 0m"
    assert svc.fmt_seconds(3700) == "1h 1m"


def test_fmt_seconds_defends_against_none_and_negative():
    assert svc.fmt_seconds(None) == "0s"
    assert svc.fmt_seconds(-30) == "0s"
