"""Phase 12 R3 follow-up (Major #1) — replay actor binding.

Verifies that the FR-058 idempotency replay short-circuit (added in R1
致命 C3 / R2 致命 C3) only echoes the cached outcome when the requester
matches the **original actor** (the user whose ``user_id`` was recorded
as ``actor_user_id`` / ``previous_owner_id`` in the cached outbox
payload). A different authenticated caller who happens to know / guess
the ``(idempotency_key, project_id, target_user_id)`` triple MUST NOT
receive the cached outcome — they fall through to the normal Stage-1
``gate_action()`` which 403s them because they no longer hold the Owner
role.

Two regression scenarios:

1. Original actor retries → cached outcome returned (replayed=True).
   This is the legitimate "network blip / proxy timeout" case the
   replay short-circuit was designed for.

2. Different authenticated user (e.g. another Admin / a freshly-promoted
   new Owner) sends the same key + target → ``peek_replay_outcome``
   returns ``None`` so the call falls through to the normal gate, AND
   ``transfer_ownership`` itself surfaces 409 in the race-tail
   (``actor != requester``) branch.

The test exercises the lower-level service surfaces
(:func:`peek_replay_outcome` and :func:`transfer_ownership`) directly
because the routes are mounted via FastAPI middleware that this
unit-style test does not boot. The HTTP wiring is covered by the
existing endpoint contract tests; the binding logic lives entirely in
the service layer.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
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
    TransferConflictError,
    peek_replay_outcome,
    transfer_ownership,
)

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://echoroo:echoroo@localhost:5432/echoroo_test",
)


# ---------------------------------------------------------------------------
# Local helpers (mirror the fixtures in test_ownership_transfer_race.py)
# ---------------------------------------------------------------------------


async def _create_user(session: AsyncSession, *, email: str) -> User:
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
    project = Project(
        name="Replay Actor Binding Project",
        description="R3 Major #1 regression",
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
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_peek_replay_returns_cached_for_original_actor(
    db_session: AsyncSession,
) -> None:
    """The original actor retrying receives the cached outcome.

    Set-up: owner transfers to admin. Owner retries with the same key.
    The pre-gate ``peek_replay_outcome()`` short-circuit returns the
    cached payload (replayed=True) so the endpoint can respond without
    re-running the now-impossible Stage-1 owner gate.
    """
    original_owner = await _create_user(
        db_session, email="r3_actor_orig_owner@example.com"
    )
    new_owner = await _create_user(
        db_session, email="r3_actor_new_owner@example.com"
    )
    project = await _create_project(db_session, owner=original_owner)
    await _add_admin(db_session, project=project, user=new_owner)
    await db_session.commit()

    key = f"r3-actor-bind-orig-{uuid4()}"

    test_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    test_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    try:
        async with test_factory() as session:
            outcome = await transfer_ownership(
                session,
                project_id=project.id,
                new_owner_user_id=new_owner.id,
                requester_id=original_owner.id,
                idempotency_key=key,
            )
            await session.commit()
        assert outcome.replayed is False

        # Original actor retries — must receive cached outcome.
        async with test_factory() as session:
            cached = await peek_replay_outcome(
                session,
                project_id=project.id,
                idempotency_key=key,
                new_owner_user_id=new_owner.id,
                requester_id=original_owner.id,
            )
            await session.rollback()

        assert cached is not None
        assert cached.replayed is True
        assert cached.new_owner_id == new_owner.id
        assert cached.previous_owner_id == original_owner.id
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_peek_replay_returns_none_for_different_requester(
    db_session: AsyncSession,
) -> None:
    """A non-actor caller MUST NOT receive the cached outcome.

    Set-up: owner transfers to admin. A different authenticated user
    (here, the freshly-promoted new owner) sends the same idempotency
    key + same target. ``peek_replay_outcome()`` returns ``None`` so the
    call falls through to the normal Stage-1 ``gate_action()`` — which,
    in production, 403s a non-actor caller.

    This regression guards against the R3 Major #1 leak: prior to the
    fix, the peek returned the cached outcome for any authenticated
    caller who guessed the ``(key, target, project)`` triple, bypassing
    the owner gate.
    """
    original_owner = await _create_user(
        db_session, email="r3_actor_attacker_owner@example.com"
    )
    new_owner = await _create_user(
        db_session, email="r3_actor_attacker_new_owner@example.com"
    )
    third_party = await _create_user(
        db_session, email="r3_actor_attacker_third@example.com"
    )
    project = await _create_project(db_session, owner=original_owner)
    await _add_admin(db_session, project=project, user=new_owner)
    await _add_admin(db_session, project=project, user=third_party)
    await db_session.commit()

    key = f"r3-actor-bind-bad-{uuid4()}"

    test_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    test_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    try:
        async with test_factory() as session:
            outcome = await transfer_ownership(
                session,
                project_id=project.id,
                new_owner_user_id=new_owner.id,
                requester_id=original_owner.id,
                idempotency_key=key,
            )
            await session.commit()
        assert outcome.replayed is False

        # Sub-case 1: the new owner (a different user) tries to replay.
        async with test_factory() as session:
            cached_for_new_owner = await peek_replay_outcome(
                session,
                project_id=project.id,
                idempotency_key=key,
                new_owner_user_id=new_owner.id,
                requester_id=new_owner.id,
            )
            await session.rollback()
        assert cached_for_new_owner is None, (
            "non-actor must not receive cached replay (R3 Major #1)"
        )

        # Sub-case 2: an unrelated Admin tries to replay.
        async with test_factory() as session:
            cached_for_third = await peek_replay_outcome(
                session,
                project_id=project.id,
                idempotency_key=key,
                new_owner_user_id=new_owner.id,
                requester_id=third_party.id,
            )
            await session.rollback()
        assert cached_for_third is None, (
            "third-party must not receive cached replay (R3 Major #1)"
        )
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_transfer_service_replay_rejects_non_actor(
    db_session: AsyncSession,
) -> None:
    """The in-TX replay branch surfaces 409 for a non-actor requester.

    Even if a non-actor caller bypasses the pre-gate peek (e.g. via
    the legacy programmatic /api/v1 surface that may not yet route the
    peek), :func:`transfer_ownership` itself MUST refuse to echo the
    cached outcome. The race-tail replay branch raises
    :class:`TransferConflictError` with an actor-mismatch message.
    """
    original_owner = await _create_user(
        db_session, email="r3_service_orig@example.com"
    )
    new_owner = await _create_user(
        db_session, email="r3_service_new@example.com"
    )
    project = await _create_project(db_session, owner=original_owner)
    await _add_admin(db_session, project=project, user=new_owner)
    await db_session.commit()

    key = f"r3-actor-svc-{uuid4()}"

    test_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    test_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    try:
        async with test_factory() as session:
            await transfer_ownership(
                session,
                project_id=project.id,
                new_owner_user_id=new_owner.id,
                requester_id=original_owner.id,
                idempotency_key=key,
            )
            await session.commit()

        # The new owner is now the current owner of the project, so the
        # C2 owner-recheck would NOT raise on its own — the only thing
        # standing between them and the cached outcome is the actor
        # binding check we added in R3 Major #1.
        async with test_factory() as session:
            with pytest.raises(TransferConflictError):
                await transfer_ownership(
                    session,
                    project_id=project.id,
                    new_owner_user_id=new_owner.id,
                    requester_id=new_owner.id,  # NOT the original actor
                    idempotency_key=key,
                )
            await session.rollback()
    finally:
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_outbox_payload_records_actor_user_id(
    db_session: AsyncSession,
) -> None:
    """The cached outbox payload must include ``actor_user_id``.

    The actor binding check relies on the field being persisted in the
    outbox JSONB payload. This regression guards against a future
    refactor accidentally dropping the field from the INSERT.
    """
    original_owner = await _create_user(
        db_session, email="r3_payload_orig@example.com"
    )
    new_owner = await _create_user(
        db_session, email="r3_payload_new@example.com"
    )
    project = await _create_project(db_session, owner=original_owner)
    await _add_admin(db_session, project=project, user=new_owner)
    await db_session.commit()

    key = f"r3-payload-{uuid4()}"

    test_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    test_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    try:
        async with test_factory() as session:
            await transfer_ownership(
                session,
                project_id=project.id,
                new_owner_user_id=new_owner.id,
                requester_id=original_owner.id,
                idempotency_key=key,
            )
            await session.commit()

        async with test_factory() as session:
            row: Any = (
                await session.execute(
                    sa.text(
                        """
                        SELECT payload
                          FROM outbox_events
                         WHERE event_type = 'project.ownership_transfer'
                           AND payload->>'idempotency_key' = :raw_key
                         LIMIT 1
                        """
                    ),
                    {"raw_key": key},
                )
            ).first()
        assert row is not None, "outbox row must exist for the consumed key"
        payload = row[0]
        if isinstance(payload, str):
            import json as _json

            payload = _json.loads(payload)
        assert payload["actor_user_id"] == str(original_owner.id), (
            "outbox payload must carry actor_user_id for R3 actor binding"
        )
    finally:
        await test_engine.dispose()


__all__ = [
    "test_peek_replay_returns_cached_for_original_actor",
    "test_peek_replay_returns_none_for_different_requester",
    "test_transfer_service_replay_rejects_non_actor",
    "test_outbox_payload_records_actor_user_id",
]


# Imported lazily inside the helper that needs it; re-export to keep
# the linter happy when the contextmanager helper below is unused (it
# isn't here, but keeps parity with sibling test modules).
__contextmanager__ = asynccontextmanager
