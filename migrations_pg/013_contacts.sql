-- /connecting (WS6, BEN-94) — bi-directional networking tracker with
-- warmth-decay scoring.
--
-- The operator tracks contacts and the touchpoints with each one.
-- Each contact has a target re-touch cadence (default 30d); a
-- warmth score is computed at read time from days-since-last-
-- interaction relative to that cadence. Coldest contacts surface
-- at the top of /connecting so the operator can see who's overdue.
--
-- Bi-directional = each interaction is tagged inbound / outbound /
-- mutual. The list view can highlight "their move" (last
-- interaction was inbound — implies a reply may be owed).
--
-- Two tables. contact_interactions has ON DELETE CASCADE so
-- archiving a contact via DELETE (rare; the normal path is the
-- archived flag) doesn't leave orphan rows.

CREATE TABLE IF NOT EXISTS contacts (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id         UUID NOT NULL,
    -- Display name as the operator wants to see them in the list.
    -- Required; everything else is optional.
    name            TEXT NOT NULL,
    -- Optional context fields. Operator decides what to fill — no
    -- validation here beyond non-empty NULLs being collapsed to NULL.
    email           TEXT,
    handle          TEXT,    -- Twitter / LinkedIn / Slack — free form.
    context         TEXT,    -- "where I know them from, why they matter"
    -- Target re-touch interval in days. Drives the warmth-decay
    -- formula: warmth = max(0, 1 - days_since_last / (cadence * 2)).
    -- 30 = monthly cadence (sensible default for professional
    -- connections); operators can override per-contact for closer or
    -- looser-cadence relationships.
    cadence_days    INTEGER NOT NULL DEFAULT 30
                    CHECK (cadence_days BETWEEN 1 AND 3650),
    -- Soft-delete. /connecting hides archived by default; an explicit
    -- "show archived" toggle on the list view surfaces them again.
    -- Hard DELETE remains available via the danger-zone path but the
    -- normal flow is archive (preserves history).
    archived        BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Main list query: contacts for a user, optionally filtering by
-- archived state. The list-view sort (by warmth) happens in the
-- service layer because warmth is a computed value over the
-- interaction history; no covering index on it would help.
CREATE INDEX IF NOT EXISTS idx_contacts_user_archived
    ON contacts (user_id, archived);

CREATE TABLE IF NOT EXISTS contact_interactions (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    contact_id      BIGINT NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    -- Denormalized for query speed + future RLS friendliness. Set on
    -- insert from the parent contact; never overwritten.
    user_id         UUID NOT NULL,
    -- When the touchpoint actually happened (vs. when the operator
    -- logged it). Operator can backdate via the form.
    occurred_at     TIMESTAMPTZ NOT NULL,
    -- Kind: 'sent' | 'received' | 'meeting' | 'call' | 'message' |
    -- 'note'. Free-form check so future kinds (e.g. 'event-attendance')
    -- can be added without a migration; the service layer validates
    -- against a known vocabulary at write time.
    kind            TEXT NOT NULL,
    -- direction: 'outbound' | 'inbound' | NULL (mutual / meeting /
    -- call). The list view highlights "their move" when the last
    -- interaction for a contact has direction='inbound'.
    direction       TEXT
                    CHECK (direction IS NULL OR direction IN ('outbound', 'inbound')),
    -- Operator notes — what was discussed, follow-ups, etc.
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Per-contact history (newest-first) and cross-contact recent feed.
CREATE INDEX IF NOT EXISTS idx_contact_interactions_contact_when
    ON contact_interactions (contact_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_contact_interactions_user_when
    ON contact_interactions (user_id, occurred_at DESC);
