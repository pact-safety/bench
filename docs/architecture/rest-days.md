# Rest days (Saturday + Sunday)

How the bench enforces weekly rest without scolding the operator into it. Filed in response to operator's 2026-05-18 request: *"I need to in-build rest or I'll lose it."*

## The problem rest solves

The bench is a daily-driver tool aimed at sustained progress over weeks or months. The most common failure mode for a tool like this isn't user inactivity — it's **monotonic guilt-driven over-drilling that collapses into burnout**. The operator has named this risk explicitly.

The research is consistent:

- **Kellmann (2010), *Preventing overtraining in athletes in high-intensity sports***: scheduled recovery improves subsequent training adaptation more than continuous load. Athletes who self-impose rest days perform meaningfully better on follow-on sessions than those who don't.
- **Walker (2017), *Why We Sleep***: skill consolidation happens during sleep, not during the doing. Inadequate recovery directly degrades the value of yesterday's practice.
- **Raichle (2001), *Default Mode Network***: the brain's integrative work — synthesis, pattern-finding, insight — happens during rest, not during focused effort. The Eureka moment is well-documented to surface during mind-wandering states (shower, walk, drive).
- **Maslach & Leiter, *The Truth About Burnout***: three burnout dimensions (exhaustion, cynicism, inefficacy) all worsen monotonically with insufficient recovery. Prevention is much easier than recovery.
- **Ericsson, *Peak***: even strict deliberate-practice protocols cap at ~4 hours/day before returns diminish, with explicit recovery between sessions.

Translation to the bench: **the work this week is consolidating while the user does something else this weekend.** That's the framing.

## Posture

The rest-day surface should be the minimum thing that respects the operator's autonomy AND prevents the bench from becoming a guilt machine. Specifically:

1. **No drilling content surfaced.** No next-action card, no daily slots, no streak penalties, no "you're falling behind."
2. **Greet, not lecture.** The page exists; it doesn't preach. The framing IS the intervention.
3. **One escape hatch for the anxious user.** If the operator can't accept the rest, surface their actual evidence (the week's accomplishments at the bench) — not as a "look how busy you were" but as a calibration check: "the work you already did this week is what you're recovering from."
4. **Don't allow an opt-out in v1.** The operator wrote "I need to in-build rest or I'll lose it." Designing in an "I'll drill on Saturday anyway" toggle defeats the point. If it bites in practice, revisit.

## What the rest-day surface looks like

When `/` is visited on Saturday or Sunday in the user's local timezone:

```
Saturday.
{display_name or "Hi"}, hope today's a good one.

No drills today. The work this week is consolidating while you do
something else.

▸ Have to peek? Here's what your week looked like at the bench.
```

The `▸` expander reveals an evidence-based week recap:

- **N problems attempted** — listed by title, linked to the attempt
- **N content items completed** — readings/videos/podcasts/exercises by kind, linked to each
- **N reflections written** — date + title (or first 80 chars), linked
- **Skill changes** — if the user retook the assessment this week, show the per-axis delta
- **Credentials uploaded** — if any

Each item has a link to itself, in case the operator wants to revisit one specific thing — but the framing is *not* "go work on these." It's *"this is what you already did. The rest is part of finishing the work."*

The recap is bounded — last 7 days only, no further-back rolling history. The point is acknowledging the week's actual output, not arguing about month-over-month progress.

## Timezone resolution

Use the same browser-local approach as the existing home-page greeting (committed in 5407f28). Sat/Sun is judged against the operator's local clock, not the server's UTC. If `display_tz` is set in user settings, that wins; else the browser's `Intl.DateTimeFormat().resolvedOptions().timeZone`.

## What does NOT change on rest days

- **Profile dropdown, navigation, all other pages still work.** The user can visit `/aim`, `/library`, `/feedback/inbox`, etc. We're only changing the **home page's content**, not blocking the rest of the app.
- **No streak penalty.** Whatever streak-tracking the bench grows in the future treats Sat/Sun as "completed by design" rather than as gaps. (No streak tracker exists today; this is a future-proofing constraint.)
- **Reflect remains accessible.** Weekly Hamming-mode review is a natural Sunday activity for some operators. If they want to open `/reflect` voluntarily, fine. We just don't *push* them there.
- **Active background tasks** (auto-archive of closed GH issues, etc.) keep running. The rest day is for the user, not the bench.

## Implementation shape

### Route logic

In `app/main.py:home()`:

```python
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    # ... existing auth + settings load ...

    # If today is Sat or Sun in the user's local timezone, route to
    # the rest-day variant. Day-of-week is computed client-side
    # (matches the existing greeting time logic from 5407f28) by
    # passing the date string and reading it back, OR computed
    # server-side from user_settings.display_tz.
    is_rest_day = _is_weekend_for_user(request)
    if is_rest_day:
        return _render_rest_home(request, uid)

    # ... existing weekday logic ...
```

`_is_weekend_for_user(request)`:
- Pull `display_tz` from user_settings if set, fall back to `Intl`-style header detection or pure UTC weekend (UTC fallback is acceptable — the worst case is one user gets the rest day starting a few hours early or late)
- Compute `weekday() in {5, 6}` (Sat = 5, Sun = 6 in Python)

`_render_rest_home(request, uid)`:
- Query last 7 days of attempts/content_progress/reflections/writings/credentials for `uid`
- Compute simple counts + the listed items
- Render `templates/home_rest.html` with the recap context

### Template

New `templates/home_rest.html`. Spare. Centered card. Mostly text. The `<details>` expander pattern from the dropdown menu (proven) is fine for the week-recap reveal.

### Tests

- Mon-Fri in user's TZ → existing home renders.
- Saturday → rest-day page renders, no `daily_slots` / `next_action` in the context.
- Sunday → same.
- Saturday with no activity this week → expander shows "Nothing logged this week — that's fine too."
- Recap surfaces correct items from the last 7 days (mock the repos).
- `display_tz` set to a timezone where it's Friday locally on Saturday UTC → returns the weekday page (or vice versa).

## Decisions baked in

| Decision | Choice | Why |
|---|---|---|
| Days | Saturday + Sunday | Operator specified. Easy to add a third "rest day" later via config if useful. |
| Opt-out | None in v1 | Operator's "I need to in-build rest or I'll lose it" is the explicit ask for forced rest. |
| Recap window | Last 7 days | Acknowledge the week; don't get lost in longer history. |
| Recap content | Read-only listing | Each item links to itself; no rebuild-of-Today UI. |
| Streak interaction | No streak tracker exists today; future-proof by treating rest days as "complete." | Don't introduce guilt at the rest-day layer. |
| Visual style | Spare, centered card. One short paragraph. | The minimum that respects the operator's autonomy. |

## What this is NOT

- **Not** a guilt trip. The recap section is opt-in via expander, not surfaced by default.
- **Not** an absolute lock. Operator can still navigate to `/library`, `/aim`, `/reflect` on a rest day if they choose.
- **Not** a streak break. Future streak tracking (if any) treats Sat/Sun as "completed by design."

## Open considerations

- **Travel / timezone hopping**: if the operator's `display_tz` is wrong (e.g., they fly to Asia and forget to update settings), the rest day will fire on the wrong calendar day. Tolerable; the worst case is one day shifted.
- **Operator gets a productive Saturday despite the rest framing**: they can visit `/library` and read content directly. That's fine — choosing to rest is the intervention, not enforced rest. The rest-day home is a default, not a wall.
- **Holiday handling**: not addressed in v1. If the user takes a Wednesday off, the bench doesn't know. Could add a manual "today is a rest day" toggle later.

## See also

- [`app/services/daily_flow.py`](https://github.com/pact-safety/bench/blob/main/app/services/daily_flow.py) — the weekday picker that this rest-day path bypasses
- [`docs/architecture/imposter-syndrome.md`](imposter-syndrome.md) — companion-philosophy doc; both pieces are about preventing the bench from becoming a guilt machine
- 5407f28 — the existing local-timezone greeting commit; uses the same TZ resolution path

## References

- Kellmann, M. (2010). Preventing overtraining in athletes in high-intensity sports and stress/recovery monitoring. *Scandinavian Journal of Medicine & Science in Sports*.
- Walker, M. (2017). *Why We Sleep: Unlocking the Power of Sleep and Dreams*. Scribner.
- Raichle, M. E., et al. (2001). A default mode of brain function. *Proceedings of the National Academy of Sciences*.
- Smallwood, J., & Schooler, J. W. (2015). The science of mind wandering: Empirically navigating the stream of consciousness. *Annual Review of Psychology*.
- Maslach, C., & Leiter, M. P. (1997). *The Truth About Burnout: How Organizations Cause Personal Stress and What to Do About It*. Jossey-Bass.
- Ericsson, A., & Pool, R. (2016). *Peak: Secrets from the New Science of Expertise*. Houghton Mifflin Harcourt.
