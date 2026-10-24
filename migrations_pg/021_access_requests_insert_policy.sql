-- BEN-150 (operator-approved 2026-08-18): tighten the public signup
-- form's anon INSERT policy so PostgREST anon-key holders cannot pick
-- their own status (previously WITH CHECK (true) — a forged
-- status='granted' row granted nothing since the allowlist moved to
-- allowlist_entries in 020, but it polluted the triage UI).
--
-- The app's own connection bypasses RLS and the form never sets
-- status (column default 'pending'), so nothing legitimate changes.

DROP POLICY IF EXISTS access_requests_anon_insert ON access_requests;
CREATE POLICY access_requests_anon_insert ON access_requests
    FOR INSERT
    TO anon, authenticated
    WITH CHECK (status = 'pending');
