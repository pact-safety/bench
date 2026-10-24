"""Personal-access allowlist (LIS-280 follow-up).

Anyone with a GitHub account can complete the Supabase OAuth flow —
Supabase doesn't restrict who can sign in. To keep bench.libearden.dev
a single-tenant tool, we add a second gate AFTER the JWT is validated:
the authenticated user's id and email are checked against env-driven
allowlists. If neither matches, the session is rejected and the user
is shown a friendly "not authorized" page.

Belt-and-suspenders pairing
---------------------------
Cloudflare Access in front of the Fly app is the better outer gate
(blocks requests before they reach the box). This module is the
INNER gate: even if Cloudflare Access is misconfigured or removed
in the future, the app-level check still prevents anyone else from
using the platform. See docs/development/deploy.md for the
Cloudflare Access setup.

Env-driven, not DB-driven
-------------------------
On purpose: the allowlist is operator config, not user-editable
data. A successful intruder shouldn't be able to add themselves to
the allowlist by writing to the DB. Putting it in env means the
attack surface is the deploy environment, which is much smaller.

(Bench v2 update: user access is now env UNION a DB-backed table so
approvals don't need a deploy — see "DB-backed allowlist" below for
how the trust model changed and what deliberately didn't.)

Empty allowlist = no restriction (single-user dev mode + local
testing where we don't want to fight the gate). Deploy doc tells
the user to set at least one allow-var before going public.
"""

from __future__ import annotations

import os
from typing import Callable


def _split_csv(value: str | None) -> set[str]:
    """Parse a comma-separated env var into a normalized set."""
    if not value:
        return set()
    return {item.strip().lower() for item in value.split(",") if item.strip()}


def allowed_user_ids() -> set[str]:
    """LIS_ALLOWED_USER_IDS — comma-separated Supabase auth.users UUIDs.
    Most stable identifier: doesn't change if the user changes their
    GitHub username or primary email."""
    return _split_csv(os.environ.get("LIS_ALLOWED_USER_IDS"))


def allowed_emails() -> set[str]:
    """LIS_ALLOWED_EMAILS — comma-separated email addresses.
    Convenient because you usually know your email without logging
    in once to discover the UUID. Less stable (an email change at
    Supabase would lock you out)."""
    return _split_csv(os.environ.get("LIS_ALLOWED_EMAILS"))


# ---------- DB-backed allowlist (Bench v2 invite flow) ----------------------
#
# The env vars above are now the additive BOOTSTRAP/back-door: they keep
# the operator signed in even when the DB is unreachable or an admin-UI
# mistake revokes the wrong entry. The day-to-day allowlist lives in the
# `allowlist_entries` table (granted/revoked from /admin/access-requests,
# no deploy needed). app/main.py injects a provider at startup — a
# TTL-cached repository read — and the two sources are UNION'd.
#
# This supersedes the "env-driven, not DB-driven" rationale in the module
# docstring for *user* access, but deliberately NOT for the admin gate:
# `is_admin` stays env-only so a compromised admin session or DB write
# can't mint new admins.

_db_email_source: Callable[[], set[str]] | None = None


def set_db_email_source(source: Callable[[], set[str]] | None) -> None:
    """Register the DB allowlist provider. Called once by app.main at
    startup; tests may swap in fakes. `None` unregisters."""
    global _db_email_source
    _db_email_source = source


def db_allowed_emails() -> set[str]:
    """Emails granted via the admin UI. Fails CLOSED (empty set) on any
    provider error — the env vars are what keeps the operator in when
    the DB is down, not this."""
    if _db_email_source is None:
        return set()
    try:
        return {e.strip().lower() for e in _db_email_source() if e and e.strip()}
    except Exception:
        return set()


def allowlist_enabled() -> bool:
    """True when either allowlist env var is non-empty OR the DB
    allowlist has active entries. False = no restriction, any
    authenticated user gets in. Local dev typically has neither."""
    return bool(allowed_user_ids() or allowed_emails() or db_allowed_emails())


def is_allowed(user_id: str | None, email: str | None) -> bool:
    """Match the session against the allowlists. ANY match passes —
    env vars and the DB allowlist are OR'd so the operator can use
    whichever identifier/source is most convenient."""
    if not allowlist_enabled():
        # No allowlist → no restriction. Documented above.
        return True
    uid = (user_id or "").strip().lower()
    em = (email or "").strip().lower()
    if uid and uid in allowed_user_ids():
        return True
    if em and em in allowed_emails():
        return True
    if em and em in db_allowed_emails():
        return True
    return False


# ---------- Admin / operator gate (LIS-301) ---------------------------------
#
# `is_allowed` answers "can this person use the bench at all". `is_admin`
# answers "is this person the operator". Distinct because once we open
# alpha/beta access, *allowlisted* users (researchers, conference
# attendees) get in via LIS_ALLOWED_USER_IDS but should NOT see the
# admin feedback inbox or have their submissions auto-promoted to
# GitHub issues.
#
# `LIS_ADMIN_USER_IDS` (UUIDs only — email-equality is too easy to
# spoof for an admin gate) is the canonical admin allowlist. If it's
# unset, we fall back to `LIS_ALLOWED_USER_IDS` so single-tenant
# deploys (the common case today) don't need a second env var.


def admin_user_ids() -> set[str]:
    """LIS_ADMIN_USER_IDS — comma-separated Supabase auth.users UUIDs.
    Falls back to `allowed_user_ids()` when unset so single-tenant
    deploys treat the operator (already on the allowlist) as admin
    without extra configuration."""
    explicit = _split_csv(os.environ.get("LIS_ADMIN_USER_IDS"))
    if explicit:
        return explicit
    return allowed_user_ids()


def is_admin(user_id: str | None) -> bool:
    """True when the session belongs to an operator. Used to gate the
    admin feedback inbox, auto-promotion of operator-typed feedback,
    and any other "show me everyone's data" surfaces.

    Returns False when there's no admin list configured (rather than
    defaulting to True): if a deploy is *intentionally* multi-user,
    we'd rather hide admin features than expose them by accident."""
    if not user_id:
        return False
    admins = admin_user_ids()
    if not admins:
        return False
    return user_id.strip().lower() in admins
