"""Stub repositories for v1.5 features.

The tables exist (see migrations_pg/001_consolidated.sql). The classes exist
so wiring code can import them without conditional `if hasattr`. Methods
raise NotImplementedError; v1.5 fills them in without restructuring.
"""

from __future__ import annotations

import psycopg


class SourceRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def insert(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise NotImplementedError("SourceRepository is reserved for v1.5")

    def get_by_id(self, source_id: int):
        raise NotImplementedError("SourceRepository is reserved for v1.5")


class NoteRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def insert(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise NotImplementedError("NoteRepository is reserved for v1.5")

    def list_for_problem(self, user_id: str, problem_id: int):
        raise NotImplementedError("NoteRepository is reserved for v1.5")
