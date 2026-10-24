"""Account deletion must cover every user-scoped table.

Found in the Bench v2 launch-week audit: `contacts`, `mira_sessions`,
`mira_memory`, `research_agenda`, and `proposed_evals` were added after
the original deletion audit, carry `user_id` with no FK to
`public.users`, and were missing from `_DELETE_ACCOUNT_TABLES_ORDER` —
a deleted account orphaned its CRM contacts and Mira history.

This test scans the migrations for tables that declare a `user_id`
column and fails when one is neither deleted directly, covered by a
declared cascade, nor explicitly exempted with a reason. The next
migration that adds a user-scoped table without deletion coverage
turns this red instead of silently leaking data.
"""

from __future__ import annotations

import re
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations_pg"

# Tables whose rows are removed indirectly when a listed parent row is
# deleted (ON DELETE CASCADE on the parent FK, verified in migrations).
CASCADE_COVERED = {
    "attempt_reviews": "attempts",
    "assessment_responses": "assessment_runs",
    "credential_files": "credential_runs",
    "credential_assessments": "credential_runs",
    "feedback_attachments": "feedback",
    "contact_interactions": "contacts",
    "mira_turns": "mira_sessions",  # no user_id column, cascade anyway
    "opportunity_events": "opportunities",
}

# Tables with user_id that deliberately survive table-order deletion,
# each with the reason the exemption is sound.
EXEMPT = {
    # Deleted explicitly at the end of the handler, after the table list.
    "users": "public.users row deleted by the handler itself",
    # FK to public.users(id) ON DELETE CASCADE — dies with the users row.
    "tts_cache": "cascades from the public.users delete",
    "notes": "cascades from the public.users delete (v1.5 table, unused)",
}


def _user_tables() -> set[str]:
    """Tables created in migrations whose definition includes a
    user_id column (or public.users itself)."""
    found: set[str] = set()
    for sql_file in MIGRATIONS.glob("*.sql"):
        text = sql_file.read_text()
        for m in re.finditer(
            r"CREATE TABLE IF NOT EXISTS\s+(?:public\.)?(\w+)\s*\((.*?)\);",
            text,
            re.IGNORECASE | re.DOTALL,
        ):
            name, body = m.group(1), m.group(2)
            if re.search(r"\buser_id\b", body) or name == "users":
                found.add(name)
    return found


def test_delete_account_covers_all_user_tables():
    import app.main as m

    listed = set(m._DELETE_ACCOUNT_TABLES_ORDER)
    covered = listed | set(CASCADE_COVERED) | set(EXEMPT)

    missing = _user_tables() - covered
    assert not missing, (
        f"user-scoped tables not covered by account deletion: {sorted(missing)}. "
        "Add them to _DELETE_ACCOUNT_TABLES_ORDER, or to CASCADE_COVERED/"
        "EXEMPT here with a verified reason."
    )


def test_cascade_parents_are_actually_deleted():
    """A cascade only covers its child if the parent is in the delete
    list (or itself exempted)."""
    import app.main as m

    listed = set(m._DELETE_ACCOUNT_TABLES_ORDER)
    for child, parent in CASCADE_COVERED.items():
        assert parent in listed or parent in EXEMPT, (
            f"{child} relies on cascade from {parent}, which is not deleted"
        )
