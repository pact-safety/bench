# Security

This is a short threat model, not a compliance document. It answers
four questions honestly, then explains how to report a problem.

## Supported versions

This project is alpha-stage. Only the current `main` branch gets
security fixes. There are no release branches or backports.

## Reporting a vulnerability

Please report privately through GitHub's private vulnerability
reporting:

https://github.com/pact-safety/bench/security/advisories/new

Include what you found and, if you can, steps to reproduce it. Please
don't open a public issue for a security problem.

This is a single-maintainer project. There's no bug bounty and no
formal SLA. The aim is to acknowledge reports within a few days and to
fix confirmed issues promptly, in roughly the priority order of the
list below.

## 1. What is this?

A learning platform for research-engineer interview prep, built with
FastAPI, Jinja2 and HTMX, on Postgres. Users sign in with GitHub OAuth
through Supabase Auth. The hosted instance is invite-only.

Data it holds: personal learning progress (problem attempts, code
submissions, spaced-repetition state), job-description and credential
text that users paste in, contacts, and chat history with the in-app
mentor. It holds no payment data and nothing in a sensitive category
(no government IDs, health data, or financial account numbers).

## 2-3. What could go wrong, worst first?

1. **Cross-user access to personal data.** Someone reads or writes
   another user's chat history, contacts, attempts, or progress. This
   is the most personal data in the system, and the most likely
   mistake as the number of users grows.
2. **API-key and spend abuse.** A bug, a bot, or a malicious user
   drives up LLM usage (Anthropic, or OpenAI for speech features). That
   runs up the bill or starves legitimate use.
3. **User-submitted code escaping the exercise runner.** The Python and
   Rust runners execute code that users submit. See "Known
   limitations" below for exactly what is and isn't isolated. Reaching
   this requires a signed-in user, not an outside attacker.
4. **Personal data leaking into logs or third-party tools.** Error
   tracking, app logs, or stack traces capture chat content, code, or
   credential text. This is lower severity (exposure, not access) and
   is partly mitigated already.

## 4. What is in place?

- **Auth.** Supabase-managed GitHub OAuth with JWT verification. There
  is no hand-rolled auth or password storage (`app/auth.py`). JWKS
  verification dispatches on the token's `alg` header.
- **Access allowlist.** After the JWT is validated, the user is checked
  against an allowlist (`app/services/access.py`). The allowlist is the
  union of environment variables (the operator's bootstrap entries)
  and an `allowlist_entries` table that admins manage. Note that **an
  empty allowlist means no restriction**. This is intended for local
  single-user development, so a self-hosted deployment must configure
  it.
- **Unauthenticated requests are redirected.** Requests to non-public
  paths without a session get a 303 redirect to `/login`
  (`app/main.py`). Public paths are a short, explicit list.
- **Owner-scoped queries.** Repository calls and routes are keyed on
  the signed-in user's ID. Data is filtered to the requesting user at
  the query layer, not just hidden in the UI.
- **Postgres row-level security as defense in depth.** RLS with
  owner-only policies is enabled on 29 of the 42 tables created in
  `migrations_pg/` (`010_enable_rls.sql` and later migrations). The app
  connects with a role that bypasses RLS, so RLS guards direct access
  through Supabase's API keys, not bugs in the app. Tables added later
  (contacts, the mentor's chat and memory tables, the knowledge-base
  tables, the TTS cache, and a few others) do not yet enable RLS.
- **Per-user daily spend caps.** A token-budget counter
  (`app/services/spend_cap.py`) is checked before each LLM call in the
  existing services. Requests over the cap get a deterministic offline
  fallback. It fails open on infrastructure errors, so it acts as a
  circuit breaker rather than a hard boundary.
- **Rate limiting** with slowapi (`app/services/rate_limit.py`) on the
  LLM-backed endpoints.
- **Security headers** on every response
  (`app/services/security.py`): Content-Security-Policy,
  X-Frame-Options: DENY, X-Content-Type-Options: nosniff, a restrictive
  Permissions-Policy, and HSTS in production.
- **Diagnostics are off by default.** The `/__sentry/*` and
  `/__claude/*` endpoints only respond when
  `LIS_DIAGNOSTICS_ENABLED=1`.
- **Personal data is kept out of Sentry.** Sentry runs with
  `send_default_pii=False` and request bodies are never captured
  (`app/observability.py`).
- **Secrets live only in the environment.** Nothing secret is
  committed. Local development reads a gitignored `.env`.
- **Exercise runners do not inherit server secrets.** Each child
  process gets a strict allowlisted environment (see below).

## Known limitations

These are listed so you know about them, not hidden:

- **The exercise runner is not a sandbox.** Submitted code runs as a
  separate child process (`subprocess.run`) in a fresh temporary
  directory, under the same OS user as the application
  (`app/runners/python_runner.py`, `app/runners/rust_runner.py`). The
  child's environment is a strict allowlist built by `safe_env` in
  `app/runners/_sandbox.py`, so API keys, the database URL and other
  secrets in the server environment are not visible to it. The only
  resource limit is a wall-clock timeout. There is **no** filesystem,
  network, or process isolation, and **no** memory or CPU limit.
  Stronger isolation (a separate low-privilege user or container, with
  networking disabled) is planned but not done.
- **Do not self-host this for untrusted users** until runner isolation
  is in place. Anyone who can submit code can read whatever files the
  application user can read, make network requests, and use resources
  up to the timeout.
- **Row-level security is incomplete**, as described above. App-layer
  owner scoping is the real boundary today.
- **Spend-cap enforcement is opt-in.** Current LLM-backed services call
  the cap helpers, but nothing at the framework level stops a new
  service that forgets to.
- **The hosted instance is invite-only** in part because of the
  limitations above.
