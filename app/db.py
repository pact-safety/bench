"""Database connection layer — Postgres via psycopg.

Phase 4 of the multi-user migration. Replaced the previous SQLite layer.
Reads `DATABASE_URL` from env (loaded via `.env.local`), connects with
psycopg, and uses `dict_row` so cursors return dicts (closest shape to
the old `sqlite3.Row`).

Connection model:
- `connect()` returns a `PooledConnection`: a facade over
  `psycopg_pool.ConnectionPool` that preserves the module-level
  single-connection call-site shape (`with conn.cursor() as cur:`,
  `with conn.transaction():`, `conn.commit()`). Each cursor block
  leases a pooled connection for exactly its own lifetime, so ~197
  sync routes in Starlette's threadpool no longer serialize behind
  one connection's round-trips (Bench v2 scaling blocker #1).
- Connections are `autocommit=True` (see `connect()` for why);
  repository `conn.commit()` calls are kept as no-ops for call-site
  compatibility.

Migration application:
- Reads `migrations_pg/*.sql` in lexical order
- Tracks applied files in `schema_migrations`
- Idempotent — re-running just skips already-applied files
- Auth.users trigger + extensions live inside the migration SQL, so
  no schema bootstrap is needed here
"""

from __future__ import annotations

import logging
import os
import threading
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Iterator

_log = logging.getLogger("bench.db.migrations")

import psycopg
import psycopg_pool
from psycopg.rows import dict_row


class PooledConnection:
    """Facade over `psycopg_pool.ConnectionPool` that preserves the
    single-shared-connection call-site shape the whole app was written
    against (`with conn.cursor()`, `with conn.transaction():`,
    `conn.commit()`).

    Replaces ResilientConnection (see git history): the pool's
    `check=` pings connections on checkout, the same self-healing that
    killed the 2026-07-19/21 dead-connection outages — plus real
    concurrency, which the single shared connection never had.

    Thread-local pinning: `bound()` leases ONE pooled connection and
    pins it to the current thread, so nested `cursor()` /
    `transaction()` calls land on the same connection. Required for:
      - the transactional multi-table deletes (/settings/reset,
        /settings/delete-account) — their inner cursor must join the
        open transaction, and
      - session-scoped advisory locks (`single_flight`) — lock and
        unlock must happen on the same session, held for the whole job.
    Sync routes and APScheduler jobs each run wholly on one thread, so
    thread-local is the right scope. Known trade-off: a pinned
    connection can't be health-checked or replaced until the scope
    ends, and a cron job pins one pool slot for its whole tick.
    """

    def __init__(self, pool: psycopg_pool.ConnectionPool) -> None:
        self._pool = pool
        self._tl = threading.local()

    @contextmanager
    def bound(self) -> Iterator[psycopg.Connection]:
        """Lease a pooled connection, pinned to this thread, and yield
        it. Reentrant: nested bound() (and every cursor()/transaction()
        inside) reuses the outer pin.

        The last-used stamp feeding `_check_if_idle` is written only on
        CLEAN exit — a block that raised must not vouch for its
        connection's health, or the next checkout inside the idle
        window would be handed a possibly-dead connection unpinged."""
        already = getattr(self._tl, "conn", None)
        if already is not None:
            yield already
            return
        with self._pool.connection() as c:
            self._tl.conn = c
            ok = False
            try:
                yield c
                ok = True
            finally:
                self._tl.conn = None
                if ok:
                    c._bench_last_used = time.monotonic()  # type: ignore[attr-defined]

    @contextmanager
    def cursor(self, *args, **kwargs) -> Iterator[psycopg.Cursor]:
        """`with conn.cursor() as cur:` — leases a pooled connection
        for exactly the block. Bare `conn.cursor()` calls (no `with`)
        are unsupported on purpose — the lease would never end. There
        are no such call sites."""
        with self.bound() as c:
            with c.cursor(*args, **kwargs) as cur:
                yield cur

    @contextmanager
    def transaction(self, *args, **kwargs) -> Iterator[None]:
        with self.bound() as c:
            with c.transaction(*args, **kwargs):
                yield

    # Without a pinned connection these are no-ops: connections are
    # autocommit and ~53 repo call sites say `self.conn.commit()` after
    # their cursor block has already returned its lease. With a pin we
    # delegate, so error-recovery `rollback()` inside a bound scope
    # really rolls back, and a stray commit()/rollback() inside a
    # `transaction()` block raises loudly (psycopg forbids it) instead
    # of silently doing nothing.
    def commit(self) -> None:
        pinned = getattr(self._tl, "conn", None)
        if pinned is not None:
            pinned.commit()

    def rollback(self) -> None:
        pinned = getattr(self._tl, "conn", None)
        if pinned is not None:
            pinned.rollback()

    def close(self) -> None:
        self._pool.close()


class _StrictNoDBConn:
    """Sentinel returned by connect() when `LIS_NO_DB=1`. Lets app.main
    import successfully in unit-test CI runs (where no Postgres is
    available) while still raising loudly if a test actually tries to
    use the connection.

    Design choice: strict-fail vs. permissive-MagicMock. A MagicMock
    would silently return another MagicMock from `conn.cursor()` and
    tests downstream would fail with cryptic AttributeError on a stub
    chain. The explicit error here fingerpoints the actual problem
    ("this test reached the conn; either mock the repo or provide a
    DB") so debugging is one read of the message."""

    _MSG = (
        "Hit the no-DB sentinel connection (LIS_NO_DB=1). This code "
        "path reached the raw `conn` object, which means it actually "
        "needs a real Postgres. Either: (1) provide DATABASE_URL and "
        "unset LIS_NO_DB, (2) mock the repo method that's being "
        "called, or (3) move the test to the integration tier."
    )

    def cursor(self, *args, **kwargs):
        raise RuntimeError(_StrictNoDBConn._MSG)

    def transaction(self, *args, **kwargs):
        raise RuntimeError(_StrictNoDBConn._MSG)

    def bound(self):
        raise RuntimeError(_StrictNoDBConn._MSG)

    def commit(self):  # no-op so cleanup paths don't blow up
        pass

    def rollback(self):
        pass

    def close(self):
        pass


# The outage class this guards against (Supabase inactivity pause, the
# session pooler recycling an idle server conn) hits after MINUTES of
# idle. The old 2.0s (ResilientConnection's global window) applied
# per-connection here would ping on nearly every checkout at
# single-user traffic — the pool rotates members FIFO, so each one
# looks "idle" between page loads. 30s keeps the healing (a
# minutes-dead conn always gets pinged) without a ping-per-query tax.
_CHECK_IDLE_S = 30.0


def _stamp_fresh(conn: psycopg.Connection) -> None:
    """Pool `configure=` hook: a connection that just finished a
    successful dial+TLS+auth is definitionally alive — stamp it so its
    first checkout skips the redundant ping."""
    conn._bench_last_used = time.monotonic()  # type: ignore[attr-defined]


def _check_if_idle(conn: psycopg.Connection) -> None:
    """Pool checkout check: ping only connections that have been idle
    longer than `_CHECK_IDLE_S`. Same policy ResilientConnection used —
    drops happen while idle (Supabase pause, pooler recycle), not
    mid-burst, so pinging a just-used connection wastes a full round
    trip per cursor block. The facade stamps `_bench_last_used` on
    lease release; a connection without the stamp (fresh from the
    factory) gets pinged once. A failed ping makes the pool discard
    the connection and retry with another — the self-healing that
    killed the 2026-07-19/21 outage class."""
    last = getattr(conn, "_bench_last_used", None)
    if last is not None and time.monotonic() - last < _CHECK_IDLE_S:
        return
    psycopg_pool.ConnectionPool.check_connection(conn)


def connect(database_url: str | None = None) -> psycopg.Connection:
    """Open a Postgres connection. Reads DATABASE_URL from env if
    `database_url` is not provided.

    `LIS_NO_DB=1` short-circuit: returns a strict sentinel that raises
    on any cursor() access. Set in CI workflows + tests/conftest.py so
    `import app.main` succeeds without a real Postgres dial. Unit
    tests that mock at the repo level never reach the conn; tests
    that DO reach it get a clear actionable error.

    `row_factory=dict_row` → cursors return dicts keyed by column name.

    `autocommit=True` is **critical** for app code that mixes reads +
    occasional writes. Without it, every SELECT starts an implicit
    transaction holding AccessShareLock on the table; that
    transaction never commits (the cursor closes but the txn stays
    open), and accumulated locks block migrations / DDL forever.
    The bug surfaced when an `ALTER TABLE ... ADD COLUMN` waited 2
    minutes for AccessExclusiveLock and hit the Supabase statement
    timeout.

    Repository write methods still call `conn.commit()` at the end
    of mutations — that's a no-op under autocommit, but safe.

    `prepare_threshold=None` disables psycopg's automatic server-side
    prepared-statement caching. This protects against the
    ``FeatureNotSupported: cached plan must not change result type``
    error that fires when:

      1. A query is auto-prepared after 5 executions (the default
         threshold), and
      2. The underlying table's schema later changes (e.g., an
         ``ALTER TABLE ... ADD COLUMN`` applied via the Supabase SQL
         editor, or RLS-policy add that invalidates the plan), and
      3. The same long-lived connection executes the prepared statement
         again.

    For the bench's traffic shape (single-tenant alpha, low QPS,
    schema migrations that happen out-of-band against a live app),
    the per-query planning overhead is negligible and the robustness
    is the right trade. This is the documented best practice for
    psycopg behind Supabase's session pooler.
    """
    # Priority order matters: DATABASE_URL wins over LIS_NO_DB. This
    # is so local pytest runs (where conftest sets LIS_NO_DB=1 before
    # app.main loads .env.local) still get a real connection when the
    # .env.local actually has a DATABASE_URL. The sentinel is purely
    # a fallback for environments that have NO DB at all.
    url = database_url or os.environ.get("DATABASE_URL", "").strip()
    if url:
        # Pool sizing: per-machine. 2 Fly machines × max 8 = 16 worst-case
        # sessions against Supabase's session pooler — comfortably inside
        # its limits. Env knobs so tuning is a restart, not a code change.
        pool = psycopg_pool.ConnectionPool(
            url,
            min_size=int(os.environ.get("LIS_DB_POOL_MIN", "1")),
            max_size=int(os.environ.get("LIS_DB_POOL_MAX", "8")),
            # Bound how long a checkout can stall when the pool is
            # exhausted or the DB is down. The library default (30s)
            # would park threadpool threads — and, on the async paths
            # that still call sync repos, the event loop — for half a
            # minute each; the old shared connection failed fast.
            timeout=float(os.environ.get("LIS_DB_POOL_TIMEOUT_S", "5")),
            kwargs={
                "row_factory": dict_row,
                "autocommit": True,
                "prepare_threshold": None,
            },
            check=_check_if_idle,
            configure=_stamp_fresh,
            open=True,
            name="bench",
        )
        # Fail fast at boot like the old psycopg.connect() did: an
        # unreachable DB should be one clear error at import, not a
        # timeout buried in the first query. Sized for a cold dial.
        pool.wait(timeout=15.0)
        # Wrapped at the single chokepoint so every caller (app, repos,
        # scripts) keeps its call-site shape. The LIS_NO_DB sentinel
        # below stays unwrapped: its job is to raise.
        return PooledConnection(pool)  # type: ignore[return-value]
    if os.environ.get("LIS_NO_DB", "").strip().lower() in ("1", "true", "yes"):
        return _StrictNoDBConn()  # type: ignore[return-value]
    raise RuntimeError(
        "DATABASE_URL not set. See .env.example for the Supabase "
        "Session-pooler connection string format. To run unit tests "
        "without a DB, set LIS_NO_DB=1 (the conftest does this "
        "automatically when DATABASE_URL is empty)."
    )


def apply_migrations(conn: psycopg.Connection, migrations_dir: Path) -> None:
    """Apply `migrations_pg/*.sql` in lexical order, tracking applied
    files in a `schema_migrations` table.

    Idempotent: a file that's already in `schema_migrations` is skipped.
    First-run on a new project creates the bookkeeping table itself.

    No-op against the `_StrictNoDBConn` sentinel — there's no real DB
    to migrate, and calling cursor() would raise. This lets app.main
    import cleanly in unit-test / no-DB CI contexts.

    Logs every step at INFO level (``bench.db.migrations``) so we can
    diagnose drift from Fly logs. Prior to 2026-05-27 this function ran
    silently, which is how prod ended up with 8 migrations'
    side-effects on the DB but no rows in ``schema_migrations`` — we
    had no signal that anything was off.

    Set ``LIS_DISABLE_AUTO_MIGRATE=1`` to make this function a no-op.
    Use that when you want migrations to be an explicit deploy step
    (run ``python scripts/apply_migrations.py`` yourself) rather than
    a side effect of container boot. The deploy-step-explicit shape is
    what most prod web apps do; the auto-apply shape is here as a
    convenience for fresh dev DBs.
    """
    if isinstance(conn, _StrictNoDBConn):
        _log.info("LIS_NO_DB sentinel — skipping migrations")
        return
    if os.environ.get("LIS_DISABLE_AUTO_MIGRATE", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        _log.info(
            "LIS_DISABLE_AUTO_MIGRATE=1 — skipping migrations. "
            "Run `python scripts/apply_migrations.py` manually."
        )
        return

    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                filename TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        conn.commit()
        cur.execute("SELECT filename FROM schema_migrations")
        applied = {r["filename"] for r in cur.fetchall()}

    all_files = sorted(migrations_dir.glob("*.sql"))
    pending = [p for p in all_files if p.name not in applied]

    _log.info(
        "schema_migrations has %d applied; %d pending (of %d files in %s)",
        len(applied),
        len(pending),
        len(all_files),
        migrations_dir,
    )
    if not pending:
        return

    # Verbose pending list so the deploy logs tell us exactly what
    # we're about to do. Cheap (a few INFO lines) and the only
    # mechanism by which we'd know up-front that drift is about to
    # heal itself on this boot.
    for p in pending:
        _log.info("  pending: %s", p.name)

    for path in pending:
        sql = path.read_text()
        started = time.monotonic()
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
                cur.execute(
                    "INSERT INTO schema_migrations (filename) VALUES (%s) "
                    "ON CONFLICT (filename) DO NOTHING",
                    (path.name,),
                )
            conn.commit()
        except Exception as exc:  # noqa: BLE001 — log + re-raise
            elapsed_ms = (time.monotonic() - started) * 1000
            _log.error(
                "  FAILED %s after %.0fms: %s: %s",
                path.name,
                elapsed_ms,
                type(exc).__name__,
                exc,
            )
            raise
        elapsed_ms = (time.monotonic() - started) * 1000
        _log.info("  applied %s in %.0fms", path.name, elapsed_ms)


# (The old `cursor(conn)` helper is gone: it had zero call sites and
# its bare `conn.cursor()` shape is incompatible with pooled leases.)


# Advisory-lock keys. Arbitrary but must be stable and globally unique
# across the app — a collision means two unrelated jobs block each other.
LOCK_REFLECT_PREGENERATE = 8_431_001
LOCK_NEWS_POLLER = 8_431_002
LOCK_VAULT_GIT_SYNC = 8_431_003


def _scalar(row) -> bool:
    """Read a one-column result whether the cursor yields dicts or tuples.

    `connect()` sets `row_factory=dict_row`, so `row[0]` is a KeyError, not
    the value. Anything that reads a scalar off this connection has to go
    through here or it silently breaks.
    """
    if row is None:
        return False
    if isinstance(row, dict):
        return bool(next(iter(row.values())))
    return bool(row[0])


@contextmanager
def single_flight(conn: psycopg.Connection, key: int) -> Iterator[bool]:
    """Yield True to exactly one caller across every running instance.

    Cron jobs are armed in-process by APScheduler, so every machine arms
    every job. With one machine that is fine; the moment the app runs two
    (`fly scale count 2`), each tick fires twice — duplicate news rows and
    duplicate Anthropic spend on reflect pre-generation.

    A Postgres advisory lock is the cheap fix: whichever instance grabs it
    does the work, the rest no-op. `pg_try_advisory_lock` never blocks, so a
    losing instance returns immediately rather than queueing behind the
    winner and running the job late.

    Hold the lock for the WHOLE job — take it, run the body inside the
    `with`, release on exit. Checking it and then releasing before doing the
    work buys nothing: both instances would pass the check.

    The lock is session-scoped, so a crash mid-tick drops it when the
    connection dies rather than wedging the job forever.

    Yields True against the no-DB sentinel so unit tests that call a tick
    body directly still run it.

    Pooled connections: the whole job runs inside `conn.bound()` so the
    lock, the job body's queries, and the unlock all share ONE pinned
    pooled connection. Session-scoped locks make this mandatory — lock
    and unlock on different pool members would leak the lock until the
    holding connection is recycled. (Trade-off: the pin holds one pool
    slot for the whole tick, including non-DB work like LLM calls and
    feed fetches.)
    """
    if isinstance(conn, _StrictNoDBConn):
        yield True
        return
    with ExitStack() as stack:
        pinned: psycopg.Connection | None = None
        if isinstance(conn, PooledConnection):
            try:
                pinned = stack.enter_context(conn.bound())
            except psycopg.Error as exc:
                # Same fail-open policy as a failed lock statement
                # below: no pooled connection (PoolTimeout, dial
                # failure) is not a reason to skip the job on a
                # single-instance deploy.
                _log.warning(
                    "advisory lock %s: no pooled connection (%s: %s); "
                    "running unguarded",
                    key, type(exc).__name__, exc,
                )
                yield True
                return
        got = False
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_try_advisory_lock(%s) AS locked", (key,))
                got = _scalar(cur.fetchone())
        except psycopg.Error:
            # A lock we cannot take is not a reason to skip the job on a
            # single-instance deploy. Fail open for genuine database errors —
            # but ONLY those. A blanket `except Exception` here silently
            # disabled this guard once already: the connection uses
            # `row_factory=dict_row`, so indexing the row by position raised
            # KeyError, which the catch-all swallowed into "run unguarded".
            # Programming errors must surface, not degrade to a no-op.
            _log.warning("advisory lock %s unavailable; running unguarded", key)
            yield True
            return
        try:
            yield got
        finally:
            if got:
                try:
                    with conn.cursor() as cur:
                        cur.execute("SELECT pg_advisory_unlock(%s)", (key,))
                except psycopg.Error:
                    # A session lock on a HEALTHY pooled member would go
                    # back to the pool still held — then every instance's
                    # try-lock returns False and the cron silently
                    # no-ops until that member is recycled (~an hour).
                    # Kill the session instead: the lock dies with it
                    # and the pool discards the closed conn on return.
                    _log.warning(
                        "advisory unlock %s failed; discarding the pinned "
                        "session so the lock dies with it", key,
                    )
                    if pinned is not None:
                        try:
                            pinned.close()
                        except Exception:  # noqa: BLE001
                            pass
