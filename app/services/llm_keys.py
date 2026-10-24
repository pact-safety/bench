"""Per-user LLM client routing (Bench v2 BYO-key).

Alpha users can point the AI features at their own key — straight to
Anthropic, or via an OmniRoute-style gateway that speaks the Anthropic
Messages API (`/v1/messages`, `x-api-key`) — so their usage bills
their wallet instead of the operator's. The `anthropic` SDK is reused
unchanged for every route; only `api_key`/`base_url` differ, so the
protected prompt-bearing services swap ONE line (`Anthropic()` →
`llm_keys.client_for(user_id)`) and their prompts stay untouched.

Failure policy:
  - config unreadable (DB blip) → house client. Availability first;
    the drain-risk case needs the DB down, at which point nothing
    else works either.
  - config says BYO but the key can't be fetched → raise. Every
    LLM-touching service already wraps its call in try/except with a
    deterministic offline fallback, so the user sees the fallback and
    a working settings page to fix their key — and the operator's key
    is never silently substituted for a broken user key.

app.main injects the repository at startup (same pattern as
access.set_db_email_source).
"""

from __future__ import annotations

import logging

_log = logging.getLogger(__name__)

_repo = None  # LlmConfigRepository, injected by app.main


class LlmKeyError(RuntimeError):
    """BYO config exists but the key is unusable — callers fall back
    to their offline path, never to the operator's key."""


def set_repo(repo) -> None:
    global _repo
    _repo = repo


def has_user_key(user_id: str | None) -> bool:
    """Cheap check for the spend cap: does this user route LLM calls
    through their own key? No vault fetch — metadata only."""
    if not user_id or _repo is None:
        return False
    try:
        cfg = _repo.get(user_id)
    except Exception:  # noqa: BLE001 — cap gating must not 500 a request
        return False
    return bool(cfg and cfg.provider != "bench" and cfg.vault_secret_id)


def client_for(user_id: str | None):
    """An `anthropic.Anthropic` client routed per the user's config.

    House key (env) when the user has no BYO config; the user's own
    key/base_url when they do. Raises LlmKeyError when a BYO config
    is present but unusable (see module docstring)."""
    from anthropic import Anthropic

    if not user_id or _repo is None:
        return Anthropic()
    try:
        provider, key, base_url = _repo.route_for(user_id)
    except Exception as exc:  # noqa: BLE001
        _log.warning(
            "llm route lookup failed for user (%s: %s); using house key",
            type(exc).__name__, exc,
        )
        return Anthropic()
    if provider == "bench":
        return Anthropic()
    if not key:
        raise LlmKeyError(
            f"user LLM config ({provider}) has no usable key; "
            "offline fallback instead of billing the house key"
        )
    kwargs: dict = {"api_key": key}
    if base_url:
        kwargs["base_url"] = base_url
    return Anthropic(**kwargs)
