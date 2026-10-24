-- 019_content_pinned.sql — pin a reading to the top of the stack (BEN-133).
--
-- Rides on the existing content_progress row per (user_id, content_id), the
-- same as favorited_bool / rating_1_to_5 in 001_consolidated — pinning is a
-- per-user preference, not a property of the shared content item.
--
-- Timestamp rather than boolean so several pins keep a stable order: the most
-- recently pinned surfaces first.
--
-- Why this file exists at all: the column was already present in the live
-- database, but nothing in migrations_pg/ created it — it had been applied
-- out of band, and the version of this migration that was written lived in
-- the dead SQLite `migrations/` directory, which the app has never applied
-- (app/main.py runs migrations_pg/ only). A fresh database would therefore
-- have come up without a column the code is about to depend on.
--
-- IF NOT EXISTS makes it a no-op against the live database and correct
-- against a fresh one, which is the whole point.

ALTER TABLE content_progress ADD COLUMN IF NOT EXISTS pinned_at TIMESTAMPTZ;

COMMENT ON COLUMN content_progress.pinned_at IS
  'When the user pinned this item. NULL = not pinned. Ordered DESC so the '
  'most recently pinned surfaces first.';
