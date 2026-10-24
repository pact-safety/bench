# Proposal: RSS news feed engine

**Status:** approved (operator 2026-05-25) — ship 3rd, Phase 1 only initially

**Resolved decisions:**
1. Read surface: **`/news` only.** Phase 3 (home-margin surfacing) explicitly deferred until `/news` usage proves the bench is the right surface for daily news consumption. Avoids news becoming a procrastination layer on the home page
2. Tagging model (Phase 2): Haiku 4.5 with prompt caching (mirrors PR #223's lesson)
3. Poll frequency: hourly (Phase 1 default; can dial back later)
4. Read state: pin + dismiss in Phase 1; click-tracking deferred

**Author:** Claude (under operator delegation)

**Date:** 2026-05-25

**Predecessor:** BEN-5 ("Homepage margins: most-relevant AI news for selected JD") + the news-engine roadmap from session 2026-05-19.

## Problem

The bench's `/library` curates evergreen reading. There's no surface for **time-sensitive** AI/alignment news — the kind the operator's role-target reviewers expect candidates to be tracking.

This matters specifically because research-engineer roles at safety orgs and frontier labs explicitly weight "do you read the field?" — a fellowship reviewer asking what the candidate makes of [recent paper / news / report] is a known phenotype of those interviews.

The other Claude chat surfaced this concretely on 2026-05-19: "RSS feeds → news feed in the bench." This proposal turns that prompt into a concrete shipping plan.

## Proposed design

Three-phase landing so each piece can ship + prove itself before the next:

### Phase 1: news_items table + poller + `/news` page

**Schema** (migration 011 or whatever's next):

```sql
CREATE TABLE news_items (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source          TEXT NOT NULL,           -- feed slug (e.g., "import-ai")
    title           TEXT NOT NULL,
    url             TEXT NOT NULL UNIQUE,    -- dedup key
    summary         TEXT,                    -- from RSS description or LLM-derived
    published_at    TIMESTAMPTZ NOT NULL,    -- from RSS pubDate
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    axes_json       JSONB NOT NULL DEFAULT '[]'::jsonb,  -- LLM-tagged; populated in Phase 2
    is_pinned       BOOLEAN NOT NULL DEFAULT FALSE,      -- operator-pinned for /aim "recent in your axes"
    is_dismissed    BOOLEAN NOT NULL DEFAULT FALSE       -- operator hides "read it"
);

CREATE INDEX idx_news_published ON news_items (published_at DESC);
CREATE INDEX idx_news_source_published ON news_items (source, published_at DESC);
```

**Feed registry** — `content/news_feeds.toml`:

```toml
[[feed]]
slug = "anthropic-news"
name = "Anthropic news"
url = "https://www.anthropic.com/news/rss.xml"
tier = 1

[[feed]]
slug = "metr"
name = "METR"
url = "https://metr.substack.com/feed"
tier = 1

# ... (initial feeds list — operator picks; recommendations below)
```

**Poller** — `app/services/news_poller.py`. APScheduler background job, hourly. For each feed:
1. Fetch RSS (with timeout, exponential backoff)
2. Parse via `feedparser` (well-trodden Python RSS lib)
3. For each item: dedup by URL, insert if new
4. Track per-feed error state in a tiny `feed_health` table so the operator can see "this feed has been failing for 3 days"

**Route**: `GET /news` — chronological feed, all sources, paginated. Filter chips by tier + source. Dismiss + pin actions (POST endpoints). Reuses the `library-list` and `journal-entry` CSS patterns.

**Recommended initial feed list (Tier 1):**

The labs themselves + canonical evals shops + alignment forum:

- Anthropic news (`anthropic.com/news/rss.xml`)
- OpenAI blog (`openai.com/blog/rss.xml`)
- Google DeepMind blog (`deepmind.google/blog/rss.xml`)
- METR (`metr.substack.com/feed`)
- Apollo Research
- Redwood Research
- Center for AI Safety newsletter (`newsletter.safe.ai/feed`)
- Alignment Forum (`alignmentforum.org/feed.xml`)
- LessWrong curated frontpage (`lesswrong.com/feed.xml?view=curated-rss`)

**Recommended Tier 2 (weekly digests / commentary):**

- Import AI (`jack-clark.net/feed`) — Jack Clark's weekly research roundup
- Don't Worry About the Vase (`thezvi.substack.com/feed`)
- AI Snake Oil (`aisnakeoil.substack.com/feed`)
- Asterisk Magazine
- Dwarkesh Patel (`dwarkesh.com/feed.xml`)

URLs to verify before shipping (some feeds change paths) — small upfront work in operator review.

### Phase 2: LLM auto-tagging against the 13 axes

When a new item lands in `news_items`, an async background job calls Sonnet (or Haiku — see open decisions) with the title + summary + first paragraph and asks: "Which of the 13 bench axes does this item touch? Score 0-1 per axis, only return axes with score ≥ 0.5."

The model output writes to `news_items.axes_json`. The poller surfaces items in two places:

- **`/news`**: filter chips by axis ("show me items touching `mechanistic_interpretability`")
- **`/aim` "Recent in your axes" section** (new): top 3-5 items from the last 7 days that touch the operator's weakest axes, calling them out as "worth reading if you're working on these"

LLM costs: with ~10-15 feeds polling hourly and ~20-50 items/day across all sources, the tagging burden is well under $1/day on Haiku.

### Phase 3: Homepage news margin (closes BEN-5)

The home page (`/`) has wide unused margins. After Phase 2 is settled, surface 3-5 axes-weighted items in the right margin, refreshed daily. Click-through to the source URL; a "✕" dismisses for that operator.

This is the simplest phase but lands last because it depends on the tagging quality from Phase 2 — surfacing un-tagged items on the homepage would be noisy.

## Open decisions (operator input needed)

1. **Feed list?** The Tier 1 + Tier 2 lists above are my best read for the operator's target roles. Worth a 10-minute review to add/remove specific sources. Mostly Open: which Substacks, which podcasts (Dwarkesh transcripts vs. audio-only handling), whether to include arXiv firehoses (probably not — too noisy without filtering).

2. **Sonnet or Haiku for tagging?** Haiku is ~5x cheaper and tagging is a templated classification task — recommend Haiku 4.5 (mirrors PR #223's Reflect-latency lesson). Sonnet only justifies if classification accuracy turns out to matter more than I expect.

3. **Poll frequency?** Recommend **hourly** during Phase 1 (light fetch load; ~10 feeds × 24 polls/day = 240 HTTPS requests, trivial). Operator can dial to 4-hour or 30-minute later.

4. **Read state per item?** Phase 1 ships pin + dismiss. Open question: also track "clicked" state via JS so /news can show "8 unread from this week"? Recommend defer — pin/dismiss is the operator's primary intent signal.

5. **Email-forward inbound for "I read this elsewhere, add it"?** Parked in `docs/roadmap.md` already. Don't ship in Phase 1; pick up if /news usage proves the bench is the right surface for news capture.

6. **Phase 3 home-margin: hidden by default?** Cleanest UX is to show it on the home page only when the operator is signed in AND the news_items table has tagged items. Otherwise the empty state would be weird.

## Scope estimate

| Phase | Files | Lines | PRs |
|---|---|---|---|
| Phase 1 (table + poller + /news) | ~7-9 | ~600-900 | 1-2 |
| Phase 2 (LLM tagging + /aim integration) | ~4-5 | ~250-400 | 1 |
| Phase 3 (home margin) | ~3-4 | ~150-250 | 1 |

**Total: 14-18 files, ~1000-1500 lines, 3-4 PRs.** Migration (`011_news_items.sql` or `012` depending on chat-outcomes-table ordering) is CODEOWNERS-protected, operator-authored. The poller dep (`feedparser`) is small and stable.

## Why now / why later

**Why now:** the bench's "make-it-legible" wave shipped /about and /writing — reviewer-facing artifacts. A news feed turns the bench into a daily-driver TOOL for the operator, not just a portfolio piece. Operator opens bench in the morning → sees what landed overnight in the field → decides whether to drill or read. The bench becomes the news-and-drill loop instead of "the news loop happens in Twitter/Substack and the drill loop happens at bench."

**Why later:** the operator's actual interview prep activity (problems, reflections) is the highest-leverage use of time. A news feed risks becoming a procrastination surface (read 5 more items instead of attempting 1 more problem). The honest counterargument is real.

**Compromise / test:** ship Phase 1 (just `/news`, no homepage surfacing) and observe whether the operator opens it daily. If yes → Phase 2+3. If no → /news exists as a captured-news log without being a daily pull.

**Trigger to ship:** when the operator notices themselves losing context on the field because they're heads-down on bench prep. The bench should serve the operator's prep, including by surfacing what's worth knowing without forcing a separate tab-thrash.

## Acceptance criteria

### Phase 1
- `news_items` table + `feed_health` table exist with the right indexes
- `content/news_feeds.toml` lists ≥6 Tier-1 feeds
- Poller runs hourly, fetches all feeds, deduplicates by URL
- `/news` renders newest-first with source filter + dismiss + pin
- One feed failing for 24h shows in operator's feedback inbox or a dedicated `/admin/feed_health` view
- Tests: feed parsing fixtures (no live network in unit tests), dedup behavior, poll-failure handling

### Phase 2
- Sonnet/Haiku call tags each new item with ≤3 axes at confidence ≥0.5
- `/news` gains axis filter chips
- `/aim` "Recent in your axes" section renders top 3-5 items
- Cost monitoring: per-day API spend logged via the existing `spend_cap` module

### Phase 3
- Home margin shows 3-5 axes-weighted items on weekdays (rest days hide it — consistent with `home_rest.html`)
- Items the operator dismisses don't reappear
- Tests: home-margin presence/absence under various data states

## Alternatives considered

- **Email digest instead of /news page**: rejected. Email subscriptions exist already; the bench's value-add is the in-app surfacing.
- **Use a third-party aggregator (Inoreader / Feedly) and embed**: rejected. Operator owns the curation; vendor lock-in is wrong shape.
- **Skip RSS, use Twitter/X API directly**: rejected. RSS is stable, doesn't require API keys, doesn't go away when X policy changes. RSS-via-Substack covers most of what's interesting anyway.
- **Don't store items; fetch on every render**: rejected. Want axis tagging persisted; want dismiss state durable.
