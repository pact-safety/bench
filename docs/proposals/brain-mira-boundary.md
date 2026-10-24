# Brain ⟷ MIRA — surface boundary & shared-infra contract

Two distinct bench surfaces that share *some* substrate. This doc is the
coordination contract so two chats can build them in tandem without
colliding. Written 2026-06 during Brain capability-1 planning, after
reading MIRA's Phase-0 foundations on `main`.

## The one-line distinction

- **Brain (`/brain`)** is a *harness with an LLM inside it*. Second brain +
  executive assistant + mirror. Narrow, well-defined tasks (rank today's
  work, glean email tasks, mirror thought-traps). Deterministic core; the
  LLM only writes narrative/phrasing. **Cheapest capable model (Haiku).**
- **MIRA (`/mira`)** is an *LLM with a harness around it*. AI-research
  advisor/mentor. Open-ended synthesis, critique, research taste, RAG over
  the safety-eval canon. **Strongest model (Sonnet/Opus).**

Brain should feel like a calculator that happens to talk. MIRA should feel
like a sharp colleague.

## Side-by-side

| | Brain `/brain` | MIRA `/mira` |
|---|---|---|
| Model tier | `claude-haiku-4-5` (`[brain].model`) | `claude-sonnet/opus` (`[mira].model`) |
| Shape | Synchronous, request/response | Async, token-streaming (voice latency budget) |
| Determinism | High — offline scorer is canonical | Low by design — RAG-grounded, free-ranging |
| State | Life state: Linear, calendar, email, decisions, capacity | Research state: papers, open questions, eval ideas |
| Substrate | Obsidian vault (`~/bench-brain-vault`) + Postgres index | Postgres KB (`kb_documents`/`kb_chunks`, pgvector) |
| Custody | Strict: metadata-only out, denylist, audit every payload | RAG: public paper chunks out; user msgs audited too |
| Tools | Small fixed set (shortlist / glean / mirror) | Growing agentic set (kb_search, add_research_question…) |
| Service | `app/services/brain.py` | `app/services/mira.py` (on main) |

## What they SHARE (build once, both consume)

1. **Audit ledger — NEW shared module `app/services/audit_log.py`.**
   Append-only JSONL. One custody record for every outbound API payload
   across the whole app. Interface (sync; MIRA calls it from its turn-
   persistence step after the stream drains):

   ```python
   def record(
       *, capability: str, model: str, payload: object,
       redaction_applied: list[str], dropped: list[str],
       usage: dict | None, path: str,
   ) -> None: ...
   ```

   Writes one JSON object per line to `<path>` (default
   `~/bench-brain-vault/_audit/outbound.jsonl`). **Owner: Brain** (custody
   is Brain's hard constraint; it needs this first). MIRA consumes it once
   it lands — writes one line per turn (model, post-retrieval payload
   summary, usage). Until then MIRA can no-op the call behind a try/except.

2. **`spend_cap`** (`app/services/spend_cap.py`) — both gate on
   `over_cap_for(uid, surface)` before the API and `record_usage_for` after.
   MIRA uses surface `"mira"`; Brain uses `"brain"`.

3. **`voices`** registry — MIRA has a `mira` voice; Brain gets a `brain`
   voice (terse, mirror-capable). Same `voices.get` / `apply_persona` path.

4. **Model-tier config discipline** — every surface declares its model in
   `config.toml` (`[brain].model`, `[mira].model`), coerced in
   `app/config.py`. No buried defaults.

5. **`llm_provider.py` (optional, recommended).** Today it's async-streaming
   only — the wrong shape for Brain's synchronous deterministic harness.
   The clean consolidation: add a sync helper to that module so there's ONE
   provider/fallback/model layer with two consumption shapes:

   ```python
   def complete_sync(system, messages, *, model, max_tokens) -> dict:
       """Non-streaming completion for sync callers (Brain). Same
       fallback ladder as the streaming path."""
   ```

   If we don't do this, Brain uses the `jds.py` synchronous
   `client.messages.create` pattern directly. Either is fine; `complete_sync`
   is the better long-term shape. **Owner: whoever needs it first** — flag
   in the other chat before editing `llm_provider.py`.

## What they DON'T share

- Retrieval scope / redaction policy (Brain = metadata-only-private with
  denylist; MIRA = public paper chunks).
- The Obsidian vault (Brain only; MIRA's KB is Postgres).
- Service modules, routes, templates, MCP tools.

## Collision points (coordinate these)

- **Migrations.** `014` is already taken **twice** (`014_mira.sql`,
  `014_interview_phase_budgets.sql`). Brain = **`015_brain.sql`**. MIRA
  Phase 1 needs **no new migration** (014_mira already has its tables). No
  collision as long as Brain uses 015+.
- **`base.html` nav.** Each surface adds its own top-level link
  (`nav_section` `"brain"` / `"mira"`). Trivial conflict if both edit at
  once; last-merged rebases.
- **`app/main.py`** imports + repo wiring + routes, and **`config.toml`** —
  both append. Keep additions in distinct blocks; conflicts are mechanical.
- **`app/mcp_server.py`** — Brain adds `brain_daily_shortlist`; MIRA adds
  its tools later. Distinct `@mcp.tool()` defs.

## Branch / ownership split

- **Brain** → branch `feat/brain-surface` (this chat). Capability 1 first
  (daily shortlist), then 2 (email gleaning), then 3 (mirror).
- **MIRA** → branch reset to `main`, Phase 1a→1b→1c (chat loop → RAG →
  seed) per the MIRA roadmap (spec §9). New chat.

Shared-infra ordering: Brain lands `audit_log.py` + `complete_sync` (if
chosen) early; MIRA rebases onto them. Both stay green via the no-DB test
path, so neither blocks the other's unit tests.
