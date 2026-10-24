"""First-run onboarding strips (design handoff: onboarding-bubbles).

Direction 1b from the design record ("Onboarding Bubbles Directions
.dc.html"): a tip occupies real layout space directly above the element
it annotates. No positioning JS, no scrim, nothing floats — so nothing
can cover its own anchor at any zoom.

State lives in ``users.settings_json["onboarding_bubbles"]``::

    {
      "enabled": true,                      # global "don't show tips"
      "seen": {"problem": ["phase_rail"]}   # per surface, ordered ids
    }

Server-side on purpose: the tour follows the user across machines, and
the server decides what renders so there is no first-paint flash and no
client-side first-visit detection. The route layer mirrors the
``/settings/glass`` save pattern (204 for HTMX, 303 for the no-JS form).

Ported from the handoff's Flask sketch to the bench's shape: pure
functions over the settings dict; routes in app/main.py pass
``bubbles=bubble_state(...)`` into their template context explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass

KEY = "onboarding_bubbles"


@dataclass(frozen=True)
class Tip:
    id: str
    anchor: str  # the slot this tip belongs to, per surface
    label: str   # shown in the kicker after the counter
    body: str


# ---------------------------------------------------------------------------
# The inventory. Ordered per surface; 1-3 tips, never more. Copy is terse,
# second person, no exclamation marks — the bench's voice. One deviation
# from the handoff sketch: settings_provider/settings_linear merged into a
# single "settings" surface, because a page carries exactly one `bubbles`
# context and both panels live on /settings.
# ---------------------------------------------------------------------------
INVENTORY: dict[str, list[Tip]] = {
    "today": [
        Tip("next_rep", "next_action", "today's rep",
            "This is the next rep the scheduler picked. You can always "
            "override from the library."),
    ],
    "problem": [
        Tip("phase_rail", "phase_rail", "the phase rail",
            "Five phases, in order. Explore is notes only — no code runs here."),
        Tip("editor", "editor", "the editor",
            "The editor unlocks when Plan has content."),
    ],
    "library": [
        Tip("filters", "filters", "filters",
            "The scheduler decides for you on Today; pull whatever you want "
            "from here. Add external content to bring in your own."),
    ],
    "mira": [
        Tip("console", "console", "what mira knows",
            "Mira knows your attempts, calibration, and — once you connect it "
            "— your vault. The mic dictates; the Voice toggle reads replies "
            "aloud."),
    ],
    "kb": [
        Tip("upload", "upload", "your vault",
            "Upload your Obsidian vault (zip). Your notes stay yours: "
            "owner-scoped, never trained on, deleted with your account."),
    ],
    "signal": [
        Tip("evidence", "signal", "what this is for",
            "Readiness asks whether you can do the work. This asks whether a "
            "stranger can tell. Record what you have already built — then rate "
            "it honestly against what strong looks like."),
    ],
    "settings": [
        Tip("provider", "provider", "provider keys",
            "Bench-provided has a daily cap. Your own key has none — your "
            "provider bills you."),
        Tip("linear", "linear", "linear sync",
            "Pushes your research agenda into your own Linear workspace."),
    ],
}


@dataclass(frozen=True)
class BoundTip:
    id: str
    anchor: str
    label: str
    body: str
    surface: str
    index: int
    total: int


@dataclass(frozen=True)
class SurfaceState:
    """What the templates read. ``current`` is at most ONE tip."""

    surface: str
    total: int
    current: BoundTip | None


def _state(settings: dict | None) -> dict:
    return (settings or {}).get(KEY) or {"enabled": True, "seen": {}}


def tips_enabled(settings: dict | None) -> bool:
    return bool(_state(settings).get("enabled", True))


def bubble_state(settings: dict | None, surface: str) -> SurfaceState:
    """The one tip that should render on this surface for this user:
    the first in the surface's ordered set the user has not seen."""
    tips = INVENTORY.get(surface, [])
    total = len(tips)
    state = _state(settings)
    if not tips or not state.get("enabled", True):
        return SurfaceState(surface, total, None)
    seen = set(state.get("seen", {}).get(surface, []))
    for i, tip in enumerate(tips, start=1):
        if tip.id not in seen:
            return SurfaceState(
                surface, total,
                BoundTip(tip.id, tip.anchor, tip.label, tip.body,
                         surface, i, total),
            )
    return SurfaceState(surface, total, None)


def mark(settings: dict | None, surface: str, tip_id: str, action: str) -> dict:
    """New settings dict with the dismissal applied. ``seen`` marks one
    tip; ``skip`` marks the whole surface. Unknown surfaces/actions
    raise — the route turns that into a 400."""
    tips = INVENTORY.get(surface)
    if not tips or action not in ("seen", "skip"):
        raise ValueError(f"bad bubble dismiss: {surface!r} {action!r}")
    out = dict(settings or {})
    state = dict(_state(out))
    seen = dict(state.get("seen", {}))
    marked = list(seen.get(surface, []))
    if action == "skip":
        marked = [t.id for t in tips]
    elif tip_id not in marked:
        marked.append(tip_id)
    seen[surface] = marked
    state["seen"] = seen
    out[KEY] = state
    return out


def set_enabled(settings: dict | None, enabled: bool) -> dict:
    out = dict(settings or {})
    state = dict(_state(out))
    state["enabled"] = enabled
    out[KEY] = state
    return out


def anchor_of(surface: str, tip_id: str) -> str:
    for t in INVENTORY.get(surface, []):
        if t.id == tip_id:
            return t.anchor
    return ""
