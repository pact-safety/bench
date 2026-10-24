-- Hash-based skip for the startup content loader.
--
-- Every uvicorn boot used to upsert 43 problems + 32 content items =
-- 75 round-trips × ~900ms over Supabase Session pooler = ~70s before
-- the app could accept requests. With this column, the loader does
-- ONE round-trip per table (the hashes SELECT) plus zero upserts on a
-- restart with no markdown changes, taking startup to ~1s.
--
-- NULLABLE column (no default backfill) so the ALTER is metadata-only
-- and doesn't acquire an exclusive lock long enough to hit the
-- Supabase pooler's statement timeout. Loader treats NULL as "no
-- hash recorded yet" → always upserts on first contact, which
-- backfills the hash naturally.

ALTER TABLE problems ADD COLUMN IF NOT EXISTS content_hash TEXT;
ALTER TABLE content_items ADD COLUMN IF NOT EXISTS content_hash TEXT;
