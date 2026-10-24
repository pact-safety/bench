-- DB-backed allowlist (Bench v2 launch week): approving an access
-- request in /admin/access-requests grants sign-in without a deploy.
-- The env vars LIS_ALLOWED_USER_IDS / LIS_ALLOWED_EMAILS remain an
-- additive bootstrap/back-door (the app UNIONs both sources) so a DB
-- problem can never lock the operator out.
--
-- Deliberately a SEPARATE table from access_requests: that table's
-- RLS allows anon INSERT (it backs the public signup form), so
-- deriving access from access_requests.status would let anyone
-- holding the anon key insert themselves pre-granted. This table has
-- RLS enabled with NO policies — deny-all for the PostgREST JWT
-- roles; only the bench's own connection (table owner, bypasses RLS)
-- reads or writes it.

CREATE TABLE IF NOT EXISTS allowlist_entries (
    id                 BIGSERIAL PRIMARY KEY,
    -- Stored lowercase (the repository normalizes) and matched against
    -- the OAuth session email exactly like LIS_ALLOWED_EMAILS.
    email              TEXT NOT NULL UNIQUE,
    note               TEXT,
    -- Admin (auth.users id) who granted. Audit only — no FK so a
    -- future admin-account deletion can't be blocked by grant history.
    added_by           UUID,
    -- Provenance when the grant came from an access request; NULL for
    -- direct adds from the admin UI. No FK for the same reason.
    access_request_id  BIGINT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Soft revoke: the row stays for audit; NULL = active.
    revoked_at         TIMESTAMPTZ
);

ALTER TABLE allowlist_entries ENABLE ROW LEVEL SECURITY;
