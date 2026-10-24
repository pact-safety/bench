"""Repository for `user_vault_syncs` — per-user git-vault sync config.

Same custody model as the BYO-LLM and Linear repositories: the GitHub
read token lives in Supabase Vault via `app/services/vault_secrets`;
this table stores the secret id plus the sync target. The decrypted
token is fetched at sync time and dropped.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import psycopg

from ..services import vault_secrets
from ._pg import naive_utc


@dataclass(frozen=True)
class UserVaultSync:
    user_id: str
    repo: str
    branch: str
    subdir: str
    vault_secret_id: str | None
    last_synced_at: datetime | None
    last_result: str | None
    created_at: datetime | None
    updated_at: datetime | None


def _row_to_config(r: dict) -> UserVaultSync:
    return UserVaultSync(
        user_id=str(r["user_id"]),
        repo=r["repo"],
        branch=r["branch"] or "",
        subdir=r["subdir"] or "",
        vault_secret_id=str(r["vault_secret_id"]) if r["vault_secret_id"] else None,
        last_synced_at=naive_utc(r["last_synced_at"]),
        last_result=r["last_result"],
        created_at=naive_utc(r["created_at"]),
        updated_at=naive_utc(r["updated_at"]),
    )


class VaultSyncRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def get(self, user_id: str) -> UserVaultSync | None:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM user_vault_syncs WHERE user_id = %s", (user_id,)
            )
            row = cur.fetchone()
        return _row_to_config(row) if row else None

    def list_all(self) -> list[UserVaultSync]:
        """Every configured sync — the nightly cron's working set."""
        with self.conn.cursor() as cur:
            cur.execute("SELECT * FROM user_vault_syncs ORDER BY user_id")
            return [_row_to_config(r) for r in cur.fetchall()]

    def set_config(
        self,
        user_id: str,
        *,
        repo: str,
        branch: str,
        subdir: str,
        token: str | None,
    ) -> None:
        """Upsert; `token=None` keeps any stored secret (target change
        without re-entering the token)."""
        existing = self.get(user_id)
        secret_id = existing.vault_secret_id if existing else None
        if token:
            secret_id = vault_secrets.store(self.conn, token, secret_id)
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_vault_syncs
                    (user_id, repo, branch, subdir, vault_secret_id, updated_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                ON CONFLICT (user_id) DO UPDATE
                   SET repo = EXCLUDED.repo,
                       branch = EXCLUDED.branch,
                       subdir = EXCLUDED.subdir,
                       vault_secret_id = EXCLUDED.vault_secret_id,
                       updated_at = NOW()
                """,
                (user_id, repo, branch, subdir, secret_id),
            )
        self.conn.commit()

    def token_for(self, user_id: str) -> str | None:
        cfg = self.get(user_id)
        if cfg is None or not cfg.vault_secret_id:
            return None
        return vault_secrets.read(self.conn, cfg.vault_secret_id)

    def record_result(self, user_id: str, result: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE user_vault_syncs
                   SET last_synced_at = NOW(), last_result = %s, updated_at = NOW()
                 WHERE user_id = %s
                """,
                (result[:300], user_id),
            )
        self.conn.commit()

    def delete_for(self, user_id: str) -> None:
        """Row + vault secret. Called from account deletion (the table
        sweep can't reach Vault) and the KB disconnect path."""
        cfg = self.get(user_id)
        if cfg and cfg.vault_secret_id:
            vault_secrets.delete(self.conn, cfg.vault_secret_id)
        with self.conn.cursor() as cur:
            cur.execute(
                "DELETE FROM user_vault_syncs WHERE user_id = %s", (user_id,)
            )
        self.conn.commit()
