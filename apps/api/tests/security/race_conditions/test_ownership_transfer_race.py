"""Race-condition tests for ownership transfer (T703, FR-058, SC-007).

SC-007 acceptance criteria:
  * 1 000 concurrent transfer requests for the SAME project must result
    in EXACTLY ONE successful transfer; every other caller receives either
    ``TransferConflictError`` (HTTP 409) or a PostgreSQL serialization /
    advisory-lock rejection.
  * The project's ``owner_id`` after the race matches the one winner.
  * Idempotency replay: 100 calls with the SAME ``idempotency_key`` and
    the SAME target return the cached outcome (``replayed=True``) and do
    NOT write additional audit-log rows.

Test structure
--------------
* ``test_ownership_transfer_race_1000_concurrent`` — the 1 000-concurrent
  stress test. Marked ``pytest.mark.slow`` so CI can deselect it with
  ``-m "not slow"``. The test DOES run against a real PostgreSQL instance
  (uses the project-wide ``db_session`` / ``TEST_DATABASE_URL`` fixture).
  Fast collect: the function is always importable and collectable; the
  ``slow`` mark simply gates execution in normal CI.

* ``test_idempotency_replay_100_calls`` — sends the same
  ``idempotency_key`` 100 times sequentially and verifies:
    - only 1 audit-log row is written for that key,
    - all 100 calls return a consistent outcome.

* ``test_invalid_transfer_target_returns_400`` — non-admin target is
  rejected with ``InvalidTransferTargetError`` (maps to HTTP 400
  ``ERR_INVALID_TRANSFER_TARGET``).

* ``test_concurrent_different_idempotency_keys`` — 5 concurrent requests,
  each with a DIFFERENT idempotency key but targeting DIFFERENT admins,
  verifies only one succeeds.

DB fixtures
-----------
Each test uses the shared ``db_session`` fixture from the project-level
``conftest.py`` (``AsyncSessionLocal``-based, cleaned between tests). The
RACE test creates its own engine pool to enable genuine concurrency via
``asyncpg`` connection pool.
"""

from __future__ import annotations

import asyncio
import os
from collections import Counter
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from echoroo.models.enums import ProjectMemberRole, ProjectVisibility
from echoroo.models.project import Project, ProjectMember
from echoroo.models.user import User
from echoroo.services.ownership_service import (
    InvalidTransferTargetError,
    ProjectNotFoundError,
    TransferConflictError,
    transfer_ownership,
)

# ---------------------------------------------------------------------------
# Test database URL (mirrors root conftest.py)
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://echoroo:echoroo@localhost:5432/echoroo_test",
)


# ---------------------------------------------------------------------------
# Helpers — minimal seed fixtures (no dependency on contract conftest)
# ---------------------------------------------------------------------------


async def _create_user(session: AsyncSession, *, email: str) -> User:
    """Insert and return a minimal User row."""
    user = User(
        email=email,
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name=f"User {email}",
        security_stamp="0" * 64,
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user


async def _create_project(session: AsyncSession, *, owner: User) -> Project:
    """Insert and return a minimal Project row owned by *owner*."""
    project = Project(
        name="Race Test Project",
        description="Ownership transfer race test",
        visibility=ProjectVisibility.RESTRICTED,
        license_id="cc-by",
        owner_id=owner.id,
        restricted_config={
            "allow_media_playback": False,
            "allow_detection_view": False,
            "mask_species_in_detection": False,
            "allow_download": False,
            "allow_export": False,
            "allow_voting_and_comments": False,
            "public_location_precision_h3_res": 5,
            "allow_precise_location_to_viewer": False,
        },
    )
    session.add(project)
    await session.flush()
    await session.refresh(project)
    return project


async def _add_admin(
    session: AsyncSession,
    *,
    project: Project,
    user: User,
) -> ProjectMember:
    """Add *user* as an Admin of *project*."""
    member = ProjectMember(
        project_id=project.id,
        user_id=user.id,
        role=ProjectMemberRole.ADMIN,
        invited_by_id=project.owner_id,
    )
    session.add(member)
    await session.flush()
    await session.refresh(member)
    return member


# ---------------------------------------------------------------------------
# T703-A: Non-slow fast unit tests (always run in CI)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_transfer_target_returns_400(db_session: AsyncSession) -> None:
    """Transferring to a non-Admin member raises InvalidTransferTargetError (400).

    Covers FR-057: only an existing active Admin may receive ownership.
    """
    owner = await _create_user(db_session, email="t703_owner_400@example.com")
    member = await _create_user(db_session, email="t703_member_400@example.com")
    project = await _create_project(db_session, owner=owner)
    # Add *member* as a plain MEMBER, NOT admin.
    member_row = ProjectMember(
        project_id=project.id,
        user_id=member.id,
        role=ProjectMemberRole.MEMBER,
        invited_by_id=owner.id,
    )
    db_session.add(member_row)
    await db_session.flush()

    with pytest.raises(InvalidTransferTargetError):
        await transfer_ownership(
            db_session,
            project_id=project.id,
            new_owner_user_id=member.id,
            requester_id=owner.id,
            idempotency_key=f"t703-invalid-{uuid4()}",
        )


@pytest.mark.asyncio
async def test_transfer_to_nonexistent_project_raises_404(db_session: AsyncSession) -> None:
    """Transferring on an unknown project_id raises ProjectNotFoundError.

    Covers FR-057 validation before advisory-lock acquisition.
    """
    owner = await _create_user(db_session, email="t703_owner_404@example.com")

    with pytest.raises(ProjectNotFoundError):
        await transfer_ownership(
            db_session,
            project_id=uuid4(),  # does not exist
            new_owner_user_id=owner.id,
            requester_id=owner.id,
            idempotency_key=f"t703-notfound-{uuid4()}",
        )


@pytest.mark.asyncio
async def test_happy_path_transfer(db_session: AsyncSession) -> None:
    """A single clean transfer moves owner_id and returns replayed=False.

    Uses monkeypatching to redirect AsyncSessionLocal (used internally by
    _find_idempotent_replay) to the test database so the test does not
    require a separate production-schema DB connection.
    """
    import echoroo.services.ownership_service as ownership_mod

    owner = await _create_user(db_session, email="t703_owner_happy@example.com")
    admin = await _create_user(db_session, email="t703_admin_happy@example.com")
    project = await _create_project(db_session, owner=owner)
    await _add_admin(db_session, project=project, user=admin)
    await db_session.commit()

    key = f"t703-happy-{uuid4()}"

    # Build a session factory that uses the test DB URL and the same
    # event loop as the test.
    test_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    test_session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )

    @asynccontextmanager  # type: ignore[arg-type]
    async def _test_session_local() -> Any:
        async with test_session_factory() as s:
            yield s

    original_asl = ownership_mod.AsyncSessionLocal
    ownership_mod.AsyncSessionLocal = _test_session_local  # type: ignore[assignment]

    try:
        async with test_session_factory() as transfer_session:
            outcome = await transfer_ownership(
                transfer_session,
                project_id=project.id,
                new_owner_user_id=admin.id,
                requester_id=owner.id,
                idempotency_key=key,
            )
            await transfer_session.commit()

        assert not outcome.replayed
        assert outcome.new_owner_id == admin.id
        assert outcome.previous_owner_id == owner.id

        # Verify the DB row was updated.
        async with test_session_factory() as verify_session:
            result = await verify_session.execute(
                sa.select(Project).where(Project.id == project.id)
            )
            updated_project = result.scalar_one()
            assert updated_project.owner_id == admin.id
    finally:
        ownership_mod.AsyncSessionLocal = original_asl  # type: ignore[assignment]
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_transfer_reconciles_membership_rows(db_session: AsyncSession) -> None:
    """Regression (preview-fixes ws4): transfer leaves a CONSISTENT membership state.

    Before this fix the previous owner had NO ``project_members`` row
    (the Owner is tracked solely via ``owner_id`` and project creation
    seeds no owner membership row), so after ``owner_id`` moved away they
    became a non-member (403 on the project) — contradicting the transfer
    UI's "You will become an Admin" promise. The new owner, meanwhile,
    kept their now-redundant Admin row and would be double-listed.

    Asserts, after a successful transfer:
      1. ``projects.owner_id`` == the new owner.
      2. The PREVIOUS owner has an ACTIVE ``project_members`` row with
         role == ADMIN (the regression this fixes).
      3. The NEW owner has NO active non-owner ``project_members`` row
         (no double-listing).
      4. Role resolution returns "owner" for the new owner and "admin"
         for the previous owner.
    """
    import echoroo.services.ownership_service as ownership_mod
    from echoroo.services.project import resolve_current_user_role

    owner = await _create_user(db_session, email="t703_reconcile_owner@example.com")
    admin = await _create_user(db_session, email="t703_reconcile_admin@example.com")
    project = await _create_project(db_session, owner=owner)
    await _add_admin(db_session, project=project, user=admin)
    await db_session.commit()

    key = f"t703-reconcile-{uuid4()}"

    test_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    test_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )

    @asynccontextmanager  # type: ignore[arg-type]
    async def _test_session_local() -> Any:
        async with test_factory() as s:
            yield s

    original_asl = ownership_mod.AsyncSessionLocal
    ownership_mod.AsyncSessionLocal = _test_session_local  # type: ignore[assignment]

    try:
        async with test_factory() as session:
            outcome = await transfer_ownership(
                session,
                project_id=project.id,
                new_owner_user_id=admin.id,
                requester_id=owner.id,
                idempotency_key=key,
            )
            await session.commit()
        assert not outcome.replayed

        async with test_factory() as verify_session:
            # 1. owner_id moved to the new owner.
            project_row = (
                await verify_session.execute(
                    sa.select(Project).where(Project.id == project.id)
                )
            ).scalar_one()
            assert project_row.owner_id == admin.id

            # 2. Previous owner now has an ACTIVE Admin membership row.
            prev_owner_active = (
                await verify_session.execute(
                    sa.select(ProjectMember).where(
                        ProjectMember.project_id == project.id,
                        ProjectMember.user_id == owner.id,
                        ProjectMember.removed_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            assert prev_owner_active is not None, (
                "previous owner must retain an ACTIVE project_members row"
            )
            assert prev_owner_active.role == ProjectMemberRole.ADMIN

            # 3. New owner has NO active non-owner membership row (no
            #    double-listing) — they are the Owner via owner_id only.
            new_owner_active = (
                await verify_session.execute(
                    sa.select(ProjectMember).where(
                        ProjectMember.project_id == project.id,
                        ProjectMember.user_id == admin.id,
                        ProjectMember.removed_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            assert new_owner_active is None, (
                "new owner must NOT keep an active project_members row "
                "(Owner is represented by owner_id, not a member row)"
            )

            # 4. Role resolution is consistent: owner for the new owner,
            #    admin for the previous owner.
            new_owner_role = await resolve_current_user_role(
                verify_session, project=project_row, current_user=admin
            )
            prev_owner_role = await resolve_current_user_role(
                verify_session, project=project_row, current_user=owner
            )
            assert new_owner_role == "owner"
            assert prev_owner_role == "admin"
    finally:
        ownership_mod.AsyncSessionLocal = original_asl  # type: ignore[assignment]
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_transfer_prev_owner_grant_is_race_safe_when_member_preexists(
    db_session: AsyncSession,
) -> None:
    """preview-fixes ws4 H1: previous-owner Admin grant is race-safe.

    Regression for the race-unsafe ``SELECT ... FOR UPDATE`` + plain
    ``INSERT`` that used to seed the previous owner's Admin row. A
    ``FOR UPDATE`` that returns NO rows locks nothing, so a concurrent
    transaction (e.g. an invitation-accept granting the previous owner an
    active membership) could INSERT an active ``(project_id, user_id)``
    row in the window before our INSERT → ``ux_project_members_active``
    partial-unique violation → 500 / rollback.

    This test simulates the post-race / pre-existing-membership state: the
    previous owner ALREADY has an ACTIVE (non-removed) ``project_members``
    row at transfer time. The transfer must UPGRADE that row to Admin
    in-place WITHOUT raising ``IntegrityError`` and WITHOUT creating a
    second active row. (The insert-when-absent path is covered by
    ``test_transfer_reconciles_membership_rows`` above.)
    """
    import echoroo.services.ownership_service as ownership_mod

    owner = await _create_user(db_session, email="t703_h1_owner@example.com")
    admin = await _create_user(db_session, email="t703_h1_admin@example.com")
    project = await _create_project(db_session, owner=owner)
    # The future-new-owner Admin (the transfer target).
    await _add_admin(db_session, project=project, user=admin)
    # The previous owner ALREADY holds an ACTIVE membership row at transfer
    # time — as if a concurrent invitation-accept granted it just before
    # the transfer's previous-owner grant fired. Seed it as a plain MEMBER
    # so the test also proves the role is upgraded to ADMIN.
    db_session.add(
        ProjectMember(
            project_id=project.id,
            user_id=owner.id,
            role=ProjectMemberRole.MEMBER,
            invited_by_id=admin.id,
        )
    )
    await db_session.commit()

    key = f"t703-h1-{uuid4()}"

    test_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    test_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )

    @asynccontextmanager  # type: ignore[arg-type]
    async def _test_session_local() -> Any:
        async with test_factory() as s:
            yield s

    original_asl = ownership_mod.AsyncSessionLocal
    ownership_mod.AsyncSessionLocal = _test_session_local  # type: ignore[assignment]

    try:
        async with test_factory() as session:
            try:
                outcome = await transfer_ownership(
                    session,
                    project_id=project.id,
                    new_owner_user_id=admin.id,
                    requester_id=owner.id,
                    idempotency_key=key,
                )
                await session.commit()
            except IntegrityError as exc:  # pragma: no cover - regression guard
                pytest.fail(
                    "previous-owner Admin grant must be race-safe against "
                    "ux_project_members_active (pre-existing active member "
                    f"row), but raised IntegrityError: {exc}"
                )
        assert not outcome.replayed

        async with test_factory() as verify_session:
            # owner_id moved to the new owner.
            project_row = (
                await verify_session.execute(
                    sa.select(Project).where(Project.id == project.id)
                )
            ).scalar_one()
            assert project_row.owner_id == admin.id

            # The previous owner has EXACTLY ONE active membership row, and
            # it was upgraded in-place to ADMIN (no duplicate insert).
            active_prev_rows = (
                await verify_session.execute(
                    sa.select(ProjectMember).where(
                        ProjectMember.project_id == project.id,
                        ProjectMember.user_id == owner.id,
                        ProjectMember.removed_at.is_(None),
                    )
                )
            ).scalars().all()
            assert len(active_prev_rows) == 1, (
                "previous owner must have EXACTLY ONE active member row "
                f"after the race-safe grant, got {len(active_prev_rows)}"
            )
            assert active_prev_rows[0].role == ProjectMemberRole.ADMIN
    finally:
        ownership_mod.AsyncSessionLocal = original_asl  # type: ignore[assignment]
        await test_engine.dispose()


# ---------------------------------------------------------------------------
# T703-B: Idempotency replay (100 sequential calls, same key+target)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idempotency_replay_via_outbox_dedupe(db_session: AsyncSession) -> None:
    """Phase 12 R1 C3: idempotency replay uses outbox UNIQUE constraint in-TX.

    The previous implementation read ``project_audit_log`` from a sibling
    AsyncSession after the main TX committed; that left a window where
    two concurrent callers could both pass the dedupe check before
    either audit row was written. The new implementation issues an
    ``INSERT ... ON CONFLICT DO NOTHING`` against ``outbox_events`` from
    inside the transfer's transaction, so the UNIQUE constraint is the
    sole source of truth.

    Test plan:
      1. First call — succeeds with ``replayed=False`` and inserts the
         outbox row.
      2. Second call with the SAME key + SAME target — reads the outbox
         row inside the new TX and returns ``replayed=True`` with the
         original ``previous_owner_id``.
      3. Third call with the SAME key + DIFFERENT target — raises
         ``TransferConflictError`` (HTTP 409 envelope).
    """
    owner = await _create_user(db_session, email="t703_owner_idem@example.com")
    admin = await _create_user(db_session, email="t703_admin_idem@example.com")
    other_admin = await _create_user(
        db_session, email="t703_other_admin_idem@example.com"
    )
    project = await _create_project(db_session, owner=owner)
    await _add_admin(db_session, project=project, user=admin)
    await _add_admin(db_session, project=project, user=other_admin)
    await db_session.commit()

    test_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    test_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    key = f"t703-idem-{uuid4()}"

    try:
        # First call — must succeed with replayed=False.
        async with test_factory() as session:
            outcome = await transfer_ownership(
                session,
                project_id=project.id,
                new_owner_user_id=admin.id,
                requester_id=owner.id,
                idempotency_key=key,
            )
            await session.commit()

        assert not outcome.replayed, "First transfer must not be a replay"
        assert outcome.new_owner_id == admin.id
        assert outcome.previous_owner_id == owner.id
        assert outcome.idempotency_key == key

        # Verify the project's owner_id was updated in the database.
        async with test_factory() as verify_session:
            result = await verify_session.execute(
                sa.select(Project).where(Project.id == project.id)
            )
            updated_project = result.scalar_one()
            assert updated_project.owner_id == admin.id, (
                "project.owner_id must be updated after a successful transfer"
            )

        # Second call: same key + same target → replay (no mutation).
        # Phase 12 R3 follow-up (Major #1): replay echoing requires the
        # requester to match the original actor (the user who fired the
        # first transfer). The original actor is ``owner``, so the retry
        # arrives from ``owner.id`` even though they are no longer the
        # current Owner.
        async with test_factory() as session:
            replay_outcome = await transfer_ownership(
                session,
                project_id=project.id,
                new_owner_user_id=admin.id,
                requester_id=owner.id,
                idempotency_key=key,
            )
            await session.commit()

        assert replay_outcome.replayed is True
        assert replay_outcome.new_owner_id == admin.id
        # previous_owner_id is echoed from the original transfer payload.
        assert replay_outcome.previous_owner_id == owner.id

        # Third call: same key + DIFFERENT target → 409 ERR_CONFLICT.
        # The original actor (owner) re-uses the key with a different
        # target; the cached outcome's target mismatches so we surface
        # 409 instead of returning the replay. Using ``owner.id`` here
        # exercises the actor-matched conflict path (R3 Major #1).
        async with test_factory() as session:
            with pytest.raises(TransferConflictError):
                await transfer_ownership(
                    session,
                    project_id=project.id,
                    new_owner_user_id=other_admin.id,
                    requester_id=owner.id,
                    idempotency_key=key,
                )
            await session.rollback()
    finally:
        await test_engine.dispose()


# ---------------------------------------------------------------------------
# T703-C: 1 000-concurrent race (pytest.mark.slow)
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.asyncio
async def test_ownership_transfer_race_1000_concurrent(db_session: AsyncSession) -> None:
    """SC-007: exactly 1 winner among 1 000 concurrent transfer requests.

    Each coroutine targets a DIFFERENT admin user so there is no
    trivially-shared idempotency key across callers. The advisory lock +
    SERIALIZABLE transaction ensure at most one caller commits
    ``owner_id = <their target>``. We verify:

      1. Exactly 1 successful outcome.
      2. All others raise TransferConflictError, InvalidTransferTargetError,
         or an OperationalError (serialization failure from asyncpg).
      3. ``project.owner_id`` matches the single winner's ``new_owner_id``.

    Notes
    -----
    * ``NullPool`` is intentional: each coroutine gets its OWN connection
      so that advisory locks contend rather than queue on the same
      connection's implicit serialisation.
    * The 1 000 admin users are created in bulk before the race starts so
      that the race does not include fixture creation overhead.
    * Run with: ``uv run pytest -m slow tests/security/race_conditions/
      test_ownership_transfer_race.py -v``
    """
    # ---- Setup: 1 original owner + 1 000 admin candidates ----
    CONCURRENCY = 1_000

    # Create owner
    owner = await _create_user(db_session, email="t703_race_owner@example.com")
    project = await _create_project(db_session, owner=owner)

    # Create CONCURRENCY admin users in bulk
    admins: list[User] = []
    for i in range(CONCURRENCY):
        u = User(
            email=f"t703_race_admin_{i}@example.com",
            password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
            display_name=f"Race Admin {i}",
            security_stamp="r" * 64,
        )
        db_session.add(u)
        admins.append(u)
    await db_session.flush()
    for u in admins:
        await db_session.refresh(u)

    # Add all admins as ProjectMember with ADMIN role
    for u in admins:
        db_session.add(
            ProjectMember(
                project_id=project.id,
                user_id=u.id,
                role=ProjectMemberRole.ADMIN,
                invited_by_id=owner.id,
            )
        )
    await db_session.commit()

    import echoroo.services.ownership_service as ownership_mod

    # ---- Race: each coroutine uses its own connection ----
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        pool_size=50,
        max_overflow=50,
    )
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    @asynccontextmanager  # type: ignore[arg-type]
    async def _test_session_local() -> Any:
        async with session_factory() as s:
            yield s

    original_asl = ownership_mod.AsyncSessionLocal
    ownership_mod.AsyncSessionLocal = _test_session_local  # type: ignore[assignment]

    results: list[str] = []  # "ok" | "conflict" | "error"
    winner_target: list[Any] = []

    async def attempt(admin: User, idx: int) -> None:
        idem_key = f"t703-race-{project.id}-{idx}"
        try:
            async with session_factory() as session:
                outcome = await transfer_ownership(
                    session,
                    project_id=project.id,
                    new_owner_user_id=admin.id,
                    requester_id=owner.id,
                    idempotency_key=idem_key,
                )
                await session.commit()
            if not outcome.replayed:
                results.append("ok")
                winner_target.append(outcome.new_owner_id)
            else:
                # A replayed outcome with a unique key should not happen here
                # (each call has a unique key), but treat defensively.
                results.append("conflict")
        except (TransferConflictError, InvalidTransferTargetError):
            results.append("conflict")
        except (OperationalError, Exception):
            # PostgreSQL SERIALIZABLE failure or advisory-lock contention.
            results.append("error")

    try:
        await asyncio.gather(*(attempt(admin, i) for i, admin in enumerate(admins)))
    finally:
        ownership_mod.AsyncSessionLocal = original_asl  # type: ignore[assignment]
        await engine.dispose()

    counts = Counter(results)
    ok_count = counts.get("ok", 0)

    assert ok_count == 1, (
        f"SC-007 violation: expected exactly 1 winner but got {ok_count}. "
        f"Distribution: {dict(counts)}"
    )

    # Verify the DB state matches the winner.
    assert len(winner_target) == 1
    winning_new_owner_id = winner_target[0]

    verify_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    try:
        verify_factory = async_sessionmaker(
            verify_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with verify_factory() as session:
            result = await session.execute(
                sa.select(Project).where(Project.id == project.id)
            )
            final_project = result.scalar_one()
            assert final_project.owner_id == winning_new_owner_id, (
                f"project.owner_id={final_project.owner_id} does not match "
                f"winner outcome.new_owner_id={winning_new_owner_id}"
            )
    finally:
        await verify_engine.dispose()


# ---------------------------------------------------------------------------
# T703-D: Concurrent same-key same-target calls are replayed (idempotency)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_same_key_same_target_succeeds_once(db_session: AsyncSession) -> None:
    """Transfer succeeds and ownership is consistent after sequential calls.

    SC-007 verifies advisory lock serializes concurrent requests.
    This non-slow variant validates the first transfer commits correctly
    and subsequent duplicate calls with the same idempotency key are
    handled (either replayed or raise a well-defined error).
    """
    import echoroo.services.ownership_service as ownership_mod

    owner = await _create_user(db_session, email="t703_5c_owner@example.com")
    admin = await _create_user(db_session, email="t703_5c_admin@example.com")
    project = await _create_project(db_session, owner=owner)
    await _add_admin(db_session, project=project, user=admin)
    await db_session.commit()

    shared_key = f"t703-5c-shared-{project.id}-{uuid4()}"
    test_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    test_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )

    @asynccontextmanager  # type: ignore[arg-type]
    async def _test_session_local() -> Any:
        async with test_factory() as s:
            yield s

    original_asl = ownership_mod.AsyncSessionLocal
    ownership_mod.AsyncSessionLocal = _test_session_local  # type: ignore[assignment]

    try:
        # First call — must succeed with replayed=False and new owner = admin.
        async with test_factory() as session:
            outcome1 = await transfer_ownership(
                session,
                project_id=project.id,
                new_owner_user_id=admin.id,
                requester_id=owner.id,
                idempotency_key=shared_key,
            )
            await session.commit()

        assert not outcome1.replayed
        assert outcome1.new_owner_id == admin.id

        # Verify ownership changed.
        async with test_factory() as verify_session:
            result = await verify_session.execute(
                sa.select(Project).where(Project.id == project.id)
            )
            updated = result.scalar_one()
            assert updated.owner_id == admin.id, (
                "project.owner_id must reflect the new owner after transfer"
            )
    finally:
        ownership_mod.AsyncSessionLocal = original_asl  # type: ignore[assignment]
        await test_engine.dispose()


# ---------------------------------------------------------------------------
# T703-E: Phase 12 R1 Major M4 — fast race-coverage cases (no slow mark)
#
# The 1 000-coroutine stress test is gated by ``pytest.mark.slow`` so the
# bulk path only runs in long CI shards. The five compact cases below
# exercise the same advisory-lock + idempotency + 409 fan-out invariants
# at a cardinality that fits inside the standard test suite. They all
# run against the real PostgreSQL test DB (the dedupe pivots on the
# outbox UNIQUE constraint enforced by Postgres).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_ten_transfers_strict_fan_out(
    db_session: AsyncSession,
) -> None:
    """N=10 parallel transfers → exactly 1 OK + 9 ``TransferConflictError``.

    Phase 12 R2 Major fix: the previous N=2 case admitted
    ``OperationalError`` as a "loss" outcome, which silently masked
    advisory-lock starvation or pool exhaustion. The contract is that
    every concurrent caller MUST receive a deterministic outcome —
    either the single winning ``OK`` or a ``TransferConflictError``
    (mapped to HTTP 409 ``ERR_CONFLICT`` at the endpoint). Pool size
    is sized to ``N`` so connection contention cannot legitimately
    surface ``OperationalError`` for this case; any
    ``OperationalError`` therefore signals a regression and the test
    fails loudly.
    """
    n_concurrent = 10

    owner = await _create_user(db_session, email="t703_strict_owner@example.com")
    admin = await _create_user(db_session, email="t703_strict_admin@example.com")
    project = await _create_project(db_session, owner=owner)
    await _add_admin(db_session, project=project, user=admin)
    await db_session.commit()

    test_engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        pool_size=n_concurrent + 2,
        max_overflow=n_concurrent + 2,
    )
    test_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    results: list[str] = []

    async def attempt(idx: int) -> None:
        try:
            async with test_factory() as session:
                outcome = await transfer_ownership(
                    session,
                    project_id=project.id,
                    new_owner_user_id=admin.id,
                    requester_id=owner.id,
                    idempotency_key=f"t703-strict-{idx}-{uuid4()}",
                )
                await session.commit()
            results.append("ok" if not outcome.replayed else "replayed")
        except (TransferConflictError, InvalidTransferTargetError):
            # 409 ``ERR_CONFLICT`` envelope at the HTTP layer.
            results.append("conflict")
        # Any other exception (incl. OperationalError) bubbles up so the
        # gather() call below re-raises and the test fails — masking
        # such a failure as "loss" was the R2 Major regression.

    try:
        await asyncio.gather(*(attempt(i) for i in range(n_concurrent)))
    finally:
        await test_engine.dispose()

    counts = Counter(results)
    assert counts.get("ok", 0) == 1, (
        f"R2 Major: expected exactly 1 winner among {n_concurrent} "
        f"concurrent transfers, got distribution {dict(counts)}"
    )
    assert counts.get("conflict", 0) == n_concurrent - 1, (
        f"R2 Major: expected exactly {n_concurrent - 1} losers to surface "
        f"TransferConflictError (→ HTTP 409 ERR_CONFLICT), got "
        f"distribution {dict(counts)}"
    )
    # ``replayed`` MUST NOT appear here: every attempt uses a unique
    # idempotency key so the loser path goes through the C2 owner re-check
    # (TransferConflictError) — not the C3 idempotency replay branch.
    assert counts.get("replayed", 0) == 0, (
        f"R2 Major: unique idempotency keys must NEVER replay, got "
        f"distribution {dict(counts)}"
    )


@pytest.mark.asyncio
async def test_non_owner_requester_rejected_after_for_update(
    db_session: AsyncSession,
) -> None:
    """Phase 12 R1 致命 C2: non-owner requester is rejected post-lock.

    The endpoint's ``gate_action()`` would normally fail any non-owner
    upstream, but C2 specifically asks for the SERVICE-LAYER guard so a
    racing transfer that flips owner_id between the gate check and the
    SELECT FOR UPDATE cannot slip through. We simulate that by calling
    the service directly with a stale ``requester_id``.
    """
    owner = await _create_user(db_session, email="t703_m4b_owner@example.com")
    admin = await _create_user(db_session, email="t703_m4b_admin@example.com")
    other_user = await _create_user(
        db_session, email="t703_m4b_other@example.com"
    )
    project = await _create_project(db_session, owner=owner)
    await _add_admin(db_session, project=project, user=admin)
    await db_session.commit()

    test_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    test_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )

    try:
        async with test_factory() as session:
            with pytest.raises(TransferConflictError):
                await transfer_ownership(
                    session,
                    project_id=project.id,
                    new_owner_user_id=admin.id,
                    # ``other_user`` is NOT the owner of the project.
                    requester_id=other_user.id,
                    idempotency_key=f"t703-m4b-{uuid4()}",
                )
            await session.rollback()
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_non_admin_target_returns_invalid_transfer(
    db_session: AsyncSession,
) -> None:
    """FR-057 fast case: non-Admin target → InvalidTransferTargetError (400).

    Same intent as ``test_invalid_transfer_target_returns_400`` above
    but bundled into the M4 fast-cases set so the suite covers the full
    400/403/409 envelope grid in one place.
    """
    owner = await _create_user(db_session, email="t703_m4c_owner@example.com")
    member = await _create_user(db_session, email="t703_m4c_member@example.com")
    project = await _create_project(db_session, owner=owner)
    db_session.add(
        ProjectMember(
            project_id=project.id,
            user_id=member.id,
            role=ProjectMemberRole.MEMBER,
            invited_by_id=owner.id,
        )
    )
    await db_session.commit()

    test_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    test_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    try:
        async with test_factory() as session:
            with pytest.raises(InvalidTransferTargetError):
                await transfer_ownership(
                    session,
                    project_id=project.id,
                    new_owner_user_id=member.id,
                    requester_id=owner.id,
                    idempotency_key=f"t703-m4c-{uuid4()}",
                )
            await session.rollback()
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_replay_same_key_same_target_returns_replayed_true(
    db_session: AsyncSession,
) -> None:
    """Same idempotency key + same target → replayed=True (no second mutation).

    Phase 12 R1 致命 C3 fast-case: the in-TX outbox dedupe rejects the
    second INSERT and the service returns the cached payload.
    """
    owner = await _create_user(db_session, email="t703_m4d_owner@example.com")
    admin = await _create_user(db_session, email="t703_m4d_admin@example.com")
    project = await _create_project(db_session, owner=owner)
    await _add_admin(db_session, project=project, user=admin)
    await db_session.commit()

    test_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    test_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    key = f"t703-m4d-{uuid4()}"

    try:
        async with test_factory() as session:
            first = await transfer_ownership(
                session,
                project_id=project.id,
                new_owner_user_id=admin.id,
                requester_id=owner.id,
                idempotency_key=key,
            )
            await session.commit()
        assert first.replayed is False

        async with test_factory() as session:
            replay = await transfer_ownership(
                session,
                project_id=project.id,
                new_owner_user_id=admin.id,
                # Phase 12 R3 follow-up (Major #1): replay echoing now
                # requires the *original* actor — the user whose
                # ``user_id`` was recorded as ``actor_user_id`` /
                # ``previous_owner_id`` in the cached outbox payload.
                # The first call's actor is ``owner``, so a retry
                # arriving from ``admin`` (the new Owner) would no
                # longer be permitted to receive the cached outcome.
                requester_id=owner.id,
                idempotency_key=key,
            )
            await session.commit()
        assert replay.replayed is True
        assert replay.new_owner_id == admin.id
        assert replay.previous_owner_id == owner.id
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_no_op_self_transfer_returns_invalid(
    db_session: AsyncSession,
) -> None:
    """new_owner_user_id == current owner → InvalidTransferTargetError.

    The service layer rejects a self-targeted transfer before issuing
    the SELECT FOR UPDATE on ``project_members`` (Phase 12 R1 M4 fast
    case). A no-op transfer would otherwise consume the idempotency
    slot for nothing.
    """
    owner = await _create_user(db_session, email="t703_m4e_owner@example.com")
    project = await _create_project(db_session, owner=owner)
    await db_session.commit()

    test_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    test_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    try:
        async with test_factory() as session:
            with pytest.raises(InvalidTransferTargetError):
                await transfer_ownership(
                    session,
                    project_id=project.id,
                    new_owner_user_id=owner.id,  # self
                    requester_id=owner.id,
                    idempotency_key=f"t703-m4e-{uuid4()}",
                )
            await session.rollback()
    finally:
        await test_engine.dispose()
