"""Phase 17 §D-1 mutation uplift — ``echoroo.services.superuser_service``.

Targets the two functions that concentrate the surviving mutants from the
PR #53 real mutation baseline (CI run 25592148927):

* ``enter_break_glass_mode`` (71 of 130 survivors, 55%)
* ``approve_request`` (25 of 130 survivors, 19%)
* ``is_break_glass_active`` (16 of 130 survivors, 12%) — opportunistic

Each test below pins a specific behavioural fact the production code MUST
preserve so a typical mutmut mutation (boundary swap, boolean flip,
constant rewrite, return path drop, branch-elision) is killed by the
assertion.

Test style follows the existing
``tests/unit/services/test_superuser_service_phase15_nogo.py``: a real
Postgres ``echoroo_test`` session via the shared ``db_session`` fixture,
minimal ad-hoc helpers, and ``monkeypatch.setattr`` to stub the upsert /
get internals when probing dispatch payloads.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.superuser import Superuser
from echoroo.models.superuser_approval_request import SuperuserApprovalRequest
from echoroo.models.system import SystemSetting
from echoroo.models.user import User
from echoroo.services import superuser_service
from echoroo.services.superuser_service import (
    ACTION_BACKUP_CODE_RESET,
    ACTION_SUPERUSER_ADD,
    ACTION_SUPERUSER_REVOKE,
    ACTION_TWO_FACTOR_RESET_SKIP_DELAY,
    BREAK_GLASS_REPLACEMENT_DEADLINE,
    BREAK_GLASS_WINDOW,
    MIN_APPROVALS,
    ApprovalRequestNotFoundError,
    ApprovalRequestStateError,
    DuplicateApprovalError,
    NotSuperuserError,
    approve_request,
    enter_break_glass_mode,
    is_break_glass_active,
)

# ---------------------------------------------------------------------------
# Helpers — kept local so the test file is self-contained.
# ---------------------------------------------------------------------------


async def _create_user(session: AsyncSession, *, email: str) -> User:
    user = User(
        email=email,
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$d1uplift",
        display_name=f"D1 Uplift {email}",
        security_stamp="d" * 64,
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


async def _wipe_break_glass_settings(session: AsyncSession) -> None:
    """Remove any pre-existing break-glass settings so each test starts clean."""
    await session.execute(
        sa.delete(SystemSetting).where(
            SystemSetting.key.in_(
                ["break_glass_started_at", "break_glass_reason"]
            )
        )
    )
    await session.flush()


# ===========================================================================
# enter_break_glass_mode — 71 surviving mutants concentration
# ===========================================================================


@pytest.mark.asyncio
async def test_enter_break_glass_window_hours_constant_is_72(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kills constant mutants on ``BREAK_GLASS_WINDOW`` / ``window_hours``.

    The detail JSONB carries ``window_hours`` derived from
    ``BREAK_GLASS_WINDOW.total_seconds() // 3600``. Any constant rewrite
    (``//`` -> ``/``, 3600 -> 60, ``BREAK_GLASS_WINDOW`` -> a different
    timedelta) shifts this off 72.
    """
    await _wipe_break_glass_settings(db_session)
    actor = await _create_user(db_session, email="d1_window_hours@example.com")
    await _create_superuser(db_session, user=actor)

    async def _stub_upsert(*args: Any, **kwargs: Any) -> None:  # noqa: ARG001
        return None

    monkeypatch.setattr(superuser_service, "_system_setting_upsert", _stub_upsert)

    outcome = await enter_break_glass_mode(
        db_session,
        reason="window-hours probe",
        actor_user_id=actor.id,
    )
    assert outcome.detail["window_hours"] == 72
    assert outcome.detail["window_hours"] == int(
        BREAK_GLASS_WINDOW.total_seconds() // 3600
    )


@pytest.mark.asyncio
async def test_enter_break_glass_replacement_deadline_hours_is_24(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kills constant mutants on ``BREAK_GLASS_REPLACEMENT_DEADLINE``."""
    await _wipe_break_glass_settings(db_session)
    actor = await _create_user(db_session, email="d1_repl_hours@example.com")
    await _create_superuser(db_session, user=actor)

    async def _stub_upsert(*args: Any, **kwargs: Any) -> None:  # noqa: ARG001
        return None

    monkeypatch.setattr(superuser_service, "_system_setting_upsert", _stub_upsert)

    outcome = await enter_break_glass_mode(
        db_session,
        reason="replacement-deadline probe",
        actor_user_id=actor.id,
    )
    assert outcome.detail["replacement_deadline_hours"] == 24
    assert outcome.detail["replacement_deadline_hours"] == int(
        BREAK_GLASS_REPLACEMENT_DEADLINE.total_seconds() // 3600
    )


@pytest.mark.asyncio
async def test_enter_break_glass_audit_action_label_is_break_glass_entered(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kills string-constant mutation on ``_AUDIT_ACTION_BREAK_GLASS_ENTERED``.

    A typical mutation rewrites ``"superuser.break_glass.entered"`` to a
    different label. Asserting the exact substring + suffix locks it.
    """
    await _wipe_break_glass_settings(db_session)
    actor = await _create_user(db_session, email="d1_action_label@example.com")
    await _create_superuser(db_session, user=actor)

    async def _stub_upsert(*args: Any, **kwargs: Any) -> None:  # noqa: ARG001
        return None

    monkeypatch.setattr(superuser_service, "_system_setting_upsert", _stub_upsert)

    outcome = await enter_break_glass_mode(
        db_session, reason="action-label probe", actor_user_id=actor.id
    )
    assert outcome.action == "superuser.break_glass.entered"
    assert outcome.action.startswith("superuser.")
    assert outcome.action.endswith(".entered")


@pytest.mark.asyncio
async def test_enter_break_glass_idempotent_keeps_original_started_at(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kills branch-elision on ``if existing_started is not None``.

    Spec: a subsequent call inside the active window must NOT overwrite
    ``started_at`` — the 72 h clock keeps ticking from the original
    incident, not the latest event. The mutation that swaps the guard
    (``is not None`` -> ``is None``) would clobber the timestamp; we
    assert detail.already_active=True + started_at preserved.
    """
    await _wipe_break_glass_settings(db_session)
    actor = await _create_user(db_session, email="d1_idem@example.com")
    actor_su = await _create_superuser(db_session, user=actor)

    upsert_calls: list[dict[str, Any]] = []

    async def _capture_upsert(
        session: AsyncSession,
        *,
        key: str,
        value: Any,
        updated_by_id: Any,
        now: datetime,
    ) -> None:
        upsert_calls.append({"key": key, "value": value})

    monkeypatch.setattr(
        superuser_service, "_system_setting_upsert", _capture_upsert
    )

    first_now = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    # Persist the started_at marker directly so the next
    # ``enter_break_glass_mode`` call observes the active window. We do
    # NOT call ``enter_break_glass_mode`` first because that would
    # require unpatching the stubbed upsert.
    db_session.add(
        SystemSetting(
            key="break_glass_started_at",
            value=first_now.isoformat(),
            updated_at=first_now,
            updated_by_id=actor_su.id,
        )
    )
    await db_session.flush()

    later_now = first_now + timedelta(hours=5)
    second = await enter_break_glass_mode(
        db_session,
        reason="second-call-while-active",
        actor_user_id=actor.id,
        now=later_now,
    )
    assert second.detail["already_active"] is True
    # The original timestamp must surface in detail (not the later one).
    assert first_now.isoformat() in str(second.detail["started_at"])
    # And NO upsert may fire on the idempotent path.
    assert upsert_calls == []


@pytest.mark.asyncio
async def test_enter_break_glass_first_call_marks_already_active_false(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kills boolean-flip mutants — first call must NOT carry already_active=True.

    The fresh-window detail dict carries ``window_hours`` /
    ``replacement_deadline_hours`` but NOT ``already_active``. A
    branch-swap mutation that funnels the fresh path through the
    idempotent return would surface ``already_active=True``.
    """
    await _wipe_break_glass_settings(db_session)
    actor = await _create_user(db_session, email="d1_first_call@example.com")
    await _create_superuser(db_session, user=actor)

    async def _stub_upsert(*args: Any, **kwargs: Any) -> None:  # noqa: ARG001
        return None

    monkeypatch.setattr(superuser_service, "_system_setting_upsert", _stub_upsert)

    outcome = await enter_break_glass_mode(
        db_session, reason="fresh", actor_user_id=actor.id
    )
    assert "already_active" not in outcome.detail
    assert "window_hours" in outcome.detail
    assert "replacement_deadline_hours" in outcome.detail
    assert outcome.after == {"break_glass_active": True}


@pytest.mark.asyncio
async def test_enter_break_glass_persists_started_at_and_reason_keys(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kills set-membership / string-constant mutants on ``system_settings`` keys.

    Both ``break_glass_started_at`` AND ``break_glass_reason`` rows must
    be persisted on the fresh path. A mutation that drops one upsert
    call or swaps the key constant would fail the assertion.
    """
    await _wipe_break_glass_settings(db_session)
    actor = await _create_user(db_session, email="d1_keys@example.com")
    await _create_superuser(db_session, user=actor)

    captured: list[dict[str, Any]] = []

    async def _capture(
        session: AsyncSession,
        *,
        key: str,
        value: Any,
        updated_by_id: Any,
        now: datetime,
    ) -> None:
        captured.append({"key": key, "value": value})

    monkeypatch.setattr(superuser_service, "_system_setting_upsert", _capture)

    await enter_break_glass_mode(
        db_session, reason="keys probe", actor_user_id=actor.id
    )
    keys = {entry["key"] for entry in captured}
    assert keys == {"break_glass_started_at", "break_glass_reason"}
    # Confirm reason value was forwarded verbatim (kills value-swap mutation).
    reason_entry = next(e for e in captured if e["key"] == "break_glass_reason")
    assert reason_entry["value"] == "keys probe"


@pytest.mark.asyncio
async def test_enter_break_glass_uses_now_argument_when_supplied(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kills ``now or datetime.now(UTC)`` short-circuit mutation.

    When a caller provides ``now=fixed_dt``, the persisted ``started_at``
    must equal ``fixed_dt.isoformat()`` rather than wall-clock time.
    """
    await _wipe_break_glass_settings(db_session)
    actor = await _create_user(db_session, email="d1_now_arg@example.com")
    await _create_superuser(db_session, user=actor)

    captured: list[dict[str, Any]] = []

    async def _capture(
        session: AsyncSession,
        *,
        key: str,
        value: Any,
        updated_by_id: Any,
        now: datetime,
    ) -> None:
        captured.append({"key": key, "value": value, "now": now})

    monkeypatch.setattr(superuser_service, "_system_setting_upsert", _capture)

    fixed = datetime(2026, 6, 15, 12, 30, 0, tzinfo=UTC)
    outcome = await enter_break_glass_mode(
        db_session,
        reason="fixed-now",
        actor_user_id=actor.id,
        now=fixed,
    )
    # detail.started_at and outcome.created_at must trace back to ``fixed``.
    assert outcome.detail["started_at"] == fixed.isoformat()
    assert outcome.created_at == fixed
    started = next(e for e in captured if e["key"] == "break_glass_started_at")
    assert started["value"] == fixed.isoformat()
    assert started["now"] == fixed


@pytest.mark.asyncio
async def test_enter_break_glass_status_is_applied_string(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kills string-constant mutation on ``status='applied'`` return value."""
    await _wipe_break_glass_settings(db_session)
    actor = await _create_user(db_session, email="d1_status@example.com")
    await _create_superuser(db_session, user=actor)

    async def _stub_upsert(*args: Any, **kwargs: Any) -> None:  # noqa: ARG001
        return None

    monkeypatch.setattr(superuser_service, "_system_setting_upsert", _stub_upsert)

    outcome = await enter_break_glass_mode(
        db_session, reason="status probe", actor_user_id=actor.id
    )
    assert outcome.status == "applied"
    assert outcome.status != "pending"
    assert outcome.status != "rejected"
    assert outcome.status != "direct"


@pytest.mark.asyncio
async def test_enter_break_glass_envelope_carries_request_id_ip_user_agent(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kills mutations that drop or swap HTTP envelope fields.

    The audit envelope's ``request_id`` / ``ip`` / ``user_agent`` MUST
    pass through unchanged so the platform_audit_log row carries the
    correlation triple.
    """
    await _wipe_break_glass_settings(db_session)
    actor = await _create_user(db_session, email="d1_envelope@example.com")
    await _create_superuser(db_session, user=actor)

    async def _stub_upsert(*args: Any, **kwargs: Any) -> None:  # noqa: ARG001
        return None

    monkeypatch.setattr(superuser_service, "_system_setting_upsert", _stub_upsert)

    outcome = await enter_break_glass_mode(
        db_session,
        reason="envelope probe",
        actor_user_id=actor.id,
        request_id="rid-d1-001",
        ip="192.0.2.42",
        user_agent="agent/x.y",
    )
    assert outcome.request_id == "rid-d1-001"
    assert outcome.ip == "192.0.2.42"
    assert outcome.user_agent == "agent/x.y"


@pytest.mark.asyncio
async def test_enter_break_glass_idempotent_envelope_also_carries_correlation(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kills correlation-drop mutation on the idempotent return path.

    The early-return inside the ``existing_started is not None`` branch
    must propagate request_id / ip / user_agent so dashboards can
    correlate the duplicate-entry audit row to the originating HTTP
    call.
    """
    await _wipe_break_glass_settings(db_session)
    actor = await _create_user(db_session, email="d1_idem_envelope@example.com")
    actor_su = await _create_superuser(db_session, user=actor)

    fixed = datetime(2026, 7, 1, 0, 0, 0, tzinfo=UTC)
    # Pre-populate the started_at marker so the idempotent branch runs.
    db_session.add(
        SystemSetting(
            key="break_glass_started_at",
            value=fixed.isoformat(),
            updated_at=fixed,
            updated_by_id=actor_su.id,
        )
    )
    await db_session.flush()

    async def _stub_upsert(*args: Any, **kwargs: Any) -> None:  # noqa: ARG001
        pytest.fail("idempotent path must not call _system_setting_upsert")

    monkeypatch.setattr(superuser_service, "_system_setting_upsert", _stub_upsert)

    outcome = await enter_break_glass_mode(
        db_session,
        reason="idem-envelope",
        actor_user_id=actor.id,
        request_id="rid-d1-002",
        ip="198.51.100.7",
        user_agent="agent/idem",
    )
    assert outcome.request_id == "rid-d1-002"
    assert outcome.ip == "198.51.100.7"
    assert outcome.user_agent == "agent/idem"
    assert outcome.action == "superuser.break_glass.entered"


@pytest.mark.asyncio
async def test_enter_break_glass_actor_user_id_none_skips_upsert(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Kills branch-flip on ``superuser_id is None`` skip-or-write decision.

    Distinct from the existing ``...skips_persist_when_actor_not_a_superuser``
    test: here ``actor_user_id`` itself is ``None`` (e.g. system-driven
    break-glass via cron), exercising the early-return inside
    ``_resolve_active_superuser_id``. A mutation that flips
    ``if superuser_id is None`` to ``is not None`` would either crash on
    the FK or silently miswrite.
    """
    await _wipe_break_glass_settings(db_session)

    async def _stub_upsert(*args: Any, **kwargs: Any) -> None:  # noqa: ARG001
        pytest.fail("upsert must not be called when actor_user_id is None")

    monkeypatch.setattr(superuser_service, "_system_setting_upsert", _stub_upsert)

    with caplog.at_level("WARNING"):
        outcome = await enter_break_glass_mode(
            db_session,
            reason="system-driven",
            actor_user_id=None,
        )
    assert outcome.status == "applied"
    # The reason still surfaces in the outcome detail even though no row
    # is persisted.
    assert outcome.detail["reason"] == "system-driven"
    assert any("could not resolve" in rec.message for rec in caplog.records)


# ===========================================================================
# is_break_glass_active — 16 surviving mutants
# ===========================================================================


@pytest.mark.asyncio
async def test_is_break_glass_active_returns_false_when_setting_absent(
    db_session: AsyncSession,
) -> None:
    """Kills branch-flip on the ``raw is None`` early return."""
    await _wipe_break_glass_settings(db_session)
    assert await is_break_glass_active(db_session) is False


@pytest.mark.asyncio
async def test_is_break_glass_active_handles_invalid_iso_string(
    db_session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Kills exception-handler removal mutation.

    A garbage value in ``system_settings.break_glass_started_at`` must
    NOT propagate ``ValueError`` — the helper logs a warning + returns
    ``False`` so admin middleware fails-open (FR-088 soft alert).
    """
    await _wipe_break_glass_settings(db_session)
    actor = await _create_user(db_session, email="d1_isactive_bad@example.com")
    actor_su = await _create_superuser(db_session, user=actor)
    db_session.add(
        SystemSetting(
            key="break_glass_started_at",
            value="not-a-date",
            updated_at=datetime.now(UTC),
            updated_by_id=actor_su.id,
        )
    )
    await db_session.flush()

    with caplog.at_level("WARNING"):
        result = await is_break_glass_active(db_session)
    assert result is False
    assert any("not a valid ISO datetime" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "delta_hours, expected",
    [
        (0, True),  # exactly at start
        (1, True),  # well inside the 72 h window
        (71, True),  # 1 h before deadline — still active
        (72, False),  # exactly at deadline — closed (strict ``<``)
        (73, False),  # past deadline
    ],
)
async def test_is_break_glass_active_boundary_hours(
    db_session: AsyncSession,
    delta_hours: int,
    expected: bool,
) -> None:
    """Kills boundary-comparison mutants on ``now < deadline``.

    The 72 h window is half-open: ``[started_at, started_at + 72h)``.
    Mutmut typically rewrites ``<`` -> ``<=`` (would flip ``72``) or
    swaps the operands; the parametrised boundaries lock the intended
    semantics.
    """
    await _wipe_break_glass_settings(db_session)
    actor = await _create_user(
        db_session,
        email=f"d1_isactive_bound_{delta_hours}@example.com",
    )
    actor_su = await _create_superuser(db_session, user=actor)
    started = datetime(2026, 3, 1, 0, 0, 0, tzinfo=UTC)
    db_session.add(
        SystemSetting(
            key="break_glass_started_at",
            value=started.isoformat(),
            updated_at=started,
            updated_by_id=actor_su.id,
        )
    )
    await db_session.flush()

    probe = started + timedelta(hours=delta_hours)
    assert await is_break_glass_active(db_session, now=probe) is expected


@pytest.mark.asyncio
async def test_is_break_glass_active_assumes_utc_when_naive_iso(
    db_session: AsyncSession,
) -> None:
    """Kills branch-elision on ``if started_at.tzinfo is None`` UTC backfill.

    A timestamp persisted without tzinfo must be treated as UTC, not
    raise on naive-vs-aware comparison.
    """
    await _wipe_break_glass_settings(db_session)
    actor = await _create_user(db_session, email="d1_isactive_naive@example.com")
    actor_su = await _create_superuser(db_session, user=actor)
    naive = datetime(2026, 4, 1, 0, 0, 0)  # no tzinfo
    db_session.add(
        SystemSetting(
            key="break_glass_started_at",
            value=naive.isoformat(),
            updated_at=datetime.now(UTC),
            updated_by_id=actor_su.id,
        )
    )
    await db_session.flush()

    probe = datetime(2026, 4, 1, 1, 0, 0, tzinfo=UTC)  # 1 h later
    assert await is_break_glass_active(db_session, now=probe) is True


# ===========================================================================
# approve_request — 25 surviving mutants concentration
# ===========================================================================


@pytest.mark.asyncio
async def test_approve_request_unknown_ticket_raises_not_found(
    db_session: AsyncSession,
) -> None:
    """Kills exception-class swap on the missing-row branch."""
    requester = await _create_user(db_session, email="d1_unknown_req@example.com")
    approver = await _create_user(db_session, email="d1_unknown_app@example.com")
    await _create_superuser(db_session, user=requester)
    approver_su = await _create_superuser(db_session, user=approver)

    from uuid import uuid4

    with pytest.raises(ApprovalRequestNotFoundError):
        await approve_request(
            db_session,
            request_id_uuid=uuid4(),
            approver_superuser_id=approver_su.id,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["applied", "rejected"])
async def test_approve_request_non_pending_status_raises_state_error(
    db_session: AsyncSession,
    status: str,
) -> None:
    """Kills equality flip on ``request.status != 'pending'`` guard.

    A mutation that swaps ``!=`` -> ``==`` (or compares to a different
    literal) would let ``applied`` / ``rejected`` tickets accept fresh
    approvals. Both terminal statuses must raise.
    """
    requester = await _create_user(
        db_session, email=f"d1_state_{status}_req@example.com"
    )
    approver = await _create_user(
        db_session, email=f"d1_state_{status}_app@example.com"
    )
    target = await _create_user(
        db_session, email=f"d1_state_{status}_tgt@example.com"
    )
    requester_su = await _create_superuser(db_session, user=requester)
    approver_su = await _create_superuser(db_session, user=approver)
    target_su = await _create_superuser(db_session, user=target)

    ticket = SuperuserApprovalRequest(
        action=ACTION_SUPERUSER_REVOKE,
        detail={
            "target_superuser_id": str(target_su.id),
            "target_user_id": str(target_su.user_id),
        },
        requested_by_id=requester_su.id,
        approvals=[],
        status=status,
        executed_at=datetime.now(UTC),
    )
    db_session.add(ticket)
    await db_session.flush()

    with pytest.raises(ApprovalRequestStateError):
        await approve_request(
            db_session,
            request_id_uuid=ticket.id,
            approver_superuser_id=approver_su.id,
        )


@pytest.mark.asyncio
async def test_approve_request_first_approval_keeps_status_pending(
    db_session: AsyncSession,
) -> None:
    """Kills boundary mutation on ``len(approvals) < MIN_APPROVALS``.

    With MIN_APPROVALS=2, the FIRST approval (``len`` becomes 1) must
    leave status=pending and NOT dispatch. Boundary swaps (``<`` -> ``<=``)
    would mis-classify the threshold.
    """
    requester = await _create_user(db_session, email="d1_first_req@example.com")
    approver = await _create_user(db_session, email="d1_first_app@example.com")
    target = await _create_user(db_session, email="d1_first_tgt@example.com")
    requester_su = await _create_superuser(db_session, user=requester)
    approver_su = await _create_superuser(db_session, user=approver)
    target_su = await _create_superuser(db_session, user=target)

    ticket = SuperuserApprovalRequest(
        action=ACTION_SUPERUSER_REVOKE,
        detail={
            "target_superuser_id": str(target_su.id),
            "target_user_id": str(target_su.user_id),
        },
        requested_by_id=requester_su.id,
        approvals=[],
        status="pending",
    )
    db_session.add(ticket)
    await db_session.flush()

    outcome = await approve_request(
        db_session,
        request_id_uuid=ticket.id,
        approver_superuser_id=approver_su.id,
    )
    assert outcome.status == "pending"
    assert outcome.action == "superuser.approval.approved"
    assert outcome.detail["approvals_count"] == 1
    assert outcome.detail["min_approvals"] == MIN_APPROVALS
    assert outcome.detail["min_approvals"] == 2  # constant-mutation kill
    assert outcome.detail["action"] == ACTION_SUPERUSER_REVOKE
    # Ticket row itself was NOT advanced.
    refreshed = await db_session.get(SuperuserApprovalRequest, ticket.id)
    assert refreshed is not None
    assert refreshed.status == "pending"
    assert refreshed.executed_at is None


@pytest.mark.asyncio
async def test_approve_request_records_approver_with_isoformat_timestamp(
    db_session: AsyncSession,
) -> None:
    """Kills mutations on the JSONB approval entry shape.

    The persisted entry must carry both ``superuser_id`` and
    ``approved_at`` (ISO-format string). A mutation that drops the
    timestamp key or stores ``now`` (a datetime, not str) would
    fail the assertions.
    """
    requester = await _create_user(db_session, email="d1_record_req@example.com")
    approver = await _create_user(db_session, email="d1_record_app@example.com")
    target = await _create_user(db_session, email="d1_record_tgt@example.com")
    requester_su = await _create_superuser(db_session, user=requester)
    approver_su = await _create_superuser(db_session, user=approver)
    target_su = await _create_superuser(db_session, user=target)

    ticket = SuperuserApprovalRequest(
        action=ACTION_SUPERUSER_REVOKE,
        detail={
            "target_superuser_id": str(target_su.id),
            "target_user_id": str(target_su.user_id),
        },
        requested_by_id=requester_su.id,
        approvals=[],
        status="pending",
    )
    db_session.add(ticket)
    await db_session.flush()

    await approve_request(
        db_session,
        request_id_uuid=ticket.id,
        approver_superuser_id=approver_su.id,
    )
    refreshed = await db_session.get(SuperuserApprovalRequest, ticket.id)
    assert refreshed is not None
    assert len(refreshed.approvals) == 1
    entry = refreshed.approvals[0]
    assert entry["superuser_id"] == str(approver_su.id)
    assert isinstance(entry["approved_at"], str)
    # ISO timestamps round-trip via fromisoformat.
    parsed = datetime.fromisoformat(entry["approved_at"])
    assert parsed.tzinfo is not None  # UTC marker present


@pytest.mark.asyncio
async def test_approve_request_quorum_dispatches_revoke(
    db_session: AsyncSession,
) -> None:
    """Kills branch-routing mutations for ``ACTION_SUPERUSER_REVOKE`` dispatch.

    Once 2 approvals land, the ticket must flip to ``applied`` and the
    target's ``revoked_at`` must be set. A mutation that misroutes the
    action string would skip the revoke side effect.
    """
    # Need 4 active superusers so revoke_apply does not trip the count guard.
    users = []
    sus = []
    for tag in ("req", "a", "b", "tgt", "extra"):
        u = await _create_user(
            db_session, email=f"d1_q_revoke_{tag}@example.com"
        )
        users.append(u)
        sus.append(await _create_superuser(db_session, user=u))
    requester_su, a_su, b_su, target_su, _extra = sus

    ticket = SuperuserApprovalRequest(
        action=ACTION_SUPERUSER_REVOKE,
        detail={
            "target_superuser_id": str(target_su.id),
            "target_user_id": str(target_su.user_id),
        },
        requested_by_id=requester_su.id,
        approvals=[],
        status="pending",
    )
    db_session.add(ticket)
    await db_session.flush()

    await approve_request(
        db_session,
        request_id_uuid=ticket.id,
        approver_superuser_id=a_su.id,
    )
    second = await approve_request(
        db_session,
        request_id_uuid=ticket.id,
        approver_superuser_id=b_su.id,
    )
    assert second.status == "applied"
    assert second.action == "superuser.revoke.applied"
    refreshed = await db_session.get(SuperuserApprovalRequest, ticket.id)
    assert refreshed is not None
    assert refreshed.status == "applied"
    assert refreshed.executed_at is not None
    refreshed_target = await db_session.get(Superuser, target_su.id)
    assert refreshed_target is not None
    assert refreshed_target.revoked_at is not None


@pytest.mark.asyncio
async def test_approve_request_quorum_dispatches_add(
    db_session: AsyncSession,
) -> None:
    """Kills branch-routing mutations for ``ACTION_SUPERUSER_ADD`` dispatch.

    Tests that the add-apply path is reached (and creates the new
    superusers row) when the quorum lands on a ``superuser.add`` ticket.
    """
    # Existing 3+ active superusers required so the add ticket path is
    # exercised (rather than the genesis direct-insert).
    requester = await _create_user(db_session, email="d1_q_add_req@example.com")
    a = await _create_user(db_session, email="d1_q_add_a@example.com")
    b = await _create_user(db_session, email="d1_q_add_b@example.com")
    extra = await _create_user(db_session, email="d1_q_add_extra@example.com")
    target = await _create_user(db_session, email="d1_q_add_target@example.com")
    requester_su = await _create_superuser(db_session, user=requester)
    a_su = await _create_superuser(db_session, user=a)
    b_su = await _create_superuser(db_session, user=b)
    await _create_superuser(db_session, user=extra)

    ticket = SuperuserApprovalRequest(
        action=ACTION_SUPERUSER_ADD,
        detail={
            "target_user_id": str(target.id),
            "webauthn_credentials": [],
            "allowed_ip_cidrs": [],
        },
        requested_by_id=requester_su.id,
        approvals=[],
        status="pending",
    )
    db_session.add(ticket)
    await db_session.flush()

    await approve_request(
        db_session,
        request_id_uuid=ticket.id,
        approver_superuser_id=a_su.id,
    )
    second = await approve_request(
        db_session,
        request_id_uuid=ticket.id,
        approver_superuser_id=b_su.id,
    )
    assert second.status == "applied"
    assert second.action == "superuser.add.applied"
    assert second.superuser_id is not None
    # Newly-added row exists, active and references the right user.
    new_row = await db_session.get(Superuser, second.superuser_id)
    assert new_row is not None
    assert new_row.user_id == target.id
    assert new_row.revoked_at is None


@pytest.mark.asyncio
async def test_approve_request_generic_action_returns_dispatched_false(
    db_session: AsyncSession,
) -> None:
    """Kills boolean-flip on the generic-dispatch ``dispatched=False`` payload.

    Actions outside the engine's domain (e.g. ``backup_code_reset``) flip
    ``status=applied`` but do NOT execute a side effect inside this
    module — the detail must surface ``dispatched=False`` so the
    orchestrator knows it owns the dispatch.
    """
    requester = await _create_user(db_session, email="d1_generic_req@example.com")
    a = await _create_user(db_session, email="d1_generic_a@example.com")
    b = await _create_user(db_session, email="d1_generic_b@example.com")
    extra = await _create_user(db_session, email="d1_generic_extra@example.com")
    requester_su = await _create_superuser(db_session, user=requester)
    a_su = await _create_superuser(db_session, user=a)
    b_su = await _create_superuser(db_session, user=b)
    await _create_superuser(db_session, user=extra)

    ticket = SuperuserApprovalRequest(
        action=ACTION_BACKUP_CODE_RESET,
        detail={"target_user_id": str(requester.id)},
        requested_by_id=requester_su.id,
        approvals=[],
        status="pending",
    )
    db_session.add(ticket)
    await db_session.flush()

    await approve_request(
        db_session,
        request_id_uuid=ticket.id,
        approver_superuser_id=a_su.id,
    )
    second = await approve_request(
        db_session,
        request_id_uuid=ticket.id,
        approver_superuser_id=b_su.id,
    )
    assert second.status == "applied"
    assert second.action == "superuser.approval.approved"
    assert second.detail["dispatched"] is False
    assert second.detail["action"] == ACTION_BACKUP_CODE_RESET
    assert second.detail["approvals_count"] == 2
    refreshed = await db_session.get(SuperuserApprovalRequest, ticket.id)
    assert refreshed is not None
    assert refreshed.status == "applied"
    assert refreshed.executed_at is not None


@pytest.mark.asyncio
async def test_approve_request_two_factor_reset_dispatch_calls_hook(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kills branch-routing + dispatched=True mutation for the A-11 2FA path.

    Patches ``two_factor_reset_service.mark_approved_after_quorum`` to a
    stub so we can assert it (and only it) is called when quorum lands
    on a ``two_factor_reset.skip_delay`` ticket. The detail must
    surface ``dispatched=True`` (distinct from the generic path).
    """
    requester = await _create_user(db_session, email="d1_2fa_req@example.com")
    a = await _create_user(db_session, email="d1_2fa_a@example.com")
    b = await _create_user(db_session, email="d1_2fa_b@example.com")
    extra = await _create_user(db_session, email="d1_2fa_extra@example.com")
    requester_su = await _create_superuser(db_session, user=requester)
    a_su = await _create_superuser(db_session, user=a)
    b_su = await _create_superuser(db_session, user=b)
    await _create_superuser(db_session, user=extra)

    calls: list[dict[str, Any]] = []

    async def _stub_mark_approved(
        session: AsyncSession,
        *,
        approval_request_id: Any,
        now: datetime,
    ) -> None:
        calls.append({"approval_request_id": approval_request_id, "now": now})

    from echoroo.services import two_factor_reset_service

    monkeypatch.setattr(
        two_factor_reset_service,
        "mark_approved_after_quorum",
        _stub_mark_approved,
    )

    ticket = SuperuserApprovalRequest(
        action=ACTION_TWO_FACTOR_RESET_SKIP_DELAY,
        detail={"two_factor_reset_request_id": "irrelevant"},
        requested_by_id=requester_su.id,
        approvals=[],
        status="pending",
    )
    db_session.add(ticket)
    await db_session.flush()

    await approve_request(
        db_session,
        request_id_uuid=ticket.id,
        approver_superuser_id=a_su.id,
    )
    assert calls == []  # Only at quorum
    second = await approve_request(
        db_session,
        request_id_uuid=ticket.id,
        approver_superuser_id=b_su.id,
    )
    assert second.status == "applied"
    assert second.detail["dispatched"] is True
    assert second.detail["action"] == ACTION_TWO_FACTOR_RESET_SKIP_DELAY
    assert len(calls) == 1
    assert calls[0]["approval_request_id"] == ticket.id


@pytest.mark.asyncio
async def test_approve_request_pending_outcome_envelope_fields(
    db_session: AsyncSession,
) -> None:
    """Kills swapped-key mutations on the pending audit envelope detail.

    The pending-state outcome carries a fixed schema:
    approval_request_id, approver_superuser_id, approvals_count,
    min_approvals, action. A mutation that omits or renames any key
    is caught by an explicit equality check.
    """
    requester = await _create_user(db_session, email="d1_env_req@example.com")
    approver = await _create_user(db_session, email="d1_env_app@example.com")
    target = await _create_user(db_session, email="d1_env_tgt@example.com")
    requester_su = await _create_superuser(db_session, user=requester)
    approver_su = await _create_superuser(db_session, user=approver)
    target_su = await _create_superuser(db_session, user=target)

    ticket = SuperuserApprovalRequest(
        action=ACTION_SUPERUSER_REVOKE,
        detail={
            "target_superuser_id": str(target_su.id),
            "target_user_id": str(target_su.user_id),
        },
        requested_by_id=requester_su.id,
        approvals=[],
        status="pending",
    )
    db_session.add(ticket)
    await db_session.flush()

    outcome = await approve_request(
        db_session,
        request_id_uuid=ticket.id,
        approver_superuser_id=approver_su.id,
        request_id="rid-d1-pend",
        ip="203.0.113.5",
        user_agent="agent/pending",
    )
    assert outcome.request_id == "rid-d1-pend"
    assert outcome.ip == "203.0.113.5"
    assert outcome.user_agent == "agent/pending"
    assert set(outcome.detail.keys()) == {
        "approval_request_id",
        "approver_superuser_id",
        "approvals_count",
        "min_approvals",
        "action",
    }
    assert outcome.detail["approval_request_id"] == str(ticket.id)
    assert outcome.detail["approver_superuser_id"] == str(approver_su.id)
    assert outcome.approval_request_id == ticket.id


@pytest.mark.asyncio
async def test_approve_request_duplicate_detection_compares_string_form(
    db_session: AsyncSession,
) -> None:
    """Kills mutation on the ``str(...)`` cast in the duplicate-scan loop.

    The membership check coerces both sides to ``str`` so JSONB-stored
    UUIDs (always strings) match the live UUID arg. A mutation that
    drops the ``str()`` would let a same-value approver sneak through
    if asyncpg ever surfaces ``superuser_id`` as a non-string type.
    """
    requester = await _create_user(db_session, email="d1_dupcoerce_req@example.com")
    approver = await _create_user(db_session, email="d1_dupcoerce_app@example.com")
    target = await _create_user(db_session, email="d1_dupcoerce_tgt@example.com")
    requester_su = await _create_superuser(db_session, user=requester)
    approver_su = await _create_superuser(db_session, user=approver)
    target_su = await _create_superuser(db_session, user=target)

    # Pre-seed an existing approval entry whose ``superuser_id`` matches
    # the approver but stored verbatim as a string. A naive non-coercive
    # ``in`` check would still match here because the JSONB driver
    # decodes to ``str`` already; the ``str(...)`` mutation we want to
    # catch is the one that would compare against a UUID object.
    ticket = SuperuserApprovalRequest(
        action=ACTION_SUPERUSER_REVOKE,
        detail={
            "target_superuser_id": str(target_su.id),
            "target_user_id": str(target_su.user_id),
        },
        requested_by_id=requester_su.id,
        approvals=[
            {
                "superuser_id": str(approver_su.id),
                "approved_at": datetime.now(UTC).isoformat(),
            }
        ],
        status="pending",
    )
    db_session.add(ticket)
    await db_session.flush()

    with pytest.raises(DuplicateApprovalError):
        await approve_request(
            db_session,
            request_id_uuid=ticket.id,
            approver_superuser_id=approver_su.id,
        )


@pytest.mark.asyncio
async def test_approve_request_revoked_approver_message_mentions_active(
    db_session: AsyncSession,
) -> None:
    """Kills string-content mutation on the NotSuperuserError message.

    Matches the regression text the API surfaces in 4xx responses; a
    mutation that strips the descriptor would still raise but the
    response payload would lose actionable wording.
    """
    requester = await _create_user(db_session, email="d1_msg_req@example.com")
    revoked = await _create_user(db_session, email="d1_msg_rev@example.com")
    target = await _create_user(db_session, email="d1_msg_tgt@example.com")
    requester_su = await _create_superuser(db_session, user=requester)
    revoked_su = await _create_superuser(db_session, user=revoked, revoked=True)
    target_su = await _create_superuser(db_session, user=target)

    ticket = SuperuserApprovalRequest(
        action=ACTION_SUPERUSER_REVOKE,
        detail={
            "target_superuser_id": str(target_su.id),
            "target_user_id": str(target_su.user_id),
        },
        requested_by_id=requester_su.id,
        approvals=[],
        status="pending",
    )
    db_session.add(ticket)
    await db_session.flush()

    with pytest.raises(NotSuperuserError) as exc_info:
        await approve_request(
            db_session,
            request_id_uuid=ticket.id,
            approver_superuser_id=revoked_su.id,
        )
    assert "active" in str(exc_info.value).lower()
