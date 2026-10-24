"""Unit coverage for app/services/drills.py — rep-trend parsing.

Pure functions over a chat transcript; no DB, no MIRA coupling. The
transcript is a list of `{"role", "content"}` mappings (the lowest
common denominator across chat surfaces).
"""

from __future__ import annotations

from types import SimpleNamespace

from app.services import drills


def _a(content: str) -> dict:
    """An assistant message."""
    return {"role": "assistant", "content": content}


def _u(content: str) -> dict:
    """A user message."""
    return {"role": "user", "content": content}


# ─── empty / no markers ──────────────────────────────────────────

def test_empty_transcript_returns_empty():
    assert drills.rep_trend_for_session([]) == []


def test_transcript_without_markers_returns_empty():
    msgs = [
        _a("Pick a mode — A (Research Taste) or B (Applied AI)?"),
        _u("A"),
        _a("Here's your scenario. Take your time."),
    ]
    assert drills.rep_trend_for_session(msgs) == []


# ─── single rep ──────────────────────────────────────────────────

def test_single_open_rep_no_end_marker():
    """A started-but-not-ended rep is 'open' with elapsed=None."""
    msgs = [
        _a("=== REP 1 · MODE A · target 20 min ===\nHere is the scenario..."),
        _u("(my submission)"),
    ]
    trend = drills.rep_trend_for_session(msgs)
    assert trend == [
        {"rep": 1, "mode": "A", "target_min": 20, "elapsed_min": None, "status": "open"}
    ]


def test_single_closed_rep_under_target():
    msgs = [
        _a("=== REP 1 · MODE A · target 20 min ===\nScenario..."),
        _u("(submission)"),
        _a("=== END REP 1 · elapsed 18 min ===\nGood. On point 1 you..."),
    ]
    trend = drills.rep_trend_for_session(msgs)
    assert trend == [
        {"rep": 1, "mode": "A", "target_min": 20, "elapsed_min": 18, "status": "under"}
    ]


def test_single_closed_rep_over_target():
    msgs = [
        _a("=== REP 1 · MODE B · target 25 min ===\nLevel 1..."),
        _u("(code)"),
        _a("=== END REP 1 · elapsed 31 min ===\nYou ran over..."),
    ]
    trend = drills.rep_trend_for_session(msgs)
    assert trend[0]["status"] == "over"
    assert trend[0]["mode"] == "B"
    assert trend[0]["elapsed_min"] == 31


# ─── multiple reps ───────────────────────────────────────────────

def test_multiple_reps_mixed_modes_in_order():
    msgs = [
        _a("=== REP 1 · MODE A · target 20 min ==="),
        _u("(sub 1)"),
        _a("=== END REP 1 · elapsed 22 min ==="),
        _a("=== REP 2 · MODE B · target 25 min ==="),
        _u("(sub 2)"),
        _a("=== END REP 2 · elapsed 19 min ==="),
    ]
    trend = drills.rep_trend_for_session(msgs)
    assert [r["rep"] for r in trend] == [1, 2]
    assert [r["mode"] for r in trend] == ["A", "B"]
    assert [r["status"] for r in trend] == ["over", "under"]


def test_partial_last_rep_stays_open():
    """Reps 1-2 closed, rep 3 started but in progress."""
    msgs = [
        _a("=== REP 1 · MODE A · target 20 min ==="),
        _a("=== END REP 1 · elapsed 18 min ==="),
        _a("=== REP 2 · MODE A · target 20 min ==="),
        _a("=== END REP 2 · elapsed 17 min ==="),
        _a("=== REP 3 · MODE A · target 20 min ==="),
        _u("(working on it)"),
    ]
    trend = drills.rep_trend_for_session(msgs)
    assert len(trend) == 3
    assert trend[2] == {
        "rep": 3, "mode": "A", "target_min": 20, "elapsed_min": None, "status": "open"
    }


# ─── robustness ──────────────────────────────────────────────────

def test_separator_tolerance_dash_and_pipe():
    """A model that reformats the middot to a dash or pipe still parses."""
    msgs = [
        _a("=== REP 1 - MODE A - target 20 min ==="),
        _a("=== END REP 1 | elapsed 15 min ==="),
    ]
    trend = drills.rep_trend_for_session(msgs)
    assert trend[0]["status"] == "under"
    assert trend[0]["elapsed_min"] == 15


def test_end_without_start_is_ignored():
    """Defensive: a stray END with no matching START doesn't crash or
    invent a rep."""
    msgs = [_a("=== END REP 5 · elapsed 10 min ===")]
    assert drills.rep_trend_for_session([*msgs]) == []


def test_markers_only_scanned_in_assistant_turns():
    """A user pasting the marker text shouldn't register as a rep."""
    msgs = [
        _u("=== REP 1 · MODE A · target 20 min ==="),  # user, ignored
        _a("Let's start for real."),
    ]
    assert drills.rep_trend_for_session(msgs) == []


def test_accepts_objects_not_just_dicts():
    """Works on objects with .role/.content (e.g. a future MiraTurn),
    not just dict messages — the structural-typing contract."""
    msgs = [
        SimpleNamespace(role="assistant", content="=== REP 1 · MODE A · target 20 min ==="),
        SimpleNamespace(role="assistant", content="=== END REP 1 · elapsed 21 min ==="),
    ]
    trend = drills.rep_trend_for_session(msgs)
    assert trend[0]["status"] == "over"


def test_duplicate_start_updates_target_not_duplicates_rep():
    """If the persona re-announces a rep (same number), we update the
    record rather than emitting two rows."""
    msgs = [
        _a("=== REP 1 · MODE A · target 20 min ==="),
        _a("=== REP 1 · MODE A · target 25 min ==="),  # re-announced, longer
        _a("=== END REP 1 · elapsed 23 min ==="),
    ]
    trend = drills.rep_trend_for_session(msgs)
    assert len(trend) == 1
    assert trend[0]["target_min"] == 25
    assert trend[0]["status"] == "under"  # 23 <= 25


# ─── trend_summary ───────────────────────────────────────────────

def test_trend_summary_empty_when_nothing_closed():
    assert drills.trend_summary([]) == ""
    open_only = [{"rep": 1, "mode": "A", "target_min": 20, "elapsed_min": None, "status": "open"}]
    assert drills.trend_summary(open_only) == ""


def test_trend_summary_reports_faster_direction():
    trend = drills.rep_trend_for_session([
        _a("=== REP 1 · MODE A · target 20 min ==="),
        _a("=== END REP 1 · elapsed 22 min ==="),
        _a("=== REP 2 · MODE A · target 20 min ==="),
        _a("=== END REP 2 · elapsed 18 min ==="),
    ])
    summary = drills.trend_summary(trend)
    assert "Rep 1: 22/20m (over)" in summary
    assert "Rep 2: 18/20m (under)" in summary
    assert "trending faster" in summary


def test_trend_summary_single_closed_rep_no_direction():
    trend = drills.rep_trend_for_session([
        _a("=== REP 1 · MODE A · target 20 min ==="),
        _a("=== END REP 1 · elapsed 18 min ==="),
    ])
    summary = drills.trend_summary(trend)
    assert "Rep 1: 18/20m (under)" in summary
    assert "trending" not in summary  # need >= 2 closed reps for direction
