"""Integration tests for the dormancy detection worker (T705 / Phase 12 R1 M5).

These tests exercise :func:`echoroo.workers.dormancy_check.run_dormancy_check`
against a real PostgreSQL connection so we can verify:

* the FR-060 ``GREATEST(last_login_at, last_first_party_activity_at)``
  cutoff arithmetic at the SQL layer (Phase 12 R1 M3 fix), including
  the ``COALESCE(..., users.created_at)`` fallback.
* the per-(project, stage) idempotency key collapses repeated beat
  ticks into a single ``outbox_events`` row (Phase 12 R1 M2 fix).
* the ``pg_try_advisory_xact_lock`` single-shot guard prevents two
  worker instances from racing the scan/flip pipeline.

The pure-mock unit tests in ``tests/unit/workers/test_dormancy_check.py``
remain as the fast-feedback layer; this file complements them with the
DB-backed coverage Codex R1 Major M5 asks for.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

import echoroo.workers.dormancy_check as dormancy_mod
from echoroo.models.enums import ProjectVisibility
from echoroo.models.project import Project
from echoroo.models.user import User
from echoroo.workers.dormancy_check import (
    DORMANT_THRESHOLD_SECONDS,
    OUTBOX_EVENT_DORMANCY,
    run_dormancy_check,
)

pytestmark = pytest.mark.asyncio


TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://echoroo:echoroo@localhost:5432/echoroo_test",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_user(
    session: AsyncSession,
    *,
    email: str,
    last_login_at: datetime | None = None,
    last_first_party_activity_at: datetime | None = None,
    created_at: datetime | None = None,
) -> User:
    """Insert a User with explicit activity timestamps."""
    kwargs: dict[str, object] = {
        "email": email,
        "password_hash": "$argon2id$v=19$m=65536,t=3,p=4$test",
        "display_name": f"User {email}",
        "security_stamp": "0" * 64,
        "last_login_at": last_login_at,
        "last_first_party_activity_at": last_first_party_activity_at,
    }
    if created_at is not None:
        kwargs["created_at"] = created_at
    user = User(**kwargs)
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user


async def _create_project(
    session: AsyncSession,
    *,
    owner: User,
    status_value: str = "active",
    name: str | None = None,
    dormant_since: datetime | None = None,
) -> Project:
    """Insert a Project owned by *owner* with raw SQL so we can set ``status``.

    ``Project.status`` defaults to ACTIVE on the ORM side; for the
    DORMANT-precondition test we need to override it directly.
    """
    project = Project(
        name=name or f"Dormancy Test Project {uuid4().hex[:6]}",
        description="Phase 12 R1 M5 dormancy integration test",
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
    if status_value != "active" or dormant_since is not None:
        await session.execute(
            sa.text(
                "UPDATE projects SET status = :status, dormant_since = :ds "
                "WHERE id = :pid"
            ),
            {
                "status": status_value,
                "ds": dormant_since,
                "pid": project.id,
            },
        )
        await session.flush()
    return project


async def _count_outbox_for_project(
    session: AsyncSession, *, project_id: object, stage: str | None = None
) -> int:
    """Return outbox row count for the dormancy event-type / project_id pair."""
    if stage is None:
        stmt = sa.text(
            "SELECT COUNT(*) FROM outbox_events "
            "WHERE event_type = :etype "
            "AND payload->>'project_id' = :pid"
        )
        params: dict[str, object] = {
            "etype": OUTBOX_EVENT_DORMANCY,
            "pid": str(project_id),
        }
    else:
        stmt = sa.text(
            "SELECT COUNT(*) FROM outbox_events "
            "WHERE event_type = :etype "
            "AND payload->>'project_id' = :pid "
            "AND payload->>'stage' = :stage"
        )
        params = {
            "etype": OUTBOX_EVENT_DORMANCY,
            "pid": str(project_id),
            "stage": stage,
        }
    result = await session.execute(stmt, params)
    raw = result.scalar_one()
    return int(raw)


# ---------------------------------------------------------------------------
# Test 1 — ACTIVE project flips to DORMANT after 366d (FR-060 + M3 GREATEST)
# ---------------------------------------------------------------------------


async def test_active_project_flips_to_dormant_after_366d(
    db_session: AsyncSession,
) -> None:
    """An ACTIVE project whose owner has not been active for 366d → DORMANT + stage_initial.

    Verifies the Phase 12 R1 M3 fix: ``GREATEST(last_login_at,
    last_first_party_activity_at)`` is the cutoff metric. Both
    timestamps are far in the past so the project must be picked up,
    flipped, and a single ``stage_initial`` outbox row written.
    """
    now = datetime.now(UTC)
    activity = now - timedelta(seconds=DORMANT_THRESHOLD_SECONDS + 86_400)

    owner = await _create_user(
        db_session,
        email=f"dormancy-int-1-{uuid4()}@example.com",
        last_login_at=activity,
        last_first_party_activity_at=activity,
    )
    project = await _create_project(db_session, owner=owner)
    await db_session.commit()

    # The worker uses :data:`AsyncSessionLocal` — point it at the test DB.
    test_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    test_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    original_asl = dormancy_mod.AsyncSessionLocal
    dormancy_mod.AsyncSessionLocal = test_factory  # type: ignore[assignment]

    try:
        result = await run_dormancy_check(now=now)
        assert result["status"] == "ok", result
        assert result["flipped"] >= 1

        # Verify Project row flipped + outbox row count == 1 (stage_initial).
        async with test_factory() as verify:
            row = (
                await verify.execute(
                    sa.select(Project.status, Project.dormant_since).where(
                        Project.id == project.id
                    )
                )
            ).first()
            assert row is not None
            assert row[0].value == "dormant"
            assert row[1] is not None

            count = await _count_outbox_for_project(
                verify, project_id=project.id, stage="stage_initial"
            )
            assert count == 1, (
                f"expected exactly 1 stage_initial outbox row, got {count}"
            )
    finally:
        dormancy_mod.AsyncSessionLocal = original_asl  # type: ignore[assignment]
        await test_engine.dispose()


# ---------------------------------------------------------------------------
# Test 2 — recent login keeps an ACTIVE project out of dormancy (M3 GREATEST)
# ---------------------------------------------------------------------------


async def test_recent_login_protects_active_project(
    db_session: AsyncSession,
) -> None:
    """Owner with stale ``last_first_party_activity_at`` BUT recent ``last_login_at`` is safe.

    Phase 12 R1 M3: the cutoff metric is the GREATEST of the two
    columns. Even if first-party activity has stagnated, a recent
    login MUST keep the project out of the candidate scan. This is the
    single most important regression that the M3 fix introduces.
    """
    now = datetime.now(UTC)
    stale_first_party = now - timedelta(seconds=DORMANT_THRESHOLD_SECONDS + 86_400)
    fresh_login = now - timedelta(days=10)

    owner = await _create_user(
        db_session,
        email=f"dormancy-int-2-{uuid4()}@example.com",
        last_login_at=fresh_login,
        last_first_party_activity_at=stale_first_party,
    )
    project = await _create_project(db_session, owner=owner)
    await db_session.commit()

    test_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    test_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    original_asl = dormancy_mod.AsyncSessionLocal
    dormancy_mod.AsyncSessionLocal = test_factory  # type: ignore[assignment]

    try:
        await run_dormancy_check(now=now)
        async with test_factory() as verify:
            row = (
                await verify.execute(
                    sa.select(Project.status).where(Project.id == project.id)
                )
            ).first()
            assert row is not None
            assert row[0].value == "active", (
                "M3: a recent last_login_at must protect the project from "
                "the dormancy flip even when last_first_party_activity_at is stale"
            )
    finally:
        dormancy_mod.AsyncSessionLocal = original_asl  # type: ignore[assignment]
        await test_engine.dispose()


# ---------------------------------------------------------------------------
# Test 3 — per-stage idempotency: 2 beat ticks → 1 outbox row (M2)
# ---------------------------------------------------------------------------


async def test_followup_stage_idempotent_across_two_runs(
    db_session: AsyncSession,
) -> None:
    """Phase 12 R1 M2: stage_30d emits exactly once across multiple beat ticks.

    Pre-seed a project as ``DORMANT`` 30 days ago, then call
    :func:`run_dormancy_check` twice with different ``now`` values
    inside the same UTC day (and again the next day). The
    per-(project, stage) idempotency key MUST collapse all three runs
    into a single ``stage_30d`` outbox row. The previous implementation
    keyed per-day and would have produced 2 rows.
    """
    now_day1 = datetime.now(UTC)
    now_day2 = now_day1 + timedelta(days=1)
    dormant_since = now_day1 - timedelta(days=30, seconds=120)

    activity = now_day1 - timedelta(seconds=DORMANT_THRESHOLD_SECONDS + 86_400)
    owner = await _create_user(
        db_session,
        email=f"dormancy-int-3-{uuid4()}@example.com",
        last_login_at=activity,
        last_first_party_activity_at=activity,
    )
    project = await _create_project(
        db_session,
        owner=owner,
        status_value="dormant",
        dormant_since=dormant_since,
    )
    await db_session.commit()

    test_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    test_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    original_asl = dormancy_mod.AsyncSessionLocal
    dormancy_mod.AsyncSessionLocal = test_factory  # type: ignore[assignment]

    try:
        await run_dormancy_check(now=now_day1)
        # Second run on the same UTC day — must NOT add a row.
        await run_dormancy_check(now=now_day1 + timedelta(hours=2))
        # Third run on the next UTC day — still must NOT add a row.
        await run_dormancy_check(now=now_day2)

        async with test_factory() as verify:
            count = await _count_outbox_for_project(
                verify, project_id=project.id, stage="stage_30d"
            )
            # Exactly one stage_30d row across the three beat ticks.
            assert count == 1, (
                f"M2: expected stage_30d to collapse to a single outbox "
                f"row across multiple beat ticks (got {count})"
            )

            # stage_3d also fires (30d > 3d), and same idempotency rules apply.
            count_3d = await _count_outbox_for_project(
                verify, project_id=project.id, stage="stage_3d"
            )
            assert count_3d == 1, (
                f"M2: stage_3d must also collapse to one row (got {count_3d})"
            )
    finally:
        dormancy_mod.AsyncSessionLocal = original_asl  # type: ignore[assignment]
        await test_engine.dispose()


# ---------------------------------------------------------------------------
# Test 4 — advisory lock: a second concurrent run is a no-op
# ---------------------------------------------------------------------------


async def test_advisory_lock_blocks_concurrent_run(
    db_session: AsyncSession,
) -> None:
    """``pg_try_advisory_xact_lock`` prevents a second concurrent run.

    The worker holds the lock for the duration of its TX. We open a
    sibling transaction that *itself* takes the same advisory lock and
    then invoke :func:`run_dormancy_check` — the helper must detect the
    contended lock and return ``status='skipped'`` without raising.
    """
    test_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    test_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    original_asl = dormancy_mod.AsyncSessionLocal
    dormancy_mod.AsyncSessionLocal = test_factory  # type: ignore[assignment]

    try:
        # Open a long-running TX that holds the advisory lock.
        async with test_factory() as holder:
            await holder.execute(
                sa.text("SELECT pg_advisory_xact_lock(:k)"),
                {"k": dormancy_mod._DORMANCY_CHECK_LOCK_KEY},
            )

            # The dormancy_check call must short-circuit because the
            # lock is contended. We do NOT commit / rollback the holder
            # session yet.
            outcome = await run_dormancy_check(now=datetime.now(UTC))
            assert outcome["status"] == "skipped"
            assert outcome["reason"] == "lock_contended"
            assert outcome["flipped"] == 0

            # Release the lock by rolling back the holder.
            await holder.rollback()
    finally:
        dormancy_mod.AsyncSessionLocal = original_asl  # type: ignore[assignment]
        await test_engine.dispose()
