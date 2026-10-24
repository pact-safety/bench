# Weekly Hamming reflections

Saturday morning is the only structured thinking time I've reliably defended. The bench knows that and acts on it: a cron pre-generates this week's reflection at 7am local on Saturday so when I open `/reflect`, the prompts are already there. No 15-second wait while I'm trying to start.

## What I see when I open it

```
This week, in numbers
   ─────────────────────────────────
   attempts          6  (4 passed · 2 used hints · 1 looked at solution)
   avg confidence    3.2 / 5
   content finished  3
   weakest axis      eval design (54%)
   writings drafted  1
   readings captured 2
   ─────────────────────────────────

This week's prompts                            [Saturday 07:00 UTC]

   AVOIDING
   You skipped Plan on 4 of 6 attempts this week. Was that signal
   (the problems were familiar enough you didn't need it) or noise
   (you were tired / impatient)? Which way would a fellowship reviewer
   read it?

   COMPOUNDING
   The "scaled dot-product attention" problem appeared twice this
   week — once on day 2 with confidence 2/5, once on day 5 with
   confidence 4/5. What changed between them, and was the change
   transferable or one-shot?

   BIGGEST PROBLEM
   You captured "annotated transformer" three days ago and rated it
   5/5 but haven't drafted on it. What writing-shaped artifact would
   force you to operationalize what you read?
```

Each prompt has a label (`Avoiding`, `Compounding`, `Biggest problem`, occasionally a fourth like `Sycophancy detection` if the week's data warrants) and a body that cites specific numbers from my week. Not "what are you avoiding?" — `you skipped Plan on 4 of 6 attempts`.

## Why this shape

The first version of this surface generated generic Hamming-style prompts and I ignored them after week two. They felt like the platform was performing thoughtfulness at me. So I rewrote the prompt to make specificity a hard rule — if Sonnet can't cite an actual number from the week, the prompt is rejected and regenerated. The system prompt has five rules in priority order:

1. **SPECIFIC.** Generic "what are you avoiding?" boilerplate is a failure. Use the data.
2. **Open-ended.** No yes/no questions. I should have to write.
3. **No prefacing.** JSON only. Don't tell me you're about to give me prompts; give me prompts.
4. **Name sparse weeks.** If I had ≤2 attempts, the prompt set says so. Don't pretend it was productive.
5. **Never sycophantic.** "Keep up the great work" is the explicit failure mode.

Rule 5 is the one I check the prompts against most. If a reflect prompt ever opens with affirmation, it's a regression and I want to know.

## The Saturday cron

Pre-generation runs at Saturday 07:00 UTC. The cron walks the allowlist (single-tenant, so just me), checks each user's last-7-days activity, and skips if either:

- I have no attempts in the last 30 days (probably traveling — don't waste a generation), OR
- I have no attempts in the last 7 days specifically (the "quiet week" skip from the 2026-05-25 validation pass — generating "complete no-show" prompts against a zero-attempt week was the explicit failure mode the operator review surfaced).

When it does generate, the row gets `pregenerated=True` so the UI can surface "your reflection is ready" rather than "click Generate."

If the cron didn't fire (Fly was down, ANTHROPIC_API_KEY was unset, whatever), the page falls back to a Generate button. Manual generation takes about 12-15 seconds — the page shows a CSS-shimmer skeleton during the wait so it doesn't feel frozen.

## Writing the response

`/reflect/<id>` shows the prompts inline with a textarea below. Autosaves on every keystroke. No deadline; some of my best responses have been completed Tuesday evening when something else triggered the thought.

I write to all the prompts maybe 60% of the time. The other 40% I respond to one — usually the `Biggest problem` one, because that's the one that gets specific about the thing I've been avoiding.

## What feeds the data

`_build_week_summary()` walks five sources:

- `attempts` in the 7-day window
- `content_progress` rows checked in-window (kind, status, rating)
- `external_readings` — user-added content with notes_md > 20 chars (substantive notes only; one-word notes get filtered out so they don't pollute the signal)
- `writings_count_by_status` — drafts vs. published in-window
- `feedback_items_opened_count` — count of feedback rows created in-window

That feeds `WeekSummary` → JSON → Sonnet → reply parsed for `{summary, prompts[]}`. If the API call fails or the spend cap is hit, the canned 3-prompt fallback fires; it's still process-grounded but not data-specific.

## What I'd change

- **Route through the voice registry.** Sometimes I want Feynman to write my Saturday prompts, not Hamming. Queued; not on the roadmap.
- **A "respond via Claude chat" path.** I write to Claude almost as often as I write to the textarea. A small MCP tool that takes the prompts and lets me carry a Claude conversation, writing the synthesis back to the response field, would close a loop I currently close by hand.

## See also

- [Hints and mentor voices](hints-and-voices.md) — for the voice roster + how the per-attempt review voice differs from the reflect voice
- [Architecture: services](../architecture/services.md#hamming-reflect) — the actual `hamming_service.generate()` shape
