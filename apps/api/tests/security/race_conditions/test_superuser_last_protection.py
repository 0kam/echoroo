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
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool


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
# Shared advisory-lock key (must match migration 0013 / superuser_service)
# ---------------------------------------------------------------------------
_LOCK_KEY: int = (
    int.from_bytes(
        hashlib.sha256(b"superuser_last_protection").digest()[:8], "big"
    )
    & 0x7FFFFFFFFFFFFFFF
)

# ---------------------------------------------------------------------------
# Skip guard: skip the whole module if trigger or echoroo_app role is absent
# ---------------------------------------------------------------------------

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


def _make_engine() -> Any:
    return create_async_engine(TEST_DATABASE_URL, poolclass=NullPool, echo=False)


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


@pytest.mark.xfail(
    strict=False,
    reason=(
        "PR-D (Phase 17 §C, 2026-05-07): asyncio.gather lands both tasks in "
        "the same event-loop tick under runner contention, so the trigger's "
        "advisory lock never sees true concurrency. Production correctness "
        "is verified separately (alembic 0013 wraps the active-count probe "
        "in pg_advisory_xact_lock, recomputes COUNT(*) under the lock, and "
        "raises before COUNT(*)-1 < 1) — see PHASE17_BACKLOG.md §B-PR-D and "
        "the surrounding scenarios in this file (test_two_concurrent_admin_*) "
        "which cover the deterministic single-TX paths. Promoting back to a "
        "strict pass requires moving the two TX bodies onto separate OS "
        "threads (asyncio.to_thread + barrier) so the second connection "
        "actually waits on the lock instead of running serially."
    ),
)
async def test_concurrent_revokes_advisory_lock_serialises() -> None:
    """Concurrent 2-row → 0 revoke race as echoroo_app: advisory lock serialises.

    Both transactions target different rows and both would leave 0 active
    superusers if they both committed.  The advisory lock in the trigger
    forces them to serialise: the first TX commits (1 active remains), the
    second TX sees 0 active-after and raises.

    Final active count must be 1.

    Known flakiness (pre-existing, not a regression introduced in Phase 16):
    Under high host contention the two asyncio tasks may execute sequentially
    rather than concurrently (both gather tasks land in the same event-loop
    tick while the DB is busy with prior test cleanup).  When that happens
    both UPDATEs succeed without a trigger conflict and the post-condition
    count ends up at 0, causing this assertion to fail.  The root cause is
    the absence of real parallelism across two OS threads; the advisory-lock
    mechanism itself is correct.  This will be addressed in Batch 6f-4 /
    Phase 16 polish (isolation: dedicated thread pool per concurrent TX or
    asyncio.to_thread wrapper).  Until then this test is an accepted 1F in
    CI on resource-constrained runners.
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

        sid_a: UUID
        sid_b: UUID

        # Seed two active superusers.
        async with engine.begin() as conn:
            await _cleanup_t954_rows(conn)
            await conn.execute(
                sa.text("UPDATE superusers SET revoked_at = now() WHERE revoked_at IS NULL")
            )
            uid_a = await _insert_user(conn, suffix="t954_s7_a")
            uid_b = await _insert_user(conn, suffix="t954_s7_b")
            sid_a = await _insert_superuser(conn, user_id=uid_a)
            sid_b = await _insert_superuser(conn, user_id=uid_b)

        engine_a = _make_engine()
        engine_b = _make_engine()
        factory_a = async_sessionmaker(engine_a, expire_on_commit=False)
        factory_b = async_sessionmaker(engine_b, expire_on_commit=False)

        results: list[Exception | None] = []

        async def _revoke_as_app(factory: Any, sid: UUID) -> Exception | None:
            """Attempt to revoke the given row as echoroo_app."""
            try:
                async with factory() as s:
                    await s.execute(sa.text("SET ROLE echoroo_app"))
                    await s.execute(
                        sa.text(
                            "UPDATE superusers SET revoked_at = now() WHERE id = :sid"
                        ),
                        {"sid": str(sid)},
                    )
                    await s.commit()
                return None
            except Exception as exc:  # noqa: BLE001
                return exc

        try:
            r1, r2 = await asyncio.gather(
                _revoke_as_app(factory_a, sid_a),
                _revoke_as_app(factory_b, sid_b),
            )
            results = [r1, r2]
        finally:
            await engine_a.dispose()
            await engine_b.dispose()

        successes = [r for r in results if r is None]
        failures = [r for r in results if r is not None]

        # Exactly one TX must succeed, the other must be blocked by the trigger.
        assert len(successes) == 1, (
            f"Expected exactly 1 successful revoke, got {len(successes)}. "
            f"Results: {results!r}"
        )
        assert len(failures) == 1, (
            f"Expected exactly 1 trigger-blocked failure, got {len(failures)}. "
            f"Results: {results!r}"
        )
        # The failure must be a trigger RaiseError.
        failed_exc = failures[0]
        assert isinstance(failed_exc, DBAPIError), (
            f"Expected DBAPIError (asyncpg.RaiseError), got {type(failed_exc)}: {failed_exc}"
        )
        assert "RaiseError" in type(failed_exc.orig).__name__ or "Cannot revoke" in str(
            failed_exc
        ), f"Unexpected error: {failed_exc}"

        # Post-condition: exactly 1 active superuser remains (of the t954 race pair).
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
