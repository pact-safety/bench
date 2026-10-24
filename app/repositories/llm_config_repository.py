"""Repository for `user_llm_configs` — per-user LLM provider routing.

Key material lives in Supabase Vault via `app/services/vault_secrets`
(platform-managed encryption; never hand-rolled). This table stores
only the vault secret id and display metadata. The decrypted key is
fetched at LLM-call time and is deliberately never cached.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import psycopg

from ..services import vault_secrets
from ._pg import naive_utc

PROVIDERS = ("bench", "anthropic", "omniroute")


@dataclass(frozen=True)
class UserLlmConfig:
    user_id: str
    provider: str
    vault_secret_id: str | None
    base_url: str | None
    key_hint: str | None
    created_at: datetime | None
    updated_at: datetime | None


def _row_to_config(r: dict) -> UserLlmConfig:
    return UserLlmConfig(
        user_id=str(r["user_id"]),
        provider=r["provider"],
        vault_secret_id=str(r["vault_secret_id"]) if r["vault_secret_id"] else None,
        base_url=r["base_url"],
        key_hint=r["key_hint"],
        created_at=naive_utc(r["created_at"]),
        updated_at=naive_utc(r["updated_at"]),
    )


class LlmConfigRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def get(self, user_id: str) -> UserLlmConfig | None:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM user_llm_configs WHERE user_id = %s", (user_id,)
            )
            row = cur.fetchone()
        return _row_to_config(row) if row else None

    def set_config(
        self,
        user_id: str,
        *,
        provider: str,
        api_key: str | None,
        base_url: str | None,
    ) -> None:
        """Upsert the routing row; store/rotate the key in Vault.

        `api_key=None` keeps any existing vault secret (provider or
        base_url change without re-entering the key)."""
        if provider not in PROVIDERS:
            raise ValueError(f"unknown provider {provider!r}")
        existing = self.get(user_id)
        secret_id = existing.vault_secret_id if existing else None
        hint = existing.key_hint if existing else None
        if api_key:
            secret_id = vault_secrets.store(self.conn, api_key, secret_id)
            hint = api_key[-4:]
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_llm_configs
                    (user_id, provider, vault_secret_id, base_url, key_hint, updated_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                ON CONFLICT (user_id) DO UPDATE
                   SET provider = EXCLUDED.provider,
                       vault_secret_id = EXCLUDED.vault_secret_id,
                       base_url = EXCLUDED.base_url,
                       key_hint = EXCLUDED.key_hint,
                       updated_at = NOW()
                """,
                (user_id, provider, secret_id, base_url, hint),
            )
        self.conn.commit()

    def route_for(self, user_id: str) -> tuple[str, str | None, str | None]:
        """(provider, decrypted_key, base_url) for one LLM call. The
        key goes straight into a client constructor and is dropped."""
        cfg = self.get(user_id)
        if cfg is None or cfg.provider == "bench" or not cfg.vault_secret_id:
            return ("bench", None, None)
        key = vault_secrets.read(self.conn, cfg.vault_secret_id)
        return (cfg.provider, key, cfg.base_url)

    def delete_for(self, user_id: str) -> None:
        """Remove the routing row AND its vault secret. Called from
        account deletion (the generic table sweep can't reach Vault)
        and from the settings 'back to bench-provided' path."""
        cfg = self.get(user_id)
        if cfg and cfg.vault_secret_id:
            vault_secrets.delete(self.conn, cfg.vault_secret_id)
        with self.conn.cursor() as cur:
            cur.execute(
                "DELETE FROM user_llm_configs WHERE user_id = %s", (user_id,)
            )
        self.conn.commit()
