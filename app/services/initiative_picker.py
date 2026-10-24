"""Resolves which initiative slug to tag a write with.

Centralizes the precedence rule used by every write path that should
carry per-attempt initiative tagging (migration 011 / per-attempt
tagging proposal):

  1. If the route received an explicit ``initiative_slug`` form value,
     validate it against the loaded-initiative set and use it.
  2. Otherwise fall back to ``settings.active_initiative`` if it's set
     and still points at a known, currently-active initiative.
  3. Otherwise tag NULL (unassigned). NULL is a first-class outcome —
     /focus's read path renders an "Unassigned" bucket for it.

The "still points at a known, currently-active initiative" check
matters because an operator can mark an initiative ``done`` (e.g.,
anthropic-fellows after rejection) while the settings JSON still
remembers it. We don't want to keep tagging fresh activity to a closed
initiative. Defensively re-validate on every read.

Validation errors raised here are caller-facing — route handlers turn
them into 400s rather than propagating to a 500.
"""

from __future__ import annotations

from typing import Iterable

from . import initiatives as initiatives_service


# Sentinel that the picker raises when an explicit form_override is
# unrecognized. Route handlers map this to 400.
class UnknownInitiativeError(ValueError):
    """Raised when an explicit slug doesn't match any loaded initiative."""


def _active_slugs(
    initiatives: Iterable[initiatives_service.Initiative] | None = None,
) -> set[str]:
    """Set of slugs whose ``status == "active"``. Dormant initiatives
    are NOT a valid tagging target — they're paused, so attributing
    fresh activity to them muddies the dashboard."""
    inits = initiatives if initiatives is not None else initiatives_service.load_initiatives()
    return {i.slug for i in inits if i.status == "active"}


def resolve_initiative_slug(
    *,
    settings: dict | None,
    form_override: str | None = None,
    initiatives: Iterable[initiatives_service.Initiative] | None = None,
) -> str | None:
    """Compute the slug to write on a new attempt/reflection/etc.

    Args:
        settings: the operator's settings_json (or None / {}).
        form_override: optional value submitted with the form. Empty
            string and None are treated as "no override."
        initiatives: optional explicit initiative list for tests; if
            omitted, calls ``initiatives_service.load_initiatives()``.

    Returns:
        A valid active initiative slug, or None if no slug should be
        recorded (unassigned).

    Raises:
        UnknownInitiativeError: if ``form_override`` is non-empty but
        doesn't match any active initiative.
    """
    active = _active_slugs(initiatives)

    override = (form_override or "").strip()
    if override:
        if override not in active:
            raise UnknownInitiativeError(
                f"unknown or non-active initiative slug: {override!r}. "
                f"Active slugs: {sorted(active) if active else '[none]'}"
            )
        return override

    settings_active = ""
    if isinstance(settings, dict):
        raw = settings.get("active_initiative", "")
        settings_active = (raw or "").strip()

    if settings_active and settings_active in active:
        return settings_active

    # Either no settings value, or the stored value points at an
    # initiative that's no longer active (closed / archived / removed).
    return None
