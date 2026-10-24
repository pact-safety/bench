"""Provider-agnostic streaming LLM interface (MIRA Phase 0 scaffold).

Why this exists
---------------
Every other LLM-touching service in this repo (`hints.py`, `review.py`,
`jds.py`, …) talks to Anthropic synchronously via `client.messages.create`
and returns a single parsed dict. That shape is right for a request/response
hint or review. It is the *wrong* shape for MIRA's voice path, where the
latency budget (§7.3 of the MIRA spec: ≤900ms end-to-end) only closes if we
flush each sentence to TTS the moment the model emits it. So this module
introduces the one thing the existing services don't have: a **streaming,
provider-agnostic** interface.

Two deliberate divergences from the surrounding code, both flagged here so a
future maintainer doesn't "fix" them into inconsistency:

  1. **Async.** The rest of the app is synchronous. This subsystem is async
     because token-by-token streaming + barge-in cancellation is what async
     iterators are for, and FastAPI serves async routes natively. This file
     is not imported by `app.main` yet (Phase 0 ships scaffolding, not wired
     routes), so the async paradigm has zero runtime impact on the existing
     synchronous services until MIRA's routes land.

  2. **Generic, not MIRA-specific.** Per the spec, this is a reusable seam
     other bench services can adopt later, so it carries no MIRA persona, no
     RAG, and — importantly — no spend-cap wiring. The cap lives one layer
     up in `mira.py`, which owns the `user_id` and the
     `over_cap_for`/`record_usage_for` hooks, exactly as `hints.py` does.

Streaming event contract
------------------------
Every provider normalizes its native stream to a flat dict so callers never
branch on which vendor answered:

    {"type": "text",   "delta": "...partial text..."}
    {"type": "tool_call", "tool_call": {"name": ..., "input": {...}, "id": ...}}
    {"type": "finish", "finish_reason": "end_turn"|"max_tokens"|...,
                       "usage": {"input_tokens": int, "output_tokens": int}}

The `usage` payload on the terminal `finish` event is what lets the caller
feed `spend_cap.record_usage_for` after the stream drains.

Fallback ladder
---------------
`get_provider()` mirrors the LLM-or-fallback discipline used everywhere else:
Anthropic → OpenAI → Gemini → `DeterministicOfflineProvider`. The offline
provider always yields a usable (if canned) turn, so a missing key or a
provider error never 500s a route — it degrades to a deterministic answer,
the same contract `hints.get_hint` honors with its per-phase nudges.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import AsyncIterator, Protocol, runtime_checkable


# Model defaults match the sibling services (review.py / jds.py) so MIRA
# rides the same env knobs the rest of the app already documents.
_ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")


@dataclass
class LLMMessage:
    """One turn in a conversation, normalized across providers.

    `role` is the Anthropic vocabulary ("user"|"assistant"|"system"|"tool");
    provider implementations translate to their own dialect. `tool_calls`
    carries assistant tool-use requests; `tool_use_id` ties a "tool" result
    message back to the call it answers.
    """

    role: str
    content: str
    tool_calls: list[dict] | None = None
    tool_use_id: str | None = None


@runtime_checkable
class LLMProvider(Protocol):
    """The single interface every backend implements.

    `stream` is an async generator yielding the normalized events described
    in the module docstring. `cache_breakpoint` asks the provider to mark the
    system prompt for prompt caching where supported (Anthropic bills cached
    input at ~10% — see MIRA spec §5.3; re-verify pricing before prod).
    """

    name: str

    def stream(
        self,
        system: str,
        messages: list[LLMMessage],
        tools: list[dict] | None = None,
        max_tokens: int = 1024,
        cache_breakpoint: bool = True,
    ) -> AsyncIterator[dict]: ...


class AnthropicProvider:
    """Primary backend: Claude (Sonnet 4.5 default).

    Implemented for real in Phase 0 because it's the one provider MIRA needs
    on day one; OpenAI/Gemini stay stubs until Phase 5 (spec §9). The
    `anthropic` import is lazy — inside `stream`, not at module load — so
    importing this module never requires the SDK to be installed, matching
    the pattern in `hints.py`/`jds.py`.

    Tool-use streaming is intentionally not emitted yet: Phase 1 is a
    chat-only loop with no tools (spec §9), so wiring tool_call events before
    there's a consumer would be untested speculation. The `tools` parameter
    is accepted and forwarded so the signature is stable when Phase 2 turns
    tools on.
    """

    name = "anthropic"

    def __init__(self, model: str | None = None) -> None:
        self.model = model or _ANTHROPIC_MODEL

    async def stream(
        self,
        system: str,
        messages: list[LLMMessage],
        tools: list[dict] | None = None,
        max_tokens: int = 1024,
        cache_breakpoint: bool = True,
    ) -> AsyncIterator[dict]:
        # Async client so the event loop isn't blocked while tokens arrive —
        # the whole point of this module. The sync `Anthropic` the rest of
        # the app uses would stall the loop during a multi-second generation.
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic()

        # Prompt caching: mark the (long, stable) system prompt as a cache
        # breakpoint so repeated voice turns replay it at the cached rate.
        # Passing the structured block form is what the SDK expects for
        # cache_control; a bare string skips caching.
        system_param: object
        if cache_breakpoint and system:
            system_param = [
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        else:
            system_param = system

        kwargs: dict = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system_param,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        if tools:
            kwargs["tools"] = tools

        async with client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                if text:
                    yield {"type": "text", "delta": text}
            final = await stream.get_final_message()

        usage = getattr(final, "usage", None)
        yield {
            "type": "finish",
            "finish_reason": getattr(final, "stop_reason", None),
            "usage": {
                "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
                "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
            },
        }


class OpenAIProvider:
    """Fallback backend (gpt-4.1). Stub until Phase 5 (spec §9)."""

    name = "openai"

    async def stream(
        self,
        system: str,
        messages: list[LLMMessage],
        tools: list[dict] | None = None,
        max_tokens: int = 1024,
        cache_breakpoint: bool = True,
    ) -> AsyncIterator[dict]:
        raise NotImplementedError("OpenAIProvider lands in MIRA Phase 5 (spec §9).")
        yield  # pragma: no cover - makes this an async generator for the Protocol


class GeminiProvider:
    """Fallback backend (gemini-2.5-pro). Stub until Phase 5 (spec §9)."""

    name = "gemini"

    async def stream(
        self,
        system: str,
        messages: list[LLMMessage],
        tools: list[dict] | None = None,
        max_tokens: int = 1024,
        cache_breakpoint: bool = True,
    ) -> AsyncIterator[dict]:
        raise NotImplementedError("GeminiProvider lands in MIRA Phase 5 (spec §9).")
        yield  # pragma: no cover - makes this an async generator for the Protocol


# Canned text the offline provider emits. Deliberately small and honest: it
# names the degraded state rather than faking a mentor turn, so a missing key
# in dev is obvious instead of silently producing low-quality "advice".
_OFFLINE_TEXT = (
    "Mira is offline right now (no LLM provider is reachable). Your message "
    "was saved — try again once the connection is back."
)


class DeterministicOfflineProvider:
    """Last-resort backend so a route never 500s on a provider failure.

    Same contract the rest of the app honors: a deterministic, no-network
    answer when the LLM can't be reached. Yields one text event plus a
    zero-usage finish so the caller's drain loop and spend-cap bookkeeping
    both behave identically to a live provider.
    """

    name = "offline"

    async def stream(
        self,
        system: str,
        messages: list[LLMMessage],
        tools: list[dict] | None = None,
        max_tokens: int = 1024,
        cache_breakpoint: bool = True,
    ) -> AsyncIterator[dict]:
        yield {"type": "text", "delta": _OFFLINE_TEXT}
        yield {
            "type": "finish",
            "finish_reason": "offline",
            "usage": {"input_tokens": 0, "output_tokens": 0},
        }


def get_provider(preference: str = "anthropic") -> LLMProvider:
    """Resolve a provider, falling through the ladder until one is usable.

    Order is preference-first, then Anthropic → OpenAI → Gemini → offline.
    A backend counts as usable only when its credentials are present *and*
    it's actually implemented; the unimplemented stubs (OpenAI/Gemini) are
    skipped so `get_provider` never hands back something that raises on first
    token. With no key set at all, you get the deterministic offline provider
    — the same graceful-degradation guarantee as `hints.get_hint`.
    """
    ladder = [preference] + [p for p in ("anthropic", "openai", "gemini") if p != preference]
    for choice in ladder:
        if choice == "anthropic" and os.environ.get("ANTHROPIC_API_KEY"):
            return AnthropicProvider()
        # OpenAI/Gemini are stubs in Phase 0 — even with a key set they raise,
        # so don't return them yet. Phase 5 (spec §9) flips them on here.
    return DeterministicOfflineProvider()
