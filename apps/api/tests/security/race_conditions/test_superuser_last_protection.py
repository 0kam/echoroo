"""T954 — DB trigger ``prevent_last_superuser_deletion`` role parity tests.

Target: FR-111a (last superuser protection) / SC-022 (DB-level enforce).

This suite exercises the BEFORE UPDATE / DELETE trigger installed by
migrations 0012 + 0013.  Because the trigger fires at the PostgreSQL
engine level—not at the SQLAlchemy service layer—these tests require a
real Postgres connection and **will be skipped** if the trigger function
does not exist in the current test DB.

Execution environment
---------------------
The tests connect to ``TEST_DATABASE_URL`` (default:
``postgresql+asyncpg://echoroo:echoroo@localhost:5432/echoroo_test``).
The Alembic migrations 0012 and 0013 must have been applied for the
trigger to be present.  In CI, ``alembic upgrade head`` runs before the
test suite.  Locally (fresh container), run::

    docker exec echoroo-backend uv run alembic upgrade head

Additionally, the ``echoroo_app`` PostgreSQL role must exist in the test
DB AND the connecting role (``postgres`` in CI / local dev) must be a
member of ``echoroo_app`` so that ``SET ROLE echoroo_app`` is permitted.
Without the membership grant the trigger guard cannot be exercised under
the application role and the SC-022 scenarios silently skip via the
``_can_set_app_role()`` probe (Phase 16 Codex 6e R2 finding).  The role
is created automatically in the CI entrypoint and can be created
locally::

    docker exec echoroo-db psql -U postgres -d echoroo_test -c \\
        "CREATE ROLE echoroo_app WITH LOGIN PASSWORD 'echoroo_app_test'; \\
         GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO echoroo_app; \\
         GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO echoroo_app; \\
         GRANT echoroo_app TO postgres;"

The trailing ``GRANT echoroo_app TO postgres`` is the membership grant
that lets the connecting superuser issue ``SET ROLE echoroo_app``.  In
CI the test workflow MUST run the same statement after starting the
PostgreSQL service (or after ``alembic upgrade head``).  CI workflow
that omits this grant will see SC-022 coverage silently skip.

Then install the trigger function (if not done by alembic on the test DB)::

    docker exec echoroo-db psql -U postgres -d echoroo_test -f /tmp/install_trigger.sql

Scenarios
---------
1.  ``echoroo_app`` role: ``revoked_at = now()`` UPDATE (2 → 0) raises.
2.  ``echoroo_app`` role: hard DELETE (1 → 0) raises.
3.  Migrator / postgres role: same operations skip the trigger.
4.  ``app.superuser_deletion_override = 'true'``: override permits the op.
5.  Re-revoke of already-revoked row is NOT blocked (idempotent).
6.  UPDATE of non-``revoked_at`` column does not fire the guard.
7.  Advisory-lock race: concurrent 2 → 0 revokes as echoroo_app — advisory lock
    ensures only 1 succeeds and final active count = 1.

Note: endpoint-level tests are deferred to Batch 5.  This file focuses
on the raw DB trigger / advisory-lock semantics.

IMPORTANT: These tests do NOT use the shared ``db_session`` fixture because
they need independent DB connections to test concurrent behaviour and role
switching. Each test manages its own engine lifecycle. The standard
``db_session`` fixture is intentionally NOT imported here to avoid FK
cleanup conflicts with leftover approval request rows from other test suites.

Role availability
-----------------
The trigger checks ``current_user = 'echoroo_app'``. This test suite uses
``SET ROLE echoroo_app`` within a transaction started by the superuser
``postgres`` connection (which has SUPERUSER privileges). This simulates
the application connection without requiring a separate TCP authentication
handshake as echoroo_app. The trigger fires based on the in-transaction
``current_user`` value — i.e. after ``SET ROLE``.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import threading
import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    create_async_engine,
)
from sqlalchemy.pool import NullPool

# Mirror of the migration's deterministic advisory-lock key
# (alembic 0013).  Folded into 63-bit positive range so that PostgreSQL's
# ``objid`` column (bigint, signed) round-trips without a sign flip.
_LOCK_KEY: int = (
    int.from_bytes(
        hashlib.sha256(b"superuser_last_protection").digest()[:8], "big"
    )
    & 0x7FFFFFFFFFFFFFFF
)
# pg_locks.objid is a 32-bit value (lower 32 bits of the 64-bit advisory
# key for ``pg_advisory_xact_lock(int8)``).  Compute the matching low half
# so the waiter detection query can target the correct row.
_LOCK_OBJID_LOW32: int = _LOCK_KEY & 0xFFFFFFFF
_LOCK_OBJID_HIGH32: int = (_LOCK_KEY >> 32) & 0xFFFFFFFF


# Use the same TEST_DATABASE_URL as the main conftest, but sourced directly
# so this module does not trigger the heavy conftest db_session fixture.
# When running inside the Docker container the DB host is "db", not
# "localhost".  Fall back to DATABASE_URL (app URL) with the DB name
# swapped to "echoroo_test" when TEST_DATABASE_URL is not set explicitly.
def _default_test_db_url() -> str:
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return explicit
    app_url = os.environ.get("DATABASE_URL", "")
    if app_url:
        # Replace the database name segment (last path component).
        base = app_url.rsplit("/", 1)[0]
        return f"{base}/echoroo_test"
    return "postgresql+asyncpg://echoroo:echoroo@localhost:5432/echoroo_test"


TEST_DATABASE_URL: str = _default_test_db_url()

# ---------------------------------------------------------------------------
# Skip guard: skip the whole module if trigger or echoroo_app role is absent
# ---------------------------------------------------------------------------

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


def _make_engine() -> Any:
    return create_async_engine(TEST_DATABASE_URL, poolclass=NullPool, echo=False)


def _make_sync_engine() -> Any:
    """Return a synchronous SQLAlchemy Engine backed by psycopg2.

    Used by the OS-thread advisory-lock test (test_concurrent_revokes_advisory_lock_serialises)
    so that each thread holds a genuine blocking DBAPI connection and the PostgreSQL
    advisory lock is actually contended across two OS threads.

    The async TEST_DATABASE_URL uses the ``postgresql+asyncpg://`` scheme; we swap
    the driver to ``postgresql+psycopg2://`` which is synchronous and thread-safe.
    """
    sync_url = TEST_DATABASE_URL.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"
    ).replace(
        "postgresql://", "postgresql+psycopg2://"
    )
    return sa.create_engine(sync_url, poolclass=NullPool, echo=False)


async def _trigger_exists(engine: Any) -> bool:
    async with engine.connect() as conn:
        row = await conn.execute(
            sa.text(
                "SELECT 1 FROM pg_proc WHERE proname = 'prevent_last_superuser_deletion'"
            )
        )
        return row.scalar() is not None


async def _app_role_exists(engine: Any) -> bool:
    """Return True if the echoroo_app role exists in the connected DB."""
    async with engine.connect() as conn:
        row = await conn.execute(
            sa.text("SELECT 1 FROM pg_roles WHERE rolname = 'echoroo_app'")
        )
        return row.scalar() is not None


async def _can_set_app_role(engine: Any) -> bool:
    """Return True if the connecting user can ``SET ROLE echoroo_app``.

    Phase 16 Batch 6e (2026-04-29) test infra fix 1C: when the test
    suite runs against the dev compose stack the connecting role
    (``echoroo``) is **not** a member of ``echoroo_app`` and is not a
    Postgres superuser, so ``SET ROLE`` raises ``InsufficientPrivilege``
    before the trigger can fire. The trigger semantics under the
    ``echoroo_app`` identity are exercised in CI where the role
    grant is set up automatically; locally we skip the role-bound
    cases rather than green-light a false negative.

    See spec ``specs/006-permissions-redesign/data-model.md`` §6.2 for
    the canonical FR-111a / SC-022 grant matrix and the CI
    ``GRANT echoroo_app TO echoroo`` step.
    """
    try:
        async with engine.begin() as conn:
            await conn.execute(sa.text("SET ROLE echoroo_app"))
            await conn.execute(sa.text("RESET ROLE"))
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Raw SQL helpers — bypass ORM to exercise trigger directly
# ---------------------------------------------------------------------------


async def _cleanup_t954_rows(conn: Any) -> None:
    """Remove any leftover t954 test rows to ensure idempotent test runs.

    T954 tests commit raw SQL rows (no ORM teardown).  A second run of the
    same test would hit a duplicate-email UniqueViolation without this guard.
    Deletes in FK-safe order: superusers → users.
    """
    await conn.execute(
        sa.text(
            "DELETE FROM superusers WHERE user_id IN "
            "(SELECT id FROM users WHERE email LIKE 't954_%@example.com')"
        )
    )
    await conn.execute(
        sa.text("DELETE FROM users WHERE email LIKE 't954_%@example.com'")
    )


async def _insert_user(conn: Any, *, suffix: str) -> UUID:
    """Insert a minimal ``users`` row and return its id."""
    uid = uuid4()
    await conn.execute(
        sa.text(
            """
            INSERT INTO users (id, email, password_hash, display_name, security_stamp)
            VALUES (:id, :email, '$argon2id$v=19$m=65536,t=3,p=4$t954', :dn, :stamp)
            """
        ),
        {
            "id": str(uid),
            "email": f"t954_{suffix}@example.com",
            "dn": f"T954 {suffix}",
            "stamp": "0" * 64,
        },
    )
    return uid


async def _insert_superuser(conn: Any, *, user_id: UUID, revoked: bool = False) -> UUID:
    """Insert a ``superusers`` row and return its id."""
    sid = uuid4()
    revoked_at = datetime.now(UTC) if revoked else None
    await conn.execute(
        sa.text(
            """
            INSERT INTO superusers
                (id, user_id, added_at, revoked_at, webauthn_credentials, allowed_ip_cidrs)
            VALUES
                (:id, :uid, now() - interval '1 day', :revoked_at, '[]', ARRAY[]::varchar[])
            """
        ),
        {"id": str(sid), "uid": str(user_id), "revoked_at": revoked_at},
    )
    return sid


async def _count_active(conn: Any) -> int:
    result = await conn.execute(
        sa.text("SELECT COUNT(*) FROM superusers WHERE revoked_at IS NULL")
    )
    return int(result.scalar())


# ---------------------------------------------------------------------------
# Scenario 1: echoroo_app role — UPDATE 2 → 0 revokes is blocked
# ---------------------------------------------------------------------------


async def test_update_revoke_2_to_0_blocked_as_app_role() -> None:
    """UPDATE flipping 2 active → 0 must raise as echoroo_app role (SC-022).

    Uses ``SET ROLE echoroo_app`` within a postgres superuser transaction to
    simulate the application connection. The trigger fires based on
    ``current_user`` at trigger execution time (post SET ROLE). Expects
    asyncpg.exceptions.RaiseError wrapped in DBAPIError.
    """
    engine = _make_engine()
    try:
        if not await _trigger_exists(engine):
            pytest.skip(
                "prevent_last_superuser_deletion trigger not installed; "
                "run `alembic upgrade head` + install trigger on test DB"
            )
        if not await _app_role_exists(engine):
            pytest.skip(
                "echoroo_app role absent in test DB; "
                "create it with GRANT ALL ON TABLES before running trigger tests"
            )
        if not await _can_set_app_role(engine):
            pytest.skip(
                "connecting role lacks SET ROLE echoroo_app privilege "
                "(local dev only — CI grants membership). "
                "See specs/006-permissions-redesign/data-model.md §6.2 "
                "for the FR-111a / SC-022 grant matrix."
            )

        sid_a: UUID
        sid_b: UUID

        # Seed two active superusers in a setup transaction (postgres role).
        async with engine.begin() as conn:
            await _cleanup_t954_rows(conn)
            await conn.execute(
                sa.text("UPDATE superusers SET revoked_at = now() WHERE revoked_at IS NULL")
            )
            uid_a = await _insert_user(conn, suffix="t954_s1a")
            uid_b = await _insert_user(conn, suffix="t954_s1b")
            sid_a = await _insert_superuser(conn, user_id=uid_a)
            sid_b = await _insert_superuser(conn, user_id=uid_b)
            assert await _count_active(conn) == 2

        # Attempt to revoke BOTH as echoroo_app — trigger must raise.
        try:
            async with engine.begin() as conn:
                await conn.execute(sa.text("SET ROLE echoroo_app"))
                # Verify the role switch took effect.
                role_row = await conn.execute(sa.text("SELECT current_user"))
                assert role_row.scalar() == "echoroo_app", (
                    "SET ROLE did not take effect — echoroo_app role may lack LOGIN"
                )
                # Revoking both active rows would leave 0 active — trigger must block.
                await conn.execute(
                    sa.text(
                        "UPDATE superusers SET revoked_at = now() "
                        "WHERE id IN (:sid_a, :sid_b)"
                    ),
                    {"sid_a": str(sid_a), "sid_b": str(sid_b)},
                )
            pytest.fail(
                "Expected trigger to raise RaiseError for 2→0 revoke as echoroo_app, "
                "but the UPDATE succeeded — SC-022 trigger is not working."
            )
        except DBAPIError as exc:
            assert "RaiseError" in type(exc.orig).__name__ or "RaiseError" in str(exc), (
                f"Expected RaiseError from trigger, got: {exc}"
            )
            assert "Cannot revoke last superuser" in str(exc), (
                f"Unexpected trigger message: {exc}"
            )

        # Post-condition: active count must not have changed (trigger rolled back).
        async with engine.begin() as conn:
            count = await _count_active(conn)
            assert count == 2, (
                f"Trigger should have blocked the revoke, "
                f"but active count changed to {count}"
            )
    finally:
        # Cleanup — run as postgres role so trigger does not interfere.
        async with engine.begin() as conn:
            await _cleanup_t954_rows(conn)
        await engine.dispose()


# ---------------------------------------------------------------------------
# Scenario 2: hard DELETE (1 → 0) blocked as echoroo_app
# ---------------------------------------------------------------------------


async def test_hard_delete_1_to_0_blocked_as_app_role() -> None:
    """Hard DELETE of last active superuser must raise as echoroo_app role.

    The DELETE branch of the trigger also takes the advisory lock and
    checks ``COUNT(*) <= 1`` before raising.
    """
    engine = _make_engine()
    try:
        if not await _trigger_exists(engine):
            pytest.skip(
                "prevent_last_superuser_deletion trigger not installed"
            )
        if not await _app_role_exists(engine):
            pytest.skip("echoroo_app role absent in test DB")
        if not await _can_set_app_role(engine):
            pytest.skip(
                "connecting role lacks SET ROLE echoroo_app privilege "
                "(local dev only — CI grants membership). "
                "See specs/006-permissions-redesign/data-model.md §6.2 "
                "for the FR-111a / SC-022 grant matrix."
            )

        sid: UUID

        async with engine.begin() as conn:
            await _cleanup_t954_rows(conn)
            await conn.execute(
                sa.text("UPDATE superusers SET revoked_at = now() WHERE revoked_at IS NULL")
            )
            uid = await _insert_user(conn, suffix="t954_s2")
            sid = await _insert_superuser(conn, user_id=uid)
            assert await _count_active(conn) == 1

        try:
            async with engine.begin() as conn:
                await conn.execute(sa.text("SET ROLE echoroo_app"))
                await conn.execute(
                    sa.text("DELETE FROM superusers WHERE id = :sid"),
                    {"sid": str(sid)},
                )
            pytest.fail(
                "Expected trigger to raise RaiseError for DELETE of last superuser "
                "as echoroo_app, but the DELETE succeeded."
            )
        except DBAPIError as exc:
            assert "RaiseError" in type(exc.orig).__name__ or "RaiseError" in str(exc), (
                f"Expected RaiseError from trigger, got: {exc}"
            )
            assert "Cannot delete last superuser" in str(exc), (
                f"Unexpected trigger message: {exc}"
            )

        # Post-condition: the row must still be present.
        async with engine.begin() as conn:
            count = await _count_active(conn)
            assert count == 1, (
                f"DELETE should have been blocked; active count = {count}"
            )
    finally:
        async with engine.begin() as conn:
            await _cleanup_t954_rows(conn)
        await engine.dispose()


# ---------------------------------------------------------------------------
# Scenario 3: postgres role skips the trigger
# ---------------------------------------------------------------------------


async def test_update_revoke_allowed_as_postgres_role() -> None:
    """postgres (migrator-equivalent) role may revoke the last superuser row.

    The trigger's first branch is ``IF current_user <> 'echoroo_app' THEN
    RETURN NEW``, so postgres / echoroo connections are not blocked.
    After the revoke the active count must be 0.
    """
    engine = _make_engine()
    try:
        if not await _trigger_exists(engine):
            pytest.skip(
                "prevent_last_superuser_deletion trigger not installed; "
                "run `alembic upgrade head` to enable trigger-level tests"
            )

        async with engine.begin() as conn:
            await _cleanup_t954_rows(conn)
            await conn.execute(
                sa.text("UPDATE superusers SET revoked_at = now() WHERE revoked_at IS NULL")
            )
            uid = await _insert_user(conn, suffix="t954_s3")
            sid = await _insert_superuser(conn, user_id=uid)
            assert await _count_active(conn) == 1

            # current_user is 'postgres' (not 'echoroo_app') — trigger must pass.
            await conn.execute(
                sa.text("UPDATE superusers SET revoked_at = now() WHERE id = :sid"),
                {"sid": str(sid)},
            )
            count = await _count_active(conn)
            assert count == 0, (
                f"postgres/echoroo role should bypass the trigger guard; count={count}"
            )
    finally:
        async with engine.begin() as conn:
            await _cleanup_t954_rows(conn)
        await engine.dispose()


# ---------------------------------------------------------------------------
# Scenario 4: app.superuser_deletion_override GUC permits echoroo_app op
# ---------------------------------------------------------------------------


async def test_deletion_override_guc_permits_op() -> None:
    """``app.superuser_deletion_override = 'true'`` bypasses the trigger guard.

    Even as echoroo_app, setting the override GUC in the same LOCAL
    transaction allows revoking the last superuser row (creator_founder
    override path, Alembic 0013).
    """
    engine = _make_engine()
    try:
        if not await _trigger_exists(engine):
            pytest.skip(
                "prevent_last_superuser_deletion trigger not installed"
            )
        if not await _app_role_exists(engine):
            pytest.skip("echoroo_app role absent in test DB")
        if not await _can_set_app_role(engine):
            pytest.skip(
                "connecting role lacks SET ROLE echoroo_app privilege "
                "(local dev only — CI grants membership). "
                "See specs/006-permissions-redesign/data-model.md §6.2 "
                "for the FR-111a / SC-022 grant matrix."
            )

        sid: UUID

        async with engine.begin() as conn:
            await _cleanup_t954_rows(conn)
            await conn.execute(
                sa.text("UPDATE superusers SET revoked_at = now() WHERE revoked_at IS NULL")
            )
            uid = await _insert_user(conn, suffix="t954_s4")
            sid = await _insert_superuser(conn, user_id=uid)
            assert await _count_active(conn) == 1

        # Same transaction: SET ROLE + SET LOCAL GUC + UPDATE.
        async with engine.begin() as conn:
            await conn.execute(sa.text("SET ROLE echoroo_app"))
            await conn.execute(
                sa.text("SET LOCAL \"app.superuser_deletion_override\" = 'true'")
            )
            # Should NOT raise — override GUC disables the trigger guard.
            await conn.execute(
                sa.text("UPDATE superusers SET revoked_at = now() WHERE id = :sid"),
                {"sid": str(sid)},
            )

        # Post-condition: row is revoked (0 active for t954 users).
        async with engine.begin() as conn:
            result = await conn.execute(
                sa.text(
                    "SELECT COUNT(*) FROM superusers "
                    "WHERE revoked_at IS NULL AND user_id IN "
                    "(SELECT id FROM users WHERE email LIKE 't954_%@example.com')"
                )
            )
            count = int(result.scalar())
            assert count == 0, (
                f"Override GUC should have allowed the revoke; active t954 count = {count}"
            )
    finally:
        async with engine.begin() as conn:
            await _cleanup_t954_rows(conn)
        await engine.dispose()


# ---------------------------------------------------------------------------
# Scenario 5: re-revoke of already-revoked row is NOT blocked
# ---------------------------------------------------------------------------


async def test_rererevoke_already_revoked_row_not_blocked() -> None:
    """Updating revoked_at on a row where it is already non-NULL must pass.

    The trigger only fires when ``OLD.revoked_at IS NULL AND
    NEW.revoked_at IS NOT NULL``. An already-revoked row should be
    unaffected (idempotent re-revoke). Tested as echoroo_app to confirm
    the trigger's conditional correctly bypasses the guard for this case.
    """
    engine = _make_engine()
    try:
        if not await _trigger_exists(engine):
            pytest.skip(
                "prevent_last_superuser_deletion trigger not installed; "
                "run `alembic upgrade head` to enable trigger-level tests"
            )
        if not await _app_role_exists(engine):
            pytest.skip("echoroo_app role absent in test DB")
        if not await _can_set_app_role(engine):
            pytest.skip(
                "connecting role lacks SET ROLE echoroo_app privilege "
                "(local dev only — CI grants membership). "
                "See specs/006-permissions-redesign/data-model.md §6.2 "
                "for the FR-111a / SC-022 grant matrix."
            )

        sid_revoked: UUID

        async with engine.begin() as conn:
            await _cleanup_t954_rows(conn)
            await conn.execute(
                sa.text("UPDATE superusers SET revoked_at = now() WHERE revoked_at IS NULL")
            )
            uid_active = await _insert_user(conn, suffix="t954_s5_active")
            uid_revoked = await _insert_user(conn, suffix="t954_s5_revoked")
            # Keep one active so overall count stays > 0.
            await _insert_superuser(conn, user_id=uid_active)
            sid_revoked = await _insert_superuser(conn, user_id=uid_revoked, revoked=True)

        # Re-touching an already-revoked row as echoroo_app must NOT raise.
        # OLD.revoked_at IS NOT NULL → trigger's guard condition is False.
        async with engine.begin() as conn:
            await conn.execute(sa.text("SET ROLE echoroo_app"))
            await conn.execute(
                sa.text(
                    "UPDATE superusers SET revoked_at = now() + interval '1 second' "
                    "WHERE id = :sid"
                ),
                {"sid": str(sid_revoked)},
            )

        # Active count unchanged — the active row should still be active.
        async with engine.begin() as conn:
            result = await conn.execute(
                sa.text(
                    "SELECT COUNT(*) FROM superusers "
                    "WHERE revoked_at IS NULL AND user_id IN "
                    "(SELECT id FROM users WHERE email LIKE 't954_%@example.com')"
                )
            )
            count = int(result.scalar())
            assert count == 1, (
                f"Active count must be 1 after idempotent re-revoke; got {count}"
            )
    finally:
        async with engine.begin() as conn:
            await _cleanup_t954_rows(conn)
        await engine.dispose()


# ---------------------------------------------------------------------------
# Scenario 6: UPDATE of non-revoked_at column does not trip the guard
# ---------------------------------------------------------------------------


async def test_update_other_column_not_blocked() -> None:
    """Updating allowed_ip_cidrs does not invoke the last-superuser guard."""
    engine = _make_engine()
    try:
        if not await _trigger_exists(engine):
            pytest.skip(
                "prevent_last_superuser_deletion trigger not installed; "
                "run `alembic upgrade head` to enable trigger-level tests"
            )
        if not await _app_role_exists(engine):
            pytest.skip("echoroo_app role absent in test DB")
        if not await _can_set_app_role(engine):
            pytest.skip(
                "connecting role lacks SET ROLE echoroo_app privilege "
                "(local dev only — CI grants membership). "
                "See specs/006-permissions-redesign/data-model.md §6.2 "
                "for the FR-111a / SC-022 grant matrix."
            )

        sid: UUID

        async with engine.begin() as conn:
            await _cleanup_t954_rows(conn)
            await conn.execute(
                sa.text("UPDATE superusers SET revoked_at = now() WHERE revoked_at IS NULL")
            )
            uid = await _insert_user(conn, suffix="t954_s6")
            sid = await _insert_superuser(conn, user_id=uid)

        # Update a non-revoked_at column as echoroo_app — trigger must not fire.
        # The BEFORE UPDATE trigger is declared ``OF revoked_at``, so it only
        # fires when that specific column is in the SET clause.
        async with engine.begin() as conn:
            await conn.execute(sa.text("SET ROLE echoroo_app"))
            await conn.execute(
                sa.text(
                    "UPDATE superusers SET allowed_ip_cidrs = ARRAY['192.168.0.0/24'] "
                    "WHERE id = :sid"
                ),
                {"sid": str(sid)},
            )

        # Row must still be active.
        async with engine.begin() as conn:
            result = await conn.execute(
                sa.text(
                    "SELECT COUNT(*) FROM superusers "
                    "WHERE revoked_at IS NULL AND user_id IN "
                    "(SELECT id FROM users WHERE email LIKE 't954_%@example.com')"
                )
            )
            count = int(result.scalar())
            assert count == 1, (
                f"Non-revoked_at UPDATE must not trip the guard; active count = {count}"
            )
    finally:
        async with engine.begin() as conn:
            await _cleanup_t954_rows(conn)
        await engine.dispose()


# ---------------------------------------------------------------------------
# Scenario 7: advisory-lock race — concurrent 2 → 0 revokes as echoroo_app,
#             only one succeeds (active count = 1 at the end).
# ---------------------------------------------------------------------------


async def test_concurrent_revokes_advisory_lock_serialises() -> None:
    """Concurrent 2-row → 0 revoke race as echoroo_app: advisory lock serialises.

    Both transactions target different rows and both would leave 0 active
    superusers if they both committed.  The advisory lock in the trigger
    forces them to serialise: the first TX commits (1 active remains), the
    second TX sees 0 active-after and raises.

    Final active count must be 1.

    Implementation: leader/follower design with explicit timing on two real
    OS threads (each holding an independent synchronous psycopg2 connection).

      1. Leader (thread A) BEGIN + SET ROLE + UPDATE.  This acquires the
         advisory lock inside the trigger and runs the trigger body.  Leader
         then does NOT commit immediately — it sets ``leader_holds`` so the
         follower may proceed and waits for ``follower_started`` before
         entering a fixed hold window.
      2. Follower (thread B) waits on ``leader_holds`` then BEGIN + SET ROLE
         + signals ``follower_started`` + UPDATE.  This UPDATE MUST block on
         ``pg_advisory_xact_lock`` because the leader still holds the lock.
      3. After ``follower_started`` is observed, the leader sleeps for the
         full ``_LEADER_HOLD_SECS`` window (≥ probe polling window + slack)
         to give the follower time to actually enter ``pg_advisory_xact_lock``
         and the probe time to observe the waiter, even if the OS preempts
         the follower thread between ``set()`` and ``conn.execute(...)``.
      4. While the leader is mid-hold, a third synchronous probe connection
         polls ``pg_locks`` to verify a session is genuinely waiting on the
         advisory lock with ``granted = false`` and ``objid = low32(_LOCK_KEY)``.
         If no waiter is observed within the probe polling window, the test
         fails — this is the assertion that proves the lock is genuinely
         contended.  If the lock were removed from the trigger, no waiter
         would ever appear and the test fails.
      5. Leader commits → follower unblocks → follower's trigger sees
         ``COUNT(*) - 1 = 0`` and raises ``P0001 Cannot revoke …``.
      6. Final state: 1 active superuser, follower raised the trigger error.

    Phase 17 §C PR-D Codex round 2 (2026-05-08): replaced the symmetric
    Barrier design (which could not distinguish "advisory lock contention"
    from "OS scheduler serialisation") with this leader/follower + pg_locks
    waiter assertion so the test fails when advisory-lock contention is not
    observed (including when the advisory lock is removed from the trigger).
    """
    # Use the async engine only for setup/teardown and pre-flight checks.
    engine = _make_engine()
    try:
        if not await _trigger_exists(engine):
            pytest.skip(
                "prevent_last_superuser_deletion trigger not installed; "
                "run `alembic upgrade head` to enable trigger-level tests"
            )
        if not await _app_role_exists(engine):
            pytest.skip("echoroo_app role absent in test DB")
        if not await _can_set_app_role(engine):
            pytest.skip(
                "connecting role lacks SET ROLE echoroo_app privilege "
                "(local dev only — CI grants membership). "
                "See specs/006-permissions-redesign/data-model.md §6.2 "
                "for the FR-111a / SC-022 grant matrix."
            )

        sid_a: UUID
        sid_b: UUID

        # Seed two active superusers (async setup transaction, postgres role).
        # Suffixes are "s7_a" / "s7_b" (no leading "t954_") so that _insert_user
        # produces emails "t954_s7_a@example.com" / "t954_s7_b@example.com" which
        # (a) are cleaned up by _cleanup_t954_rows (pattern: t954_%) and (b) are
        # matched by the post-condition query (pattern: t954_s7%@example.com).
        async with engine.begin() as conn:
            await _cleanup_t954_rows(conn)
            await conn.execute(
                sa.text("UPDATE superusers SET revoked_at = now() WHERE revoked_at IS NULL")
            )
            uid_a = await _insert_user(conn, suffix="s7_a")
            uid_b = await _insert_user(conn, suffix="s7_b")
            sid_a = await _insert_superuser(conn, user_id=uid_a)
            sid_b = await _insert_superuser(conn, user_id=uid_b)

        # Coordination primitives for leader/follower timing.
        leader_holds = threading.Event()  # leader has the advisory lock
        follower_started = threading.Event()  # follower entered UPDATE (about to block)
        thread_results: list[Exception | None] = [None, None]
        # Probe polling window for pg_locks waiter observation.
        _PROBE_POLL_SECS = 2.0
        # Hold window: leader keeps the lock (transaction open) for this many
        # seconds AFTER follower signals ``follower_started``.  MUST exceed the
        # probe polling window (2.0s) plus slack so that even if the OS
        # preempts the follower thread between ``follower_started.set()`` and
        # ``conn.execute(...)`` actually entering ``pg_advisory_xact_lock``,
        # the probe still has time to observe the waiter row in pg_locks.
        # 2.5s = 2.0s probe window + 0.5s slack for slow CI runners.
        _LEADER_HOLD_SECS = 2.5
        # Max time the leader will wait for ``follower_started`` to be set.
        # Independent of the hold window — purely a join-timeout for the case
        # where the follower thread fails to start at all.
        _FOLLOWER_WAIT_SECS = 10.0

        def _set_safety_timeouts(conn: Any) -> None:
            """Apply per-transaction lock_timeout and statement_timeout.

            5s lock_timeout / 30s statement_timeout protects against indefinite
            hangs if the test logic is wrong or the DB is misconfigured.  The
            connection self-aborts rather than hanging the whole test forever.
            """
            conn.execute(sa.text("SET LOCAL lock_timeout = '5000ms'"))
            conn.execute(sa.text("SET LOCAL statement_timeout = '30000ms'"))

        def _leader(sid: UUID) -> None:
            """Acquire advisory lock via UPDATE, signal, hold, then commit."""
            sync_engine = _make_sync_engine()
            try:
                with sync_engine.begin() as conn:
                    _set_safety_timeouts(conn)
                    conn.execute(sa.text("SET ROLE echoroo_app"))
                    # This UPDATE acquires pg_advisory_xact_lock(_LOCK_KEY)
                    # inside the trigger.  Lock is held until COMMIT (xact lock).
                    conn.execute(
                        sa.text(
                            "UPDATE superusers SET revoked_at = now() WHERE id = :sid"
                        ),
                        {"sid": str(sid)},
                    )
                    leader_holds.set()
                    # Wait until follower has signalled it is about to issue
                    # its UPDATE.  The wait timeout is a generous join-style
                    # guard (not the hold duration).
                    follower_started.wait(timeout=_FOLLOWER_WAIT_SECS)
                    # Hold the advisory lock for the FULL probe-polling window
                    # plus slack AFTER follower_started.  This is required
                    # because follower_started.set() runs BEFORE conn.execute
                    # actually enters pg_advisory_xact_lock — if the OS
                    # preempts the follower thread between those two calls,
                    # the leader committing too early would race the probe and
                    # cause spurious failures on slow CI runners.
                    time.sleep(_LEADER_HOLD_SECS)
                # Commit releases the advisory lock; follower unblocks.
            except Exception as exc:  # noqa: BLE001
                thread_results[0] = exc
            finally:
                sync_engine.dispose()

        def _follower(sid: UUID) -> None:
            """Wait for leader, then attempt the conflicting UPDATE."""
            sync_engine = _make_sync_engine()
            try:
                # Don't even start the transaction until leader holds the lock.
                if not leader_holds.wait(timeout=10):
                    raise RuntimeError(
                        "Leader did not signal lock acquisition within 10s"
                    )
                with sync_engine.begin() as conn:
                    _set_safety_timeouts(conn)
                    conn.execute(sa.text("SET ROLE echoroo_app"))
                    follower_started.set()
                    # This UPDATE blocks on pg_advisory_xact_lock until leader
                    # commits.  After unblock, trigger sees ``COUNT(*) - 1 = 0``
                    # and raises P0001 "Cannot revoke last superuser …".
                    conn.execute(
                        sa.text(
                            "UPDATE superusers SET revoked_at = now() WHERE id = :sid"
                        ),
                        {"sid": str(sid)},
                    )
            except Exception as exc:  # noqa: BLE001
                thread_results[1] = exc
                # Even on failure, signal so leader does not wait the full timeout.
                follower_started.set()
            finally:
                sync_engine.dispose()

        # Non-daemon threads: if join times out we still surface a failure rather
        # than letting the interpreter exit while connections leak.  Per-conn
        # statement_timeout (30s) is the secondary safety net.
        t_leader = threading.Thread(
            target=_leader, args=(sid_a,), daemon=False, name="t954-pr-d-leader"
        )
        t_follower = threading.Thread(
            target=_follower, args=(sid_b,), daemon=False, name="t954-pr-d-follower"
        )
        t_leader.start()
        t_follower.start()

        # While leader is holding, poll pg_locks from a third sync connection to
        # confirm the follower is waiting on the advisory lock.  If we never see
        # a waiter, the advisory lock has been removed/disabled and the test fails.
        # Use a fresh sync engine in autocommit so the probe does not interfere
        # with locking semantics.
        probe_engine = _make_sync_engine()
        waiter_observed = False
        try:
            # Wait until leader signals it holds the lock.
            assert leader_holds.wait(timeout=10), (
                "Leader did not acquire advisory lock within 10s"
            )
            # Wait until follower has at least started its transaction so the
            # pg_locks waiter row will be present.
            follower_started.wait(timeout=5)
            deadline = time.monotonic() + _PROBE_POLL_SECS
            with probe_engine.connect() as probe:
                # Need autocommit-ish behaviour for the probe — we just SELECT.
                while time.monotonic() < deadline:
                    # objsubid = 1 marks the int8 (single-key) variant of the
                    # advisory lock — distinguishes from int4+int4 form.
                    row = probe.execute(
                        sa.text(
                            """
                            SELECT 1
                            FROM pg_locks
                            WHERE locktype = 'advisory'
                              AND granted = false
                              AND objid = :objid_low
                              AND classid = :objid_high
                              AND objsubid = 1
                            LIMIT 1
                            """
                        ),
                        {
                            "objid_low": _LOCK_OBJID_LOW32,
                            "objid_high": _LOCK_OBJID_HIGH32,
                        },
                    ).scalar()
                    if row is not None:
                        waiter_observed = True
                        break
                    time.sleep(0.05)
        finally:
            probe_engine.dispose()

        await asyncio.to_thread(t_leader.join, 30)
        await asyncio.to_thread(t_follower.join, 30)

        if t_leader.is_alive() or t_follower.is_alive():
            pytest.fail(
                "Advisory-lock test threads did not complete within 30 s "
                "(connections rely on lock_timeout/statement_timeout for safety)"
            )

        # === Assertion 1: advisory lock was genuinely contended. ===
        # If this fails, the trigger's pg_advisory_xact_lock has been removed
        # or the follower somehow committed without ever waiting — both would
        # mean the serialisation guarantee no longer holds.
        assert waiter_observed, (
            "pg_locks never showed a waiter on the superuser advisory lock "
            f"(objid={_LOCK_OBJID_LOW32}, classid={_LOCK_OBJID_HIGH32}). "
            "This means the follower transaction was not blocked by the "
            "advisory lock — the trigger's pg_advisory_xact_lock is missing "
            "or ineffective and the SC-022 race protection is broken."
        )

        leader_exc = thread_results[0]
        follower_exc = thread_results[1]

        # === Assertion 2: leader succeeded, follower raised. ===
        assert leader_exc is None, (
            f"Leader (first revoke) should have succeeded, but raised: {leader_exc!r}"
        )
        assert follower_exc is not None, (
            "Follower (second revoke) should have been blocked by the trigger "
            "after the advisory lock was released, but it succeeded — final "
            "active count would be 0."
        )

        # === Assertion 3: follower failure is the trigger's P0001 RaiseException. ===
        assert isinstance(follower_exc, DBAPIError), (
            f"Expected DBAPIError from trigger, got {type(follower_exc).__name__}: "
            f"{follower_exc!r}"
        )
        # psycopg2.errors.RaiseException carries pgcode 'P0001' on the .orig.
        orig = getattr(follower_exc, "orig", None)
        pgcode = getattr(orig, "pgcode", None)
        assert pgcode == "P0001", (
            f"Expected SQLSTATE P0001 (RaiseException) from trigger, "
            f"got pgcode={pgcode!r}: {follower_exc!r}"
        )
        msg = str(orig) if orig is not None else str(follower_exc)
        assert "Cannot revoke" in msg, (
            f"Expected trigger message 'Cannot revoke last superuser …' in "
            f"failure, got: {msg!r}"
        )

        # === Assertion 4: post-condition: exactly 1 active superuser remains. ===
        async with engine.begin() as conn:
            result = await conn.execute(
                sa.text(
                    "SELECT COUNT(*) FROM superusers "
                    "WHERE revoked_at IS NULL AND user_id IN "
                    "(SELECT id FROM users WHERE email LIKE 't954_s7%@example.com')"
                )
            )
            count = int(result.scalar())
            assert count == 1, (
                f"Advisory lock must leave exactly 1 active superuser; got {count}"
            )
    finally:
        async with engine.begin() as conn:
            await _cleanup_t954_rows(conn)
        await engine.dispose()
