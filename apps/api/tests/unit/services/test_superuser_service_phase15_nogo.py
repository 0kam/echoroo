"""Phase 15 NO-GO regression tests for ``superuser_service``.

These tests pin the four critical + minor fixes from the Codex review of
commit ``e52b9321``:

* C1 — ``approve_request`` race / duplicate detection
* C2 — ``enter_break_glass_mode`` resolves ``users.id`` → ``superusers.id``
  before stamping ``system_settings.updated_by_id``
* C3 — ``revoke_superuser_apply`` raises ``LastSuperuserProtectionError``
  when ``active_before <= 1``
* Minor 1 — ``approve_request`` rejects a revoked approver_superuser_id

All tests use the shared ``db_session`` fixture (Postgres ``echoroo_test``).
The tests intentionally do NOT exercise the BEFORE UPDATE trigger (that is
covered by the trigger parity test ``test_baseline_baseline_parity`` once
migration 0012 lands and gets included in the 9-axis snapshot); the
service-side defence is what this suite locks in.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from echoroo.models.superuser import Superuser
from echoroo.models.superuser_approval_request import SuperuserApprovalRequest
from echoroo.models.user import User
from echoroo.services import superuser_service
from echoroo.services.superuser_service import (
    ACTION_SUPERUSER_REVOKE,
    DuplicateApprovalError,
    LastSuperuserProtectionError,
    NotSuperuserError,
    approve_request,
    enter_break_glass_mode,
    revoke_superuser_apply,
)
from tests.conftest import TEST_DATABASE_URL

# ---------------------------------------------------------------------------
# Helpers — minimal fixtures (avoid pulling the whole admin contract suite).
# ---------------------------------------------------------------------------


async def _create_user(session: AsyncSession, *, email: str) -> User:
    user = User(
        email=email,
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$nogo",
        display_name=f"User {email}",
        security_stamp="0" * 64,
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user


async def _create_superuser(
    session: AsyncSession, *, user: User, revoked: bool = False
) -> Superuser:
    row = Superuser(
        user_id=user.id,
        added_by_id=None,  # genesis path is acceptable for unit isolation
        added_at=datetime.now(UTC) - timedelta(days=1),
        webauthn_credentials=[],
        allowed_ip_cidrs=[],
        revoked_at=datetime.now(UTC) if revoked else None,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


# ---------------------------------------------------------------------------
# C1 — approve_request race / duplicate detection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approve_request_rejects_duplicate_from_same_approver(
    db_session: AsyncSession,
) -> None:
    """The same approver may not co-sign twice (Phase 15 NO-GO C1 path).

    The lock + JSONB membership scan should reject the second call with
    ``DuplicateApprovalError`` regardless of whether the first
    approval has been committed yet.
    """
    requester_user = await _create_user(db_session, email="phase15_c1_req@example.com")
    approver_user = await _create_user(db_session, email="phase15_c1_app@example.com")
    target_user = await _create_user(db_session, email="phase15_c1_tgt@example.com")
    requester = await _create_superuser(db_session, user=requester_user)
    approver = await _create_superuser(db_session, user=approver_user)
    target = await _create_superuser(db_session, user=target_user)

    ticket = SuperuserApprovalRequest(
        action=ACTION_SUPERUSER_REVOKE,
        detail={
            "target_superuser_id": str(target.id),
            "target_user_id": str(target.user_id),
        },
        requested_by_id=requester.id,
        approvals=[],
        status="pending",
    )
    db_session.add(ticket)
    await db_session.flush()

    # First approval succeeds (status remains pending — only 1 of 2 yet).
    await approve_request(
        db_session,
        request_id_uuid=ticket.id,
        approver_superuser_id=approver.id,
    )

    # Second approval from the SAME approver must raise.
    with pytest.raises(DuplicateApprovalError):
        await approve_request(
            db_session,
            request_id_uuid=ticket.id,
            approver_superuser_id=approver.id,
        )


@pytest.mark.asyncio
async def test_approve_request_rejects_revoked_approver(
    db_session: AsyncSession,
) -> None:
    """Minor 1: a revoked superuser cannot push a ticket past quorum."""
    requester_user = await _create_user(db_session, email="phase15_minor_req@example.com")
    revoked_user = await _create_user(db_session, email="phase15_minor_rev@example.com")
    target_user = await _create_user(db_session, email="phase15_minor_tgt@example.com")
    requester = await _create_superuser(db_session, user=requester_user)
    revoked_su = await _create_superuser(db_session, user=revoked_user, revoked=True)
    target = await _create_superuser(db_session, user=target_user)

    ticket = SuperuserApprovalRequest(
        action=ACTION_SUPERUSER_REVOKE,
        detail={
            "target_superuser_id": str(target.id),
            "target_user_id": str(target.user_id),
        },
        requested_by_id=requester.id,
        approvals=[],
        status="pending",
    )
    db_session.add(ticket)
    await db_session.flush()

    with pytest.raises(NotSuperuserError):
        await approve_request(
            db_session,
            request_id_uuid=ticket.id,
            approver_superuser_id=revoked_su.id,
        )


# ---------------------------------------------------------------------------
# C2 — enter_break_glass_mode resolves users.id → superusers.id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enter_break_glass_resolves_actor_user_id_to_superuser_id(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``enter_break_glass_mode`` must persist ``superusers.id`` (FK target).

    Phase 15 NO-GO C2: the previous code path passed ``actor_user_id``
    (``users.id``) directly into ``system_settings.updated_by_id`` (FK
    → ``superusers.id``). A fresh insert against ``system_settings``
    raised ``ForeignKeyViolationError`` and aborted the entire revoke
    transaction. The fix calls ``_resolve_active_superuser_id`` and
    only writes when the lookup succeeds.

    We assert via a stub upsert that captures the ``updated_by_id``
    value the helper would persist.
    """
    actor_user = await _create_user(db_session, email="phase15_c2_actor@example.com")
    actor_su = await _create_superuser(db_session, user=actor_user)

    captured: list[dict[str, Any]] = []

    async def _fake_upsert(
        session: AsyncSession,
        *,
        key: str,
        value: Any,
        updated_by_id: Any,
        now: datetime,
    ) -> None:
        captured.append(
            {"key": key, "value": value, "updated_by_id": updated_by_id, "now": now}
        )

    monkeypatch.setattr(superuser_service, "_system_setting_upsert", _fake_upsert)

    outcome = await enter_break_glass_mode(
        db_session,
        reason="phase15-c2-test",
        actor_user_id=actor_user.id,
    )
    assert outcome.status == "applied"
    # Two rows: started_at + reason.
    assert len(captured) == 2
    for row in captured:
        # Phase 15 NO-GO C2: must be the SUPERUSER id, never the user id.
        assert row["updated_by_id"] == actor_su.id
        assert row["updated_by_id"] != actor_user.id


@pytest.mark.asyncio
async def test_enter_break_glass_skips_persist_when_actor_not_a_superuser(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When ``actor_user_id`` resolves to no active superuser, persistence
    is skipped + a warning is logged. The outcome itself still flips to
    ``applied`` so the audit trail captures the attempt."""
    foreign_user = await _create_user(db_session, email="phase15_c2_foreign@example.com")

    async def _fake_upsert(*args: Any, **kwargs: Any) -> None:  # noqa: ARG001
        pytest.fail("upsert MUST NOT be called when no active superuser resolves")

    monkeypatch.setattr(superuser_service, "_system_setting_upsert", _fake_upsert)

    with caplog.at_level("WARNING"):
        outcome = await enter_break_glass_mode(
            db_session,
            reason="phase15-c2-skip",
            actor_user_id=foreign_user.id,  # never promoted
        )
    assert outcome.status == "applied"
    assert any(
        "could not resolve an active superuser" in rec.message
        for rec in caplog.records
    )


# ---------------------------------------------------------------------------
# C3 — revoke_superuser_apply count guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoke_apply_blocks_when_only_one_active_superuser(
    db_session: AsyncSession,
) -> None:
    """Service-side defence in depth (Phase 15 NO-GO C3).

    Even though the DB trigger from migration 0012 is the primary
    block, the service raises ``LastSuperuserProtectionError`` so the
    API surface returns a clean error instead of asyncpg's raw
    ``RAISE EXCEPTION`` string.
    """
    # Wipe any pre-existing active superusers in the test DB so the
    # count-of-one precondition is deterministic.
    await db_session.execute(
        sa.update(Superuser).where(Superuser.revoked_at.is_(None)).values(
            revoked_at=datetime.now(UTC)
        )
    )
    await db_session.flush()

    only_user = await _create_user(db_session, email="phase15_c3_only@example.com")
    only_su = await _create_superuser(db_session, user=only_user)

    ticket = SuperuserApprovalRequest(
        action=ACTION_SUPERUSER_REVOKE,
        detail={
            "target_superuser_id": str(only_su.id),
            "target_user_id": str(only_user.id),
        },
        requested_by_id=only_su.id,
        approvals=[],
        status="pending",
    )
    db_session.add(ticket)
    await db_session.flush()

    with pytest.raises(LastSuperuserProtectionError):
        await revoke_superuser_apply(
            db_session,
            request=ticket,
            actor_user_id=only_user.id,
            request_id="",
            ip="",
            user_agent="",
            now=datetime.now(UTC),
        )

    # Sanity: target row was NOT mutated.
    refreshed = await db_session.get(Superuser, only_su.id)
    assert refreshed is not None
    assert refreshed.revoked_at is None


# ---------------------------------------------------------------------------
# C3 R3 race — two concurrent revoke applies cannot both leave 0 active
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoke_apply_two_concurrent_revokes_leave_one_active(
    db_session: AsyncSession,
) -> None:
    """Phase 15 R3 NO-GO C3: 2 active → 0 race must be impossible.

    Pre-R3 the BEFORE UPDATE trigger only locked the target row, so two
    concurrent revoke transactions targeting *different* superusers
    each computed ``COUNT(*) - 1 = 1`` from the pre-image of their
    sibling and passed the trigger guard, leaving zero active rows
    after both commits.

    The R3 fix adds ``pg_advisory_xact_lock(<constant>)`` at both the
    service (defence in depth → clean Python exception) and trigger
    (authoritative DB-level block) layers. This test drives a genuine
    asyncpg-level race: two engines, two sessions, ``asyncio.gather``.
    Exactly one revoke must succeed; the other must raise
    ``LastSuperuserProtectionError`` (or surface as a
    ``DBAPIError`` from the trigger when the service-side guard is
    skipped). The post-condition is ``COUNT(active) == 1``.
    """
    # Wipe any pre-existing active superusers so we start with exactly
    # the two we are about to seed.
    await db_session.execute(
        sa.update(Superuser).where(Superuser.revoked_at.is_(None)).values(
            revoked_at=datetime.now(UTC)
        )
    )
    await db_session.flush()

    a_user = await _create_user(
        db_session, email="phase15_r3_c3_a@example.com"
    )
    b_user = await _create_user(
        db_session, email="phase15_r3_c3_b@example.com"
    )
    a_su = await _create_superuser(db_session, user=a_user)
    b_su = await _create_superuser(db_session, user=b_user)

    ticket_a = SuperuserApprovalRequest(
        action=ACTION_SUPERUSER_REVOKE,
        detail={
            "target_superuser_id": str(a_su.id),
            "target_user_id": str(a_user.id),
        },
        requested_by_id=a_su.id,
        approvals=[],
        status="pending",
    )
    ticket_b = SuperuserApprovalRequest(
        action=ACTION_SUPERUSER_REVOKE,
        detail={
            "target_superuser_id": str(b_su.id),
            "target_user_id": str(b_user.id),
        },
        requested_by_id=b_su.id,
        approvals=[],
        status="pending",
    )
    db_session.add_all([ticket_a, ticket_b])
    await db_session.flush()
    await db_session.commit()

    ticket_a_id = ticket_a.id
    ticket_b_id = ticket_b.id

    # Two independent engines so each has its own asyncpg connection.
    engine_a = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    engine_b = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    factory_a = async_sessionmaker(
        engine_a, class_=AsyncSession, expire_on_commit=False
    )
    factory_b = async_sessionmaker(
        engine_b, class_=AsyncSession, expire_on_commit=False
    )

    async def _do_revoke(
        factory: Any, ticket_id: Any
    ) -> Exception | None:
        try:
            async with factory() as s:
                ticket = await s.get(SuperuserApprovalRequest, ticket_id)
                assert ticket is not None
                await revoke_superuser_apply(
                    s,
                    request=ticket,
                    actor_user_id=None,
                    request_id="",
                    ip="",
                    user_agent="",
                    now=datetime.now(UTC),
                )
                await s.commit()
            return None
        except Exception as exc:  # noqa: BLE001
            return exc

    try:
        results = await asyncio.gather(
            _do_revoke(factory_a, ticket_a_id),
            _do_revoke(factory_b, ticket_b_id),
            return_exceptions=False,
        )
    finally:
        await engine_a.dispose()
        await engine_b.dispose()

    # Exactly one revoke must succeed; the other must surface the
    # last-superuser guard. Whichever transaction loses the advisory
    # lock race observes ``active_before == 1`` at the service guard
    # and raises ``LastSuperuserProtectionError``.
    successes = [r for r in results if r is None]
    failures = [r for r in results if r is not None]
    assert len(successes) == 1, (
        f"expected exactly one successful revoke, got {results!r}"
    )
    assert len(failures) == 1, (
        f"expected exactly one failed revoke, got {results!r}"
    )
    assert isinstance(failures[0], LastSuperuserProtectionError), (
        f"expected LastSuperuserProtectionError, got {failures[0]!r}"
    )

    # Post-condition: exactly one active superuser remains. Use a fresh
    # engine because the shared ``db_session`` snapshot pre-dates the
    # parallel commits.
    verify_engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    verify_factory = async_sessionmaker(
        verify_engine, class_=AsyncSession, expire_on_commit=False
    )
    try:
        async with verify_factory() as s:
            count = await s.scalar(
                sa.select(sa.func.count())
                .select_from(Superuser)
                .where(Superuser.revoked_at.is_(None))
            )
            assert count == 1, (
                f"FR-111a violated — {count} active superusers remain "
                "after concurrent revokes (expected exactly 1)"
            )
    finally:
        await verify_engine.dispose()


# ---------------------------------------------------------------------------
# C1 race — two co-signers serialise on the FOR UPDATE lock
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approve_request_two_concurrent_approvers_serialise(
    db_session: AsyncSession,
) -> None:
    """Two concurrent approvers must NOT both observe ``approvals=[]``.

    With ``with_for_update`` the second writer blocks until the first
    commits, then re-reads ``approvals`` and sees the freshly-appended
    entry. The post-condition: exactly two distinct entries land in
    the JSONB array, status flips to ``applied`` exactly once, and
    the ticket dispatches the underlying action exactly once.
    """
    # Seed identities on the shared session; commit so the parallel
    # sessions below can see them.
    requester_user = await _create_user(db_session, email="phase15_race_req@example.com")
    a_user = await _create_user(db_session, email="phase15_race_a@example.com")
    b_user = await _create_user(db_session, email="phase15_race_b@example.com")
    target_user = await _create_user(db_session, email="phase15_race_tgt@example.com")
    requester = await _create_superuser(db_session, user=requester_user)
    a_su = await _create_superuser(db_session, user=a_user)
    b_su = await _create_superuser(db_session, user=b_user)
    target = await _create_superuser(db_session, user=target_user)

    # A fourth active superuser keeps ``active_before > 1`` so the
    # revoke_apply count guard does not fire (we are testing approve
    # serialisation, not the C3 guard).
    extra_user = await _create_user(db_session, email="phase15_race_extra@example.com")
    await _create_superuser(db_session, user=extra_user)

    ticket = SuperuserApprovalRequest(
        action=ACTION_SUPERUSER_REVOKE,
        detail={
            "target_superuser_id": str(target.id),
            "target_user_id": str(target.user_id),
        },
        requested_by_id=requester.id,
        approvals=[],
        status="pending",
    )
    db_session.add(ticket)
    await db_session.flush()
    await db_session.commit()
    ticket_id = ticket.id

    # Two independent engines so each has its own connection (genuine
    # concurrency at the asyncpg level).
    engine_a = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    engine_b = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    factory_a = async_sessionmaker(engine_a, class_=AsyncSession, expire_on_commit=False)
    factory_b = async_sessionmaker(engine_b, class_=AsyncSession, expire_on_commit=False)

    async def _approve(factory: Any, approver_id: Any) -> Exception | None:
        try:
            async with factory() as s:
                await approve_request(
                    s,
                    request_id_uuid=ticket_id,
                    approver_superuser_id=approver_id,
                )
                await s.commit()
            return None
        except Exception as exc:  # noqa: BLE001 — we want to observe outcomes
            return exc

    try:
        results = await asyncio.gather(
            _approve(factory_a, a_su.id),
            _approve(factory_b, b_su.id),
            return_exceptions=False,
        )
    finally:
        await engine_a.dispose()
        await engine_b.dispose()

    # Both must succeed — they are different approvers, so no
    # duplicate-detection error fires.
    assert results == [None, None], f"unexpected approve outcomes: {results!r}"

    # Now read the ticket back. Status should be ``applied`` (quorum
    # crossed exactly once) and the approvals array must contain
    # exactly two distinct superuser ids. We use a fresh engine for the
    # post-condition read because the shared ``db_session`` fixture
    # holds an open transaction that snapshotted the ticket BEFORE the
    # parallel approvers committed.
    verify_engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    verify_factory = async_sessionmaker(
        verify_engine, class_=AsyncSession, expire_on_commit=False
    )
    try:
        async with verify_factory() as verify_session:
            refreshed_ticket = await verify_session.get(
                SuperuserApprovalRequest, ticket_id
            )
            assert refreshed_ticket is not None
            assert refreshed_ticket.status == "applied"
            approver_ids = {
                entry["superuser_id"] for entry in refreshed_ticket.approvals
            }
            assert approver_ids == {str(a_su.id), str(b_su.id)}

            refreshed_target = await verify_session.get(Superuser, target.id)
            assert refreshed_target is not None
            assert refreshed_target.revoked_at is not None
    finally:
        await verify_engine.dispose()
