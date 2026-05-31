"""Integration tests for the Phase 17 A-11 admin 2FA reset endpoint.

Covers the full implementation of ``POST /admin/users/{user_id}/reset-2fa``
(replaced the 501 stub). Tests the default ``skip_delay=false`` flow with:

* 202 happy-path with valid confirmation_token
* audit row written (two_factor_reset.requested + token_verified)
* email send stubs verified
* 401 / 403 auth gates
* 422 schema validation
* 409 invalid/expired/used/wrong-user confirmation_token
* 409 duplicate active request
* 404 unknown user

Magic link flow dependencies are satisfied using the service layer
directly (no real email dispatch).

Spec references: FR-072, admin.yaml operationId=reset2FA, PHASE17_BACKLOG A-11.
"""

from __future__ import annotations

import secrets
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.api.web_v1.admin import router as admin_router
from echoroo.core.database import get_db
from echoroo.middleware.auth import get_current_user_optional
from echoroo.models.superuser import Superuser
from echoroo.models.two_factor_reset_request import (
    STATUS_PENDING_DELAY,
    TwoFactorResetRequest,
)
from echoroo.models.user import User
from echoroo.services.step_up_token_service import (
    issue_admin_recovery_step_up_token,
)
from echoroo.services.two_factor_confirmation_token import (
    PURPOSE_ADMIN_RESET_2FA,
    issue_confirmation_token,
)

# ---------------------------------------------------------------------------
# DB / model helpers
# ---------------------------------------------------------------------------


async def _create_user(
    db: AsyncSession,
    *,
    email: str,
    two_factor_enabled: bool = True,
) -> User:
    user = User(
        email=email,
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$reset2fa-test",
        display_name=f"User {email}",
        security_stamp=secrets.token_hex(32),
        two_factor_enabled=two_factor_enabled,
        two_factor_secret_encrypted=b"dummy-encrypted-secret" if two_factor_enabled else None,
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


async def _mint_confirmation_token(
    db: AsyncSession,
    *,
    user_id: UUID,
    now: datetime | None = None,
) -> str:
    """Issue a fresh confirmation token for user_id and commit it."""
    token, _payload = await issue_confirmation_token(
        db,
        user_id=user_id,
        purpose=PURPOSE_ADMIN_RESET_2FA,
        now=now,
    )
    await db.commit()
    return token


# ---------------------------------------------------------------------------
# App / client fixtures (mirroring test_admin_reset_2fa_stub.py pattern)
# ---------------------------------------------------------------------------


@pytest.fixture
async def admin_app(db_session: AsyncSession) -> FastAPI:
    app = FastAPI()
    app.include_router(admin_router, prefix="/web-api/v1")

    async def _override_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    return app


@pytest.fixture
async def admin_client_factory(  # type: ignore[no-untyped-def]
    admin_app: FastAPI,
    db_session: AsyncSession,
):
    """Build an HTTP client bound to a specific user (or anonymous)."""
    transport = ASGITransport(app=admin_app)
    captured_session = db_session

    def _override_user(user: User | None) -> None:
        async def _override() -> User | None:
            if user is None:
                return None
            probe = await captured_session.execute(
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

        admin_app.dependency_overrides[get_current_user_optional] = _override

    async def _factory(
        user: User | None,
        *,
        include_step_up: bool = True,
    ) -> AsyncClient:
        _override_user(user)
        headers: dict[str, str] = {}
        if include_step_up:
            # spec/011 §FR-011-306 / T400: the admin 2FA reset endpoint is
            # now gated by ``require_step_up_token(SCOPE_ADMIN_RECOVERY)``
            # (was ``SCOPE_ADMIN_DESTRUCTIVE``). Mint an ``admin_recovery``
            # token via the canonical issuer so the AND-condition factors
            # (password + 2nd factor) are present and the gate passes.
            token, _ = issue_admin_recovery_step_up_token(
                user_id=user.id if user is not None else uuid4(),
                security_stamp=(
                    user.security_stamp if user is not None else "0" * 64
                ),
                assertion_id="test-fixture-credential",
                password_verified=True,
                second_factor="totp",
            )
            headers["X-Step-Up-Token"] = token
        return AsyncClient(
            transport=transport,
            base_url="http://testserver",
            headers=headers,
        )

    return _factory


def _base_payload(confirmation_token: str) -> dict[str, Any]:
    return {
        "support_ticket_id": "ZD-A11-001",
        "reason": "User forgot 2FA device; support ticket verified identity.",
        "skip_delay": False,
        "confirmation_token": confirmation_token,
    }


@pytest.fixture(autouse=True)
def reset_redis_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force a fresh Redis client per test to avoid cross-loop reuse.

    ``echoroo.core.redis._redis_client`` is module-level cached and
    binds to the event loop on first use. Function-scoped event loops
    in pytest-asyncio break this — a Redis call from test N fails
    with ``MissingGreenlet`` because the underlying connection still
    points at test N-1's loop. Resetting the singleton before each
    test forces a fresh client bound to the current loop.
    """
    import echoroo.core.redis as redis_mod

    monkeypatch.setattr(redis_mod, "_redis_client", None)


@pytest.fixture(autouse=True)
def patch_audit_session(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Insert ``platform_audit_log`` rows into the test session directly.

    Round-3 Fix R2-1 / R2-2 / R2-3 require asserting that audit rows
    actually land in ``platform_audit_log``. The service module's
    ``_write_platform_audit`` opens a fresh session via
    ``AsyncSessionLocal`` which is bound to the **production** engine
    (``DATABASE_URL``) — the audit rows commit to the wrong database
    and the test SELECT returns an empty list.

    Trying to monkey-patch ``AsyncSessionLocal`` to a fresh
    AsyncEngine bound to ``TEST_DATABASE_URL`` runs into greenlet /
    event-loop lifetime issues when the per-test event loop tears
    down. Instead we replace ``_write_platform_audit`` with a thin
    stand-in that writes a minimal row directly into ``db_session``
    via raw SQL — bypassing the chained-hash audit service entirely.
    The test queries the same ``db_session`` so visibility is
    guaranteed; the chained hash is irrelevant for this test scope
    (the service-layer audit chain is exercised by
    ``tests/security/audit/`` separately).
    """
    import json

    import echoroo.services.two_factor_reset_service as svc_mod

    async def _stub_write(  # noqa: ANN001 — kwargs match the real signature
        *,
        actor_user_id=None,
        action,
        detail,
        request_id="",
        ip="",
        user_agent="",
    ) -> None:
        # Reuse the test's session bind — ensures the row commits to the
        # same DB the test queries against. We INSERT with NULL hash
        # columns to skip the trigger; the test only inspects
        # ``action`` and ``detail`` so the chained hash is irrelevant.
        await db_session.execute(
            sa.text(
                "INSERT INTO platform_audit_log "
                "(action, detail, actor_user_id_hash, request_id, "
                " ip_hash, user_agent_hash, prev_hash, row_hash) "
                "VALUES (:action, CAST(:detail AS JSONB), '', :req, "
                " '', '', '', :rowh)"
            ),
            {
                "action": action,
                "detail": json.dumps(detail),
                "req": request_id or "",
                "rowh": "0" * 64,
            },
        )
        await db_session.commit()

    monkeypatch.setattr(svc_mod, "_write_platform_audit", _stub_write)

    # ``two_factor_service.TwoFactorService._record_audit_event`` also
    # opens its own ``AsyncSessionLocal`` for the post-reset audit row
    # and binds to the production engine. Replace it with a no-op so
    # the in-test ``reset_user_two_factor`` call does not blow up on
    # cross-loop AsyncEngine re-use.
    import echoroo.services.two_factor_service as tfs_mod

    async def _stub_record_audit_event(
        self,  # noqa: ANN001
        *,
        actor_id,  # noqa: ANN001, ARG001
        target_user,  # noqa: ANN001, ARG001
        action,  # noqa: ANN001, ARG001
        detail,  # noqa: ANN001, ARG001
    ) -> None:
        return None

    monkeypatch.setattr(
        tfs_mod.TwoFactorService,
        "_record_audit_event",
        _stub_record_audit_event,
    )


# ---------------------------------------------------------------------------
# Auth / permission gates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reset_2fa_anonymous_returns_401(
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    """Anonymous callers must be rejected with 401."""
    async with await admin_client_factory(None) as client:
        response = await client.post(
            f"/web-api/v1/admin/users/{uuid4()}/reset-2fa",
            json={"support_ticket_id": "X", "reason": "R", "confirmation_token": "T"},
        )
    assert response.status_code == 401, response.text


@pytest.mark.asyncio
async def test_reset_2fa_non_superuser_returns_403(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    """Authenticated non-superuser must be rejected with 403."""
    regular_user = await _create_user(db_session, email="r2fa_nonsup@example.com")
    async with await admin_client_factory(regular_user) as client:
        response = await client.post(
            f"/web-api/v1/admin/users/{uuid4()}/reset-2fa",
            json={"support_ticket_id": "X", "reason": "R", "confirmation_token": "T"},
        )
    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_reset_2fa_without_step_up_token_returns_403(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    """Superuser without step-up token must be rejected."""
    su_user = await _create_user(db_session, email="r2fa_nosu_stepup@example.com")
    await _create_superuser(db_session, user=su_user)
    async with await admin_client_factory(su_user, include_step_up=False) as client:
        response = await client.post(
            f"/web-api/v1/admin/users/{uuid4()}/reset-2fa",
            json={"support_ticket_id": "X", "reason": "R", "confirmation_token": "T"},
        )
    assert response.status_code in (401, 403), response.text


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reset_2fa_missing_confirmation_token_returns_422(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    """Missing confirmation_token must yield 422."""
    su_user = await _create_user(db_session, email="r2fa_422_missing@example.com")
    await _create_superuser(db_session, user=su_user)
    target_id = uuid4()
    async with await admin_client_factory(su_user) as client:
        response = await client.post(
            f"/web-api/v1/admin/users/{target_id}/reset-2fa",
            json={"support_ticket_id": "ZD-001", "reason": "R"},
        )
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_reset_2fa_extra_field_returns_422(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    """Extra fields must be rejected by the extra=forbid schema."""
    su_user = await _create_user(db_session, email="r2fa_422_extra@example.com")
    await _create_superuser(db_session, user=su_user)
    target_id = uuid4()
    async with await admin_client_factory(su_user) as client:
        response = await client.post(
            f"/web-api/v1/admin/users/{target_id}/reset-2fa",
            json={
                "support_ticket_id": "ZD-001",
                "reason": "R",
                "confirmation_token": "dummy",
                "force_grant_admin": True,  # extra field
            },
        )
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_reset_2fa_empty_support_ticket_id_returns_422(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    """Empty support_ticket_id must yield 422 (min_length=1)."""
    su_user = await _create_user(db_session, email="r2fa_422_emptyticket@example.com")
    await _create_superuser(db_session, user=su_user)
    target_id = uuid4()
    async with await admin_client_factory(su_user) as client:
        response = await client.post(
            f"/web-api/v1/admin/users/{target_id}/reset-2fa",
            json={
                "support_ticket_id": "",
                "reason": "R",
                "confirmation_token": "dummy",
            },
        )
    assert response.status_code == 422, response.text


# ---------------------------------------------------------------------------
# 404 – unknown user
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reset_2fa_unknown_user_returns_404(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    """Non-existent user_id must return 404."""
    su_user = await _create_user(db_session, email="r2fa_su_for404@example.com")
    await _create_superuser(db_session, user=su_user)
    target_user = await _create_user(db_session, email="r2fa_target_for404@example.com")
    token = await _mint_confirmation_token(db_session, user_id=target_user.id)

    async with await admin_client_factory(su_user) as client:
        response = await client.post(
            f"/web-api/v1/admin/users/{uuid4()}/reset-2fa",
            json=_base_payload(token),
        )
    assert response.status_code == 404, response.text


# ---------------------------------------------------------------------------
# 409 – invalid / expired / already-used / wrong-user confirmation token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reset_2fa_invalid_token_returns_409(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    """A completely bogus confirmation_token must return 409."""
    su_user = await _create_user(db_session, email="r2fa_su_409invalid@example.com")
    await _create_superuser(db_session, user=su_user)
    target = await _create_user(db_session, email="r2fa_target_409invalid@example.com")
    async with await admin_client_factory(su_user) as client:
        response = await client.post(
            f"/web-api/v1/admin/users/{target.id}/reset-2fa",
            json=_base_payload("this-is-not-a-valid-token"),
        )
    assert response.status_code == 409, response.text
    body = response.json()
    assert body["detail"]["error"] == "ERR_INVALID_CONFIRMATION_TOKEN"


@pytest.mark.asyncio
async def test_reset_2fa_expired_token_returns_409(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    """A confirmation_token issued in the past (past TTL) must return 409."""
    su_user = await _create_user(db_session, email="r2fa_su_409expired@example.com")
    await _create_superuser(db_session, user=su_user)
    target = await _create_user(db_session, email="r2fa_target_409expired@example.com")

    # Issue a token with a backdated now so it is already past its 5-min TTL.
    past = datetime.now(UTC) - timedelta(minutes=10)
    token = await _mint_confirmation_token(db_session, user_id=target.id, now=past)

    async with await admin_client_factory(su_user) as client:
        response = await client.post(
            f"/web-api/v1/admin/users/{target.id}/reset-2fa",
            json=_base_payload(token),
        )
    assert response.status_code == 409, response.text
    body = response.json()
    assert body["detail"]["error"] == "ERR_INVALID_CONFIRMATION_TOKEN"


@pytest.mark.asyncio
async def test_reset_2fa_wrong_user_token_returns_409(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    """A confirmation_token bound to user A must fail when used against user B."""
    su_user = await _create_user(db_session, email="r2fa_su_409wronguser@example.com")
    await _create_superuser(db_session, user=su_user)
    user_a = await _create_user(db_session, email="r2fa_usera@example.com")
    user_b = await _create_user(db_session, email="r2fa_userb@example.com")

    token_for_a = await _mint_confirmation_token(db_session, user_id=user_a.id)

    async with await admin_client_factory(su_user) as client:
        response = await client.post(
            f"/web-api/v1/admin/users/{user_b.id}/reset-2fa",
            json=_base_payload(token_for_a),
        )
    assert response.status_code == 409, response.text
    body = response.json()
    assert body["detail"]["error"] == "ERR_INVALID_CONFIRMATION_TOKEN"


@pytest.mark.asyncio
async def test_reset_2fa_already_used_token_returns_409(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A confirmation_token must be one-time-use; second use returns 409."""
    from unittest.mock import AsyncMock

    import echoroo.services.email as email_svc

    monkeypatch.setattr(email_svc, "send_2fa_reset_dispatched", AsyncMock())

    su_user = await _create_user(db_session, email="r2fa_su_409reuse@example.com")
    await _create_superuser(db_session, user=su_user)
    target = await _create_user(db_session, email="r2fa_target_409reuse@example.com")

    token = await _mint_confirmation_token(db_session, user_id=target.id)

    async with await admin_client_factory(su_user) as client:
        # First use — must succeed (202)
        resp1 = await client.post(
            f"/web-api/v1/admin/users/{target.id}/reset-2fa",
            json=_base_payload(token),
        )
        assert resp1.status_code == 202, resp1.text

        # Second use — token is consumed; must return 409
        resp2 = await client.post(
            f"/web-api/v1/admin/users/{target.id}/reset-2fa",
            json=_base_payload(token),
        )
    assert resp2.status_code == 409, resp2.text
    body = resp2.json()
    assert body["detail"]["error"] in (
        "ERR_INVALID_CONFIRMATION_TOKEN",
        "ERR_ACTIVE_RESET_REQUEST",
    )


# ---------------------------------------------------------------------------
# 409 – duplicate active request
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reset_2fa_duplicate_active_request_returns_409(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second reset request for a user with a pending request must return 409."""
    from unittest.mock import AsyncMock

    import echoroo.services.email as email_svc

    monkeypatch.setattr(email_svc, "send_2fa_reset_dispatched", AsyncMock())

    su_user = await _create_user(db_session, email="r2fa_su_409dup@example.com")
    await _create_superuser(db_session, user=su_user)
    target = await _create_user(db_session, email="r2fa_target_409dup@example.com")

    token1 = await _mint_confirmation_token(db_session, user_id=target.id)
    token2 = await _mint_confirmation_token(db_session, user_id=target.id)

    async with await admin_client_factory(su_user) as client:
        resp1 = await client.post(
            f"/web-api/v1/admin/users/{target.id}/reset-2fa",
            json=_base_payload(token1),
        )
        assert resp1.status_code == 202, resp1.text

        # Second request: token2 is valid but there is already an active row.
        resp2 = await client.post(
            f"/web-api/v1/admin/users/{target.id}/reset-2fa",
            json={**_base_payload(token2), "support_ticket_id": "ZD-A11-002"},
        )
    assert resp2.status_code == 409, resp2.text
    body = resp2.json()
    assert body["detail"]["error"] == "ERR_ACTIVE_RESET_REQUEST"


# ---------------------------------------------------------------------------
# Happy path — default flow (skip_delay=false)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reset_2fa_happy_path_creates_pending_delay_request(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valid superuser + confirmation_token → 202, pending_delay row created."""
    from unittest.mock import AsyncMock

    import echoroo.services.email as email_svc

    mock_send = AsyncMock()
    monkeypatch.setattr(email_svc, "send_2fa_reset_dispatched", mock_send)

    su_user = await _create_user(db_session, email="r2fa_su_happy@example.com")
    await _create_superuser(db_session, user=su_user)
    target = await _create_user(db_session, email="r2fa_target_happy@example.com")

    before_request = datetime.now(UTC)
    token = await _mint_confirmation_token(db_session, user_id=target.id)

    async with await admin_client_factory(su_user) as client:
        response = await client.post(
            f"/web-api/v1/admin/users/{target.id}/reset-2fa",
            json=_base_payload(token),
        )

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == STATUS_PENDING_DELAY
    assert body["dispatch_at"] is not None
    assert body["approval_request_id"] is None
    request_id = UUID(body["request_id"])

    # DB row sanity check
    row = (
        await db_session.execute(
            sa.select(TwoFactorResetRequest).where(
                TwoFactorResetRequest.id == request_id
            )
        )
    ).scalar_one_or_none()
    assert row is not None
    assert row.status == STATUS_PENDING_DELAY
    assert row.user_id == target.id
    assert row.skip_delay is False
    assert row.dispatch_at is not None
    # dispatch_at should be approximately 24 hours from now
    expected_dispatch = before_request + timedelta(hours=23, minutes=50)
    assert row.dispatch_at >= expected_dispatch

    # The dispatched email is sent only when the poller runs, not at creation.
    # The mock should NOT have been called yet.
    mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_reset_2fa_happy_path_audit_rows_written(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """202 response must call trigger_create_request_audit with expected actions."""
    from unittest.mock import AsyncMock, patch

    import echoroo.services.email as email_svc

    monkeypatch.setattr(email_svc, "send_2fa_reset_dispatched", AsyncMock())

    su_user = await _create_user(db_session, email="r2fa_su_audit@example.com")
    await _create_superuser(db_session, user=su_user)
    target = await _create_user(db_session, email="r2fa_target_audit@example.com")
    token = await _mint_confirmation_token(db_session, user_id=target.id)

    audit_calls: list[dict] = []

    async def _capture_audit(**kwargs: object) -> None:
        audit_calls.append(dict(kwargs))

    # Patch at the import site used by admin.py
    import echoroo.services.two_factor_reset_service as tfs

    original_audit = tfs.trigger_create_request_audit
    monkeypatch.setattr(tfs, "trigger_create_request_audit", _capture_audit)

    async with await admin_client_factory(su_user) as client:
        response = await client.post(
            f"/web-api/v1/admin/users/{target.id}/reset-2fa",
            json=_base_payload(token),
        )
    assert response.status_code == 202, response.text

    # trigger_create_request_audit must have been called once
    assert len(audit_calls) == 1, f"Expected 1 audit call, got {len(audit_calls)}"
    call = audit_calls[0]
    assert "target_user_id" in call
    assert call["target_user_id"] == target.id
    # confirmation_token_nonce must be present (not the raw token)
    nonce = call.get("confirmation_token_nonce", "")
    assert nonce, "confirmation_token_nonce must be set in audit call"
    assert token not in str(nonce), (
        "Raw confirmation token must never appear in audit call"
    )


@pytest.mark.asyncio
async def test_reset_2fa_audit_detail_has_nonce_not_raw_token(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Audit call must include confirmation_token_nonce, not the raw token."""
    from unittest.mock import AsyncMock

    import echoroo.services.email as email_svc
    import echoroo.services.two_factor_reset_service as tfs

    monkeypatch.setattr(email_svc, "send_2fa_reset_dispatched", AsyncMock())

    su_user = await _create_user(db_session, email="r2fa_su_nonce@example.com")
    await _create_superuser(db_session, user=su_user)
    target = await _create_user(db_session, email="r2fa_target_nonce@example.com")
    token = await _mint_confirmation_token(db_session, user_id=target.id)

    audit_calls: list[dict] = []

    async def _capture_audit(**kwargs: object) -> None:
        audit_calls.append(dict(kwargs))

    monkeypatch.setattr(tfs, "trigger_create_request_audit", _capture_audit)

    async with await admin_client_factory(su_user) as client:
        response = await client.post(
            f"/web-api/v1/admin/users/{target.id}/reset-2fa",
            json=_base_payload(token),
        )
    assert response.status_code == 202, response.text

    assert audit_calls, "trigger_create_request_audit must have been called"
    call = audit_calls[0]
    nonce = str(call.get("confirmation_token_nonce", ""))
    assert nonce, "confirmation_token_nonce must be present"
    # The raw full token (header.payload.signature) must not appear in the nonce
    assert token not in nonce, (
        "Raw confirmation token must never be written to audit log"
    )


# ---------------------------------------------------------------------------
# Beat poller dispatch (run_dispatch_due_requests)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_due_requests_applies_reset(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """run_dispatch_due_requests applies a pending_delay row whose dispatch_at <= now."""
    from unittest.mock import AsyncMock

    import echoroo.services.email as email_svc
    from echoroo.services.two_factor_reset_service import run_dispatch_due_requests

    monkeypatch.setattr(email_svc, "send_2fa_reset_dispatched", AsyncMock())

    su_user = await _create_user(db_session, email="r2fa_su_dispatch@example.com")
    su_row = await _create_superuser(db_session, user=su_user)
    target = await _create_user(db_session, email="r2fa_target_dispatch@example.com")

    # Insert a row with dispatch_at in the past so it fires immediately.
    past = datetime.now(UTC) - timedelta(minutes=1)
    row = TwoFactorResetRequest(
        user_id=target.id,
        requested_by_superuser_id=su_row.id,
        support_ticket_id="ZD-DISPATCH-001",
        reason="Direct insert for poller test",
        status=STATUS_PENDING_DELAY,
        skip_delay=False,
        dispatch_at=past,
        expires_at=datetime.now(UTC) + timedelta(hours=71),
        confirmation_token_nonce=secrets.token_hex(32),
    )
    db_session.add(row)
    await db_session.commit()

    summary = await run_dispatch_due_requests(db_session)
    assert summary.applied == 1
    assert summary.failed == 0
    assert summary.cancelled == 0

    # User should no longer have 2FA enabled.
    await db_session.refresh(target)
    assert target.two_factor_enabled is False

    # Email notification should have been sent.
    email_svc.send_2fa_reset_dispatched.assert_called_once()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_dispatch_due_requests_cancels_if_user_deleted(
    db_session: AsyncSession,
) -> None:
    """Poller cancels (not fails) if the target user was deleted before dispatch."""
    import echoroo.services.email as email_svc
    from echoroo.services.two_factor_reset_service import run_dispatch_due_requests
    from unittest.mock import AsyncMock

    monkeypatch_email = AsyncMock()
    # Patch module-level so the import inside the service sees the mock
    original = email_svc.send_2fa_reset_dispatched
    email_svc.send_2fa_reset_dispatched = monkeypatch_email

    try:
        su_user = await _create_user(db_session, email="r2fa_su_del@example.com")
        su_row = await _create_superuser(db_session, user=su_user)
        target = await _create_user(db_session, email="r2fa_target_del@example.com")

        # Soft-delete the target user
        target.deleted_at = datetime.now(UTC) - timedelta(seconds=1)
        await db_session.commit()

        past = datetime.now(UTC) - timedelta(minutes=1)
        row = TwoFactorResetRequest(
            user_id=target.id,
            requested_by_superuser_id=su_row.id,
            support_ticket_id="ZD-DEL-001",
            reason="Target deleted test",
            status=STATUS_PENDING_DELAY,
            skip_delay=False,
            dispatch_at=past,
            expires_at=datetime.now(UTC) + timedelta(hours=71),
            confirmation_token_nonce=secrets.token_hex(32),
        )
        db_session.add(row)
        await db_session.commit()

        summary = await run_dispatch_due_requests(db_session)
        assert summary.cancelled == 1
        assert summary.applied == 0
        monkeypatch_email.assert_not_called()
    finally:
        email_svc.send_2fa_reset_dispatched = original


@pytest.mark.asyncio
async def test_dispatch_due_requests_cancels_if_2fa_already_disabled(
    db_session: AsyncSession,
) -> None:
    """Poller cancels if the target user no longer has 2FA enabled."""
    from echoroo.services.two_factor_reset_service import run_dispatch_due_requests

    su_user = await _create_user(db_session, email="r2fa_su_nodisable@example.com")
    su_row = await _create_superuser(db_session, user=su_user)
    target = await _create_user(
        db_session,
        email="r2fa_target_nodisable@example.com",
        two_factor_enabled=False,
    )

    past = datetime.now(UTC) - timedelta(minutes=1)
    row = TwoFactorResetRequest(
        user_id=target.id,
        requested_by_superuser_id=su_row.id,
        support_ticket_id="ZD-NODISABLE-001",
        reason="2FA already disabled test",
        status=STATUS_PENDING_DELAY,
        skip_delay=False,
        dispatch_at=past,
        expires_at=datetime.now(UTC) + timedelta(hours=71),
        confirmation_token_nonce=secrets.token_hex(32),
    )
    db_session.add(row)
    await db_session.commit()

    summary = await run_dispatch_due_requests(db_session)
    assert summary.cancelled == 1
    assert summary.applied == 0


@pytest.mark.asyncio
async def test_dispatch_due_requests_expires_overdue_rows(
    db_session: AsyncSession,
) -> None:
    """Poller expires rows past their expires_at before processing due rows."""
    from echoroo.services.two_factor_reset_service import run_dispatch_due_requests

    su_user = await _create_user(db_session, email="r2fa_su_expire@example.com")
    su_row = await _create_superuser(db_session, user=su_user)
    target = await _create_user(db_session, email="r2fa_target_expire@example.com")

    # Row whose expires_at is in the past — should be swept by the expiry pass.
    past_dispatch = datetime.now(UTC) - timedelta(hours=73)
    row = TwoFactorResetRequest(
        user_id=target.id,
        requested_by_superuser_id=su_row.id,
        support_ticket_id="ZD-EXPIRE-001",
        reason="Expiry test",
        status=STATUS_PENDING_DELAY,
        skip_delay=False,
        dispatch_at=past_dispatch,
        expires_at=past_dispatch + timedelta(hours=1),  # also in the past
        confirmation_token_nonce=secrets.token_hex(32),
    )
    db_session.add(row)
    await db_session.commit()

    summary = await run_dispatch_due_requests(db_session)
    assert summary.expired == 1
    assert summary.applied == 0


# ---------------------------------------------------------------------------
# Round-2 Fix-1 — email failure surfaces as ``email_notification_failed`` audit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_email_failure_writes_email_notification_failed_audit(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``send_2fa_reset_dispatched`` raises, the poller must write
    a ``two_factor_reset.email_notification_failed`` audit row with
    ``stage='applied_notification'`` while keeping the request in
    ``applied`` (the reset itself succeeded — only the user-facing
    notification mail failed).
    """
    import echoroo.services.email as email_svc
    from echoroo.services.two_factor_reset_service import run_dispatch_due_requests

    async def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated banner-enqueue outage")

    monkeypatch.setattr(email_svc, "send_2fa_reset_dispatched", _boom)

    su_user = await _create_user(db_session, email="r2fa_email_fail_su@example.com")
    su_row = await _create_superuser(db_session, user=su_user)
    target = await _create_user(db_session, email="r2fa_email_fail_target@example.com")

    past = datetime.now(UTC) - timedelta(minutes=1)
    row = TwoFactorResetRequest(
        user_id=target.id,
        requested_by_superuser_id=su_row.id,
        support_ticket_id="ZD-EMAILFAIL-001",
        reason="Email failure path test",
        status=STATUS_PENDING_DELAY,
        skip_delay=False,
        dispatch_at=past,
        expires_at=datetime.now(UTC) + timedelta(hours=71),
        confirmation_token_nonce=secrets.token_hex(32),
    )
    db_session.add(row)
    await db_session.commit()
    request_id = row.id

    summary = await run_dispatch_due_requests(db_session)
    # The reset itself must still succeed — only the notification mail failed.
    assert summary.applied == 1
    assert summary.failed == 0

    # Audit row must exist for the email failure (best-effort visibility).
    audit_rows = (
        await db_session.execute(
            sa.text(
                "SELECT detail FROM platform_audit_log "
                "WHERE action = 'two_factor_reset.email_notification_failed' "
                "ORDER BY created_at DESC LIMIT 5"
            )
        )
    ).fetchall()
    assert audit_rows, "email_notification_failed audit row must be written"
    found = any(
        str(request_id) in str(r[0])
        and (r[0] or {}).get("stage") == "applied_notification"
        for r in audit_rows
    )
    assert found, (
        "audit row for this request_id with stage='applied_notification' "
        "must be present"
    )


# ---------------------------------------------------------------------------
# Round-2 Fix-2 — stale ``dispatching`` reclaim sweep
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_reclaim_reverts_stale_dispatching_row(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A row stuck in ``dispatching`` past ``DISPATCH_RECLAIM_TIMEOUT``
    must be reverted back to ``pending_delay`` by the sweep, with a
    ``two_factor_reset.dispatching_reclaimed`` audit row written.

    Round-3 design note (Fix R2-2):
    The reclaim sweep sets ``dispatch_at = now()`` and clears
    ``dispatching_started_at`` so the **same** poll tick can re-claim
    the row — this is the deliberate immediate-retry behaviour. The
    test target user has 2FA enabled, so the same-tick re-dispatch
    runs to ``applied``. The user-facing "row was reclaimed" signal
    therefore lives in the ``two_factor_reset.dispatching_reclaimed``
    audit row, NOT in a lingering ``pending_delay`` status — we
    assert the audit row was emitted and the row reached a terminal
    success state in the same tick.
    """
    from echoroo.services.two_factor_reset_service import (
        DISPATCH_RECLAIM_TIMEOUT,
        run_dispatch_due_requests,
    )

    # Stub the user-facing notification email so a Resend outage does
    # not blow up the test. The reset itself is what matters.
    import echoroo.services.email as email_svc
    from unittest.mock import AsyncMock
    monkeypatch.setattr(email_svc, "send_2fa_reset_dispatched", AsyncMock())

    su_user = await _create_user(db_session, email="r2fa_reclaim_su@example.com")
    su_row = await _create_superuser(db_session, user=su_user)
    target = await _create_user(db_session, email="r2fa_reclaim_target@example.com")

    # Create a stuck ``dispatching`` row whose ``dispatching_started_at``
    # is older than the reclaim timeout.
    stale_started = datetime.now(UTC) - DISPATCH_RECLAIM_TIMEOUT - timedelta(minutes=1)
    from echoroo.models.two_factor_reset_request import (
        STATUS_APPLIED,
        STATUS_DISPATCHING,
    )
    row = TwoFactorResetRequest(
        user_id=target.id,
        requested_by_superuser_id=su_row.id,
        support_ticket_id="ZD-RECLAIM-001",
        reason="Reclaim sweep test",
        status=STATUS_DISPATCHING,
        skip_delay=False,
        dispatch_at=stale_started,
        dispatching_started_at=stale_started,
        expires_at=datetime.now(UTC) + timedelta(hours=71),
        confirmation_token_nonce=secrets.token_hex(32),
    )
    db_session.add(row)
    await db_session.commit()
    request_id = row.id

    summary = await run_dispatch_due_requests(db_session)
    # The reclaim sweep AND the same-tick re-dispatch should both fire.
    assert summary.applied == 1, (
        "the reclaimed row must be re-dispatched in the same tick "
        "(immediate-retry design)"
    )

    # Reload — the row is now in a terminal ``applied`` state with the
    # lease cleared.
    db_session.expire_all()
    refreshed = (
        await db_session.execute(
            sa.select(TwoFactorResetRequest).where(
                TwoFactorResetRequest.id == request_id
            )
        )
    ).scalar_one()
    assert refreshed.status == STATUS_APPLIED
    assert refreshed.dispatching_started_at is None

    # Audit row must exist for the reclaim event so on-call has signal
    # for repeat crashes.
    audit_rows = (
        await db_session.execute(
            sa.text(
                "SELECT detail FROM platform_audit_log "
                "WHERE action = 'two_factor_reset.dispatching_reclaimed' "
                "ORDER BY created_at DESC LIMIT 5"
            )
        )
    ).fetchall()
    assert any(str(request_id) in str(r[0]) for r in audit_rows), (
        "dispatching_reclaimed audit row must be written for the reverted "
        "request"
    )


@pytest.mark.asyncio
async def test_dispatch_reclaim_does_not_touch_recent_dispatching_row(
    db_session: AsyncSession,
) -> None:
    """A row in ``dispatching`` newer than the reclaim timeout must NOT
    be reverted (so we don't race against a healthy in-flight worker).
    """
    from echoroo.services.two_factor_reset_service import run_dispatch_due_requests

    su_user = await _create_user(db_session, email="r2fa_recent_su@example.com")
    su_row = await _create_superuser(db_session, user=su_user)
    target = await _create_user(db_session, email="r2fa_recent_target@example.com")

    fresh_started = datetime.now(UTC) - timedelta(seconds=30)
    from echoroo.models.two_factor_reset_request import STATUS_DISPATCHING
    row = TwoFactorResetRequest(
        user_id=target.id,
        requested_by_superuser_id=su_row.id,
        support_ticket_id="ZD-RECENT-001",
        reason="Recent dispatching row guard",
        status=STATUS_DISPATCHING,
        skip_delay=False,
        dispatch_at=fresh_started,
        dispatching_started_at=fresh_started,
        expires_at=datetime.now(UTC) + timedelta(hours=71),
        confirmation_token_nonce=secrets.token_hex(32),
    )
    db_session.add(row)
    await db_session.commit()
    request_id = row.id

    await run_dispatch_due_requests(db_session)

    db_session.expire_all()
    refreshed = (
        await db_session.execute(
            sa.select(TwoFactorResetRequest).where(
                TwoFactorResetRequest.id == request_id
            )
        )
    ).scalar_one()
    assert refreshed.status == STATUS_DISPATCHING
    assert refreshed.dispatching_started_at is not None


# ---------------------------------------------------------------------------
# Round-3 Fix R2-2 — lease + CAS guards against double-dispatch when a
# stalled worker's terminal flip races with a reclaim sweep
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_reclaim_does_not_double_dispatch_when_apply_in_progress(
    db_session: AsyncSession,
) -> None:
    """When ``_apply_one`` stalls past ``DISPATCH_RECLAIM_TIMEOUT`` and a
    reclaim sweep on another worker clears the lease, the original
    worker's terminal CAS UPDATE must affect 0 rows so the row is NOT
    flipped twice (and audit / counters are NOT double-fired).

    Round-3 Fix R2-2 contract:
    * Original worker captures ``dispatching_started_at`` as its lease.
    * Reclaim sweep clears that lease (sets it to NULL, status =
      pending_delay).
    * Original worker's terminal UPDATE gates on
      ``dispatching_started_at = :lease`` and therefore matches 0
      rows. The helper must return ``False`` and the caller MUST skip
      audit + counter writes so on-call doesn't see a phantom
      ``two_factor_reset.applied`` row for a row that never finished.
    """
    from echoroo.services.two_factor_reset_service import (
        STATUS_PENDING_DELAY as _SVC_PENDING_DELAY,
        _terminal_cas_update,
    )

    su_user = await _create_user(db_session, email="r2fa_lease_su@example.com")
    su_row = await _create_superuser(db_session, user=su_user)
    target = await _create_user(db_session, email="r2fa_lease_target@example.com")
    assert _SVC_PENDING_DELAY == STATUS_PENDING_DELAY  # sanity check

    # Plant a row in ``dispatching`` with a captured lease value.
    lease = datetime.now(UTC) - timedelta(seconds=10)
    from echoroo.models.two_factor_reset_request import (
        STATUS_APPLIED,
        STATUS_DISPATCHING,
    )
    row = TwoFactorResetRequest(
        user_id=target.id,
        requested_by_superuser_id=su_row.id,
        support_ticket_id="ZD-LEASE-001",
        reason="Lease + CAS test",
        status=STATUS_DISPATCHING,
        skip_delay=False,
        dispatch_at=lease,
        dispatching_started_at=lease,
        expires_at=datetime.now(UTC) + timedelta(hours=71),
        confirmation_token_nonce=secrets.token_hex(32),
    )
    db_session.add(row)
    await db_session.commit()
    request_id = row.id

    # Simulate "another worker has already reclaimed" by clearing the
    # lease on the row directly (this is what ``_reclaim_stale_dispatching``
    # would do after DISPATCH_RECLAIM_TIMEOUT elapses).
    await db_session.execute(
        sa.text(
            "UPDATE two_factor_reset_requests "
            "SET status = 'pending_delay', dispatching_started_at = NULL "
            "WHERE id = :id"
        ),
        {"id": request_id},
    )
    await db_session.commit()

    # The original worker now tries its terminal flip, holding the
    # ``lease`` value it captured BEFORE the reclaim. The CAS UPDATE
    # must affect 0 rows because (a) status is no longer ``dispatching``
    # AND (b) ``dispatching_started_at`` is no longer ``= :lease``.
    ok = await _terminal_cas_update(
        db_session,
        row_id=request_id,
        lease=lease,
        new_status=STATUS_APPLIED,
        failure_reason=None,
        applied_at=datetime.now(UTC),
    )
    assert ok is False, (
        "terminal CAS UPDATE must return False when the lease has been "
        "cleared by a concurrent reclaim — the caller MUST then skip "
        "audit + counter writes"
    )

    # Verify the row is still ``pending_delay`` (the reclaimed state)
    # and was NOT silently flipped to ``applied`` by our stale terminal
    # UPDATE — that would be the double-dispatch bug.
    db_session.expire_all()
    refreshed = (
        await db_session.execute(
            sa.select(TwoFactorResetRequest).where(
                TwoFactorResetRequest.id == request_id
            )
        )
    ).scalar_one()
    assert refreshed.status == STATUS_PENDING_DELAY, (
        "row must remain in pending_delay (the reclaimed state); the "
        "stale worker's terminal UPDATE must NOT have stomped on it"
    )


# ---------------------------------------------------------------------------
# Round-4 Fix R3-Blocker2 — pre-CAS check prevents destructive reset when
# the lease has already been cleared by a concurrent reclaim sweep.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_one_aborts_before_destructive_reset_when_lease_reclaimed(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the dispatch poller has captured a row in ``dispatching``
    but a concurrent reclaim sweep clears the lease BEFORE
    ``_apply_one`` reaches its destructive ``reset_user_two_factor``
    call, the pre-CAS lease re-confirmation must abort cleanly without
    flipping the user's ``two_factor_enabled`` to False.

    Without this guard the user's 2FA would be silently disabled while
    the request row remained in ``pending_delay`` (reclaimed) — the
    next cycle would observe ``two_factor_enabled=False`` and CANCEL
    the request, producing a catastrophic "applied but recorded as
    cancelled" inconsistency with no audit trail of the apply.
    """
    from echoroo.models.two_factor_reset_request import STATUS_DISPATCHING
    from echoroo.services.two_factor_reset_service import _apply_one

    # Fail loudly if anything below tries to actually wipe 2FA.
    reset_calls: list[UUID] = []

    async def _refuse_reset(  # noqa: ANN001
        self, user, *, actor_id, reason, commit=True
    ):
        reset_calls.append(user.id)
        raise AssertionError(
            "reset_user_two_factor must NOT be called when the lease has "
            "been reclaimed before the pre-CAS check"
        )

    import echoroo.services.two_factor_service as tfs_mod
    monkeypatch.setattr(
        tfs_mod.TwoFactorService, "reset_user_two_factor", _refuse_reset
    )

    su_user = await _create_user(db_session, email="r4_pre_cas_su@example.com")
    su_row = await _create_superuser(db_session, user=su_user)
    target = await _create_user(db_session, email="r4_pre_cas_target@example.com")
    target_id = target.id

    # Plant a row in ``dispatching`` with a captured lease.
    lease = datetime.now(UTC) - timedelta(seconds=10)
    row = TwoFactorResetRequest(
        user_id=target_id,
        requested_by_superuser_id=su_row.id,
        support_ticket_id="ZD-PRECAS-001",
        reason="pre-CAS R3-Blocker2 test",
        status=STATUS_DISPATCHING,
        skip_delay=False,
        dispatch_at=lease,
        dispatching_started_at=lease,
        expires_at=datetime.now(UTC) + timedelta(hours=71),
        confirmation_token_nonce=secrets.token_hex(32),
    )
    db_session.add(row)
    await db_session.commit()

    # Simulate "another worker reclaimed mid-flight" by clearing the
    # lease and reverting status BEFORE we call ``_apply_one``.
    await db_session.execute(
        sa.text(
            "UPDATE two_factor_reset_requests "
            "SET status = 'pending_delay', dispatching_started_at = NULL "
            "WHERE id = :id"
        ),
        {"id": row.id},
    )
    await db_session.commit()
    await db_session.refresh(row)

    # _apply_one should NOT raise and should NOT call reset_user_two_factor.
    # It should return False (lease lost).
    result = await _apply_one(
        db_session, row=row, current=datetime.now(UTC), lease=lease
    )
    assert result is False, (
        "pre-CAS check must abort and return False when the lease has "
        "been cleared by a concurrent reclaim — the destructive reset "
        "MUST NOT happen"
    )
    assert reset_calls == [], (
        "reset_user_two_factor must NOT be invoked once the pre-CAS "
        "ownership check has failed"
    )

    # Critical post-condition: the user's 2FA state must remain intact.
    db_session.expire_all()
    refreshed_user = await db_session.get(User, target_id)
    assert refreshed_user is not None
    assert refreshed_user.two_factor_enabled is True, (
        "target user's two_factor_enabled MUST remain True — the pre-CAS "
        "guard prevents the destructive reset when the lease was lost"
    )


# ---------------------------------------------------------------------------
# Round-5 Fix R4-Blocker — pre-CAS row lock blocks concurrent reclaim
# until ``_apply_one`` commits the terminal flip. Without the single-TX
# refactor, the reclaim sweep on another worker could clear the lease
# in the window between pre-CAS and terminal CAS, leaving the user's
# 2FA wiped while the request row got cancelled with no apply audit.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_one_holds_row_lock_blocking_concurrent_reclaim(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A concurrent reclaim sweep MUST block on the row lock acquired
    by ``_apply_one``'s pre-CAS UPDATE until ``_apply_one`` commits.

    Round-5 Fix R4-Blocker contract: pre-CAS UPDATE → user mutation →
    terminal CAS UPDATE → single commit, all under one transaction.
    The row lock is held continuously, so a reclaim sweep firing on
    another connection blocks at its ``UPDATE … WHERE status =
    'dispatching' …`` until our commit. Once we commit, the row's
    status is ``applied`` and the reclaim's WHERE no longer matches.

    Without the fix, the original Round-4 implementation committed
    after the pre-CAS check (line 1142), which released the row lock
    and let a reclaim sweep clear the lease back to NULL while
    ``reset_user_two_factor`` ran. The terminal CAS would then miss,
    leaving "user 2FA wiped, request row reverted to pending_delay,
    next cycle cancels" — the catastrophic inconsistency.
    """
    import asyncio
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from echoroo.models.two_factor_reset_request import (
        STATUS_APPLIED,
        STATUS_DISPATCHING,
    )
    from echoroo.services.two_factor_reset_service import (
        DISPATCH_RECLAIM_TIMEOUT,
        _apply_one,
        _reclaim_stale_dispatching,
    )
    import echoroo.services.email as email_svc
    from unittest.mock import AsyncMock

    # Round-6 Fix R5-Minor: import the conftest-resolved URL so this
    # test honours the TEST_DATABASE_URL env var with the same default
    # as the rest of the test suite (``localhost:5432`` for host runs,
    # ``db:5432`` when ``TEST_DATABASE_URL`` is exported in CI / docker).
    # Hard-coding ``db:5432`` here used to break ``uv run pytest`` from
    # the project root because no other fixture in this module needs
    # the URL — the env var was never set on the host shell path.
    from tests.conftest import TEST_DATABASE_URL

    monkeypatch.setattr(email_svc, "send_2fa_reset_dispatched", AsyncMock())

    su_user = await _create_user(db_session, email="r5_lock_block_su@example.com")
    su_row = await _create_superuser(db_session, user=su_user)
    target = await _create_user(db_session, email="r5_lock_block_target@example.com")
    target_id = target.id

    # Plant a row in ``dispatching`` whose lease is OLD enough that the
    # reclaim sweep would normally clear it. The bug-or-fix verdict
    # turns on whether the reclaim's UPDATE blocks (fixed) or proceeds
    # in parallel with our half-committed mutation (broken).
    old_lease = datetime.now(UTC) - DISPATCH_RECLAIM_TIMEOUT - timedelta(seconds=5)
    row = TwoFactorResetRequest(
        user_id=target_id,
        requested_by_superuser_id=su_row.id,
        support_ticket_id="ZD-R5-LOCK-001",
        reason="R5 lock-blocking regression",
        status=STATUS_DISPATCHING,
        skip_delay=False,
        dispatch_at=old_lease,
        dispatching_started_at=old_lease,
        expires_at=datetime.now(UTC) + timedelta(hours=71),
        confirmation_token_nonce=secrets.token_hex(32),
    )
    db_session.add(row)
    await db_session.commit()
    row_id = row.id

    # Build two independent async sessions on the SAME engine so they
    # see real PostgreSQL row-level locking (a single AsyncSession
    # would serialize at the asyncpg connection layer and never
    # exercise the lock contention we care about).
    engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    sessmaker = async_sessionmaker(engine, expire_on_commit=False)

    apply_session = sessmaker()
    reclaim_session = sessmaker()

    # Slow stub for ``reset_user_two_factor`` so we have a deterministic
    # window during which the reclaim sweep races us. The stub mimics
    # the new ``commit=False`` contract so the surrounding TX in
    # ``_apply_one`` stays open.
    apply_call_started = asyncio.Event()
    release_apply = asyncio.Event()

    async def _slow_reset(self, user, *, actor_id, reason, commit=True):  # noqa: ANN001, ARG001
        # Stage user mutation just like the real method — we want the
        # surrounding TX to look identical to a real apply (DEK column
        # writes, security stamp rotation, etc.) so any locking
        # surprise is exposed.
        user.two_factor_enabled = False
        user.two_factor_secret_encrypted = None
        user.two_factor_secret_dek_version = None
        user.two_factor_backup_codes_hashed = None
        self.db.add(user)
        if commit:
            await self.db.commit()
        else:
            await self.db.flush()
        apply_call_started.set()
        # Hold inside the destructive call so the reclaim task gets a
        # chance to fire while our row lock is still held.
        await release_apply.wait()

    import echoroo.services.two_factor_service as tfs_mod
    monkeypatch.setattr(
        tfs_mod.TwoFactorService, "reset_user_two_factor", _slow_reset
    )

    # Re-fetch the row in the apply_session so ``_apply_one`` sees its
    # own ORM identity-map entry.
    apply_row = await apply_session.get(TwoFactorResetRequest, row_id)
    assert apply_row is not None

    async def _drive_apply() -> bool:
        return await _apply_one(
            apply_session,
            row=apply_row,
            current=datetime.now(UTC),
            lease=old_lease,
        )

    async def _drive_reclaim() -> int:
        # Wait until ``_apply_one`` has reached the destructive call so
        # the row lock is definitely held.
        await apply_call_started.wait()
        # The reclaim's UPDATE should BLOCK on the row lock until we
        # release the apply task. We give it a short window to prove
        # blocking; if it returns quickly with a non-zero count, the
        # row lock was NOT held and the fix is broken.
        return await _reclaim_stale_dispatching(
            reclaim_session, current=datetime.now(UTC)
        )

    apply_task = asyncio.create_task(_drive_apply())
    reclaim_task = asyncio.create_task(_drive_reclaim())

    # Hold the apply task for a beat so the reclaim task definitely
    # tries to acquire the row lock first and ends up waiting.
    await apply_call_started.wait()
    await asyncio.sleep(0.5)
    # The reclaim must NOT have completed yet — proves it is blocked
    # on the row lock held by the apply task.
    assert not reclaim_task.done(), (
        "reclaim sweep completed while _apply_one was still holding "
        "the destructive section — the row lock was NOT held; this is "
        "the R4-Blocker race that Round-5 was supposed to close"
    )

    # Release the apply task; once it commits, the row lock drops and
    # the reclaim's UPDATE re-evaluates its WHERE — by which point the
    # row is ``applied`` so the reclaim sees 0 matches.
    release_apply.set()
    apply_ok = await asyncio.wait_for(apply_task, timeout=10.0)
    reclaim_count = await asyncio.wait_for(reclaim_task, timeout=10.0)

    assert apply_ok is True, "_apply_one should succeed once unblocked"
    assert reclaim_count == 0, (
        f"reclaim should affect 0 rows because the row is now 'applied' "
        f"(got {reclaim_count}); a non-zero count means the reclaim "
        f"raced with our apply"
    )

    # Final state inspection in a fresh session so we read committed
    # state (not the apply_session's identity map).
    inspect_session = sessmaker()
    final = await inspect_session.get(TwoFactorResetRequest, row_id)
    assert final is not None
    assert final.status == STATUS_APPLIED, (
        f"row must be 'applied' (got {final.status}); a 'pending_delay' "
        f"or 'cancelled' state would mean the reclaim won the race"
    )
    assert final.dispatching_started_at is None
    final_user = await inspect_session.get(User, target_id)
    assert final_user is not None
    assert final_user.two_factor_enabled is False, (
        "user 2FA must be wiped (the apply path completed atomically)"
    )
    await inspect_session.close()
    await apply_session.close()
    await reclaim_session.close()
    await engine.dispose()


# ---------------------------------------------------------------------------
# Round-4 Fix R3-Blocker1 — atomic claim+stamp prevents lock-release race
# (commit inside the per-row loop used to release locks for the WHOLE
# batch, allowing a concurrent worker to finish a row that this worker
# would then re-stamp back to ``dispatching``).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_batch_claim_does_not_re_stamp_already_finalized_row(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The atomic claim+stamp UPDATE must filter on
    ``status IN DISPATCHABLE_STATUSES`` so a row that was concurrently
    finalized (e.g. ``applied`` by another worker) is NOT picked up
    again and re-stamped back to ``dispatching``.

    Round-4 Fix R3-Blocker1 contract: the single
    ``UPDATE ... WHERE id IN (SELECT ... FOR UPDATE SKIP LOCKED)``
    holds the row lock through the UPDATE so a row that has been
    concurrently flipped to a terminal status by another worker fails
    the inner SELECT's status filter and is NOT touched.
    """
    from echoroo.models.two_factor_reset_request import (
        STATUS_APPLIED,
        STATUS_DISPATCHING,
    )
    from echoroo.services.two_factor_reset_service import (
        run_dispatch_due_requests,
    )

    import echoroo.services.email as email_svc
    from unittest.mock import AsyncMock
    monkeypatch.setattr(email_svc, "send_2fa_reset_dispatched", AsyncMock())

    su_user = await _create_user(db_session, email="r4_batch_claim_su@example.com")
    su_row = await _create_superuser(db_session, user=su_user)
    target_a = await _create_user(db_session, email="r4_batch_a@example.com")
    target_b = await _create_user(db_session, email="r4_batch_b@example.com")

    past = datetime.now(UTC) - timedelta(minutes=1)

    # Row A — already finalized by an "imaginary other worker" before
    # this poller runs; it sits in ``applied``. It must be ignored by
    # the claim UPDATE (status filter excludes ``applied``).
    row_a = TwoFactorResetRequest(
        user_id=target_a.id,
        requested_by_superuser_id=su_row.id,
        support_ticket_id="ZD-BATCH-A",
        reason="row A — already applied",
        status=STATUS_APPLIED,
        skip_delay=False,
        dispatch_at=past,
        dispatching_started_at=None,
        applied_at=datetime.now(UTC) - timedelta(seconds=5),
        expires_at=datetime.now(UTC) + timedelta(hours=71),
        confirmation_token_nonce=secrets.token_hex(32),
    )
    # Row B — a normal due row that should be processed normally.
    row_b = TwoFactorResetRequest(
        user_id=target_b.id,
        requested_by_superuser_id=su_row.id,
        support_ticket_id="ZD-BATCH-B",
        reason="row B — normal due row",
        status=STATUS_PENDING_DELAY,
        skip_delay=False,
        dispatch_at=past,
        expires_at=datetime.now(UTC) + timedelta(hours=71),
        confirmation_token_nonce=secrets.token_hex(32),
    )
    db_session.add_all([row_a, row_b])
    await db_session.commit()
    row_a_id = row_a.id
    row_b_id = row_b.id

    summary = await run_dispatch_due_requests(db_session)
    # Only row B should be processed.
    assert summary.applied == 1, (
        "row B should be applied, row A must NOT be re-stamped"
    )
    assert summary.inspected == 1, "row A must NOT enter the per-row loop"

    # Row A must remain in ``applied`` — never re-stamped to dispatching.
    db_session.expire_all()
    refreshed_a = await db_session.get(TwoFactorResetRequest, row_a_id)
    assert refreshed_a is not None
    assert refreshed_a.status == STATUS_APPLIED, (
        "row A must remain in 'applied' — the atomic claim+stamp must "
        "NOT pick up rows that are already in a terminal status"
    )
    assert refreshed_a.dispatching_started_at is None, (
        "row A's dispatching_started_at must remain NULL (never re-stamped)"
    )

    # Row B should now be ``applied``.
    refreshed_b = await db_session.get(TwoFactorResetRequest, row_b_id)
    assert refreshed_b is not None
    assert refreshed_b.status == STATUS_APPLIED


# ---------------------------------------------------------------------------
# Round-2 Fix-3 / Fix-4 — confirmation token replay audit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reset_2fa_confirmation_token_replay_writes_replay_audit(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the same confirmation_token is replayed (used twice), the
    second call must return 409 AND a
    ``two_factor_reset.confirmation_token_replay_attempted`` audit row
    must be written so on-call can spot the replay.
    """
    from unittest.mock import AsyncMock

    import echoroo.services.email as email_svc

    monkeypatch.setattr(email_svc, "send_2fa_reset_dispatched", AsyncMock())

    su_user = await _create_user(db_session, email="r2fa_replay_su@example.com")
    await _create_superuser(db_session, user=su_user)
    target = await _create_user(db_session, email="r2fa_replay_target@example.com")
    # Capture the UUID up front — the admin endpoint shares ``db_session``
    # via the dependency override and may expire ORM attributes through
    # rollback/commit, leaving ``target.id`` unsafe to access later.
    target_id = target.id
    token = await _mint_confirmation_token(db_session, user_id=target_id)

    async with await admin_client_factory(su_user) as client:
        resp1 = await client.post(
            f"/web-api/v1/admin/users/{target_id}/reset-2fa",
            json=_base_payload(token),
        )
        assert resp1.status_code == 202, resp1.text

        # Replay — token has been consumed.
        resp2 = await client.post(
            f"/web-api/v1/admin/users/{target_id}/reset-2fa",
            json=_base_payload(token),
        )
    assert resp2.status_code == 409, resp2.text
    body = resp2.json()
    assert body["detail"]["error"] in (
        "ERR_INVALID_CONFIRMATION_TOKEN",
        "ERR_ACTIVE_RESET_REQUEST",
    )

    # Replay audit row must exist.
    audit_rows = (
        await db_session.execute(
            sa.text(
                "SELECT detail FROM platform_audit_log "
                "WHERE action = 'two_factor_reset.confirmation_token_replay_attempted' "
                "ORDER BY created_at DESC LIMIT 5"
            )
        )
    ).fetchall()
    assert audit_rows, (
        "confirmation_token_replay_attempted audit row must be written when a "
        "consumed token is presented again"
    )
    # The detail must NOT contain the raw token; it should contain the
    # target_user_id.
    has_target = any(str(target_id) in str(r[0]) for r in audit_rows)
    assert has_target, "replay audit detail must reference the target user_id"
    no_raw_token = all(token not in str(r[0]) for r in audit_rows)
    assert no_raw_token, "raw confirmation token must NEVER appear in audit"


# ---------------------------------------------------------------------------
# Round-2 Fix-3 — serial double-submit returns 409 ERR_ACTIVE_RESET_REQUEST
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reset_2fa_serial_double_submit_returns_409_active_reset(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two serial reset requests for the same user (with separate
    confirmation tokens) must yield 202 then 409 ERR_ACTIVE_RESET_REQUEST
    — even if the partial unique index races against the SELECT
    pre-check in ``create_request`` (Round-2 Fix-3 IntegrityError
    translation).

    The serial flow exercises the same code path the IntegrityError
    fallback handles (since the explicit ``ActiveResetRequestExistsError``
    pre-check fires first); the test guarantees the deterministic 409
    body envelope is returned regardless of which path triggers.
    """
    from unittest.mock import AsyncMock

    import echoroo.services.email as email_svc

    monkeypatch.setattr(email_svc, "send_2fa_reset_dispatched", AsyncMock())

    su_user = await _create_user(db_session, email="r2fa_serial_su@example.com")
    await _create_superuser(db_session, user=su_user)
    target = await _create_user(db_session, email="r2fa_serial_target@example.com")

    token_a = await _mint_confirmation_token(db_session, user_id=target.id)
    token_b = await _mint_confirmation_token(db_session, user_id=target.id)

    async with await admin_client_factory(su_user) as client:
        first = await client.post(
            f"/web-api/v1/admin/users/{target.id}/reset-2fa",
            json=_base_payload(token_a),
        )
        assert first.status_code == 202, first.text

        second = await client.post(
            f"/web-api/v1/admin/users/{target.id}/reset-2fa",
            json={**_base_payload(token_b), "support_ticket_id": "ZD-SERIAL-002"},
        )
    assert second.status_code == 409, second.text
    body = second.json()
    assert body["detail"]["error"] == "ERR_ACTIVE_RESET_REQUEST"


# ---------------------------------------------------------------------------
# Round-6 Fix R5-Blocker — audit failure must not poison the user mutation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_one_audit_failure_does_not_commit_user_dirty_mutation(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If anything between the destructive flush and the outer commit
    raises, ``_apply_one`` MUST roll back the user dirty mutation
    BEFORE the ``failed`` CAS publishes the request row's terminal
    status. Without the rollback, autoflush inside the failed-CAS
    UPDATE would persist the user 2FA wipe alongside the ``failed``
    flip, producing the silent "request=failed but user 2FA wiped
    with no reset_completed audit" inconsistency Round-5 Codex flagged.

    We simulate the post-flush failure by patching
    :func:`TwoFactorService.reset_user_two_factor` to (a) stage the
    destructive user mutation via ``session.flush`` exactly like the
    real method does and then (b) raise a synthetic exception. The
    ``except Exception`` arm in :func:`run_dispatch_due_requests`
    should rollback first, then fire the ``failed`` CAS, leaving the
    user's 2FA state intact.
    """
    from echoroo.models.two_factor_reset_request import (
        STATUS_DISPATCHING,
        STATUS_FAILED,
    )
    from echoroo.services.two_factor_reset_service import (
        run_dispatch_due_requests,
    )
    import echoroo.services.two_factor_service as tfs_mod

    su_user = await _create_user(db_session, email="r6_audit_fail_su@example.com")
    su_row = await _create_superuser(db_session, user=su_user)
    target = await _create_user(db_session, email="r6_audit_fail_target@example.com")
    target_id = target.id

    past = datetime.now(UTC) - timedelta(seconds=30)
    row = TwoFactorResetRequest(
        user_id=target_id,
        requested_by_superuser_id=su_row.id,
        support_ticket_id="ZD-R6-AUDIT-FAIL",
        reason="R6 audit-fail rollback regression",
        status=STATUS_PENDING_DELAY,
        skip_delay=False,
        dispatch_at=past,
        expires_at=datetime.now(UTC) + timedelta(hours=71),
        confirmation_token_nonce=secrets.token_hex(32),
    )
    db_session.add(row)
    await db_session.commit()
    row_id = row.id

    async def _stage_then_raise(  # noqa: ANN001
        self, user, *, actor_id, reason, commit=True
    ):
        # Mimic the real method's destructive flush so the user
        # dirty mutation is staged in the session...
        user.two_factor_enabled = False
        user.two_factor_secret_encrypted = None
        user.two_factor_secret_dek_version = None
        user.two_factor_backup_codes_hashed = None
        self.db.add(user)
        if commit:
            await self.db.commit()
        else:
            await self.db.flush()
        # ...then explode AFTER flush, BEFORE outer commit. Simulates
        # a post-flush failure (KMS hiccup, audit chain misconfig, etc.)
        raise RuntimeError("synthetic post-flush failure for R5-Blocker regression")

    monkeypatch.setattr(
        tfs_mod.TwoFactorService, "reset_user_two_factor", _stage_then_raise
    )

    summary = await run_dispatch_due_requests(db_session)
    assert summary.failed == 1, "the synthetic failure must mark the row failed"
    assert summary.applied == 0

    # Inspect committed state. Use a fresh ``expire_all`` so we read
    # what is actually in the DB and not the session's identity map
    # (the failed CAS commit refreshes the request row but not the
    # user row).
    db_session.expire_all()
    refreshed_row = await db_session.get(TwoFactorResetRequest, row_id)
    assert refreshed_row is not None
    assert refreshed_row.status == STATUS_FAILED
    refreshed_user = await db_session.get(User, target_id)
    assert refreshed_user is not None
    # The user's 2FA state MUST be intact — the rollback before the
    # failed CAS dropped the dirty mutation. A True here would mean the
    # rollback was missing and the destructive flush leaked into the
    # failed-CAS commit alongside the terminal flip.
    assert refreshed_user.two_factor_enabled is True, (
        "user 2FA wipe leaked into the failed-CAS commit; the "
        "rollback before _terminal_cas_update is missing"
    )
    assert refreshed_user.two_factor_secret_encrypted == b"dummy-encrypted-secret"


@pytest.mark.asyncio
async def test_apply_one_reset_completed_audit_lands_post_commit(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ``two_factor.reset_completed`` audit row MUST be written
    AFTER ``_apply_one``'s outer commit, not from inside
    :meth:`TwoFactorService.reset_user_two_factor` BEFORE the commit.

    Round-6 Fix R5-Major. The ``commit=False`` contract returns the
    audit envelope to the caller; the caller writes it via the
    fresh-session ``_write_platform_audit`` (FR-088 soft alert). This
    test asserts that contract by inspecting the ORDER of audit row
    writes — the ``reset_completed`` row must appear AFTER the
    ``two_factor_reset.dispatched`` row (which is itself written
    post-commit), and it must reference the request's user_id in its
    detail payload so dashboards can correlate.
    """
    from echoroo.models.two_factor_reset_request import (
        STATUS_APPLIED,
    )
    from echoroo.services.two_factor_reset_service import (
        run_dispatch_due_requests,
    )

    import echoroo.services.email as email_svc
    from unittest.mock import AsyncMock
    monkeypatch.setattr(email_svc, "send_2fa_reset_dispatched", AsyncMock())

    su_user = await _create_user(db_session, email="r6_audit_order_su@example.com")
    su_row = await _create_superuser(db_session, user=su_user)
    target = await _create_user(db_session, email="r6_audit_order_target@example.com")
    target_id = target.id

    past = datetime.now(UTC) - timedelta(seconds=30)
    row = TwoFactorResetRequest(
        user_id=target_id,
        requested_by_superuser_id=su_row.id,
        support_ticket_id="ZD-R6-AUDIT-ORDER",
        reason="R6 reset_completed post-commit ordering",
        status=STATUS_PENDING_DELAY,
        skip_delay=False,
        dispatch_at=past,
        expires_at=datetime.now(UTC) + timedelta(hours=71),
        confirmation_token_nonce=secrets.token_hex(32),
    )
    db_session.add(row)
    await db_session.commit()
    row_id = row.id

    summary = await run_dispatch_due_requests(db_session)
    assert summary.applied == 1

    # Request row reached ``applied`` — i.e. the outer commit succeeded
    # before any post-commit audit landed.
    db_session.expire_all()
    refreshed_row = await db_session.get(TwoFactorResetRequest, row_id)
    assert refreshed_row is not None
    assert refreshed_row.status == STATUS_APPLIED

    # Inspect the audit trail. The patched ``_stub_write`` in this
    # module's ``patch_audit_session`` autouse fixture writes minimal
    # rows into the test ``db_session``; row ordering is created_at
    # (default NOW()) which we proxy via the implicit serial ``id`` if
    # equal timestamps tie.
    audit_rows = (
        await db_session.execute(
            sa.text(
                "SELECT action, detail::text FROM platform_audit_log "
                "WHERE detail::text LIKE :req_id "
                "ORDER BY created_at ASC, id ASC"
            ),
            {"req_id": f"%{row_id}%"},
        )
    ).fetchall()
    actions = [r[0] for r in audit_rows]
    # Must contain the post-commit triplet in order (dispatched
    # before reset_completed before applied — see _apply_one's tail
    # block).
    assert "two_factor_reset.dispatched" in actions
    assert "two_factor.reset_completed" in actions, (
        "reset_completed audit row must be written post-commit by "
        "_apply_one (Round-6 Fix R5-Major)"
    )
    assert "two_factor_reset.applied" in actions
    dispatched_idx = actions.index("two_factor_reset.dispatched")
    reset_idx = actions.index("two_factor.reset_completed")
    applied_idx = actions.index("two_factor_reset.applied")
    assert dispatched_idx < reset_idx < applied_idx, (
        f"audit ordering must be dispatched -> reset_completed -> applied, "
        f"got actions={actions}"
    )

    # The reset_completed detail must carry the target user's id so on-call
    # can correlate (no raw email / PII; just the UUID).
    reset_detail = audit_rows[reset_idx][1]
    assert str(target_id) in reset_detail
    assert "cooldown_hours" in reset_detail
