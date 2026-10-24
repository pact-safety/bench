"""Group problem references by EM phase for the UI."""

from __future__ import annotations

from ..models import EM_PHASES


_PHASE_LABELS = {
    "explore": "Explore",
    "brainstorm": "Brainstorm",
    "plan": "Plan",
    "implement": "Implement",
    "verify": "Verify",
    "general": "General",
}


def group_by_phase(refs: list[dict]) -> list[tuple[str, str, list[dict]]]:
    """Return [(phase_key, phase_label, [ref, ...]), ...] in phase order,
    with 'general' (no phase) last. Empty groups are dropped."""
    buckets: dict[str, list[dict]] = {p: [] for p in EM_PHASES}
    buckets["general"] = []
    for r in refs or []:
        phase = r.get("phase") or "general"
        if phase not in buckets:
            phase = "general"
        buckets[phase].append(r)
    order = list(EM_PHASES) + ["general"]
    return [(p, _PHASE_LABELS[p], buckets[p]) for p in order if buckets[p]]
