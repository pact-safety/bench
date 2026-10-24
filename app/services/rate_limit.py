"""Rate-limit setup for LLM-touching endpoints.

slowapi-backed limiter. Key is the user_id when signed in (the auth
middleware populates `request.state.user_session.user_id`), else the
client IP. The limits are per-window-per-key.

The thresholds err generous for a logged-in single user driving the
platform legitimately. The real adversary they defend against is a
runaway loop bug or scripted bot — not the user typing fast.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address


def _identify(request) -> str:
    """User_id if signed in; remote IP otherwise. Tests poke
    `request.state.user_session` directly so this works without a
    real auth flow."""
    sess = getattr(request.state, "user_session", None)
    if sess is not None:
        return f"u:{sess.user_id}"
    return f"ip:{get_remote_address(request)}"


limiter = Limiter(key_func=_identify, default_limits=[])


# Per-endpoint limits (route decorator strings). Tuned conservatively:
# nothing here should ever hit the cap during normal use, but a
# runaway loop or scripted hit is checked immediately.
LIMITS = {
    # Hints: phase-aware nudges. Three tiers per phase × 5 phases =
    # 15 legitimate calls per problem. Allow ~30/min to cover the
    # natural pace of working through a problem with hints.
    "hint": "30/minute",
    # Problem submission. Each submission fires a Sonnet review. The
    # in-page resubmit guard already prevents accidental doubles;
    # this is the second line.
    "submit": "10/minute",
    # Reflect generation. Sonnet, 12-15s call. ~weekly cadence; 5/hour
    # is plenty for legitimate use even if the user is testing.
    "reflect_generate": "5/hour",
    # URL parse on /library/add. Fires a Haiku call per click.
    "parse_url": "20/hour",
    # Hint endpoint also gates the JD parse + credentials analyze
    # which fire Sonnet calls on user-triggered ingest. JD ingest is
    # rare; cap loose.
    "jd_parse": "10/hour",
    "credentials_analyze": "5/hour",
    # Feedback widget submissions. Rare per page; high cap.
    "feedback": "60/hour",
    # Auth OAuth start. Should never need to fire more than a few
    # times in a normal session.
    "auth_signin": "10/minute",
    # Public access-request submissions. Per-IP since submitters
    # aren't authenticated. Tuned for "person + their friend on the
    # same wifi at a conference" without letting a bot spam.
    "request_access": "5/hour",
    # Admin-triggered feedback → GitHub Issue promotion. Manual click
    # in the inbox, so loose; the real concern is a script-flooding
    # bug, not legitimate operator clicks.
    "feedback_promote": "30/hour",
    # Voice transcription via /api/transcribe. Each call hits the
    # Groq Whisper API (~$0.001/min). 60/hour = ~1/min average, ample
    # for active dictation but tight enough to catch a runaway loop.
    # The spend cap in transcription_service is the second line of
    # defense (daily seconds budget).
    "transcribe": "60/hour",
}
