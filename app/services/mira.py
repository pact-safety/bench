"""MIRA — Li's research mentor. Agent loop (Phase 0 scaffold).

Mira (codename MIRA — Mentor for Inquiry, Research, and Apprenticeship) is
one more bench service, not a new app. This module owns the agent loop that
both the chat surface (`/mira/turn`, HTMX SSE) and the voice surface
(`/mira/voice/turn`, LiveKit worker over WebSocket) call — one loop, one
memory, one KB across modalities.

Phase 0 (spec §9, §15) ships only the entry-point signature. `mira_turn`
raises `NotImplementedError`; Phase 1 fills in the chat-only loop (no tools),
Phase 2 adds memory + agenda + tool use. The docstring below records the
intended loop so the wiring is on the record before the code exists.

This module is where the MIRA-specific concerns live that `llm_provider.py`
deliberately stays out of:

  - **Persona.** The system prompt is built from `voices.get("mira")` via
    `voices.apply_persona`, the same registry the review/reflect paths use.
  - **Spend cap.** `mira_turn` carries `user_id` and is the layer that calls
    `spend_cap.over_cap_for(user_id, "mira")` before streaming (cap hit →
    deterministic offline turn, no API spend) and `record_usage_for` after
    the stream drains (reading the `usage` payload on the terminal `finish`
    event from `llm_provider`). A new per-modality `MIRA_DAILY_TOKEN_CAP`
    extends the cap because voice turns replay the long system prompt every
    time and so cost more (spec §11).
  - **RAG + memory + agenda.** The loop assembles context from
    `rag.hybrid_search`, `mira_memory`, and `research_agenda`, then streams
    the model's reply back token-by-token.
"""

from __future__ import annotations

import logging
import time
from types import SimpleNamespace
from typing import TYPE_CHECKING, AsyncIterator, Literal

from . import llm_provider, rag, spend_cap, voices
from . import drills

# Chat-capable personas (mirrors _NON_REVIEW_VOICE_KEYS in app.main —
# the registry's other entries are review lenses, not mentors).
_CHAT_PERSONA_KEYS = frozenset({"mira", "mats-empirical-drill"})


def _drill_system_note(history) -> str:
    """Elapsed clock + rep trend for MATS drill sessions.

    The drill persona's BENCH FORMAT block instructs it to read these
    from a system note and emit `=== END REP N · elapsed X min ===`
    lines. Elapsed = minutes since the last assistant turn (a rep
    boundary); trend = drills.trend_summary over the transcript."""
    import datetime as _dt

    elapsed_line = ""
    last_assistant = None
    for t in history:
        if getattr(t, "role", None) == "assistant":
            last_assistant = t
    created = getattr(last_assistant, "created_at", None)
    if created is not None:
        mins = max(0, int((_dt.datetime.utcnow() - created).total_seconds() // 60))
        elapsed_line = f"elapsed since your last message: {mins}m."
    trend = drills.trend_summary(drills.rep_trend_for_session(history))
    if not elapsed_line and not trend:
        return ""
    return f"\n<system_note>{elapsed_line} {trend}</system_note>"

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids an import cycle
    from ..repositories.mira_repository import MiraRepository


_log = logging.getLogger(__name__)

Modality = Literal["chat", "voice"]

# MIRA is the expansive surface, so it gets more room than the 1024 default —
# but the persona's BREVITY-FIRST rule means most turns stay short, so this is
# a ceiling for the occasional eval-design / multi-step-plan answer, not a
# target. Bounds worst-case spend per turn.
_MAX_TOKENS = 2048


def _bounded_history(
    turns: list,
    *,
    max_turns: int,
    token_budget: int,
) -> list[llm_provider.LLMMessage]:
    """Turn the stored conversation into the message list for the API call,
    newest-bounded by both a turn count and an approximate token budget.

    Phase 1a is chat-only with no tools, so 'tool' rows are skipped — only
    user/assistant content goes back to the model. We walk newest→oldest
    accumulating until either bound trips, then return chronological order
    (which is what the Messages API wants). ~4 chars/token is the standard
    rough estimate; the real token count lands when tokenizer-accurate
    trimming becomes worth it (it isn't yet)."""
    picked: list = []
    used = 0
    for turn in reversed(turns):
        if turn.role not in ("user", "assistant"):
            continue
        content = turn.content or ""
        cost = max(1, len(content) // 4)
        if picked and (used + cost > token_budget or len(picked) >= max_turns):
            break
        picked.append(turn)
        used += cost
    picked.reverse()
    return [
        llm_provider.LLMMessage(role=t.role, content=t.content or "")
        for t in picked
    ]


def _audit_turn(*, model: str, usage: dict | None, content_len: int) -> None:
    """Write one custody line per turn — but only once Brain's shared
    `audit_log.py` ledger lands (it owns that module per the Brain⟷MIRA
    boundary doc). Until then this is a no-op behind the import guard so MIRA
    never builds a parallel audit. When it exists, MIRA records the model +
    a post-retrieval payload summary + usage, exactly as the contract spells.
    """
    try:
        from . import audit_log  # type: ignore
    except Exception:
        return
    try:
        audit_log.record(
            capability="mira",
            model=model,
            payload={"assistant_chars": content_len},
            redaction_applied=[],
            dropped=[],
            usage=usage,
            path=getattr(audit_log, "DEFAULT_PATH", None),  # type: ignore[arg-type]
        )
    except Exception as e:  # custody must never break the user's turn
        _log.warning("mira audit record failed: %s", e)


async def mira_turn(
    session_id: str,
    user_msg: str,
    modality: Modality = "chat",
    user_id: str | None = None,
    *,
    repo: "MiraRepository | None" = None,
    model: str | None = None,
    history_max_turns: int = 20,
    history_token_budget: int = 6000,
    persona_key: str | None = None,
) -> AsyncIterator[dict]:
    """Run one mentor turn, streaming normalized events back to the caller.

    Yields the same event dicts `llm_provider` emits (`{"type": "text", ...}`,
    `{"type": "finish", ...}`) so the chat SSE writer and the voice
    sentence-chunker consume one shape regardless of modality.

    Phase 1a is the chat-only loop: no RAG, no tools, no long-term memory yet
    (those are spec §9 Phase 1b/2). The steps that ARE wired:

      1. Load the last N `mira_turns`, bounded by a token budget (`repo`).
      2. Persist the user's message immediately, so it survives even if the
         provider stream fails mid-way.
      3. Build the system prompt: `voices.apply_persona(base, voices.get("mira"))`.
      4. Spend cap: if `spend_cap.over_cap_for(user_id, "mira")`, stream the
         deterministic offline turn instead of hitting the API. Otherwise
         `provider = llm_provider.get_provider("anthropic")` and stream.
      5. Persist the assistant `mira_turn` row (content, provider_used,
         latency_ms) and call `spend_cap.record_usage_for(user_id, ...)` from
         the terminal `finish` usage. Write one audit line (no-op until
         Brain's shared ledger lands).

    `repo` is injected by the route (the service layer never holds the conn,
    matching `hints.py`/`review.py`). With `repo=None` the loop still runs —
    no history, no persistence — which is what the no-DB unit path uses.

    Steps 1–5 of the *full* loop (memory, agenda, retrieve-decision, RAG) are
    deferred to Phase 1b/2; their hooks live in the module docstring so the
    wiring intent stays on the record.
    """
    # 1. Prior turns → bounded message history (before we persist this one,
    #    so the current message isn't double-counted).
    history: list = []
    if repo is not None:
        try:
            history = repo.list_turns(session_id, limit=max(history_max_turns * 4, 50))
        except Exception as e:
            # A history read failure must not 500 the turn — degrade to a
            # no-context reply rather than dropping the conversation.
            _log.warning("mira: could not load history for %s: %s", session_id, e)
            history = []

    messages = _bounded_history(
        history,
        max_turns=history_max_turns,
        token_budget=history_token_budget,
    )
    messages.append(llm_provider.LLMMessage(role="user", content=user_msg))

    # 2. Durably record the user's message up front.
    if repo is not None:
        try:
            repo.append_turn(session_id=session_id, role="user", content=user_msg)
        except Exception as e:
            _log.warning("mira: could not persist user turn for %s: %s", session_id, e)

    # 3. System prompt — the full Mira mentor persona (voices registry is the
    #    single source of truth). v2.1 slice 2: the turn is grounded in KB
    #    retrieval (the user's vault + shared canon) when it returns chunks;
    #    the honest no-substrate footer remains the zero-chunk path so the
    #    model never fabricates [cite:...] markers on an empty KB.
    retrieved: list = []
    try:
        retrieved = await rag.hybrid_search(user_msg, k_final=5, user_id=user_id)
    except Exception as e:  # noqa: BLE001 — retrieval must never kill a turn
        _log.warning("mira: retrieval failed for %s: %s", session_id, e)
    if retrieved:
        blocks = "\n\n".join(
            f"[cite:{c.document_id}] {c.title or 'untitled'}"
            + (f" › {c.section_path}" if c.section_path else "")
            + "\n"
            + c.content[:1200]
            for c in retrieved
        )
        base = (
            f"(Runtime context: modality={modality}. RETRIEVED CONTEXT from "
            "the user's own knowledge base is below. When you draw on a "
            "block, cite it inline as [cite:<id>] using the id exactly as "
            "given. Do not cite blocks you did not use, and never invent "
            "citations for content that is not in a block.)\n\n"
            "RETRIEVED CONTEXT:\n\n" + blocks
        )
    else:
        base = (
            f"(Runtime context: modality={modality}. No knowledge-base "
            "retrieval or long-term memory is wired into this session yet — "
            "reason from first principles and do not invent [cite:...] "
            "citations.)"
        )
    # Persona: sessions carry a persona_key in meta (the MATS drill
    # launcher sets it); default = the Mira mentor. Whitelisted here —
    # voices.get() falls back to the REVIEW default on unknown keys,
    # which would silently swap the mentor for a review lens.
    chat_key = persona_key if persona_key in _CHAT_PERSONA_KEYS else "mira"
    if chat_key == "mats-empirical-drill":
        # Drill sessions get the elapsed clock + rep trend the persona
        # is instructed to read from a system note. Not persisted —
        # rebuilt fresh every turn from turn timestamps + rep markers.
        base += _drill_system_note(history)
    system = voices.apply_persona(base, voices.get(chat_key))

    # 4. Spend-cap gate → provider. Over cap streams the deterministic offline
    #    turn (no API spend); otherwise the real ladder, with the configured
    #    model applied to the Anthropic backend.
    over_cap = spend_cap.over_cap_for(user_id, "mira")
    if over_cap:
        provider = llm_provider.DeterministicOfflineProvider()
    else:
        provider = llm_provider.get_provider("anthropic")
        if model and hasattr(provider, "model"):
            provider.model = model  # type: ignore[attr-defined]

    # 5. Stream, accumulating the assistant text + the terminal usage so we
    #    can persist the turn and record spend after the stream drains.
    parts: list[str] = []
    finish_usage: dict | None = None
    t0 = time.monotonic()
    try:
        async for event in provider.stream(system, messages, max_tokens=_MAX_TOKENS):
            if event.get("type") == "text":
                parts.append(event.get("delta", ""))
            elif event.get("type") == "finish":
                finish_usage = event.get("usage")
            yield event
    except Exception as e:
        # Any provider blow-up (network, SDK, cancellation) degrades to the
        # offline turn rather than 500ing the route — the same graceful-
        # degradation guarantee the offline provider exists for. We restart
        # the stream from the deterministic backend so the caller still gets
        # text + finish events.
        _log.warning("mira: provider stream failed (%s); falling back offline", e)
        provider = llm_provider.DeterministicOfflineProvider()
        parts = []
        async for event in provider.stream(system, messages, max_tokens=_MAX_TOKENS):
            if event.get("type") == "text":
                parts.append(event.get("delta", ""))
            elif event.get("type") == "finish":
                finish_usage = event.get("usage")
            yield event

    latency_ms = int((time.monotonic() - t0) * 1000)
    assistant_text = "".join(parts)

    # 6. Persist the assistant turn + record spend + audit. All best-effort:
    #    bookkeeping failures must not break the response the user already saw.
    if repo is not None:
        try:
            repo.append_turn(
                session_id=session_id,
                role="assistant",
                content=assistant_text,
                provider_used=provider.name,
                latency_ms={"total": latency_ms},
            )
        except Exception as e:
            _log.warning("mira: could not persist assistant turn for %s: %s", session_id, e)

    if finish_usage is not None:
        # spend_cap.record_usage_for reads resp.usage.{input,output}_tokens;
        # adapt the normalized finish dict to that shape. Offline turns carry
        # zero usage, so this is a no-op there.
        resp_shim = SimpleNamespace(
            usage=SimpleNamespace(
                input_tokens=int(finish_usage.get("input_tokens", 0) or 0),
                output_tokens=int(finish_usage.get("output_tokens", 0) or 0),
            )
        )
        spend_cap.record_usage_for(user_id, resp_shim)

    _audit_turn(
        model=getattr(provider, "model", provider.name),
        usage=finish_usage,
        content_len=len(assistant_text),
    )
