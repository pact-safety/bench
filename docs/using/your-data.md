# Your data

What bench stores, who can read it, and how to get rid of it. Short, because
the honest answer is short.

## What's stored

Everything you produce in the app, tied to your user id:

- Attempts — code, phase notes, timings, whether tests passed, confidence
- Content progress — what you read or watched, when, and recitation history
- Assessment and skill scores, readiness, JD analyses, credential runs
- Reflections, decisions, writing drafts
- Mira sessions and messages
- Settings — display name, time zone, review voice, accessibility toggles
- Feedback you submit
- Cached read-aloud audio (`tts_cache`) — generated speech, so a chapter is
  synthesised once rather than on every visit. Your own voice recordings are
  **not** stored; they are transcribed and discarded.

Authentication is GitHub OAuth via Supabase. Bench never sees your GitHub
password, and there is no password for bench itself to leak.

## Who can read it

**Only you.** Two independent layers, on purpose:

1. **Application layer** — every serve route filters on the requesting user's
   id. A route that forgets is a bug, which is why there is a second layer.
2. **Database layer** — row-level security is enabled on all 36 tables in the
   `public` schema, with owner-scoped policies. Even a query that forgot its
   `WHERE user_id =` clause returns nothing for another user's rows.

The five tables without per-row policies (`news_items`, `feed_health`,
`kb_documents`, `kb_chunks`, `schema_migrations`) hold no per-user data and are
deny-all to signed-in roles — they are reachable only by the server itself.

The operator (Li) has database access, as the operator of any self-hosted tool
does. There is no analytics vendor, no session-replay tool, and no third-party
script on the page.

## What is sent to third parties

- **Model providers** — only for the surfaces listed in
  [AI in the bench](ai-and-your-work.md), and only that call's inputs.
- **Sentry** — error reports when something breaks. Stack traces and request
  metadata, not your attempt contents.
- **Resend** — transactional email to the operator when you submit an access
  request.

That is the complete list. No advertising, no data brokers, no "partners".

## Deleting your account

`/settings/delete-account` — it is a real delete, not a soft flag.

You have to type `DELETE MY ACCOUNT` exactly, and the server re-checks that
phrase rather than trusting the form, so a crafted POST can't skip the gate.
The deletion runs as a single transaction across 12 user-scoped tables plus
your `public.users` row, so a failure part-way through cannot leave you with
attempts wiped and writings intact. Tables that reference your user row with
`ON DELETE CASCADE` — cached audio among them — go with it.

Two honest caveats:

- **Your Supabase `auth.users` row survives.** That is the auth provider's
  table, not bench's, and bench does not mutate it. Signing in again with the
  same GitHub identity produces a clean account that goes through onboarding as
  new — but the identity record itself persists until removed at the Supabase
  level. Ask the operator if you want that too.
- **Backups.** The database is backed up daily. Deleted rows leave live tables
  immediately and age out of backups on the retention schedule.

If you want everything gone rather than reset, `/settings/reset` clears
progress while keeping the account.

## Export

There isn't one yet. If you want your data out, ask — it's a query, not a
project, and if more than one person asks it becomes a feature.

## Related

- [AI in the bench](ai-and-your-work.md)
- [Settings](settings.md)
- [`SECURITY.md`](https://github.com/pact-safety/bench/blob/main/SECURITY.md) — the threat model
