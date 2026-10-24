-- RSS news feed engine Phase 1 — news_items + feed_health.
--
-- See docs/proposals/rss-news-feed.md (approved 2026-05-25, ship 3rd).
-- A poller running hourly (app/services/news_poller.py) fetches the
-- feeds listed in content/news_feeds.toml, parses each entry via
-- feedparser, and inserts into news_items (deduped by url). The
-- /news route reads from this table; pin/dismiss flip operator
-- intent flags; axes_json gets populated in Phase 2 by an LLM
-- classification pass against the bench's 13 axes.
--
-- feed_health is the per-feed observability table — last successful
-- fetch + last error so the operator can spot dead feeds without
-- diving into logs.

CREATE TABLE IF NOT EXISTS news_items (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    -- Feed slug from news_feeds.toml. Not a FK to a feeds table
    -- because feeds live in TOML (operator-curated, version-controlled);
    -- repo-level join is by string match.
    source          TEXT NOT NULL,
    title           TEXT NOT NULL,
    -- Dedup key. UNIQUE so the poller's "INSERT … ON CONFLICT DO
    -- NOTHING" is atomic.
    url             TEXT NOT NULL UNIQUE,
    -- Either the RSS <description> or, in Phase 2, an LLM-derived
    -- short summary. Plain text only; HTML stripped at insert time.
    summary         TEXT,
    -- Item-side pubDate. Used for ordering and "last 7 days" windows.
    published_at    TIMESTAMPTZ NOT NULL,
    -- When the bench saw the item (vs. when the publisher dated it).
    -- Useful when a feed back-fills items with old pubDates so we
    -- can still surface "new since yesterday."
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- LLM-tagged axes — populated in Phase 2 by the classifier job.
    -- Shape: ["mechanistic_interpretability", "alignment_proxies", ...]
    -- Empty array in Phase 1; the column exists now so the read path
    -- doesn't need a schema bump later.
    axes_json       JSONB NOT NULL DEFAULT '[]'::jsonb,
    -- Operator intent flags.
    --   is_pinned = "keep this visible, top of /news"
    --   is_dismissed = "I've read it / don't care, hide from /news"
    -- Mutually-exclusive in practice (UI only exposes one at a time)
    -- but both can be true at once — no constraint, the read paths
    -- handle the corner case.
    is_pinned       BOOLEAN NOT NULL DEFAULT FALSE,
    is_dismissed    BOOLEAN NOT NULL DEFAULT FALSE
);

-- /news chronological feed: newest first across all sources.
CREATE INDEX IF NOT EXISTS idx_news_items_published
    ON news_items (published_at DESC);

-- /news?source=foo filter: per-source chronological.
CREATE INDEX IF NOT EXISTS idx_news_items_source_published
    ON news_items (source, published_at DESC);

-- Pinned items: surface on top quickly. Partial index keeps it tiny.
CREATE INDEX IF NOT EXISTS idx_news_items_pinned
    ON news_items (published_at DESC)
    WHERE is_pinned = TRUE;


-- Per-feed observability. The poller upserts one row per feed_slug
-- on every tick; the operator can `SELECT * FROM feed_health` (or
-- the future /admin/feed_health UI) to spot dead feeds without
-- digging through stdout logs.
CREATE TABLE IF NOT EXISTS feed_health (
    feed_slug              TEXT PRIMARY KEY,
    last_success_at        TIMESTAMPTZ,
    last_failure_at        TIMESTAMPTZ,
    last_error_message     TEXT,
    -- Consecutive failure count, reset to 0 on each success. The UI
    -- uses this to decide whether to nag the operator ("feed X has
    -- failed 24 ticks in a row").
    consecutive_failures   INTEGER NOT NULL DEFAULT 0,
    -- How many items the last successful tick ingested (new + dupes).
    -- New = inserted; total = parsed from the feed XML. Useful for
    -- catching "feed returns the same 10 items forever" vs. "feed
    -- has stopped publishing" failures.
    last_items_seen        INTEGER NOT NULL DEFAULT 0,
    last_items_inserted    INTEGER NOT NULL DEFAULT 0
);
