"""Repository for `user_linear_configs` — per-user Linear connection.

Same custody model as llm_config_repository: the API key lives in
Supabase Vault via `app/services/vault_secrets`; this table stores the
secret id plus the chosen team. The decrypted key is fetched at sync
time and dropped.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import psycopg

from ..services import vault_secrets
from ._pg import naive_utc


@dataclass(frozen=True)
class UserLinearConfig:
    user_id: str
    vault_secret_id: str | None
    team_id: str | None
    team_name: str | None
    account_label: str | None
    created_at: datetime | None
    updated_at: datetime | None


def _row_to_config(r: dict) -> UserLinearConfig:
    return UserLinearConfig(
        user_id=str(r["user_id"]),
        vault_secret_id=str(r["vault_secret_id"]) if r["vault_secret_id"] else None,
        team_id=r["team_id"],
        team_name=r["team_name"],
        account_label=r["account_label"],
        created_at=naive_utc(r["created_at"]),
        updated_at=naive_utc(r["updated_at"]),
    )


class LinearConfigRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def get(self, user_id: str) -> UserLinearConfig | None:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM user_linear_configs WHERE user_id = %s", (user_id,)
            )
            row = cur.fetchone()
        return _row_to_config(row) if row else None

    def set_config(
        self,
        user_id: str,
        *,
        api_key: str | None,
        team_id: str | None,
        team_name: str | None,
        account_label: str | None,
    ) -> None:
        """Upsert; `api_key=None` keeps the stored secret (team change
        without re-entering the key)."""
        existing = self.get(user_id)
        secret_id = existing.vault_secret_id if existing else None
        if api_key:
            secret_id = vault_secrets.store(self.conn, api_key, secret_id)
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_linear_configs
                    (user_id, vault_secret_id, team_id, team_name, account_label, updated_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                ON CONFLICT (user_id) DO UPDATE
                   SET vault_secret_id = EXCLUDED.vault_secret_id,
                       team_id = EXCLUDED.team_id,
                       team_name = EXCLUDED.team_name,
                       account_label = EXCLUDED.account_label,
                       updated_at = NOW()
                """,
                (user_id, secret_id, team_id, team_name, account_label),
            )
        self.conn.commit()

    def api_key_for(self, user_id: str) -> str | None:
        cfg = self.get(user_id)
        if cfg is None or not cfg.vault_secret_id:
            return None
        return vault_secrets.read(self.conn, cfg.vault_secret_id)

    def delete_for(self, user_id: str) -> None:
        """Row + vault secret. Called from account deletion (the table
        sweep can't reach Vault) and the settings disconnect path."""
        cfg = self.get(user_id)
        if cfg and cfg.vault_secret_id:
            vault_secrets.delete(self.conn, cfg.vault_secret_id)
        with self.conn.cursor() as cur:
            cur.execute(
                "DELETE FROM user_linear_configs WHERE user_id = %s", (user_id,)
            )
        self.conn.commit()
