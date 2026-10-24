from __future__ import annotations

import json
from typing import Any

import psycopg

from .. import cache
from ..models import Problem
from ._pg import jsonb


def _row_to_problem(r: dict) -> Problem:
    return Problem(
        id=r["id"],
        slug=r["slug"],
        title=r["title"],
        difficulty=r["difficulty"],
        time_bucket=r["time_bucket"],
        problem_type=r["problem_type"],
        is_warmup=bool(r["is_warmup"]),
        structural_tags=jsonb(r.get("structural_tags_json")) or [],
        domain_tags=jsonb(r.get("domain_tags_json")) or [],
        competency_tags=jsonb(r.get("competency_tags_json")) or [],
        jd_signal_tags=jsonb(r.get("jd_signal_tags_json")) or [],
        content_md=r["content_md"] or "",
        starter_code_python=r.get("starter_code_python"),
        starter_code_rust=r.get("starter_code_rust"),
        reference_solution_python=r.get("reference_solution_python"),
        reference_solution_rust=r.get("reference_solution_rust"),
        key_insight=r.get("key_insight"),
        pitfalls_md=r.get("pitfalls_md"),
        test_code_python=r.get("test_code_python"),
        rust_crate_dir=r.get("rust_crate_dir"),
        source_provenance=r.get("source_provenance"),
        original=bool(r.get("original_bool", True)),
        authored_by=r.get("authored_by"),
        authored_date=r.get("authored_date"),
        version=r.get("version_int", 1),
        em_mode=r.get("em_mode", "full"),
        em_prompts=jsonb(r.get("em_prompts_json")) or {},
        references=jsonb(r.get("references_json")) or [],
    )


class ProblemRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def upsert(self, p: Problem, *, content_hash: str = "") -> int:
        """INSERT-or-UPDATE in a single round-trip via ON CONFLICT.

        `content_hash` (if set) lets the row store its SHA-256 so
        subsequent startups can SELECT all hashes and skip unchanged
        files. Pass an empty string to opt out (the column defaults
        to '' which never matches a real hash → always re-upserts)."""
        cols: dict[str, Any] = dict(
            slug=p.slug,
            title=p.title,
            difficulty=p.difficulty,
            time_bucket=p.time_bucket,
            problem_type=p.problem_type,
            is_warmup=bool(p.is_warmup),
            structural_tags_json=json.dumps(p.structural_tags),
            domain_tags_json=json.dumps(p.domain_tags),
            competency_tags_json=json.dumps(p.competency_tags),
            jd_signal_tags_json=json.dumps(p.jd_signal_tags),
            content_md=p.content_md,
            starter_code_python=p.starter_code_python,
            starter_code_rust=p.starter_code_rust,
            reference_solution_python=p.reference_solution_python,
            reference_solution_rust=p.reference_solution_rust,
            key_insight=p.key_insight,
            pitfalls_md=p.pitfalls_md,
            test_code_python=p.test_code_python,
            rust_crate_dir=p.rust_crate_dir,
            source_provenance=p.source_provenance,
            original_bool=bool(p.original),
            authored_by=p.authored_by,
            authored_date=p.authored_date,
            version_int=p.version,
            em_mode=p.em_mode,
            em_prompts_json=json.dumps(p.em_prompts or {}),
            references_json=json.dumps(p.references or []),
            content_hash=content_hash,
        )
        col_names = list(cols.keys())
        placeholders = ",".join(["%s"] * len(cols))
        # Update every column except slug (the conflict key).
        update_clause = ",".join(f"{c} = EXCLUDED.{c}" for c in col_names if c != "slug")
        with self.conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO problems ({','.join(col_names)}) "
                f"VALUES ({placeholders}) "
                f"ON CONFLICT (slug) DO UPDATE SET {update_clause} "
                f"RETURNING id",
                tuple(cols.values()),
            )
            new_id = cur.fetchone()["id"]
        self.conn.commit()
        # Invalidate the all_core / all_warmups cache so the next read
        # picks up the new shape. get_by_id / get_by_slug aren't cached
        # so they're already correct.
        cache.invalidate("problems:all_core")
        cache.invalidate("problems:all_warmups")
        return new_id

    def get_by_id(self, problem_id: int) -> Problem | None:
        with self.conn.cursor() as cur:
            cur.execute("SELECT * FROM problems WHERE id = %s", (problem_id,))
            r = cur.fetchone()
        return _row_to_problem(r) if r else None

    def get_by_slug(self, slug: str) -> Problem | None:
        with self.conn.cursor() as cur:
            cur.execute("SELECT * FROM problems WHERE slug = %s", (slug,))
            r = cur.fetchone()
        return _row_to_problem(r) if r else None

    def hashes_by_slug(self) -> dict[str, str]:
        """One round-trip; returns {slug: content_hash} for every row.

        Used by the startup loader's hash-skip optimization: compute
        the SHA-256 of each markdown file's canonical content,
        compare against the DB-stored hash, only upsert on mismatch."""
        with self.conn.cursor() as cur:
            cur.execute("SELECT slug, content_hash FROM problems")
            rows = cur.fetchall()
        return {r["slug"]: r["content_hash"] or "" for r in rows}

    def all_core(self) -> list[Problem]:
        """Cached: problems table changes once at app boot. Cleared on
        `upsert()` so a content-edit + restart picks up changes."""
        def _load():
            with self.conn.cursor() as cur:
                cur.execute("SELECT * FROM problems WHERE NOT is_warmup ORDER BY id")
                rows = cur.fetchall()
            return [_row_to_problem(r) for r in rows]
        return cache.get("problems:all_core", loader=_load)

    def all_warmups(self) -> list[Problem]:
        def _load():
            with self.conn.cursor() as cur:
                cur.execute("SELECT * FROM problems WHERE is_warmup ORDER BY id")
                rows = cur.fetchall()
            return [_row_to_problem(r) for r in rows]
        return cache.get("problems:all_warmups", loader=_load)

    def list_recent_for_user(self, user_id: str, limit: int = 5) -> list[tuple[Problem, Any]]:
        """Recent attempts joined to the problem rows. Returns
        `[(problem, attempt_started_at)]` so the caller can render a
        short list of "what you worked on lately"."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT p.*, a.started_at AS a_started, a.test_passed_bool AS a_passed,
                       a.confidence_1_to_5 AS a_conf
                  FROM attempts a
                  JOIN problems p ON p.id = a.problem_id
                 WHERE a.user_id = %s
                 ORDER BY a.started_at DESC
                 LIMIT %s
                """,
                (user_id, limit),
            )
            rows = cur.fetchall()
        return [(_row_to_problem(r), r["a_started"]) for r in rows]
