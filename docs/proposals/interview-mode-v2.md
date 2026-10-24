# Proposal: Interview mode v2 — voice-first, time-budgeted, calendar-driven mock interviews

**Status:** draft — awaiting operator review

**Resolved decisions (from operator AskUserQuestion 2026-05-28):**
1. **TTS provider:** ElevenLabs. Costs managed by capping interviewer lines at ≤180 chars, caching canned phrases, and a per-month character budget with Web Speech API fallback at cap.
2. **Live coach default:** silent unless asked — the realistic-interview mode. A pre-session preference flips to discreet nudges (training-wheels) or full live-coach (1:1 tutor) when the operator wants scaffolding.
3. **Calendar matching:** LLM classifier on event title + description + attendees → operator confirms before MIRA generates a mock. Avoids false positives.

**Author:** Claude (under operator delegation)

**Date:** 2026-05-28

**Predecessor:** Current `/problem/<slug>?mode=interview` (basic timer + interview banner), `voice-note.js` (STT shipped), MIRA Phase 0+1 (in flight as PR #298).

## Problem

The current interview-mode page is a stub: it shows a timer that counts up from the total `time_bucket`, sets a "stricter rubric" banner, and otherwise behaves identically to free-practice mode. Real interview prep needs:

- **Phase-level time pressure.** Real interviewers expect candidates to spend 15% on Explore, 20% on Brainstorm, etc. The current single-counter doesn't surface when the operator is over-budget on Plan and starving Implement.
- **Voice as the primary modality.** Interviewers speak the question and listen to spoken answers. Typing into a textarea trains the wrong muscle.
- **A live "interviewer" reacting in real time.** A silent timer is the easy version; a real interviewer asks clarifying questions, says "walk me through that edge case", drops the kind of prods that make the operator either rise to the moment or freeze.
- **Practice tied to actual upcoming interviews.** Generic problems are warmups; the highest-value mocks are tuned to the company, role, and format of next Tuesday's onsite.
- **Calibration data over time.** Where does the operator consistently under-budget? Where do they panic-finish? The bench already knows; it isn't surfacing this.

## Goal

Turn `/problem/<slug>?mode=interview` (and a new `/interview/mock`) into a **voice-first interview simulator** that:
- Reads the problem aloud (ElevenLabs).
- Times each Engineering Method phase against a budget.
- Listens to the operator's voice (STT — existing infrastructure).
- Optionally lets MIRA prod the operator like a real interviewer.
- Records the session for post-mortem.
- Pulls upcoming calendar events flagged as interviews → offers tuned mocks.
- Builds per-axis time-budget calibration data that informs future budgets.

## Scope

### v1 — phase-budgeted interview mode (no voice yet)

Ship the time-budget machinery first; layer voice on top in v2 once the budget tracking is stable.

- Add `phase_budgets: dict[str, int]` to the problem TOML (seconds per phase). LLM-generated for existing problems via a one-shot script; authored-by-hand going forward. The five EM phases (Explore / Brainstorm / Plan / Implement / Verify) get an explicit budget; budgets sum to `time_bucket * 60`.
- Soft warning at 80% of the active phase budget: small toast in the corner ("30 seconds left in Brainstorm — wrap up your thoughts"). No audio in v1.
- Hard cutoff at 100% of total session time: the form locks, MIRA's review fires automatically against whatever the operator has so far, AND a reflection prompt opens ("what tripped you up?"). The locked session is also marked `cutoff: True` in the attempt row so the calibration data knows.
- Per-phase time tracking: new `phase_time_seconds: dict[str, int]` column on the attempt row. Already partially populated by the existing `time_per_phase_json` hidden field; promote it to a real column with migration.
- Post-session review page surfaces the per-phase breakdown: "Plan: 23% of total (budget 25%), healthy. Implement: 51% (budget 35%), over budget." Comparative line vs. running average per axis ("you take ~28% longer than budget on algorithmic problems").

### v2 — voice-first input + ElevenLabs TTS output

Layer audio onto v1 once budget tracking is shipped.

- **TTS — interviewer reads the problem.** ElevenLabs voice id stored in user settings. On "Start", MIRA TTS-reads the problem statement (capped at ~600 chars; longer problems get an auto-generated summary spoken aloud + the full text still on screen). "Replay" button. Mute toggle.
- **STT default.** The Explore / Brainstorm / Plan / Verify textareas open with the dictation button highlighted; voice-note.js already shipped. Operator can still type.
- **Phase transitions narrated.** A short canned-line plays at each phase boundary ("Plan phase. Three minutes."). Canned lines are pre-rendered MP3s served from `/static/audio/` to keep ElevenLabs cost at zero per session for these.
- **Cost-effectiveness controls:**
  - Per-month TTS character cap (default: 30k chars/mo on the Starter plan). At cap, fall through to Web Speech API.
  - Interviewer responses constrained to ≤180 chars by prompt (matches a real interviewer's terseness; saves cost).
  - Aggressive caching of phrase blobs (the 80% warning is the same 6 words every time).
  - Mute button — silent practice mode skips TTS entirely.

### v3 — live interviewer agent (MIRA)

Depends on MIRA Phase 0+1 being live (PR #298). The interview agent is a MIRA persona with a specific system prompt and a specific set of triggers.

- **Default mode: silent.** MIRA does not speak unless the operator types/says "stuck" or clicks the hint button. This is the realistic-interview default per operator pick.
- **Discreet-nudge mode:** stuck detector fires after 30s+ of no input AND no progress on the current phase. MIRA TTS-asks one short clarifying question.
- **Live-coach mode:** MIRA proactively narrates ("good, you've named the invariant — what about boundary conditions?"), asks clarifying questions during pauses (8s+), and treats the session like a 1:1 tutorial.
- Mode picker on the pre-start screen (silent / nudges / live coach). Defaults to silent.

### v4 — calendar-driven virtual interviews

Depends on v3 + Google Calendar MCP (already available in session).

- **Background classifier**: a daily job (or on-page-load if cheap) reads upcoming calendar events in the next 14 days, LLM-classifies each as "interview / not interview / unclear", surfaces a notification chip on `/today` for the "interview" ones: "Anthropic onsite on Tuesday — generate prep?"
- **Operator confirms** → MIRA composes a mock matching the expected format. Inputs to the generator: company (from event attendees), role (from JD URL the operator has tagged), expected format (algo / system design / ML coding / behavioral / research-engineer-specific — classified from the event description).
- **Pre-interview brief** generated 24h before the event: study sheet of likely topics, suggested warm-ups, 2-3 sample problems the operator should drill the night before.
- **Behavioral mode** as a sibling to coding interview mode: MIRA asks STAR-format questions, listens via STT, gives feedback on structure + specificity (the Claude Code voice pattern the operator described from BlueDot prep).
- **Same-day debrief** after the real interview event passes: structured reflection prompt ("what tripped you up? what would you do differently?"). Feeds the next mock's question selection.

## Data model

### v1 additions

```sql
-- Migration 014_interview_phase_budgets.sql
ALTER TABLE attempts ADD COLUMN phase_time_seconds JSONB DEFAULT '{}'::jsonb;
ALTER TABLE attempts ADD COLUMN phase_budgets JSONB DEFAULT '{}'::jsonb;
ALTER TABLE attempts ADD COLUMN cutoff BOOLEAN DEFAULT FALSE;

-- For tracking interview-mode sessions specifically (vs. free practice)
ALTER TABLE attempts ADD COLUMN interview_mode_preference TEXT;
  -- 'silent' | 'nudges' | 'live_coach' | NULL (free practice)
```

```toml
# content/problems/<slug>.toml — new field
phase_budgets_seconds = { explore = 180, brainstorm = 240, plan = 180, implement = 480, verify = 120 }
# Must sum to time_bucket * 60. Validated at load.
```

### v3 / v4 additions (deferred)

```sql
-- Migration 015_interview_sessions.sql
CREATE TABLE interview_sessions (
  id BIGSERIAL PK,
  user_id UUID,
  source TEXT NOT NULL,  -- 'problem' | 'calendar_mock' | 'behavioral'
  -- For calendar-driven mocks
  calendar_event_id TEXT,         -- Google Cal event id
  target_role TEXT,               -- "Anthropic Research Engineer"
  target_company TEXT,            -- "Anthropic"
  format TEXT,                    -- 'algo' | 'system_design' | 'ml_coding' | 'behavioral'
  -- Audio capture
  audio_url TEXT,                 -- where the session recording lives (Fly volume? S3?)
  transcript JSONB,               -- full STT transcript with timestamps
  duration_seconds INT,
  -- Outcome
  mira_feedback_md TEXT,
  reflection_md TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Future: cap_hits tracking for the ElevenLabs character budget
CREATE TABLE tts_usage_monthly (
  user_id UUID,
  yyyymm TEXT,                    -- '2026-05'
  chars_used INT NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, yyyymm)
);
```

## Services

### v1: `app/services/phase_budget.py` (new)

Pure functions over the per-phase data. No I/O.

- `validate_budgets(budgets, time_bucket)` — sum check, all five phases present
- `phase_status(elapsed_seconds, budget_seconds, soft_threshold=0.8)` → `'ok' | 'soft_warn' | 'over'`
- `compose_review_breakdown(phase_time_seconds, phase_budgets, axis)` → dict with per-phase status, comparison vs. running average

### v2: `app/services/tts.py` (new)

ElevenLabs client with cost controls.

- `tts_say(user_id, text, cache_key=None)` — speaks text, increments user's monthly char count, returns audio URL (cached or freshly generated)
- `at_cap(user_id)` — boolean, true when the user hit their monthly cap
- `interviewer_voice_id(user_id)` — reads from settings
- Per-user cap default 30k chars/month, configurable

### v3: `app/services/interview_agent.py` (new — MIRA persona)

- `stuck_detector(elapsed_idle, prior_input, phase)` → `'silent' | 'nudge_offer'`
- `clarifying_question(problem, current_notes, phase, mode)` → short prompt for MIRA
- `live_coach_reaction(problem, current_notes, phase, recent_voice_transcript)` → next utterance for MIRA's voice

### v4: `app/services/calendar_classifier.py` (new)

- `is_interview_event(event)` — LLM call (Haiku) on title + description + attendees + duration
- `extract_interview_meta(event)` → `{company, role, format, jd_url}` if classifier confidence > threshold

## UI surfaces

### v1 — enhance existing `/problem/<slug>?mode=interview`

- Pre-start screen: shows phase budgets ("Explore 3m → Brainstorm 4m → Plan 3m → Implement 8m → Verify 2m · total 20m"). "Start" button.
- During session:
  - Existing timer (top-right) becomes a phase-aware widget: current phase name + countdown for that phase + total session countdown.
  - Soft warning at 80% of phase: corner toast (existing component, color = `--warn`).
  - On phase transition, auto-collapse the previous phase's textarea + auto-focus next phase's.
  - Hard cutoff at 100% of session: form locks, "Time's up" overlay, "Submit what you have for review →" CTA.
- Post-session review: existing review page + new "Time breakdown" section.

### v2 — voice layer on top of v1

- Pre-start: "🔊 Voice mode (default)" pill above the Start button. Toggle to mute.
- During: small audio-status indicator in the corner shows when MIRA is speaking, when STT is listening.
- Per-phase textarea: dictation button is the primary affordance; type-instead button is secondary.

### v3 — live agent + mode picker

- Pre-start: mode picker (silent / nudges / live coach). Affects the whole session's MIRA behavior.
- During: a discreet "MIRA listening" indicator when the agent is active. "Stuck" button visible.

### v4 — calendar-driven mocks

- **New surface:** `/interview/mock` — lists upcoming interview events (from calendar classifier) with "generate mock" CTA per event. Also accepts a pasted JD URL as an alternative.
- **Today / rail surface:** notification chip when an upcoming interview event is detected: "Anthropic onsite Tue 2pm — 24h study brief?".
- **Calendar event detail page** (new): pre-interview brief (study sheet) + "do a mock for this event" + "log debrief after the interview" stub.

## Cost estimate (ElevenLabs)

Modeling a heavy practice cadence: 3 interview-mode problems per day × 5 days × ~600 chars problem statement + 5-10 interviewer interjections × ~150 chars each (live-coach mode) ≈ **~3500 chars per session × 15 sessions = ~52k chars/month**.

| Plan | Monthly chars | Cost/mo | Sessions/mo at the model above |
|---|---|---|---|
| Starter | 30k | $5 | ~9 |
| Creator | 100k | $22 | ~28 |
| Pro | 500k | $99 | ~140 |

Recommendation: start on **Creator** ($22) once v2 ships. Until then, dev/staging uses Web Speech API. The character cap + canned-phrase caching keep us well inside Creator tier for daily prep + 1-2 calendar-driven mocks per week.

## Open questions for the next iteration

After v1 ships, these need answering before v2/v3:

1. **Audio recording storage** — Fly volume (cheap, low-latency, local to app), or S3/Backblaze (durable, replayable from anywhere, but adds an integration)? Cheap volume in v2; reconsider if mobile-app port wants remote replay.
2. **Voice id choice** — which ElevenLabs voice? "Adam" (default male) reads as Big Tech recruiter; "Bella" (default female) reads as research scientist. Operator-pickable in settings; the proposal leaves the default open.
3. **Mode-switch mid-session** — can the operator flip silent → nudges mid-problem? Probably yes (no state corruption); flag for the UX during v3.
4. **Behavioral mode vs. coding mode shared infrastructure** — most services overlap (timer, audio, MIRA agent), but the question rendering and rubric differ enough that they probably want sibling templates. Decide during v4.
5. **Calendar event ⇄ Linear task** — when an upcoming interview event triggers a mock, does it also create a Linear task ("study for Anthropic onsite") in the Personal Context project? Probably yes (matches the cross-surface integration pattern), but the linking model isn't designed yet.

## Phasing & rough sizing

| Phase | What | Rough effort | Depends on |
|---|---|---|---|
| **v1** | Phase budgets + tracking + soft/hard warnings + review breakdown | 1 PR · ~600 LoC across migration + service + template + tests | Standalone. Can start now after Charlie tickets + #330 clear. |
| **v2** | ElevenLabs TTS + STT default + caching + cost controls | 1 PR · ~400 LoC + ElevenLabs account + Fly secret | v1 + ElevenLabs API key |
| **v3** | Live interviewer agent (silent / nudges / live coach modes) | 1 PR · ~500 LoC + new MIRA persona | v2 + MIRA Phase 0+1 |
| **v4** | Calendar classifier + mock generation + behavioral mode + debrief | 2-3 PRs · ~1200 LoC across Cal MCP wiring + new surfaces | v3 + Google Cal MCP wired |

## When to start

Per operator instruction: after Charlie tickets #299–#306 land + PR #330 (hint fix) merges + MIRA Phase 0+1 ships + PR-1 of the Linear integration (using prototype #333 variant D) lands. v1 of this proposal can run in parallel with MIRA since it doesn't depend on the agent.

If you want me to start v1 sooner (since it's standalone and unblocked), say the word — otherwise this proposal sits as the queued spec for after the Linear integration PR-1.
