"""Integration-tier fixtures. Touches real Postgres + Supabase Auth
(via service_role key). Skipped automatically if env isn't configured."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


# Load .env.local BEFORE the autouse skip fixture checks for the env
# vars. Without this, `app.env.load_dotenv()` only fires at app.main
# import time, but the skip-or-run decision happens earlier.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))
from app.env import load_dotenv as _load_dotenv  # noqa: E402

_load_dotenv()


@pytest.fixture(scope="session", autouse=True)
def _require_database_url():
    """Auto-skip all integration tests if Postgres + service-role key
    aren't configured. Tier-1 unit tests still run."""
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set; integration tests need Postgres")
    if not os.environ.get("SUPABASE_SERVICE_ROLE_KEY"):
        pytest.skip("SUPABASE_SERVICE_ROLE_KEY not set; integration tests need admin access")


@pytest.fixture(scope="session")
def app():
    """Import app.main once per session. Startup loader is skipped via
    LIS_SKIP_STARTUP_LOAD=1 (set in top-level conftest); the session-
    scoped reuse means we pay the import cost once."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from app import main
    return main.app


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient
    return TestClient(app)


@pytest.fixture(scope="session")
def test_user_factory():
    """Session-scoped factory for creating fresh test users.

    Each call returns `{user_id, email, password}` for a brand-new
    auth.users row (with the on_auth_user_created trigger having
    auto-created public.users.is_test=TRUE). Tests that need a
    signed-in user call this and get full isolation — no test's
    writes affect another test's reads.

    At session teardown, every user we created gets deleted. The FK
    cascade on public.users.id cleans up every attempt /
    content_progress / feedback / writing / reflection / etc. row
    owned by these users. Real user data is untouched (those rows
    have is_test=FALSE).
    """
    from . import _helpers
    created_ids: list[str] = []

    def _make():
        user = _helpers.create_test_user()
        created_ids.append(user["user_id"])
        return user

    yield _make

    # Teardown: delete each user we created.
    for uid in created_ids:
        try:
            _helpers.delete_test_user(uid)
        except Exception as e:
            # Log + continue — orphans get swept by
            # cleanup_all_test_users on next run.
            print(f"[teardown] failed to delete test user {uid}: {e}")


@pytest.fixture
def signed_in_user(client, test_user_factory):
    """A `(client, user)` pair where `client` already has a session
    cookie set to a real test user. Tests use this for any signed-in
    route exercise.

    Returns the user dict so tests can assert against the actual
    UUID / email when they need to."""
    from . import _helpers
    user = test_user_factory()
    token = _helpers.mint_test_jwt(user["user_id"], user["email"])
    client.cookies.set("sb-access-token", token)
    return client, user
