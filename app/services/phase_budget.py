"""Interview-mode v1 — per-phase budget math.

Pure functions over per-attempt time tracking. No I/O, no DB; the
attempt repo stores `time_per_phase` and `phase_budgets` as JSONB on
the attempts row, and this service composes the read-side views the
template + review surface use.

Phase vocab matches the Engineering Method on /problem:
    explore · brainstorm · plan · implement · verify

The five phases sum to `time_bucket * 60` seconds. Problems can
override budgets via the `phase_budgets_seconds` TOML field; if
omitted, `default_budgets()` returns a proportional split.

Why not store budgets only on the Problem? Because budgets evolve.
Each attempt snapshots its budgets so historical review pages stay
accurate even when the operator re-tunes the problem's budgets
later. The repo writes problem.phase_budgets at submit time; this
service just reads it back.

Operator-facing semantics:
    - soft warning at 80% of the active phase budget (toast in the
      corner; doesn't block input)
    - hard cutoff at 100% of total session time (form locks, review
      fires against whatever the operator has, reflection prompt
      opens, attempt is marked `cutoff=True`)
"""

from __future__ import annotations

from typing import Iterable


# Canonical phase ordering. Used for default-budget allocation +
# review-breakdown rendering. Keep in sync with EM_PHASES in models.py.
PHASES: tuple[str, ...] = ("explore", "brainstorm", "plan", "implement", "verify")


# Default proportional split — used when a problem's TOML doesn't
# carry `phase_budgets_seconds`. Calibrated against the operator's
# Engineering Method intent: small slice for exploration (~15% — read
# the prompt, list constraints), bigger for brainstorming options
# (~20%), small slice for picking the plan (~15%), the bulk for
# implementation (~40%), small slice for verification (~10%).
#
# code_read and design_only problems have less to implement; their
# defaults shift weight toward earlier phases. Operators can still
# override per-problem in the TOML.
_DEFAULT_PROPORTIONS: dict[str, dict[str, float]] = {
    "code_compose": {"explore": 0.15, "brainstorm": 0.20, "plan": 0.15, "implement": 0.40, "verify": 0.10},
    "code_debug":   {"explore": 0.25, "brainstorm": 0.15, "plan": 0.15, "implement": 0.35, "verify": 0.10},
    "code_read":    {"explore": 0.40, "brainstorm": 0.20, "plan": 0.20, "implement": 0.15, "verify": 0.05},
    "design_only":  {"explore": 0.30, "brainstorm": 0.30, "plan": 0.30, "implement": 0.05, "verify": 0.05},
}


def default_budgets(time_bucket_minutes: int, problem_type: str) -> dict[str, int]:
    """Return a proportional per-phase budget split in seconds.

    Used when a problem TOML doesn't carry an explicit
    `phase_budgets_seconds` block. The split sums to
    `time_bucket * 60` exactly; rounding error is allocated to
    `implement` (the biggest slice) so the total stays correct.

    Unknown problem_type falls back to the `code_compose` shape —
    it's the most common case in the bench's library.
    """
    total = max(0, int(time_bucket_minutes)) * 60
    proportions = _DEFAULT_PROPORTIONS.get(problem_type, _DEFAULT_PROPORTIONS["code_compose"])
    budgets: dict[str, int] = {}
    for phase in PHASES:
        budgets[phase] = int(total * proportions[phase])
    # Reconcile rounding error into `implement`.
    drift = total - sum(budgets.values())
    budgets["implement"] = max(0, budgets["implement"] + drift)
    return budgets


def validate_budgets(budgets: dict[str, int], time_bucket_minutes: int) -> tuple[bool, str]:
    """Validate a TOML-supplied budget dict against the canonical
    phase set + the problem's time_bucket.

    Returns (ok, reason). `reason` is empty on the happy path; on
    failure it names the first problem encountered (missing phase,
    extra phase, negative value, sum mismatch beyond tolerance).
    Used at load time so a malformed TOML doesn't reach prod.
    """
    expected = set(PHASES)
    got = set(budgets.keys())
    if expected != got:
        missing = expected - got
        extra = got - expected
        parts: list[str] = []
        if missing:
            parts.append(f"missing phases: {sorted(missing)}")
        if extra:
            parts.append(f"unknown phases: {sorted(extra)}")
        return False, "; ".join(parts)
    for phase in PHASES:
        if budgets[phase] < 0:
            return False, f"phase {phase!r} has negative budget {budgets[phase]}"
    expected_total = max(0, int(time_bucket_minutes)) * 60
    actual_total = sum(budgets.values())
    # Tolerate ±10s rounding from operator-authored TOMLs.
    if abs(actual_total - expected_total) > 10:
        return False, (
            f"budget sum {actual_total}s ≠ time_bucket {expected_total}s "
            f"(expected ±10s tolerance)"
        )
    return True, ""


def phase_status(elapsed_seconds: int, budget_seconds: int, *, soft_threshold: float = 0.8) -> str:
    """Bucket the current phase elapsed time vs. its budget.

    Returns one of:
        'ok'         — elapsed < soft_threshold of budget
        'soft_warn'  — elapsed >= soft_threshold but < 100%
        'over'       — elapsed >= 100% of budget

    The template's timer JS calls this on every tick (well, the JS
    has its own equivalent — this Python version is for tests +
    server-side rendering of the post-session review).
    """
    if budget_seconds <= 0:
        return "ok"
    ratio = elapsed_seconds / budget_seconds
    if ratio >= 1.0:
        return "over"
    if ratio >= soft_threshold:
        return "soft_warn"
    return "ok"


def total_budget_seconds(budgets: dict[str, int]) -> int:
    """Sum of all per-phase budgets. Used as the session-level
    timer's hard cutoff. Defends against a None or partial dict by
    skipping non-numeric values."""
    if not isinstance(budgets, dict):
        return 0
    total = 0
    for phase in PHASES:
        v = budgets.get(phase)
        if isinstance(v, (int, float)) and v >= 0:
            total += int(v)
    return total


def compose_review_breakdown(
    phase_time_seconds: dict[str, int] | None,
    phase_budgets: dict[str, int] | None,
) -> list[dict]:
    """Compose the per-phase rows the post-session review template
    renders. Each row carries:

        phase          — 'explore' | 'brainstorm' | etc.
        elapsed        — seconds the operator spent in this phase
        budget         — seconds budgeted for this phase
        elapsed_pct    — int 0-100, percent of TOTAL session time
        budget_pct     — int 0-100, percent of TOTAL session budget
        status         — 'under' | 'on_budget' | 'over'

    If the attempt has no `phase_time_seconds` (legacy row) the list
    is empty — the template knows to skip the section. Same for
    `phase_budgets` (legacy problem with no budgets recorded).

    `status` semantics:
        elapsed_pct < budget_pct - 5  →  'under'      (room to spare)
        elapsed_pct > budget_pct + 5  →  'over'       (over-spent)
        otherwise                     →  'on_budget'  (within ±5pp)

    5pp tolerance avoids flagging healthy ±5% jitter as a problem.
    """
    if not phase_time_seconds or not phase_budgets:
        return []
    total_elapsed = sum(int(phase_time_seconds.get(p, 0) or 0) for p in PHASES)
    total_budget = sum(int(phase_budgets.get(p, 0) or 0) for p in PHASES)
    if total_elapsed <= 0 or total_budget <= 0:
        return []

    rows: list[dict] = []
    for phase in PHASES:
        elapsed = int(phase_time_seconds.get(phase, 0) or 0)
        budget = int(phase_budgets.get(phase, 0) or 0)
        elapsed_pct = int(round(100 * elapsed / total_elapsed))
        budget_pct = int(round(100 * budget / total_budget)) if total_budget else 0
        diff = elapsed_pct - budget_pct
        if diff < -5:
            status = "under"
        elif diff > 5:
            status = "over"
        else:
            status = "on_budget"
        rows.append({
            "phase": phase,
            "elapsed": elapsed,
            "budget": budget,
            "elapsed_pct": elapsed_pct,
            "budget_pct": budget_pct,
            "status": status,
        })
    return rows


def fmt_seconds(seconds: int | None) -> str:
    """Render an integer second-count as 'Hh Mm' (over 1h) or 'Mm Ss'
    (under 1h) for the review surface. Defensive against None /
    negatives so the template can call this unconditionally."""
    if seconds is None or seconds < 0:
        return "0s"
    s = int(seconds)
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {sec}s" if sec else f"{m}m"
    return f"{sec}s"
