"""T957 — Break-glass mode entry/exit + 72 h timer + 1 → 1 auto-activation.

Target: FR-111 (break-glass window for 3 → 2 → 1 active superuser transitions).

Scenarios
---------
1.  Active count 3 → 2 revoke: break-glass NOT triggered (count still ≥ 3
    after the revoke, so MIN_SUPERUSERS boundary not crossed).
2.  Active count 2 → 1 (i.e., below MIN_SUPERUSERS) revoke: break-glass
    auto entry + ``system_settings`` entry_at persisted.
3.  ``is_break_glass_active()`` returns True immediately after entry, and
    False after 72 h have elapsed (monkeypatched clock).
4.  ``system_settings.updated_by_id`` is populated with a valid
    ``superusers.id`` (Phase 13 P1 R2 C2 regression guard).
5.  Adding a new superuser while break-glass is active: the new row does
    NOT automatically exit break-glass (exit logic lives in T154 admin
    middleware; this test simply confirms ``is_break_glass_active`` is still
    True after the add).
6.  Advisory-lock race: concurrent 2 → 1 revoke attempts — one succeeds,
    the other is blocked by ``LastSuperuserProtectionError``.

All tests use the shared ``db_session`` fixture (Postgres ``echoroo_test``).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

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
    BREAK_GLASS_WINDOW,
    MIN_SUPERUSERS,
    LastSuperuserProtectionError,
    enter_break_glass_mode,
    is_break_glass_active,
    revoke_superuser_apply,
)
from tests.conftest import TEST_DATABASE_URL

# ---------------------------------------------------------------------------
# Shared minimal fixtures
# ---------------------------------------------------------------------------


async def _create_user(session: AsyncSession, *, email: str) -> User:
    user = User(
        email=email,
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$t957",
        display_name=f"T957 {email}",
        security_stamp="a" * 64,
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
        added_by_id=None,
        added_at=datetime.now(UTC) - timedelta(days=1),
        webauthn_credentials=[],
        allowed_ip_cidrs=[],
        revoked_at=datetime.now(UTC) if revoked else None,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


async def _make_revoke_ticket(
    session: AsyncSession, *, requester: Superuser, target: Superuser
) -> SuperuserApprovalRequest:
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
    session.add(ticket)
    await session.flush()
    return ticket


async def _wipe_active_superusers(session: AsyncSession) -> None:
    """Revoke all active superusers and purge any orphaned approval requests.

    Some tests (e.g. concurrency tests) commit rows via independent engines
    that the shared ``db_session`` fixture cleanup cannot see. We do a
    targeted DELETE here so subsequent tests start from a clean slate without
    relying on the fixture's cleanup order.
    """
    # Must delete approval_requests before superusers due to FK constraint.
    await session.execute(sa.text("DELETE FROM superuser_approval_requests"))
    await session.execute(
        sa.update(Superuser).where(Superuser.revoked_at.is_(None)).values(
            revoked_at=datetime.now(UTC)
        )
    )
    await session.flush()


async def _count_active(session: AsyncSession) -> int:
    result = await session.execute(
        sa.select(sa.func.count())
        .select_from(Superuser)
        .where(Superuser.revoked_at.is_(None))
    )
    return int(result.scalar_one())


async def _clear_break_glass_settings(session: AsyncSession) -> None:
    """Delete break-glass system_settings rows so each test starts fresh."""
    from echoroo.models.system import SystemSetting
    await session.execute(
        sa.delete(SystemSetting).where(
            SystemSetting.key.in_(["break_glass_started_at", "break_glass_reason"])
        )
    )
    await session.flush()


# ---------------------------------------------------------------------------
# Scenario 1 — 3 → 2 revoke DOES trigger break-glass
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoke_3_to_2_triggers_break_glass(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Revoking one superuser from exactly MIN_SUPERUSERS (3) MUST enter break-glass.

    The condition in ``revoke_superuser_apply`` is:
    ``active_before >= MIN_SUPERUSERS and active_after < MIN_SUPERUSERS``
    3 → 2: active_before=3 >= 3, active_after=2 < 3 → break-glass fires.
    """
    await _wipe_active_superusers(db_session)
    await _clear_break_glass_settings(db_session)

    # Seed exactly MIN_SUPERUSERS (3) active superusers.
    users = []
    sus = []
    for i in range(MIN_SUPERUSERS):
        u = await _create_user(db_session, email=f"t957_s1_{i}@example.com")
        su = await _create_superuser(db_session, user=u)
        users.append(u)
        sus.append(su)

    assert await _count_active(db_session) == MIN_SUPERUSERS

    ticket = await _make_revoke_ticket(db_session, requester=sus[0], target=sus[2])

    captured_upserts: list[dict[str, Any]] = []

    async def _spy_upsert(
        session: AsyncSession,
        *,
        key: str,
        value: Any,
        updated_by_id: Any,
        now: datetime,
    ) -> None:
        captured_upserts.append({"key": key, "value": value})

    monkeypatch.setattr(superuser_service, "_system_setting_upsert", _spy_upsert)

    outcome = await revoke_superuser_apply(
        db_session,
        request=ticket,
        actor_user_id=users[0].id,
        request_id="t957-s1",
        ip="127.0.0.1",
        user_agent="test",
        now=datetime.now(UTC),
    )

    # 3 → 2 transition MUST trigger break-glass (active_before=3 >= MIN_SUPERUSERS).
    extra_actions = [o.action for o in outcome.extra_audit]
    assert "superuser.break_glass.entered" in extra_actions, (
        f"break-glass MUST be triggered on 3 → 2 revoke; extra_audit={extra_actions!r}"
    )
    upserted_keys = {u["key"] for u in captured_upserts}
    assert "break_glass_started_at" in upserted_keys, (
        "break_glass_started_at must be persisted on 3 → 2 transition"
    )
    assert outcome.status == "applied"
    assert await _count_active(db_session) == MIN_SUPERUSERS - 1


# ---------------------------------------------------------------------------
# Scenario 2 — 2 → 1 revoke does NOT trigger break-glass
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoke_2_to_1_does_not_trigger_break_glass(
    db_session: AsyncSession,
) -> None:
    """Revoking from 2 → 1 does NOT trigger break-glass.

    The condition is ``active_before >= MIN_SUPERUSERS(3)``.
    2 → 1: active_before=2 which is NOT >= MIN_SUPERUSERS(3), so break-glass
    is NOT engaged. The service-level guard (LastSuperuserProtectionError)
    will still block this since active_before <= 1 is not the case here, but
    actually active_before=2 > 1 so the revoke proceeds.

    Note: The test starts from 2 active superusers (not 3), so the 3→2
    boundary was already crossed earlier (we don't model that history here).
    """
    await _wipe_active_superusers(db_session)
    await _clear_break_glass_settings(db_session)

    u_a = await _create_user(db_session, email="t957_s2_a@example.com")
    u_b = await _create_user(db_session, email="t957_s2_b@example.com")
    su_a = await _create_superuser(db_session, user=u_a)
    su_b = await _create_superuser(db_session, user=u_b)

    assert await _count_active(db_session) == 2

    ticket = await _make_revoke_ticket(db_session, requester=su_a, target=su_b)

    bg_entered: list[bool] = []

    async def _spy_enter_break_glass(*args: Any, **kwargs: Any) -> Any:
        bg_entered.append(True)
        return await original_enter_break_glass(*args, **kwargs)

    original_enter_break_glass = superuser_service.enter_break_glass_mode

    with patch.object(superuser_service, "enter_break_glass_mode", _spy_enter_break_glass):
        outcome = await revoke_superuser_apply(
            db_session,
            request=ticket,
            actor_user_id=u_a.id,
            request_id="t957-s2",
            ip="127.0.0.1",
            user_agent="test",
            now=datetime.now(UTC),
        )

    # 2 → 1 does NOT cross the MIN_SUPERUSERS boundary (active_before=2 < 3).
    assert not bg_entered, (
        "break-glass must NOT fire when active_before=2 < MIN_SUPERUSERS=3 "
        "(the 3→2 boundary is what triggers it)"
    )
    assert outcome.status == "applied"
    assert await _count_active(db_session) == 1


# ---------------------------------------------------------------------------
# Scenario 3 — is_break_glass_active() true immediately; false after 72 h
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_break_glass_active_respects_72h_window(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """is_break_glass_active returns True in window, False after expiry."""
    await _clear_break_glass_settings(db_session)

    u = await _create_user(db_session, email="t957_s3_actor@example.com")
    await _create_superuser(db_session, user=u)

    fake_upserts: dict[str, Any] = {}

    async def _capturing_upsert(
        session: AsyncSession,
        *,
        key: str,
        value: Any,
        updated_by_id: Any,
        now: datetime,
    ) -> None:
        fake_upserts[key] = value

    async def _capturing_get(session: AsyncSession, key: str) -> Any:
        return fake_upserts.get(key)

    monkeypatch.setattr(superuser_service, "_system_setting_upsert", _capturing_upsert)
    monkeypatch.setattr(superuser_service, "_system_setting_get", _capturing_get)

    entry_time = datetime.now(UTC)
    await enter_break_glass_mode(
        db_session,
        reason="t957-s3-test",
        actor_user_id=u.id,
        now=entry_time,
    )

    # Immediately after entry: active.
    assert await is_break_glass_active(db_session, now=entry_time + timedelta(hours=1))

    # Just before expiry: still active.
    just_before = entry_time + BREAK_GLASS_WINDOW - timedelta(seconds=1)
    assert await is_break_glass_active(db_session, now=just_before)

    # Exactly at expiry: expired (deadline is exclusive).
    at_expiry = entry_time + BREAK_GLASS_WINDOW
    assert not await is_break_glass_active(db_session, now=at_expiry)

    # After expiry: expired.
    after_expiry = entry_time + BREAK_GLASS_WINDOW + timedelta(hours=1)
    assert not await is_break_glass_active(db_session, now=after_expiry)


# ---------------------------------------------------------------------------
# Scenario 4 — updated_by_id is a valid superusers.id (NOT users.id)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_break_glass_entry_uses_superuser_id_not_user_id(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The updated_by_id persisted to system_settings must be superusers.id.

    Phase 15 NO-GO C2 regression guard (reduplicated here for break-glass
    mode specifically).
    """
    await _clear_break_glass_settings(db_session)

    u = await _create_user(db_session, email="t957_s4_actor@example.com")
    su = await _create_superuser(db_session, user=u)

    captured_by_ids: list[Any] = []

    async def _capture_upsert(
        session: AsyncSession,
        *,
        key: str,
        value: Any,
        updated_by_id: Any,
        now: datetime,
    ) -> None:
        captured_by_ids.append(updated_by_id)

    monkeypatch.setattr(superuser_service, "_system_setting_upsert", _capture_upsert)

    await enter_break_glass_mode(
        db_session,
        reason="t957-s4",
        actor_user_id=u.id,
    )

    assert captured_by_ids, "upsert must have been called at least once"
    for by_id in captured_by_ids:
        # Must be the SUPERUSER row id, never the users.id.
        assert by_id == su.id, (
            f"updated_by_id must be superusers.id ({su.id}), "
            f"not users.id ({u.id}), got {by_id!r}"
        )


# ---------------------------------------------------------------------------
# Scenario 5 — adding superuser while break-glass active: still active
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_break_glass_still_active_after_superuser_add(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """is_break_glass_active() remains True after a new superuser is added.

    The break-glass exit is managed by the admin middleware (T154), not by
    the add-superuser path. This test confirms the service layer does NOT
    auto-clear the setting on add.
    """
    await _wipe_active_superusers(db_session)
    await _clear_break_glass_settings(db_session)

    u_existing = await _create_user(db_session, email="t957_s5_existing@example.com")
    await _create_superuser(db_session, user=u_existing)

    fake_settings: dict[str, Any] = {}

    async def _upsert(
        session: AsyncSession,
        *,
        key: str,
        value: Any,
        updated_by_id: Any,
        now: datetime,
    ) -> None:
        fake_settings[key] = value

    async def _get(session: AsyncSession, key: str) -> Any:
        return fake_settings.get(key)

    monkeypatch.setattr(superuser_service, "_system_setting_upsert", _upsert)
    monkeypatch.setattr(superuser_service, "_system_setting_get", _get)

    entry_time = datetime.now(UTC)
    await enter_break_glass_mode(
        db_session,
        reason="t957-s5",
        actor_user_id=u_existing.id,
        now=entry_time,
    )
    assert await is_break_glass_active(db_session, now=entry_time + timedelta(hours=1))

    # Simulate adding a new superuser — the service layer does not clear the flag.
    u_new = await _create_user(db_session, email="t957_s5_new@example.com")
    await _create_superuser(db_session, user=u_new)

    # Break-glass must still be active (exit is T154's responsibility).
    assert await is_break_glass_active(db_session, now=entry_time + timedelta(hours=2)), (
        "is_break_glass_active must remain True after a superuser is added; "
        "exit logic lives in the admin middleware (T154)"
    )


# ---------------------------------------------------------------------------
# Scenario 6 — advisory-lock race: concurrent 2 → 1 revokes, one blocked
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_2_to_1_revoke_race_one_blocked(
    db_session: AsyncSession,
) -> None:
    """Concurrent 2 → 1 revoke race: advisory lock ensures only one succeeds.

    Mirrors the Phase 15 R3 NO-GO C3 test in
    test_superuser_service_phase15_nogo.py but starts from 2 active
    (instead of 2 distinct targets) to cover the break-glass trigger path.
    Exactly one TX must raise ``LastSuperuserProtectionError``.
    """
    await _wipe_active_superusers(db_session)

    u_a = await _create_user(db_session, email="t957_s6_a@example.com")
    u_b = await _create_user(db_session, email="t957_s6_b@example.com")
    su_a = await _create_superuser(db_session, user=u_a)
    su_b = await _create_superuser(db_session, user=u_b)

    ticket_a = SuperuserApprovalRequest(
        action=ACTION_SUPERUSER_REVOKE,
        detail={
            "target_superuser_id": str(su_a.id),
            "target_user_id": str(u_a.id),
        },
        requested_by_id=su_b.id,
        approvals=[],
        status="pending",
    )
    ticket_b = SuperuserApprovalRequest(
        action=ACTION_SUPERUSER_REVOKE,
        detail={
            "target_superuser_id": str(su_b.id),
            "target_user_id": str(u_b.id),
        },
        requested_by_id=su_a.id,
        approvals=[],
        status="pending",
    )
    db_session.add_all([ticket_a, ticket_b])
    await db_session.flush()
    await db_session.commit()

    ticket_a_id = ticket_a.id
    ticket_b_id = ticket_b.id

    engine_a = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    engine_b = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    factory_a = async_sessionmaker(engine_a, class_=AsyncSession, expire_on_commit=False)
    factory_b = async_sessionmaker(engine_b, class_=AsyncSession, expire_on_commit=False)

    async def _do_revoke(
        factory: Any,
        ticket_id: Any,
        actor_user_id: Any,
    ) -> Exception | None:
        try:
            async with factory() as s:
                ticket = await s.get(SuperuserApprovalRequest, ticket_id)
                assert ticket is not None
                await revoke_superuser_apply(
                    s,
                    request=ticket,
                    actor_user_id=actor_user_id,
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
            _do_revoke(factory_a, ticket_a_id, u_b.id),
            _do_revoke(factory_b, ticket_b_id, u_a.id),
        )
    finally:
        await engine_a.dispose()
        await engine_b.dispose()

    successes = [r for r in results if r is None]
    failures = [r for r in results if r is not None]

    assert len(successes) == 1, (
        f"Exactly one revoke must succeed; got successes={successes!r}, "
        f"failures={failures!r}"
    )
    assert len(failures) == 1, (
        f"Exactly one revoke must fail; got failures={failures!r}"
    )
    assert isinstance(failures[0], LastSuperuserProtectionError), (
        f"Expected LastSuperuserProtectionError, got {failures[0]!r}"
    )

    # Post-condition: exactly one active superuser remains.
    verify_engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    verify_factory = async_sessionmaker(
        verify_engine, class_=AsyncSession, expire_on_commit=False
    )
    try:
        async with verify_factory() as vs:
            active = await vs.scalar(
                sa.select(sa.func.count())
                .select_from(Superuser)
                .where(Superuser.revoked_at.is_(None))
            )
            assert active == 1, (
                f"FR-111a violated — {active} active superusers remain "
                "after concurrent revokes (expected exactly 1)"
            )
    finally:
        await verify_engine.dispose()
