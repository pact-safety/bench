"""Thin wrapper over Supabase Vault for user-supplied credentials.

Why Vault: Agent-Security-Standards rule 3 — never hand-roll crypto.
Vault encrypts at rest with platform-managed keys, so user API keys
never sit plaintext in table data or logical backups. This module is
the ONLY place the app touches vault.* objects; everything else deals
in opaque secret ids.

Handling rules (binding): a decrypted value is fetched at point of
use, passed to exactly one consumer, and never cached, logged, or
rendered. Callers display `hint` metadata (stored elsewhere), never
the value.
"""

from __future__ import annotations

import psycopg


def store(conn: psycopg.Connection, value: str, existing_id: str | None) -> str:
    """Create or rotate a secret; returns the vault secret id."""
    with conn.cursor() as cur:
        if existing_id:
            cur.execute("SELECT vault.update_secret(%s::uuid, %s)", (existing_id, value))
            new_id = existing_id
        else:
            cur.execute("SELECT vault.create_secret(%s) AS id", (value,))
            new_id = str(cur.fetchone()["id"])
    conn.commit()
    return new_id


def read(conn: psycopg.Connection, secret_id: str) -> str | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT decrypted_secret AS v FROM vault.decrypted_secrets WHERE id = %s",
            (secret_id,),
        )
        row = cur.fetchone()
    return row["v"] if row else None


def delete(conn: psycopg.Connection, secret_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM vault.secrets WHERE id = %s", (secret_id,))
    conn.commit()
