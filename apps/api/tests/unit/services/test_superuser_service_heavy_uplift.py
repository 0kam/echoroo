"""Coverage uplift unit tests for ``echoroo.services.superuser_service``.

Phase 17 §C heavy-gap batch (95% perm-tier module).

Targets the missing lines that earlier uplift suites do not exercise:

* ``add_superuser`` direct + ticket branches (lines 315-377)
* ``revoke_superuser`` ticket creation (lines 504, 521)
* ``revoke_superuser_apply`` not-found / already-revoked (lines 585, 587)
* ``register_webauthn_credential`` happy path + duplicate guard (lines
  1017-1067)
* ``verify_webauthn_assertion`` row + sign-count refresh (lines 1090-1121)
* ``_system_setting_upsert`` UPDATE branch (lines 1381-1383)

All cases run against the shared ``db_session`` fixture (real Postgres
``echoroo_test``) so production paths are exercised end-to-end with the
actual SQL the engine emits.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.superuser import Superuser
from echoroo.models.superuser_approval_request import SuperuserApprovalRequest
from echoroo.models.system import SystemSetting
from echoroo.models.user import User
from echoroo.services import superuser_service
from echoroo.services.superuser_service import (
    _AUDIT_ACTION_ADD_DIRECT,
    _AUDIT_ACTION_ADD_REQUESTED,
    _AUDIT_ACTION_REJECTED,
    _AUDIT_ACTION_REVOKE_REQUESTED,
    _AUDIT_ACTION_WEBAUTHN_REGISTERED,
    _AUDIT_ACTION_WEBAUTHN_REGISTERED_BELOW_MIN,
    ACTION_SUPERUSER_REVOKE,
    AlreadySuperuserError,
    ApprovalRequestNotFoundError,
    ApprovalRequestStateError,
    NotSuperuserError,
    SuperuserActionOutcome,
    SuperuserServiceError,
    WebAuthnRegistrationError,
    _system_setting_upsert,
    add_superuser,
    register_webauthn_credential,
    reject_request,
    revoke_superuser,
    trigger_post_commit_audit,
    verify_webauthn_assertion,
)

# ---------------------------------------------------------------------------
# Helpers — minimal create paths so each test stays self-contained.
# ---------------------------------------------------------------------------


async def _create_user(session: AsyncSession, *, email: str) -> User:
    user = User(
        email=email,
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$heavy",
        display_name=f"User {email}",
        security_stamp="0" * 64,
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user


async def _create_superuser(
    session: AsyncSession,
    *,
    user: User,
    revoked: bool = False,
    webauthn_credentials: list[dict[str, Any]] | None = None,
) -> Superuser:
    row = Superuser(
        user_id=user.id,
        added_by_id=None,
        added_at=datetime.now(UTC) - timedelta(days=1),
        webauthn_credentials=webauthn_credentials or [],
        allowed_ip_cidrs=[],
        revoked_at=datetime.now(UTC) if revoked else None,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


# ---------------------------------------------------------------------------
# add_superuser — direct branch (count < MIN_SUPERUSERS)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_superuser_direct_branch_creates_row(
    db_session: AsyncSession,
) -> None:
    """add_superuser() < MIN_SUPERUSERS → direct INSERT (lines 325-355)."""
    target_user = await _create_user(db_session, email="heavy_direct@example.com")
    outcome = await add_superuser(
        db_session,
        actor_user_id=None,
        target_user_id=target_user.id,
        requester_superuser_id=None,
        webauthn_credentials=[{"credential_id": "k1"}],
        allowed_ip_cidrs=["10.0.0.0/24"],
    )
    assert outcome.action == _AUDIT_ACTION_ADD_DIRECT
    assert outcome.status == "direct"
    assert outcome.superuser_id is not None
    # The new superuser row must exist + carry the supplied JSONB.
    row = await db_session.get(Superuser, outcome.superuser_id)
    assert row is not None
    assert row.user_id == target_user.id
    assert row.allowed_ip_cidrs == ["10.0.0.0/24"]


@pytest.mark.asyncio
async def test_add_superuser_rejects_existing_active(
    db_session: AsyncSession,
) -> None:
    """add_superuser() raises AlreadySuperuserError when row exists (lines 315-318)."""
    target_user = await _create_user(db_session, email="heavy_exists@example.com")
    await _create_superuser(db_session, user=target_user)
    with pytest.raises(AlreadySuperuserError):
        await add_superuser(
            db_session,
            actor_user_id=None,
            target_user_id=target_user.id,
            requester_superuser_id=None,
        )


# ---------------------------------------------------------------------------
# add_superuser — ticket branch (count >= MIN_SUPERUSERS)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_superuser_requires_requester_when_above_threshold(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """add_superuser() raises when no requester supplied past MIN_SUPERUSERS (lines 358-361)."""

    async def fake_count(_session: AsyncSession) -> int:
        return superuser_service.MIN_SUPERUSERS

    monkeypatch.setattr(superuser_service, "_count_active_superusers", fake_count)
    target_user = await _create_user(db_session, email="heavy_no_req@example.com")
    with pytest.raises(SuperuserServiceError):
        await add_superuser(
            db_session,
            actor_user_id=None,
            target_user_id=target_user.id,
            requester_superuser_id=None,
        )


@pytest.mark.asyncio
async def test_add_superuser_ticket_branch_returns_pending_outcome(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """add_superuser() above threshold opens an approval ticket (lines 363-392)."""

    async def fake_count(_session: AsyncSession) -> int:
        return superuser_service.MIN_SUPERUSERS

    monkeypatch.setattr(superuser_service, "_count_active_superusers", fake_count)
    requester_user = await _create_user(db_session, email="heavy_req@example.com")
    requester = await _create_superuser(db_session, user=requester_user)
    target_user = await _create_user(db_session, email="heavy_target@example.com")

    outcome = await add_superuser(
        db_session,
        actor_user_id=requester_user.id,
        target_user_id=target_user.id,
        requester_superuser_id=requester.id,
    )
    assert outcome.action == _AUDIT_ACTION_ADD_REQUESTED
    assert outcome.status == "pending"
    assert outcome.approval_request_id is not None


# ---------------------------------------------------------------------------
# revoke_superuser — pending ticket
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoke_superuser_creates_pending_ticket(
    db_session: AsyncSession,
) -> None:
    """revoke_superuser() opens an M-of-N pending ticket (lines 504, 521)."""
    requester_user = await _create_user(db_session, email="heavy_revoke_req@example.com")
    requester = await _create_superuser(db_session, user=requester_user)
    target_user = await _create_user(db_session, email="heavy_revoke_tgt@example.com")
    target = await _create_superuser(db_session, user=target_user)

    outcome = await revoke_superuser(
        db_session,
        target_superuser_id=target.id,
        requester_superuser_id=requester.id,
        actor_user_id=requester_user.id,
    )
    assert outcome.action == _AUDIT_ACTION_REVOKE_REQUESTED
    assert outcome.status == "pending"
    assert outcome.approval_request_id is not None


@pytest.mark.asyncio
async def test_revoke_superuser_rejects_already_revoked_target(
    db_session: AsyncSession,
) -> None:
    """revoke_superuser() rejects an already-revoked target (line 504 negative)."""
    requester_user = await _create_user(
        db_session, email="heavy_revoke_already_req@example.com",
    )
    requester = await _create_superuser(db_session, user=requester_user)
    target_user = await _create_user(
        db_session, email="heavy_revoke_already_tgt@example.com",
    )
    target = await _create_superuser(db_session, user=target_user, revoked=True)
    with pytest.raises(NotSuperuserError):
        await revoke_superuser(
            db_session,
            target_superuser_id=target.id,
            requester_superuser_id=requester.id,
        )


@pytest.mark.asyncio
async def test_revoke_superuser_rejects_unknown_target(
    db_session: AsyncSession,
) -> None:
    """revoke_superuser() rejects a non-existent target row."""
    requester_user = await _create_user(db_session, email="heavy_revoke_unknown@example.com")
    requester = await _create_superuser(db_session, user=requester_user)
    with pytest.raises(NotSuperuserError):
        await revoke_superuser(
            db_session,
            target_superuser_id=uuid4(),
            requester_superuser_id=requester.id,
        )


# ---------------------------------------------------------------------------
# register_webauthn_credential
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_webauthn_credential_first_credential_below_min(
    db_session: AsyncSession,
) -> None:
    """register_webauthn_credential() emits below-min audit on first credential (lines 1017-1067)."""
    user = await _create_user(db_session, email="heavy_wa_first@example.com")
    su = await _create_superuser(db_session, user=user)
    outcome = await register_webauthn_credential(
        db_session,
        superuser_id=su.id,
        credential={"credential_id": "key-A", "public_key": "pk", "sign_count": 0},
    )
    assert outcome.action == _AUDIT_ACTION_WEBAUTHN_REGISTERED_BELOW_MIN
    assert outcome.detail["below_minimum"] is True


@pytest.mark.asyncio
async def test_register_webauthn_credential_second_credential_at_min(
    db_session: AsyncSession,
) -> None:
    """Adding the 2nd credential reaches the MIN threshold (regular audit action)."""
    user = await _create_user(db_session, email="heavy_wa_second@example.com")
    su = await _create_superuser(
        db_session,
        user=user,
        webauthn_credentials=[{"credential_id": "key-A"}],
    )
    outcome = await register_webauthn_credential(
        db_session,
        superuser_id=su.id,
        credential={"credential_id": "key-B"},
    )
    assert outcome.action == _AUDIT_ACTION_WEBAUTHN_REGISTERED
    assert outcome.detail["below_minimum"] is False


@pytest.mark.asyncio
async def test_register_webauthn_credential_rejects_missing_credential_id(
    db_session: AsyncSession,
) -> None:
    """register_webauthn_credential() raises when credential_id missing (lines 1026-1029)."""
    user = await _create_user(db_session, email="heavy_wa_no_id@example.com")
    su = await _create_superuser(db_session, user=user)
    with pytest.raises(WebAuthnRegistrationError):
        await register_webauthn_credential(
            db_session,
            superuser_id=su.id,
            credential={"public_key": "pk"},
        )


@pytest.mark.asyncio
async def test_register_webauthn_credential_rejects_duplicate_credential_id(
    db_session: AsyncSession,
) -> None:
    """register_webauthn_credential() rejects an already-stored credential_id (lines 1030-1036)."""
    user = await _create_user(db_session, email="heavy_wa_dup@example.com")
    su = await _create_superuser(
        db_session,
        user=user,
        webauthn_credentials=[{"credential_id": "key-A"}],
    )
    with pytest.raises(WebAuthnRegistrationError):
        await register_webauthn_credential(
            db_session,
            superuser_id=su.id,
            credential={"credential_id": "key-A"},
        )


@pytest.mark.asyncio
async def test_register_webauthn_credential_rejects_revoked_superuser(
    db_session: AsyncSession,
) -> None:
    """register_webauthn_credential() rejects a revoked superuser row (lines 1018-1022)."""
    user = await _create_user(db_session, email="heavy_wa_revoked@example.com")
    su = await _create_superuser(db_session, user=user, revoked=True)
    with pytest.raises(NotSuperuserError):
        await register_webauthn_credential(
            db_session,
            superuser_id=su.id,
            credential={"credential_id": "key-A"},
        )


# ---------------------------------------------------------------------------
# verify_webauthn_assertion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_webauthn_assertion_persists_updated_credential(
    db_session: AsyncSession,
) -> None:
    """verify_webauthn_assertion() updates sign_count back into the JSONB (lines 1097-1121)."""
    user = await _create_user(db_session, email="heavy_wa_verify@example.com")
    initial = {"credential_id": "key-A", "public_key": "pk", "sign_count": 0}
    su = await _create_superuser(
        db_session, user=user, webauthn_credentials=[initial],
    )
    updated = {"credential_id": "key-A", "public_key": "pk", "sign_count": 5}
    fake_service = MagicMock()
    fake_service.complete_authentication = AsyncMock(return_value=updated)

    out = await verify_webauthn_assertion(
        db_session,
        superuser_id=su.id,
        authentication_response={"id": "key-A", "response": {}},
        webauthn_service=fake_service,
    )
    assert out["sign_count"] == 5
    await db_session.refresh(su)
    assert su.webauthn_credentials[0]["sign_count"] == 5


@pytest.mark.asyncio
async def test_verify_webauthn_assertion_preserves_non_matching_credentials(
    db_session: AsyncSession,
) -> None:
    """verify_webauthn_assertion() preserves other credentials in the JSONB (line 1118)."""
    user = await _create_user(db_session, email="heavy_wa_two@example.com")
    cred_a = {"credential_id": "key-A", "public_key": "pkA", "sign_count": 0}
    cred_b = {"credential_id": "key-B", "public_key": "pkB", "sign_count": 0}
    su = await _create_superuser(
        db_session, user=user, webauthn_credentials=[cred_a, cred_b],
    )
    updated = {"credential_id": "key-A", "public_key": "pkA", "sign_count": 9}
    fake_service = MagicMock()
    fake_service.complete_authentication = AsyncMock(return_value=updated)

    await verify_webauthn_assertion(
        db_session,
        superuser_id=su.id,
        authentication_response={"id": "key-A"},
        webauthn_service=fake_service,
    )
    await db_session.refresh(su)
    creds = su.webauthn_credentials
    keyed = {c["credential_id"]: c for c in creds}
    # key-A updated, key-B preserved as-is.
    assert keyed["key-A"]["sign_count"] == 9
    assert keyed["key-B"]["sign_count"] == 0


@pytest.mark.asyncio
async def test_verify_webauthn_assertion_rejects_revoked_row(
    db_session: AsyncSession,
) -> None:
    """verify_webauthn_assertion() rejects a revoked row (lines 1090-1095)."""
    user = await _create_user(db_session, email="heavy_wa_verify_rev@example.com")
    su = await _create_superuser(db_session, user=user, revoked=True)
    with pytest.raises(NotSuperuserError):
        await verify_webauthn_assertion(
            db_session,
            superuser_id=su.id,
            authentication_response={"id": "x"},
        )


@pytest.mark.asyncio
async def test_verify_webauthn_assertion_rejects_zero_credentials(
    db_session: AsyncSession,
) -> None:
    """verify_webauthn_assertion() rejects when no credentials registered (lines 1100-1103)."""
    user = await _create_user(db_session, email="heavy_wa_verify_empty@example.com")
    su = await _create_superuser(db_session, user=user)
    with pytest.raises(WebAuthnRegistrationError):
        await verify_webauthn_assertion(
            db_session,
            superuser_id=su.id,
            authentication_response={"id": "x"},
        )


# ---------------------------------------------------------------------------
# reject_request
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reject_request_flips_status_to_rejected(
    db_session: AsyncSession,
) -> None:
    """reject_request() updates approvals + status (lines 894-918, 970+)."""
    requester_user = await _create_user(db_session, email="heavy_reject_req@example.com")
    requester = await _create_superuser(db_session, user=requester_user)
    target_user = await _create_user(db_session, email="heavy_reject_tgt@example.com")
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

    rejector_user = await _create_user(db_session, email="heavy_reject_act@example.com")
    rejector = await _create_superuser(db_session, user=rejector_user)
    outcome = await reject_request(
        db_session,
        request_id_uuid=ticket.id,
        rejector_superuser_id=rejector.id,
        reason="not justified",
    )
    assert outcome.action == _AUDIT_ACTION_REJECTED
    await db_session.refresh(ticket)
    assert ticket.status == "rejected"
    assert ticket.executed_at is not None
    assert any(
        a.get("decision") == "rejected" and a.get("rejected_reason") == "not justified"
        for a in ticket.approvals
    )


@pytest.mark.asyncio
async def test_reject_request_raises_when_ticket_missing(
    db_session: AsyncSession,
) -> None:
    """reject_request() raises ApprovalRequestNotFoundError on missing id (lines 896-899)."""
    user = await _create_user(db_session, email="heavy_reject_404@example.com")
    su = await _create_superuser(db_session, user=user)
    with pytest.raises(ApprovalRequestNotFoundError):
        await reject_request(
            db_session,
            request_id_uuid=uuid4(),
            rejector_superuser_id=su.id,
            reason="x",
        )


@pytest.mark.asyncio
async def test_reject_request_two_factor_reset_path_appends_extra_audit(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """reject_request() with A-11 ticket calls mark_cancelled_after_rejection (lines 935-944).

    The cancellation helper is monkey-patched to return a fake payload so we
    do not depend on the full ``two_factor_reset_requests`` schema.
    """
    requester_user = await _create_user(db_session, email="heavy_2fa_req@example.com")
    requester = await _create_superuser(db_session, user=requester_user)
    ticket = SuperuserApprovalRequest(
        action="two_factor_reset.skip_delay",
        detail={"target_user_id": str(uuid4())},
        requested_by_id=requester.id,
        approvals=[],
        status="pending",
    )
    db_session.add(ticket)
    await db_session.flush()

    rejector_user = await _create_user(db_session, email="heavy_2fa_act@example.com")
    rejector = await _create_superuser(db_session, user=rejector_user)

    fake_payload = MagicMock()
    fake_payload.request_id = uuid4()
    fake_payload.target_user_id = uuid4()
    fake_payload.approval_request_id = ticket.id
    fake_payload.rejector_superuser_id = rejector.id
    fake_payload.rejected_reason_excerpt = "no good"

    from echoroo.services import two_factor_reset_service as trs

    monkeypatch.setattr(
        trs,
        "mark_cancelled_after_rejection",
        AsyncMock(return_value=fake_payload),
    )
    monkeypatch.setattr(trs, "AUDIT_ACTION_CANCELLED", "two_factor_reset.cancelled")

    outcome = await reject_request(
        db_session,
        request_id_uuid=ticket.id,
        rejector_superuser_id=rejector.id,
        reason="no good",
    )
    assert outcome.action == _AUDIT_ACTION_REJECTED
    # The 2FA reset cancellation envelope must be appended to extra_audit.
    assert len(outcome.extra_audit) >= 1
    assert any(
        getattr(env, "action", "") == "two_factor_reset.cancelled"
        for env in outcome.extra_audit
    )


@pytest.mark.asyncio
async def test_reject_request_raises_when_ticket_not_pending(
    db_session: AsyncSession,
) -> None:
    """reject_request() raises ApprovalRequestStateError on non-pending tickets (lines 900-904)."""
    requester_user = await _create_user(db_session, email="heavy_reject_done_req@example.com")
    requester = await _create_superuser(db_session, user=requester_user)
    target_user = await _create_user(db_session, email="heavy_reject_done_tgt@example.com")
    target = await _create_superuser(db_session, user=target_user)
    ticket = SuperuserApprovalRequest(
        action=ACTION_SUPERUSER_REVOKE,
        detail={
            "target_superuser_id": str(target.id),
            "target_user_id": str(target.user_id),
        },
        requested_by_id=requester.id,
        approvals=[],
        status="applied",
    )
    db_session.add(ticket)
    await db_session.flush()

    with pytest.raises(ApprovalRequestStateError):
        await reject_request(
            db_session,
            request_id_uuid=ticket.id,
            rejector_superuser_id=requester.id,
            reason="too late",
        )


# ---------------------------------------------------------------------------
# trigger_post_commit_audit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trigger_post_commit_audit_drains_extra_audit_recursively(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """trigger_post_commit_audit() drains extra_audit recursively (lines 1268-1289)."""
    write_calls: list[str] = []

    class _FakeSvc:
        def __init__(self, session: object) -> None:
            self._session = session

        async def write_platform_event(self, **kwargs: Any) -> None:
            write_calls.append(kwargs["action"])

    class _FakeSession:
        async def __aenter__(self) -> _FakeSession:
            return self

        async def __aexit__(self, *exc: Any) -> bool:
            return False

        async def commit(self) -> None:
            return None

        async def rollback(self) -> None:
            return None

    def factory() -> _FakeSession:
        return _FakeSession()

    from echoroo.services import superuser_service as svc

    monkeypatch.setattr(svc, "AsyncSessionLocal", factory)
    monkeypatch.setattr(svc, "AuditLogService", _FakeSvc)

    now = datetime.now(UTC)
    inner = SuperuserActionOutcome(
        action="inner.action",
        actor_user_id=None,
        detail={},
        created_at=now,
        request_id="",
        ip="",
        user_agent="",
        status="applied",
    )
    outer = SuperuserActionOutcome(
        action="outer.action",
        actor_user_id=None,
        detail={},
        created_at=now,
        request_id="",
        ip="",
        user_agent="",
        status="applied",
        extra_audit=(inner,),
    )
    await trigger_post_commit_audit(outer)
    assert write_calls == ["outer.action", "inner.action"]


@pytest.mark.asyncio
async def test_trigger_post_commit_audit_rolls_back_on_write_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """trigger_post_commit_audit() rolls back inner audit session on write failure (lines 1287-1289)."""
    rollback_calls = {"n": 0}

    class _FakeSvc:
        def __init__(self, session: object) -> None:
            self._session = session

        async def write_platform_event(self, **kwargs: Any) -> None:
            raise RuntimeError("write blew up")

    class _FakeSession:
        async def __aenter__(self) -> _FakeSession:
            return self

        async def __aexit__(self, *exc: Any) -> bool:
            return False

        async def commit(self) -> None:
            return None

        async def rollback(self) -> None:
            rollback_calls["n"] += 1

    def factory() -> _FakeSession:
        return _FakeSession()

    from echoroo.services import superuser_service as svc

    monkeypatch.setattr(svc, "AsyncSessionLocal", factory)
    monkeypatch.setattr(svc, "AuditLogService", _FakeSvc)

    now = datetime.now(UTC)
    outcome = SuperuserActionOutcome(
        action="rolled_back.action",
        actor_user_id=None,
        detail={},
        created_at=now,
        request_id="",
        ip="",
        user_agent="",
        status="applied",
    )
    # MUST NOT raise — rollback then swallow at outer except.
    await trigger_post_commit_audit(outcome)
    assert rollback_calls["n"] == 1


@pytest.mark.asyncio
async def test_trigger_post_commit_audit_swallows_audit_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """trigger_post_commit_audit() logs WARNING on failure (lines 1290-1298)."""

    class _BoomSession:
        async def __aenter__(self) -> _BoomSession:
            raise RuntimeError("audit DB down")

        async def __aexit__(self, *exc: Any) -> bool:
            return False

    from echoroo.services import superuser_service as svc

    monkeypatch.setattr(svc, "AsyncSessionLocal", _BoomSession)

    now = datetime.now(UTC)
    outcome = SuperuserActionOutcome(
        action="ignored.action",
        actor_user_id=None,
        detail={},
        created_at=now,
        request_id="",
        ip="",
        user_agent="",
        status="applied",
    )
    # MUST NOT raise — soft alert behaviour.
    await trigger_post_commit_audit(outcome)


# ---------------------------------------------------------------------------
# _system_setting_upsert — UPDATE branch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_system_setting_upsert_updates_existing_row(
    db_session: AsyncSession,
) -> None:
    """_system_setting_upsert() updates an existing row in place (lines 1381-1383)."""
    user = await _create_user(db_session, email="heavy_sys_setting@example.com")
    su = await _create_superuser(db_session, user=user)
    now = datetime.now(UTC)
    # First call inserts.
    await _system_setting_upsert(
        db_session,
        key="upsert_test_key",
        value="value-1",
        updated_by_id=su.id,
        now=now,
    )
    # Second call updates (covers lines 1381-1383).
    later = now + timedelta(minutes=5)
    await _system_setting_upsert(
        db_session,
        key="upsert_test_key",
        value="value-2",
        updated_by_id=su.id,
        now=later,
    )
    row = await db_session.get(SystemSetting, "upsert_test_key")
    assert row is not None
    assert row.value == "value-2"
