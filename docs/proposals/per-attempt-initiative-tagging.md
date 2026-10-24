# Proposal: per-attempt initiative tagging

**Status:** approved (operator 2026-05-25) — ship 2nd (after chat-outcomes-table)

**Resolved decisions:**
1. Tagging mode: **optional, defaults to `settings.active_initiative`** at write time
2. Non-bench-resident initiatives: yes, `writings` accepts any active slug
3. `/focus` "Unassigned" row: hidden by default, toggleable (cleaner dashboard)
4. MCP `set_active_initiative` tool: separate follow-up, not bundled here

**Author:** Claude (under operator delegation)

**Date:** 2026-05-25

## Problem

Right now `/focus` attributes all bench-resident activity to **every** initiative whose `bench.surface == "/"`. So:

- An attempt on a Capstone-relevant problem (e.g., `13-sycophancy-eval-scoring`) shows under "Bench Product Development" *and* "MSCS Sycophancy Capstone" with the same count.
- A reflection written about drafting a fellowship application essay can't be distinguished from a reflection about a bench bug fix.
- The "last decided" link on `/focus` (from BEN-82 follow-up) does work per-initiative because the operator types the initiative slug into `log_chat_outcome` — but bench-internal activity (attempts / reflections / content / writings) has no such structured tag.

The fix: a per-row `initiative_slug` field on the bench's primary activity tables. Without it, `/focus` is structurally lying about per-initiative activity.

## Proposed design

### Schema

Migration 010 (assuming chat_outcomes table is 009) adds `initiative_slug TEXT NULL` to four tables:

```sql
ALTER TABLE attempts          ADD COLUMN IF NOT EXISTS initiative_slug TEXT;
ALTER TABLE reflections       ADD COLUMN IF NOT EXISTS initiative_slug TEXT;
ALTER TABLE content_progress  ADD COLUMN IF NOT EXISTS initiative_slug TEXT;
ALTER TABLE writings          ADD COLUMN IF NOT EXISTS initiative_slug TEXT;

CREATE INDEX IF NOT EXISTS idx_attempts_user_initiative
    ON attempts (user_id, initiative_slug, started_at DESC);
-- similar indexes on the other three tables
```

NULL = "unassigned" (or pre-tagging legacy). Foreign key NOT added because initiatives live in markdown files, not the DB. Validation happens at the write layer (the route handler checks the slug against `initiatives_service.load_initiatives()`).

### Write path

For each table, the relevant route gains an `initiative_slug` form field with a default from `settings.active_initiative` (which the operator can set via the existing settings page or — once it ships — via a chat).

Routes that need updating:

| Route | Current | Change |
|---|---|---|
| `POST /problem/{slug}/start` (or wherever attempts are created) | `Attempt` row with no initiative | Form field `initiative_slug` defaults to `settings.active_initiative`; validated against loaded initiatives |
| `POST /content/{slug}/progress` | `ContentProgress` row | Same pattern |
| `POST /reflect/generate` | `Reflection` row | Same — defaults to the active initiative at the time the reflection is generated (which is when the operator started writing it) |
| `POST /writings` | `Writing` row | Same |

A `data-initiative-slug` attribute on the operator-facing button means the operator usually doesn't see the picker at all — it's pre-filled from `settings.active_initiative`. The picker only appears when:
- No active initiative is set
- Operator explicitly wants to override (an "Other initiative?" link below the start button)

### Read path

`/focus` switches from the `bench.surface == "/"` attribution heuristic to **exact slug match**. The `FocusActivity` computation in `app/services/focus.py` now filters attempts/reflections/content_progress to those whose `initiative_slug == initiative.slug`. Capstone attempts show only under Capstone. Bench attempts only under Bench.

Initiatives whose `bench.surface` is null (e.g., `legal`, `content`) can still accrue activity if the operator explicitly tags it — useful if, say, a writing draft is for Legal correspondence. The picker accepts ANY active initiative slug.

### Migration / backfill

Existing rows have NULL initiative_slug. Two options:

**A. Leave NULL.** Existing activity stays "unassigned." `/focus` shows it under no initiative card; introduce an "Unassigned (legacy)" row on the dashboard if the count is non-zero. Operator can re-tag manually via a one-time admin page (or skip).

**B. Best-effort backfill at migration time.** Walk existing rows, infer initiative from problem-axis overlap with each initiative's `linear.label` or notes vocabulary. Almost certainly wrong for most rows; not worth the implementation cost.

**Recommend A.** Honest "we didn't know until now"; cheap to ship; the operator's recent activity dominates `/focus` anyway, and recent activity will all be tagged.

### Settings UI

Settings page gains an "Active initiative" dropdown sourced from `initiatives_service.load_initiatives()` filtered to `status="active"`. Persisted under `settings.active_initiative` (already supported by `/focus` for the ★ pin).

The MCP server's `set_active_initiative(slug)` tool — small addition to BEN-81 — lets a Claude chat change the active initiative mid-session. Operator says "I'm switching to capstone for the next hour"; subsequent attempts default to capstone tagging.

## Open decisions (operator input needed)

1. **Required or optional tagging at write time?**
   - **Optional** (recommend): defaults to `settings.active_initiative`; if that's unset, defaults to NULL. Zero new friction. Trade-off: operator can accidentally start a problem without realizing the active initiative is wrong; the attempt gets mis-tagged.
   - **Required**: operator MUST pick an initiative before starting any tracked activity. Worst friction; best data quality. Probably overkill for single-tenant.

2. **What about non-bench-resident initiatives?** Legal correspondence isn't really an "attempt" — it'd be a writing or a tracked task elsewhere. Should `writings` accept ANY initiative slug (including ones with no bench surface)?
   - **Recommend yes** — writings are the most likely place to want cross-initiative tagging (essays for a fellowship application, blog posts for Content, etc.).

3. **Should `/focus`'s "Unassigned" bucket be visible by default?**
   - **Visible**: makes the data-quality gap obvious. Encourages re-tagging.
   - **Hidden by default, toggleable**: cleaner dashboard. Recommend.

4. **MCP `set_active_initiative` tool: ship with this, or separately?**
   - **Recommend separately.** It's a one-line addition; doesn't gate the primary tagging work. Keeps PRs focused.

## Scope estimate

| File | Purpose |
|---|---|
| `migrations_pg/010_initiative_tagging.sql` | CODEOWNERS, operator-authored |
| `app/models.py` | Add `initiative_slug: str \| None = None` to Attempt, Reflection, ContentProgress, Writing |
| `app/repositories/{attempt,reflection,content,writing}_repository.py` | Read/write the new column |
| `app/main.py` | Form-field handling on 4-5 route handlers |
| `app/services/focus.py` | Switch activity attribution from bench.surface to slug match |
| `templates/*.html` | Initiative picker on start-problem / reflect-generate / writings forms; "Unassigned" row on /focus |
| `app/services/settings_form.py` (or similar) | Active-initiative dropdown |
| `tests/unit/test_*.py` | Many — every touched route + the focus attribution change |

**~10-14 files, ~700-1000 lines, 2-3 PRs (split: migration prep → write path → read path)**. Mostly mechanical except the focus attribution refactor, which needs careful test coverage for "Unassigned (NULL slug)" buckets.

## Why now / why later

**Why now:** the cross-surface integration we just shipped (`/focus` "last decided") only works for one of four activity types — chat outcomes via MCP. The other three (attempts/reflections/content) are still attributed by `bench.surface` heuristic. Closing the gap makes `/focus` actually useful for switching context across initiatives.

**Why later:** the operator is single-tenant, primarily working on bench-surface activity in a single dominant initiative ("Bench Product Development") most days. The lying-by-default is real but the practical impact is small. If the operator's daily mix is genuinely dominated by ONE initiative at a time, they can use `settings.active_initiative` as a pin and the data quality issue effectively disappears.

**Trigger to ship:** when operator starts working across ≥3 initiatives in a week and `/focus` becomes unhelpful because of activity bleed.

## Acceptance criteria

- All four primary tables have `initiative_slug` columns indexed appropriately
- Write paths default to `settings.active_initiative` and validate against loaded initiatives
- `/focus` activity counts match exactly tagged rows (no more bench.surface attribution)
- Existing rows show up under "Unassigned" (or hidden by default per open-decision 3)
- Tests cover the attribution change end-to-end
- MCP `set_active_initiative` is a separate follow-up

## Alternatives considered

- **Tag-based (many initiatives per attempt)**: rejected. Single-tag is the operator's actual mental model; multi-tag would require disambiguation in /focus.
- **Derive initiative from active track or active JD**: rejected. Initiatives are the unit; tracks and JDs are inputs to specific initiatives, not the carrier. Wiring derivation creates implicit coupling.
- **Build a job/tag table separate from primary tables**: rejected. Adds a join on every /focus query for marginal flexibility.
