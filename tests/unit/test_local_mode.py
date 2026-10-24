"""The LIS_LOCAL_MODE auth-bypass interlock.

Security-sensitive: local mode disables auth for single-user self-hosting,
but MUST refuse to engage when real auth (SUPABASE_JWT_SECRET) is configured,
so the flag can never silently open up a hosted deployment.
"""

from __future__ import annotations

from app.main import _local_mode_enabled


def test_enabled_when_flag_set_and_no_auth_configured():
    assert _local_mode_enabled({"LIS_LOCAL_MODE": "1"}) is True


def test_disabled_when_flag_unset():
    assert _local_mode_enabled({}) is False
    assert _local_mode_enabled({"LIS_LOCAL_MODE": "0"}) is False


def test_interlock_refuses_when_real_auth_is_configured():
    # Even with the flag on, a configured JWT secret (i.e. a real
    # deployment) must keep auth enabled.
    env = {"LIS_LOCAL_MODE": "1", "SUPABASE_JWT_SECRET": "shhh"}
    assert _local_mode_enabled(env) is False
