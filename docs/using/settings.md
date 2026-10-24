# Settings and accessibility

!!! tip "Looking for what the accessibility toggles actually do?"

    [Accessibility](accessibility.md) covers the three toggles, what holds
    regardless of your settings, and where the app is still weak.

`/settings` collects all the toggles. Five panels: skill profile, review voice, profile, accessibility, weekly reflection.

## Skill profile

- Shows latest assessment date.
- `Retake the assessment` → starts a new run at `/assess/<run_id>`.
- `or reset all progress →` link goes to `/settings/reset` (see below).

## Review voice

A pointer to `/voices` where you browse the named-thinker roster and set your default. See [Hints and voices](hints-and-voices.md).

## Profile

Local single-user mode. Three fields, all persisted to `users.settings_json`:

- Display name (used in the home page greeting)
- Email (for future hosted mode; not sent anywhere now)
- Time zone (IANA list — empty = system default; affects "today" boundary in scheduler)

Live email validation mirrors the server-side regex; surfaces the error on blur once you've left an invalid value.

## Accessibility

Three toggles, all persisted to `users.settings_json.a11y`. Applied via `data-*` attributes on `<html>` in `base.html`, with CSS in `static/css/main.css`.

| Toggle | What it does | Implementation |
|---|---|---|
| **Reduce motion** | Zeroes animations + transitions. Also respects the OS `prefers-reduced-motion` media query automatically. | `[data-reduce-motion="1"]` selector + `@media (prefers-reduced-motion: reduce)` global rule |
| **Larger text** | Bumps base font 16px → 19px (matches WCAG large-text threshold). | `html[data-larger-text="1"] { font-size: 19px; }` |
| **Higher contrast** | Pure black/white body text, thicker focus rings, underlined links. | `html[data-high-contrast="1"]` overrides several `--text-color` and `--border-*` variables |

All three persist across reload (server-side) and apply on the next render.

## Weekly reflection

A pointer to `/reflect`. See [Reflect](reflect.md).

## Reset progress

`/settings/reset` is the destructive escape hatch. Useful for:

- Testing the onboarding flow
- Starting over after a stretch of test attempts
- Wiping practice data while keeping authored work

### What it deletes

| Table | Why |
|---|---|
| `attempts` | Practice submissions |
| `content_progress` | Read/watched/rated content rows |
| `review_state` | Per-problem recall scoring |
| `sessions` | Session aggregates |
| `assessment_runs` + `assessment_responses` | The assessment itself |
| `attempt_reviews` | Cascades from attempts |
| `reflections` | Hamming-mode replies |

Also clears `users.settings_json.onboarding_skipped` so the next visit to `/` redirects to `/onboarding`.

### What it keeps

- JDs you've pasted
- Writings + drafts
- Feedback inbox
- Credential uploads (CV parses)
- Your account itself (no re-sign-in)

### Confirmation gate

The big red button is **disabled by default**. To enable: retype the visible row-count number into the confirmation input. Prevents single-click fat-finger deletes.

## See also

- [Architecture: data model](../architecture/data-model.md)
