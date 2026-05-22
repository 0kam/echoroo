"""Integration tests for POST /auth/confirm-identity-for-2fa-reset (Phase 17 A-11).

Covers the user-facing magic-link issuance + redeem endpoints:

1. POST /auth/confirm-identity-for-2fa-reset
   - Always 202 (enumeration defence)
   - Unknown email → 202 (no email sent)
   - Known email with 2FA enabled → 202 + magic link persisted

2. POST /auth/confirm-identity-for-2fa-reset/redeem
   - Valid magic_token → 200 + confirmation_token + expires_at
   - Expired magic_token → 400
   - Already-used magic_token → 400
   - Invalid/random magic_token → 400

Spec references: FR-072, auth.yaml (confirm-identity), PHASE17_BACKLOG A-11.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import AsyncGenerator, AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.api.web_v1.auth_confirm_identity import router as confirm_identity_router
from echoroo.core.database import get_db
from echoroo.models.two_factor_reset_request import (
    TwoFactorResetMagicLink,
)
from echoroo.models.user import User
from echoroo.services.two_factor_reset_service import (
    _hash_magic_link,
    issue_magic_link,
)

# ---------------------------------------------------------------------------
# Helper: create users
# ---------------------------------------------------------------------------


async def _create_user(
    db: AsyncSession,
    *,
    email: str,
    two_factor_enabled: bool = True,
) -> User:
    user = User(
        email=email,
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$confirm-identity-test",
        display_name=f"User {email}",
        security_stamp=secrets.token_hex(32),
        two_factor_enabled=two_factor_enabled,
        two_factor_secret_encrypted=b"dummy-encrypted-secret" if two_factor_enabled else None,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# App fixture — only the auth_confirm_identity router mounted
# ---------------------------------------------------------------------------


@pytest.fixture
async def auth_app(db_session: AsyncSession) -> FastAPI:
    """Minimal FastAPI app with only the confirm-identity router."""
    app = FastAPI()
    app.include_router(confirm_identity_router, prefix="/web-api/v1")

    async def _override_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    return app


@pytest.fixture
async def auth_client(auth_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=auth_app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        yield client


@pytest.fixture(autouse=True)
def patch_audit_session(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Insert audit rows into the test session directly (Round-3 R2-1).

    Both ``two_factor_reset_service._write_platform_audit`` (service
    layer) and the endpoint's local ``_write_audit`` helper open
    fresh sessions via ``AsyncSessionLocal`` bound to the production
    engine — audit rows therefore commit to the wrong DB and the
    test SELECT returns empty. We stub both writers to insert via
    ``db_session`` so visibility is guaranteed.
    """
    import json

    import echoroo.api.web_v1.auth_confirm_identity as endpoint_mod
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

    async def _stub_endpoint_write(*, request, actor_user_id, action, detail) -> None:  # noqa: ANN001, ARG001
        await _stub_write(action=action, detail=detail)

    monkeypatch.setattr(svc_mod, "_write_platform_audit", _stub_write)
    monkeypatch.setattr(endpoint_mod, "_write_audit", _stub_endpoint_write)


# ---------------------------------------------------------------------------
# POST /confirm-identity-for-2fa-reset — enumeration defence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirm_identity_always_returns_202_for_unknown_email(
    auth_client: AsyncClient,
) -> None:
    """Unknown email must still return 202 (enumeration defence)."""
    response = await auth_client.post(
        "/web-api/v1/auth/confirm-identity-for-2fa-reset",
        json={"email": "nobody-knows-me@example.com"},
    )
    assert response.status_code == 202, response.text


@pytest.mark.asyncio
async def test_confirm_identity_always_returns_202_for_invalid_email(
    auth_client: AsyncClient,
) -> None:
    """Syntactically invalid email must still return 202 (not 422)."""
    response = await auth_client.post(
        "/web-api/v1/auth/confirm-identity-for-2fa-reset",
        json={"email": "not-an-email"},
    )
    assert response.status_code == 202, response.text


@pytest.mark.asyncio
async def test_confirm_identity_returns_202_when_no_2fa_enrolled(
    db_session: AsyncSession,
    auth_client: AsyncClient,
) -> None:
    """A known user without 2FA enrolled must return 202 (no magic link)."""
    user = await _create_user(
        db_session,
        email="ci_no2fa@example.com",
        two_factor_enabled=False,
    )
    response = await auth_client.post(
        "/web-api/v1/auth/confirm-identity-for-2fa-reset",
        json={"email": user.email},
    )
    assert response.status_code == 202, response.text

    # No magic link should have been persisted
    count = (
        await db_session.execute(
            sa.select(sa.func.count()).where(
                TwoFactorResetMagicLink.user_id == user.id
            )
        )
    ).scalar_one()
    assert count == 0


@pytest.mark.asyncio
async def test_confirm_identity_with_2fa_user_persists_magic_link(
    db_session: AsyncSession,
    auth_client: AsyncClient,
) -> None:
    """Known user with 2FA enabled → 202 and a magic link row is persisted.

    spec/011 Step 4 (T403): the outbound-email branch is removed from
    ``two_factor_reset_service.issue_magic_link``; the helper now only
    persists the magic-link hash row. The previous "email dispatched"
    side-effect assertion is therefore gone — the persistence
    invariant alone is the contract a caller relies on.
    """
    user = await _create_user(db_session, email="ci_with2fa@example.com")

    response = await auth_client.post(
        "/web-api/v1/auth/confirm-identity-for-2fa-reset",
        json={"email": user.email},
    )
    assert response.status_code == 202, response.text

    # A magic link row should have been created
    link_rows = (
        await db_session.execute(
            sa.select(TwoFactorResetMagicLink).where(
                TwoFactorResetMagicLink.user_id == user.id
            )
        )
    ).scalars().all()
    assert len(link_rows) == 1
    link = link_rows[0]
    assert link.redeemed_at is None
    assert link.expires_at > datetime.now(UTC)


# ---------------------------------------------------------------------------
# POST /confirm-identity-for-2fa-reset/redeem
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redeem_valid_magic_link_returns_confirmation_token(
    db_session: AsyncSession,
    auth_client: AsyncClient,
) -> None:
    """A valid magic token must return 200 with a confirmation_token and expires_at.

    spec/011 Step 4 (T403): ``issue_magic_link`` no longer touches the
    email subsystem, so the previous email monkeypatch is removed.
    """
    user = await _create_user(db_session, email="ci_redeem_valid@example.com")

    # Issue a magic link via the service
    raw_token = await issue_magic_link(db_session, user=user)
    await db_session.commit()

    response = await auth_client.post(
        "/web-api/v1/auth/confirm-identity-for-2fa-reset/redeem",
        json={"magic_token": raw_token},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "confirmation_token" in body
    assert "expires_at" in body
    assert len(body["confirmation_token"]) > 10


@pytest.mark.asyncio
async def test_redeem_expired_magic_link_returns_400(
    db_session: AsyncSession,
    auth_client: AsyncClient,
) -> None:
    """An expired magic link must return 400 with ERR_INVALID_MAGIC_LINK."""
    user = await _create_user(db_session, email="ci_redeem_expired@example.com")

    # Insert a magic link that expired 10 minutes ago
    past = datetime.now(UTC) - timedelta(minutes=10)
    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_magic_link(raw_token)
    link = TwoFactorResetMagicLink(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=past,  # already expired
    )
    db_session.add(link)
    await db_session.commit()

    response = await auth_client.post(
        "/web-api/v1/auth/confirm-identity-for-2fa-reset/redeem",
        json={"magic_token": raw_token},
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body["detail"]["error"] == "ERR_INVALID_MAGIC_LINK"


@pytest.mark.asyncio
async def test_redeem_already_used_magic_link_returns_400(
    db_session: AsyncSession,
    auth_client: AsyncClient,
) -> None:
    """A magic link that has already been redeemed must return 400.

    spec/011 Step 4 (T403): ``issue_magic_link`` no longer touches the
    email subsystem, so the previous email monkeypatch is removed.
    """
    user = await _create_user(db_session, email="ci_redeem_used@example.com")

    raw_token = await issue_magic_link(db_session, user=user)
    await db_session.commit()

    # First redeem — must succeed
    resp1 = await auth_client.post(
        "/web-api/v1/auth/confirm-identity-for-2fa-reset/redeem",
        json={"magic_token": raw_token},
    )
    assert resp1.status_code == 200, resp1.text

    # Second redeem of the same token — must fail
    resp2 = await auth_client.post(
        "/web-api/v1/auth/confirm-identity-for-2fa-reset/redeem",
        json={"magic_token": raw_token},
    )
    assert resp2.status_code == 400, resp2.text
    body = resp2.json()
    assert body["detail"]["error"] == "ERR_INVALID_MAGIC_LINK"


@pytest.mark.asyncio
async def test_redeem_invalid_random_token_returns_400(
    auth_client: AsyncClient,
) -> None:
    """A completely random (non-existent) magic token must return 400."""
    response = await auth_client.post(
        "/web-api/v1/auth/confirm-identity-for-2fa-reset/redeem",
        json={"magic_token": secrets.token_urlsafe(32)},
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body["detail"]["error"] == "ERR_INVALID_MAGIC_LINK"


@pytest.mark.asyncio
async def test_redeem_missing_magic_token_field_returns_422(
    auth_client: AsyncClient,
) -> None:
    """Missing magic_token field must return 422 (schema validation)."""
    response = await auth_client.post(
        "/web-api/v1/auth/confirm-identity-for-2fa-reset/redeem",
        json={},
    )
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_redeem_returns_confirmation_token_valid_for_admin_endpoint(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The confirmation_token from redeem must be accepted by the admin reset endpoint."""
    from unittest.mock import AsyncMock

    import sqlalchemy as _sa

    import echoroo.services.email as email_svc
    from echoroo.api.web_v1.admin import router as admin_router
    from echoroo.middleware.auth import get_current_user_optional
    from echoroo.services.step_up_token_service import (
        SCOPE_ADMIN_DESTRUCTIVE,
        issue_step_up_token,
    )

    # spec/011 Step 4 (T403) removed ``send_2fa_reset_magic_link`` from
    # ``services.email``; only ``send_2fa_reset_dispatched`` (used by
    # the dispatcher poller) is still in-tree and worth mocking out
    # here to keep the test transport-free.
    monkeypatch.setattr(email_svc, "send_2fa_reset_dispatched", AsyncMock())

    # Build a combined app with both routers
    app = FastAPI()
    app.include_router(confirm_identity_router, prefix="/web-api/v1")
    app.include_router(admin_router, prefix="/web-api/v1")

    async def _override_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_db

    su_user = await _create_user(db_session, email="ci_e2e_su@example.com")
    await db_session.execute(
        _sa.text(
            """
            INSERT INTO superusers (user_id, added_by_id, added_at, webauthn_credentials, allowed_ip_cidrs)
            VALUES (:uid, NULL, now() - interval '1 day', '[]'::jsonb, ARRAY[]::varchar[])
            """
        ),
        {"uid": su_user.id},
    )
    await db_session.commit()

    async def _su_override() -> User | None:
        probe = await db_session.execute(
            _sa.text(
                "SELECT id FROM superusers WHERE user_id = :uid AND revoked_at IS NULL LIMIT 1"
            ),
            {"uid": su_user.id},
        )
        row = probe.scalar_one_or_none()
        su_user.is_superuser = row is not None  # type: ignore[attr-defined]
        su_user._superuser_id = row  # type: ignore[attr-defined]
        return su_user

    app.dependency_overrides[get_current_user_optional] = _su_override

    step_up_token, _ = issue_step_up_token(
        user_id=su_user.id,
        security_stamp=su_user.security_stamp,
        assertion_id="test-e2e-credential",
        scope=SCOPE_ADMIN_DESTRUCTIVE,
    )

    target = await _create_user(db_session, email="ci_e2e_target@example.com")

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"X-Step-Up-Token": step_up_token},
    ) as client:
        # 1. Issue magic link via service (would normally come from email click)
        raw_token = await issue_magic_link(db_session, user=target)
        await db_session.commit()

        # 2. Redeem magic link → get confirmation_token
        redeem_resp = await client.post(
            "/web-api/v1/auth/confirm-identity-for-2fa-reset/redeem",
            json={"magic_token": raw_token},
        )
        assert redeem_resp.status_code == 200, redeem_resp.text
        confirmation_token = redeem_resp.json()["confirmation_token"]

        # 3. Use confirmation_token in the admin reset endpoint
        reset_resp = await client.post(
            f"/web-api/v1/admin/users/{target.id}/reset-2fa",
            json={
                "support_ticket_id": "ZD-E2E-001",
                "reason": "End-to-end magic link flow test",
                "skip_delay": False,
                "confirmation_token": confirmation_token,
            },
        )
    assert reset_resp.status_code == 202, reset_resp.text
    body = reset_resp.json()
    assert body["status"] == "pending_delay"


# spec/011 Step 4 (T403): the historical
# ``test_request_confirm_identity_email_failure_writes_audit`` covered
# the Round-2 Fix-1 contract where ``issue_magic_link`` caught a
# ``send_2fa_reset_magic_link`` exception, wrote an
# ``email_notification_failed`` audit row and rolled back the
# supporting DB row. The zero-email deployment removed the email
# transport so the failure branch is no longer reachable; the test
# was deleted with the branch it was pinning.
