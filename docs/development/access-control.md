# Access control (who can sign in, and what they can reach)

!!! note "The shape changed as bench opened to alpha users"

    This page was written when bench was single-tenant and the allowlist held
    exactly one identity. The mechanism below is unchanged and still correct —
    the allowlist is now an *invite list* rather than a list of one, and two
    things have been added since:

    - **A public front door.** `/` serves a landing page to signed-out
      visitors instead of redirecting to `/login`. See
      "The unauthenticated surface" below.
    - **A database-layer gate.** Row-level security is enabled on all 36
      tables in `public` with owner-scoped policies, so the app-level
      `WHERE user_id =` filter is no longer the only thing separating one
      user's rows from another's.

Supabase OAuth lets **anyone with a GitHub account** complete the sign-in flow — Supabase itself doesn't restrict who's allowed to authenticate. To gate `bench.libearden.dev`, layer **two gates**:

| Layer | Where it runs | What it does |
|---|---|---|
| **App-level allowlist** | FastAPI middleware | After a JWT validates, checks the identity against env-driven allow vars. Anyone not on the list gets signed out + a 403. |
| **Cloudflare Access** | Cloudflare edge | Requires identity at Cloudflare's edge BEFORE the request ever reaches Fly. |

Layered = defense-in-depth. If one fails (typo'd env var, IdP misconfig), the other still blocks.

---

## Inner gate: app-level allowlist (required)

Set at least one of these as a Fly secret. Either matches → access granted. Both empty = no restriction (which is the local-dev default; deliberately permissive).

```bash
# By user_id (UUID). Most stable — doesn't change if you rotate your
# GitHub username or primary email. After your first successful
# sign-in, find your UUID via the Supabase SQL editor:
#   SELECT id FROM auth.users WHERE email = 'you@example.com';
flyctl secrets set LIS_ALLOWED_USER_IDS="<your-uuid>"

# Or by email — simpler if you don't want to sign in once first to
# look up the UUID. Case-insensitive. Comma-separate to allow multiple.
flyctl secrets set LIS_ALLOWED_EMAILS="you@example.com"
```

### What happens when an unauthorized user signs in

1. Their GitHub OAuth round-trip succeeds — Supabase issues them a JWT.
2. Our auth middleware sees the session, runs `access_service.is_allowed(user_id, email)`.
3. They're not on the list → session cookies cleared (`sb-access-token`, `sb-refresh-token`).
4. They get a 403 with the `access_denied.html` page explaining the situation.
5. The page links back to `/login` so they can sign out the rest of the way.

The check sits in `app/main.py:_inject_session` (the auth middleware), so **every authenticated route is covered** — not just specific endpoints. Adding new routes doesn't require remembering to gate them.

### Local dev posture

`.env.local` typically leaves both vars unset → allowlist disabled → any signed-in user (i.e., you) can use the app. This is intentional so you don't have to add yourself to the allowlist every time you reset state.

### Tests

`tests/unit/test_access.py` pins the contract. The most important assertion: **empty allowlist = no restriction** (so you don't accidentally lock yourself out by forgetting to set the var locally), but **non-empty allowlist rejects-by-default** (so a typo'd UUID doesn't quietly leave the door open).

---

## Outer gate: Cloudflare Access (strongly recommended)

Cloudflare's zero-trust layer sits in front of Fly's load balancer. Visitors authenticate at Cloudflare's edge **before Fly ever sees the request**. Free tier covers up to 50 users — plenty for a single-tenant app.

### Why bother if the app-level allowlist works?

Three reasons:

1. **Defense-in-depth**: a future code change can't accidentally break the gate; Cloudflare Access is enforced upstream of your code.
2. **WAF + DDoS for free**: protected apps get Cloudflare's WAF + edge cache as a side benefit.
3. **Blocks bots before they spin up your Fly machine**: if `auto_stop_machines = "stop"` and your app is sleeping, an unauthorized request never wakes it. Saves the cold-start cost.

### Setup at the Cloudflare Zero Trust dashboard

Dashboard URL: `https://one.dash.cloudflare.com`

1. **Applications → Add an application → Self-hosted**
2. **Application name**: `Li's Bench`
   **Subdomain**: `bench`
   **Domain**: `libearden.dev`
   **Path**: leave empty — protects every path
3. **Identity providers** (Settings → Authentication → Login Methods):
   - **GitHub** is the most natural pairing here — your Supabase OAuth uses GitHub too, so it's the same identity round-trip from the visitor's perspective. Cloudflare Access supports GitHub as a built-in IdP.
   - Or **One-time PIN** for a passwordless email flow if you'd rather not depend on GitHub at the edge.
4. **Policies → Add a policy → Allow**
   - **Selector**: `Emails` → `you@example.com`
   - Or `GitHub → Organizations` if you want anyone in a specific GH org. For single-user, email is cleaner.
5. **Save**.

Cloudflare now sets a `CF_Authorization` cookie on `bench.libearden.dev` after a successful identity check. First visit triggers the Cloudflare login screen.

### Bypass Cloudflare Access for the health check

Otherwise Fly's load-balancer probe will get a 302 redirect to Cloudflare's login page on every check and the app will look "unhealthy" to Fly.

In the same Access policy editor:

- **Add an additional policy** → **Bypass** → **Path matches**: `/__health`

Bypass policies don't require identity; they just let traffic through. The `/__health` route is intentionally non-sensitive (returns `200 ok`).

### After Cloudflare Access is enabled

The full request flow becomes:

```
visitor
   ↓
Cloudflare Access (identity check at edge)
   ↓
Cloudflare WAF + DDoS
   ↓
Fly LB
   ↓
FastAPI auth middleware (Supabase JWT verify)
   ↓
FastAPI access middleware (app-level allowlist)
   ↓
Your route handler
```

Three gates have to be misconfigured before an attacker gets a session.

---

## Recovery: I locked myself out

### App-level allowlist lockout

If you change emails / rotate UUIDs and end up on the wrong side of `LIS_ALLOWED_*`:

```bash
# From your local machine where you have flyctl auth:
flyctl secrets set LIS_ALLOWED_EMAILS="new@example.com"
# Or disable the gate while you fix things:
flyctl secrets unset LIS_ALLOWED_USER_IDS LIS_ALLOWED_EMAILS
```

Setting a secret triggers a redeploy automatically.

### Cloudflare Access lockout

Sign in to `https://one.dash.cloudflare.com` (the dashboard is independent of your `bench.libearden.dev` Access policy — Cloudflare's own account auth, not the one you're configuring). Edit the Access policy. Add yourself, save, retry the visit.

If you lose access to your Cloudflare account entirely: that's a bigger problem (recover via the email on the account), but in the meantime your Fly app is still reachable at its underlying `lis-bench.fly.dev` hostname — that URL bypasses Cloudflare Access by definition. The app-level allowlist is still in force at that URL.

---

## What this does NOT protect against

- **Account takeover at GitHub**: if someone steals your GitHub credentials, they pass both gates (since you're the allowlisted identity). Defense: GitHub 2FA + a strong unique password.
- **Account takeover at Supabase**: same shape — Supabase magic-link or password recovery sent to a compromised email would let an attacker get a JWT signed for your UUID. Defense: protect the email account that owns the Supabase OAuth identity.
- **Postgres-level access via DATABASE_URL**: if your `DATABASE_URL` leaks, that's full-DB access regardless of the web gate. Keep it in Fly secrets only; never commit, never log.
- **Sentry / Anthropic API key leakage**: same shape; the app-level gate doesn't protect those secrets. Rotate immediately if compromised.

The gates above protect the **app's authenticated user surface**. Account-level hygiene is a separate (and equally important) responsibility.

---

## See also

- [Deploy](deploy.md) — for the broader deploy walkthrough
- LIS-280 hardening (Linear)

---

## The unauthenticated surface

Everything not on this list redirects a session-less request to `/login`
(`_is_public_path` in `app/main.py`). Adding to it moves the auth boundary, so
it is worth being deliberate.

**Exact matches** — `_PUBLIC_EXACT_PATHS`, compared by equality:

| Path | Why |
|---|---|
| `/` | The landing page for signed-out visitors |

**Prefix matches** — `_PUBLIC_PATH_PREFIXES`:

| Prefix | Why |
|---|---|
| `/static/` | Assets |
| `/auth/` | The OAuth flow itself |
| `/login` | Sign-in |
| `/public/` | Public dashboard |
| `/about` | Redirects to the operator's site |
| `/request-access` | The access-request funnel — has to work without a session |
| `/writing` | Public technical-writing index |
| `/__health` | Fly's load-balancer check; has no session to present |
| `/__sentry/`, `/__claude/` | Diagnostics |
| `/mcp` | The MCP server enforces its own bearer-token auth |

!!! danger "Why `/` is in a separate set"

    Entries in `_PUBLIC_PATH_PREFIXES` that end in `/` are **prefix-matched**.
    Putting `"/"` in that tuple would match every path in the application and
    silently unauthenticate the entire app — a change that looks like a
    one-line addition and reads as correct in review.

    `_PUBLIC_EXACT_PATHS` is matched by equality only.
    `tests/unit/test_landing_public.py` asserts 24 named protected routes are
    still protected, that the exact set contains only `"/"`, and that `"/"` is
    not prefix-matched. Extend those tests alongside any change here.

## The third layer: row-level security

The two gates above decide **who gets in**. RLS decides **what they can read
once they are in**, and it is enforced by Postgres rather than by application
code:

- RLS is enabled on all 36 tables in the `public` schema.
- 31 carry owner-scoped policies keyed on the requesting user.
- The other 5 (`news_items`, `feed_health`, `kb_documents`, `kb_chunks`,
  `schema_migrations`) hold no per-user data and have no policies at all —
  which under RLS is deny-all, reachable only by the server's own role.

A serve route that forgets its `WHERE user_id = ...` filter is still a bug, but
it is no longer a data leak. Run the Supabase security advisor after any DDL to
keep it that way.
