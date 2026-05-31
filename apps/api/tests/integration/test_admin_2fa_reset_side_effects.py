"""spec/011 §US5 / FR-011-306 / T404 — admin 2FA reset side-effects.

This suite pins the four observable side-effects of the admin-mediated
2FA disable (reset) flow plus its step-up scope contract:

1. **Step-up scope (T400, FR-011-306)** — the
   ``POST /web-api/v1/admin/users/{user_id}/reset-2fa`` endpoint is
   gated by ``require_step_up_token(SCOPE_ADMIN_RECOVERY)``. A request
   with no ``X-Step-Up-Token`` is rejected, and a request bearing a
   valid ``admin_destructive``-scoped token (the spec/006 scope) is
   rejected with a scope mismatch. Only an ``admin_recovery`` token is
   accepted. This is the negative-control that locks the T400 bug fix:
   the endpoint MUST NOT accept the old ``admin_destructive`` scope.

2. **Session invalidation (T401, FR-011-306)** — when the reset is
   actually applied (by the dispatch poller), the target user's
   ``security_stamp`` is rotated, which immediately invalidates every
   outstanding refresh / access / step-up token bound to the old
   stamp.

3. **Trusted-device revocation (T401, FR-011-402, R10)** — every active
   ``trusted_devices`` row for the target user is revoked
   (``revoked_at`` set) in the same transaction.

4. **Audit emission (T402, FR-011-306)** — a
   ``platform.user.two_factor_reset_by_superuser`` audit row is emitted
   with the actor / target dimension. The operator-vs-target case
   carries ``self_reset=False``; the superuser self-reset
   (``actor == target``) carries ``self_reset=True``. No email is
   enqueued (the email subsystem is removed in spec/011), and the audit
   detail carries only opaque UUIDs — no PII / no secret.

Architecture note
~~~~~~~~~~~~~~~~~
The endpoint at ``/admin/users/{user_id}/reset-2fa`` *opens* a
delayed-dispatch request (Phase 17 A-11 state machine). The actual 2FA
disable + session invalidation + trusted-device revoke + the
``two_factor_reset_by_superuser`` audit happen when the dispatch poller
(:func:`run_dispatch_due_requests` → ``_apply_one`` in
:mod:`echoroo.services.two_factor_reset_service`) processes a due row.
The side-effect cases below therefore drive the poller directly against
a ``pending_delay`` row whose ``dispatch_at`` is in the past, mirroring
a real beat tick. The step-up-scope cases exercise the HTTP gate on the
request-open endpoint.
"""

from __future__ import annotations

import json
import secrets
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
import pytest_asyncio
import sqlalchemy as sa
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.api.web_v1.admin import router as admin_router
from echoroo.core.database import get_db
from echoroo.middleware.auth import get_current_user_optional
from echoroo.models.superuser import Superuser
from echoroo.models.trusted_device import TrustedDevice
from echoroo.models.two_factor_reset_request import (
    STATUS_PENDING_DELAY,
    TwoFactorResetRequest,
)
from echoroo.models.user import User
from echoroo.services import two_factor_reset_service as svc_mod
from echoroo.services.step_up_token_service import (
    issue_admin_recovery_step_up_token,
    issue_step_up_token,
)
from echoroo.services.two_factor_reset_service import (
    AUDIT_ACTION_PLATFORM_USER_TWO_FACTOR_RESET_BY_SUPERUSER,
    run_dispatch_due_requests,
)

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _create_user(
    db: AsyncSession,
    *,
    email: str,
    two_factor_enabled: bool = True,
) -> User:
    user = User(
        email=email,
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$reset2fa-sideeffects",
        display_name=f"User {email}",
        security_stamp=secrets.token_hex(32),
        two_factor_enabled=two_factor_enabled,
        two_factor_secret_encrypted=(
            b"dummy-encrypted-secret" if two_factor_enabled else None
        ),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _create_superuser(db: AsyncSession, *, user: User) -> Superuser:
    row = Superuser(
        user_id=user.id,
        added_by_id=None,
        added_at=datetime.now(UTC) - timedelta(days=1),
        webauthn_credentials=[],
        allowed_ip_cidrs=["10.0.0.0/24"],
        revoked_at=None,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def _create_trusted_device(
    db: AsyncSession,
    *,
    user: User,
) -> TrustedDevice:
    now = datetime.now(UTC)
    device = TrustedDevice(
        user_id=user.id,
        device_secret_hash=secrets.token_hex(32),
        security_stamp=user.security_stamp,
        label="test-device",
        created_at=now,
        expires_at=now + timedelta(days=30),
        revoked_at=None,
    )
    db.add(device)
    await db.commit()
    await db.refresh(device)
    return device


async def _create_pending_request(
    db: AsyncSession,
    *,
    target_user_id: UUID,
    requested_by_superuser_id: UUID,
    dispatch_at: datetime,
    expires_at: datetime,
) -> TwoFactorResetRequest:
    """Insert a ``pending_delay`` request that the poller will pick up."""
    row = TwoFactorResetRequest(
        user_id=target_user_id,
        requested_by_superuser_id=requested_by_superuser_id,
        support_ticket_id="ZD-T404-001",
        reason="User lost 2FA device; identity verified via support ticket.",
        status=STATUS_PENDING_DELAY,
        skip_delay=False,
        dispatch_at=dispatch_at,
        expires_at=expires_at,
        confirmation_token_nonce=secrets.token_hex(16),
        approval_request_id=None,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


# ---------------------------------------------------------------------------
# App / client fixtures (step-up gate cases)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def admin_app(db_session: AsyncSession) -> FastAPI:
    app = FastAPI()
    app.include_router(admin_router, prefix="/web-api/v1")

    async def _override_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    return app


def _override_user(app: FastAPI, db: AsyncSession, user: User) -> None:
    captured = db

    async def _override() -> User | None:
        probe = await captured.execute(
            sa.text(
                "SELECT id FROM superusers "
                "WHERE user_id = :uid AND revoked_at IS NULL LIMIT 1"
            ),
            {"uid": user.id},
        )
        row = probe.scalar_one_or_none()
        user.is_superuser = row is not None  # type: ignore[attr-defined]
        user._superuser_id = row  # type: ignore[attr-defined]
        return user

    app.dependency_overrides[get_current_user_optional] = _override


def _reset_2fa_url(target_user_id: UUID) -> str:
    return f"/web-api/v1/admin/users/{target_user_id}/reset-2fa"


# ---------------------------------------------------------------------------
# 1. Step-up scope contract (T400 bug-fix lock)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reset_2fa_without_step_up_token_is_rejected(
    admin_app: FastAPI,
    db_session: AsyncSession,
) -> None:
    """No ``X-Step-Up-Token`` header → 401 ``step_up_token_required``."""
    su_user = await _create_user(db_session, email="t404_nostepup_su@example.com")
    await _create_superuser(db_session, user=su_user)
    target = await _create_user(db_session, email="t404_nostepup_target@example.com")
    _override_user(admin_app, db_session, su_user)

    transport = ASGITransport(app=admin_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            _reset_2fa_url(target.id),
            json={
                "support_ticket_id": "ZD-1",
                "reason": "lost device",
                "confirmation_token": "T",
            },
        )
    assert response.status_code == 401, response.text
    detail = response.json().get("detail", {})
    assert detail.get("error_code") == "step_up_token_required", detail


@pytest.mark.asyncio
async def test_reset_2fa_with_admin_destructive_token_is_rejected(
    admin_app: FastAPI,
    db_session: AsyncSession,
) -> None:
    """admin_destructive scope (spec/006) is refused by the admin_recovery gate.

    This is the direct regression lock for T400: before the fix the
    endpoint accepted ``admin_destructive``. A properly-signed,
    properly-bound ``admin_destructive`` token MUST now yield a 403
    scope mismatch so 2FA-reset is recognised as a *recovery* action.
    """
    su_user = await _create_user(db_session, email="t404_destructive_su@example.com")
    await _create_superuser(db_session, user=su_user)
    target = await _create_user(db_session, email="t404_destructive_target@example.com")
    _override_user(admin_app, db_session, su_user)

    # default scope = SCOPE_ADMIN_DESTRUCTIVE
    token, _ = issue_step_up_token(
        user_id=su_user.id,
        security_stamp=su_user.security_stamp,
        assertion_id="t404-destructive-vs-recovery",
    )
    transport = ASGITransport(app=admin_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            _reset_2fa_url(target.id),
            json={
                "support_ticket_id": "ZD-1",
                "reason": "lost device",
                "confirmation_token": "T",
            },
            headers={"X-Step-Up-Token": token},
        )
    assert response.status_code == 403, response.text
    detail = response.json().get("detail", {})
    assert detail.get("error_code") == "step_up_token_scope_mismatch", detail


@pytest.mark.asyncio
async def test_reset_2fa_with_admin_recovery_token_passes_step_up_gate(
    admin_app: FastAPI,
    db_session: AsyncSession,
) -> None:
    """An ``admin_recovery`` token clears the step-up gate.

    The request fails downstream on the (deliberately invalid)
    confirmation token with a 409, NOT on the step-up gate — proving
    the ``admin_recovery`` scope is the accepted scope. A 401/403 here
    would mean the gate wrongly rejected the recovery scope.
    """
    su_user = await _create_user(db_session, email="t404_recovery_su@example.com")
    await _create_superuser(db_session, user=su_user)
    target = await _create_user(db_session, email="t404_recovery_target@example.com")
    _override_user(admin_app, db_session, su_user)

    token, _ = issue_admin_recovery_step_up_token(
        user_id=su_user.id,
        security_stamp=su_user.security_stamp,
        assertion_id="t404-recovery-positive",
        password_verified=True,
        second_factor="totp",
    )
    transport = ASGITransport(app=admin_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            _reset_2fa_url(target.id),
            json={
                "support_ticket_id": "ZD-1",
                "reason": "lost device",
                "confirmation_token": "definitely-not-a-valid-confirmation-token",
            },
            headers={"X-Step-Up-Token": token},
        )
    # 409 = past the step-up gate, rejected on the confirmation token.
    assert response.status_code == 409, response.text
    assert response.status_code not in (401, 403), (
        "admin_recovery token must clear the step-up gate"
    )


# ---------------------------------------------------------------------------
# Audit-capture + cross-engine fixtures for the poller side-effect cases.
# ---------------------------------------------------------------------------


@pytest.fixture
def capture_audit(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> list[dict[str, object]]:
    """Capture every ``_write_platform_audit`` call into a list.

    The service's real ``_write_platform_audit`` opens a fresh
    ``AsyncSessionLocal`` bound to the production engine, so its rows
    never land in the test ``db_session``. We replace it with a capture
    stand-in (the audit chain itself is exercised by
    ``tests/security/audit/`` separately) so we can assert the
    ``two_factor_reset_by_superuser`` action + detail directly.
    """
    captured: list[dict[str, object]] = []

    async def _stub_write(
        *,
        actor_user_id: UUID | None = None,
        action: str,
        detail: dict[str, object],
        request_id: str = "",
        ip: str = "",
        user_agent: str = "",
    ) -> None:
        # Round-trip the detail through JSON so the assertion exercises
        # the same serialisable shape the real writer persists (catches
        # an accidental non-JSON value sneaking into the detail).
        captured.append(
            {
                "actor_user_id": actor_user_id,
                "action": action,
                "detail": json.loads(json.dumps(detail, default=str)),
            }
        )

    monkeypatch.setattr(svc_mod, "_write_platform_audit", _stub_write)
    return captured


@pytest.fixture(autouse=True)
def reset_redis_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force a fresh Redis client per test to avoid cross-loop reuse.

    ``echoroo.core.redis._redis_client`` is module-level cached and binds
    to the event loop on first use. Function-scoped event loops in
    pytest-asyncio break this — a Redis call from test N (the poller's
    ``_clear_totp_failures`` / ``_clear_backup_failures``) fails with
    "Future attached to a different loop" because the cached connection
    still points at test N-1's loop. Resetting the singleton before each
    test forces a fresh client bound to the current loop. Mirrors the
    same autouse fixture in ``test_admin_reset_2fa.py``.
    """
    import echoroo.core.redis as redis_mod

    monkeypatch.setattr(redis_mod, "_redis_client", None)


@pytest.fixture(autouse=True)
def stub_two_factor_record_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    """No-op the TwoFactorService internal audit writer (cross-engine).

    ``TwoFactorService._record_audit_event`` opens its own
    ``AsyncSessionLocal`` bound to the production engine; left live it
    blows up on cross-loop AsyncEngine reuse during ``reset_user_two_factor``.
    The ``two_factor.reset_completed`` row is not under test here (the
    T402 row is ``platform.user.two_factor_reset_by_superuser``).
    """
    import echoroo.services.two_factor_service as tfs_mod

    async def _noop(self, **_kwargs: object) -> None:  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(
        tfs_mod.TwoFactorService, "_record_audit_event", _noop
    )


# ---------------------------------------------------------------------------
# 2-4. Side-effects when the poller applies the reset (operator != target)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_invalidates_sessions_revokes_devices_and_emits_audit(
    db_session: AsyncSession,
    capture_audit: list[dict[str, object]],
) -> None:
    """Operator-driven 2FA reset: stamp rotated, devices revoked, audit emitted."""
    su_user = await _create_user(db_session, email="t404_apply_su@example.com")
    su = await _create_superuser(db_session, user=su_user)
    target = await _create_user(
        db_session, email="t404_apply_target@example.com", two_factor_enabled=True
    )
    device = await _create_trusted_device(db_session, user=target)

    original_stamp = target.security_stamp
    now = datetime.now(UTC)
    await _create_pending_request(
        db_session,
        target_user_id=target.id,
        requested_by_superuser_id=su.id,
        dispatch_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=24),
    )

    summary = await run_dispatch_due_requests(db_session, now=now)
    assert summary.applied == 1, summary

    # (2) Session invalidation — security_stamp rotated.
    await db_session.refresh(target)
    assert target.security_stamp != original_stamp, (
        "security_stamp must rotate to invalidate outstanding sessions"
    )
    assert target.two_factor_enabled is False

    # (3) Trusted-device revocation.
    await db_session.refresh(device)
    assert device.revoked_at is not None, "active trusted device must be revoked"

    # (4) Audit emission — exactly one two_factor_reset_by_superuser row.
    su_reset_rows = [
        row
        for row in capture_audit
        if row["action"] == AUDIT_ACTION_PLATFORM_USER_TWO_FACTOR_RESET_BY_SUPERUSER
    ]
    assert len(su_reset_rows) == 1, capture_audit
    emitted = su_reset_rows[0]
    # actor_user_id is the requesting superuser's *user* id (the audit
    # dimension dashboards filter on), resolved from the superuser row.
    assert emitted["actor_user_id"] == su_user.id
    detail = emitted["detail"]
    assert isinstance(detail, dict)
    assert detail["target_user_id"] == str(target.id)
    assert detail["self_reset"] is False
    _ = su  # superuser row created to satisfy the FK on the request row

    # No PII / secret in the detail — only opaque UUIDs / timestamps.
    serialised = json.dumps(detail).lower()
    assert "@" not in serialised, f"audit detail leaked an email: {detail}"
    assert "dummy-encrypted-secret" not in serialised
    assert target.email.lower() not in serialised


@pytest.mark.asyncio
async def test_self_reset_emits_self_variant(
    db_session: AsyncSession,
    capture_audit: list[dict[str, object]],
) -> None:
    """Superuser self-reset (actor == target) → ``self_reset=True`` variant.

    FR-011-306 has no separate ``user.2fa_reset_self`` event, so the
    self-reset case reuses the same action string with a
    ``self_reset=True`` detail discriminator.
    """
    su_user = await _create_user(
        db_session, email="t404_selfreset_su@example.com", two_factor_enabled=True
    )
    su = await _create_superuser(db_session, user=su_user)

    # actor == target: the superuser recovers their OWN 2FA. The request
    # row's ``requested_by_superuser_id`` is the superuser ROW id (FK to
    # ``superusers.id``) while ``user_id`` is the TARGET user id (FK to
    # ``users.id``). A self-reset is therefore the case where the
    # requesting superuser's underlying ``user_id`` equals ``user_id``;
    # _apply_one resolves the superuser row to make that comparison.
    now = datetime.now(UTC)
    row = TwoFactorResetRequest(
        user_id=su_user.id,
        requested_by_superuser_id=su.id,
        support_ticket_id="ZD-T404-SELF",
        reason="Superuser self-recovery after device loss.",
        status=STATUS_PENDING_DELAY,
        skip_delay=False,
        dispatch_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=24),
        confirmation_token_nonce=secrets.token_hex(16),
        approval_request_id=None,
    )
    db_session.add(row)
    await db_session.commit()

    summary = await run_dispatch_due_requests(db_session, now=now)
    assert summary.applied == 1, summary

    su_reset_rows = [
        r
        for r in capture_audit
        if r["action"] == AUDIT_ACTION_PLATFORM_USER_TWO_FACTOR_RESET_BY_SUPERUSER
    ]
    assert len(su_reset_rows) == 1, capture_audit
    detail = su_reset_rows[0]["detail"]
    assert isinstance(detail, dict)
    assert detail["self_reset"] is True
    assert detail["target_user_id"] == str(su_user.id)
    _ = su  # keep the superuser fixture referenced for clarity
