"""Destructive admin endpoints require a fresh step-up token (T979z).

Phase 16 Batch 6g-3: every destructive superuser admin endpoint
(``POST /admin/superusers``, ``POST /admin/superusers/{id}/revoke``,
``POST /admin/superusers/approval-requests/{id}/approve``,
``POST /admin/superusers/approval-requests/{id}/reject``,
``POST /admin/superusers/break-glass/enter``,
``PATCH /admin/superusers/{id}/ip-allowlist``) MUST refuse to execute
unless the request carries a valid ``X-Step-Up-Token`` header bound to
``scope='admin_destructive'``.

This is the **negative-control suite**: it exercises the absence of the
header, an expired token, a scope-mismatch token, and a structurally
invalid token, asserting the gate returns the standard envelope:

* missing → 401 ``step_up_token_required``
* expired → 401 ``step_up_token_expired``
* invalid → 401 ``step_up_token_invalid``
* scope mismatch → 403 ``step_up_token_scope_mismatch``

Positive controls live in
``tests/integration/api/web_v1/test_admin_superusers.py`` whose
fixture now injects a freshly-minted token automatically.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.api.web_v1.admin import router as admin_router
from echoroo.core.database import get_db
from echoroo.core.settings import get_settings
from echoroo.middleware.auth import get_current_user_optional
from echoroo.models.superuser import Superuser
from echoroo.models.user import User
from echoroo.services.step_up_token_service import (
    SCOPE_ADMIN_DESTRUCTIVE,
    STEP_UP_TOKEN_TYPE,
    issue_step_up_token,
)

# ---------------------------------------------------------------------------
# Helpers — mirror the admin_client_factory fixture in the integration suite.
# ---------------------------------------------------------------------------


async def _create_user(db: AsyncSession, *, email: str) -> User:
    user = User(
        email=email,
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$step-up-test",
        display_name=f"User {email}",
        security_stamp="0" * 64,
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


@pytest.fixture
async def admin_app(db_session: AsyncSession) -> FastAPI:
    app = FastAPI()
    app.include_router(admin_router, prefix="/web-api/v1")

    async def _override_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    return app


@pytest.fixture
async def superuser_user(db_session: AsyncSession) -> User:
    user = await _create_user(db_session, email="t979z_su@example.com")
    await _create_superuser(db_session, user=user)
    return user


@pytest.fixture
async def target_superuser(db_session: AsyncSession) -> Superuser:
    target_user = await _create_user(db_session, email="t979z_target@example.com")
    return await _create_superuser(db_session, user=target_user)


def _override_user(app: FastAPI, db: AsyncSession, user: User) -> None:
    """Match the production middleware behaviour (stamp ``is_superuser``)."""
    captured = db

    async def _override() -> User | None:
        from sqlalchemy import text as _sa_text

        probe = await captured.execute(
            _sa_text(
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


# Each entry: (endpoint method, url-builder taking target Superuser, optional body)
def _build_endpoints(target_superuser_id: UUID, ticket_id: UUID) -> list[
    tuple[str, str, dict | None]
]:
    return [
        ("POST", "/web-api/v1/admin/superusers",
         {"target_user_id": str(uuid4()), "allowed_ip_cidrs": []}),
        ("POST", f"/web-api/v1/admin/superusers/{target_superuser_id}/revoke", None),
        ("POST",
         f"/web-api/v1/admin/superusers/approval-requests/{ticket_id}/approve",
         None),
        ("POST",
         f"/web-api/v1/admin/superusers/approval-requests/{ticket_id}/reject",
         {"reason": "negative test"}),
        ("POST", "/web-api/v1/admin/superusers/break-glass/enter",
         {"reason": "step-up gate negative test"}),
        ("PATCH",
         f"/web-api/v1/admin/superusers/{target_superuser_id}/ip-allowlist",
         {"allowed_ip_cidrs": ["10.0.0.0/24"]}),
    ]


def _expired_step_up_token() -> str:
    settings = get_settings()
    past = datetime.now(UTC) - timedelta(seconds=600)
    payload = {
        "sub": str(uuid4()),
        "type": STEP_UP_TOKEN_TYPE,
        "scope": SCOPE_ADMIN_DESTRUCTIVE,
        "ss": "stamp",
        "aid": "aid",
        "jti": str(uuid4()),
        "iat": int(past.timestamp()) - 10,
        "exp": int(past.timestamp()),
    }
    return jwt.encode(
        payload, settings.web_session_secret, algorithm=settings.JWT_ALGORITHM
    )


def _wrong_scope_step_up_token(user_id: UUID, security_stamp: str) -> str:
    token, _ = issue_step_up_token(
        user_id=user_id,
        security_stamp=security_stamp,
        assertion_id="aid",
        scope="some_other_scope",
    )
    return token


# ===========================================================================
# Missing header → 401 step_up_token_required
# ===========================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,url_template,body",
    [
        ("POST", "/web-api/v1/admin/superusers",
         {"target_user_id": "00000000-0000-0000-0000-000000000001",
          "allowed_ip_cidrs": []}),
        ("POST", "/web-api/v1/admin/superusers/{target}/revoke", None),
        ("POST",
         "/web-api/v1/admin/superusers/approval-requests/{ticket}/approve",
         None),
        ("POST",
         "/web-api/v1/admin/superusers/approval-requests/{ticket}/reject",
         {"reason": "missing header"}),
        ("POST", "/web-api/v1/admin/superusers/break-glass/enter",
         {"reason": "missing header"}),
        ("PATCH", "/web-api/v1/admin/superusers/{target}/ip-allowlist",
         {"allowed_ip_cidrs": ["10.0.0.0/24"]}),
    ],
    ids=[
        "add_superuser",
        "revoke_superuser",
        "approve_request",
        "reject_request",
        "break_glass_enter",
        "ip_allowlist_update",
    ],
)
async def test_destructive_endpoint_without_step_up_header_returns_401(
    admin_app: FastAPI,
    db_session: AsyncSession,
    superuser_user: User,
    target_superuser: Superuser,
    method: str,
    url_template: str,
    body: dict | None,
) -> None:
    """No ``X-Step-Up-Token`` header → 401 ``step_up_token_required``."""
    _override_user(admin_app, db_session, superuser_user)
    url = url_template.format(target=target_superuser.id, ticket=uuid4())
    transport = ASGITransport(app=admin_app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.request(method, url, json=body)
    assert response.status_code == 401
    detail = response.json().get("detail", {})
    assert detail.get("error_code") == "step_up_token_required", detail


# ===========================================================================
# Expired token → 401 step_up_token_expired
# ===========================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,url_template,body",
    [
        ("POST", "/web-api/v1/admin/superusers",
         {"target_user_id": "00000000-0000-0000-0000-000000000001",
          "allowed_ip_cidrs": []}),
        ("POST", "/web-api/v1/admin/superusers/{target}/revoke", None),
        ("PATCH", "/web-api/v1/admin/superusers/{target}/ip-allowlist",
         {"allowed_ip_cidrs": ["10.0.0.0/24"]}),
    ],
    ids=["add_superuser", "revoke_superuser", "ip_allowlist_update"],
)
async def test_destructive_endpoint_with_expired_token_returns_401(
    admin_app: FastAPI,
    db_session: AsyncSession,
    superuser_user: User,
    target_superuser: Superuser,
    method: str,
    url_template: str,
    body: dict | None,
) -> None:
    """Expired token → 401 ``step_up_token_expired``."""
    _override_user(admin_app, db_session, superuser_user)
    url = url_template.format(target=target_superuser.id)
    transport = ASGITransport(app=admin_app)
    headers = {"X-Step-Up-Token": _expired_step_up_token()}
    async with AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.request(method, url, json=body, headers=headers)
    assert response.status_code == 401
    detail = response.json().get("detail", {})
    assert detail.get("error_code") == "step_up_token_expired", detail


# ===========================================================================
# Scope mismatch → 403 step_up_token_scope_mismatch
# ===========================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,url_template,body",
    [
        ("POST", "/web-api/v1/admin/superusers",
         {"target_user_id": "00000000-0000-0000-0000-000000000001",
          "allowed_ip_cidrs": []}),
        ("POST", "/web-api/v1/admin/superusers/{target}/revoke", None),
        ("POST", "/web-api/v1/admin/superusers/break-glass/enter",
         {"reason": "scope mismatch test"}),
        ("PATCH", "/web-api/v1/admin/superusers/{target}/ip-allowlist",
         {"allowed_ip_cidrs": ["10.0.0.0/24"]}),
    ],
    ids=[
        "add_superuser",
        "revoke_superuser",
        "break_glass_enter",
        "ip_allowlist_update",
    ],
)
async def test_destructive_endpoint_with_wrong_scope_returns_403(
    admin_app: FastAPI,
    db_session: AsyncSession,
    superuser_user: User,
    target_superuser: Superuser,
    method: str,
    url_template: str,
    body: dict | None,
) -> None:
    """Token signed for a different scope → 403 ``step_up_token_scope_mismatch``."""
    _override_user(admin_app, db_session, superuser_user)
    url = url_template.format(target=target_superuser.id)
    transport = ASGITransport(app=admin_app)
    headers = {
        "X-Step-Up-Token": _wrong_scope_step_up_token(
            superuser_user.id, superuser_user.security_stamp
        )
    }
    async with AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.request(method, url, json=body, headers=headers)
    assert response.status_code == 403
    detail = response.json().get("detail", {})
    assert detail.get("error_code") == "step_up_token_scope_mismatch", detail


# ===========================================================================
# Structurally invalid token → 401 step_up_token_invalid
# ===========================================================================


@pytest.mark.asyncio
async def test_destructive_endpoint_with_garbage_token_returns_401_invalid(
    admin_app: FastAPI,
    db_session: AsyncSession,
    superuser_user: User,
    target_superuser: Superuser,
) -> None:
    """A non-JWT string in ``X-Step-Up-Token`` → 401 ``step_up_token_invalid``."""
    _override_user(admin_app, db_session, superuser_user)
    url = f"/web-api/v1/admin/superusers/{target_superuser.id}/revoke"
    transport = ASGITransport(app=admin_app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.request(
            "POST", url, headers={"X-Step-Up-Token": "not-a-real-jwt"}
        )
    assert response.status_code == 401
    detail = response.json().get("detail", {})
    assert detail.get("error_code") == "step_up_token_invalid", detail


@pytest.mark.asyncio
async def test_destructive_endpoint_with_forged_signature_returns_401_invalid(
    admin_app: FastAPI,
    db_session: AsyncSession,
    superuser_user: User,
    target_superuser: Superuser,
) -> None:
    """A JWT signed with the wrong secret → 401 ``step_up_token_invalid``."""
    _override_user(admin_app, db_session, superuser_user)
    forged = jwt.encode(
        {
            "sub": str(superuser_user.id),
            "type": STEP_UP_TOKEN_TYPE,
            "scope": SCOPE_ADMIN_DESTRUCTIVE,
            "ss": superuser_user.security_stamp,
            "aid": "aid",
            "jti": str(uuid4()),
            "iat": int(datetime.now(UTC).timestamp()),
            "exp": int(datetime.now(UTC).timestamp()) + 300,
        },
        "wrong-secret-not-the-real-one-padded-32",
        algorithm="HS256",
    )
    url = f"/web-api/v1/admin/superusers/{target_superuser.id}/revoke"
    transport = ASGITransport(app=admin_app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.request(
            "POST", url, headers={"X-Step-Up-Token": forged}
        )
    assert response.status_code == 401
    detail = response.json().get("detail", {})
    assert detail.get("error_code") == "step_up_token_invalid", detail


# ===========================================================================
# Positive control: a valid token allows the request to reach the endpoint body
# ===========================================================================


@pytest.mark.asyncio
async def test_destructive_endpoint_with_valid_token_passes_step_up_gate(
    admin_app: FastAPI,
    db_session: AsyncSession,
    superuser_user: User,
    target_superuser: Superuser,
) -> None:
    """A valid token + valid superuser session → the step-up gate is transparent.

    The /revoke endpoint then opens an M-of-N ticket (202) — proving the
    gate let the request through.
    """
    _override_user(admin_app, db_session, superuser_user)
    token, _ = issue_step_up_token(
        user_id=superuser_user.id,
        security_stamp=superuser_user.security_stamp,
        assertion_id="positive-control",
    )
    url = f"/web-api/v1/admin/superusers/{target_superuser.id}/revoke"
    transport = ASGITransport(app=admin_app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.request(
            "POST", url, headers={"X-Step-Up-Token": token}
        )
    # Either 202 (M-of-N ticket opened) or 409 (last-superuser protection)
    # — both prove the step-up gate did NOT short-circuit. The forbidden
    # outcome here is a 401/403 from the gate.
    assert response.status_code not in (401, 403), response.text


# ===========================================================================
# Phase 16 Batch 6h-0 — token-to-session binding
#
# The Codex Phase 16 6g final review flagged that ``require_step_up_token``
# only checked JWT signature / expiry / scope — never the ``sub`` (user_id)
# or ``ss`` (security_stamp) claims against the current session.  That left
# two replay vectors open:
#
#   1. A fresh token minted for user A could be replayed against user B's
#      session as long as B held a valid first-party cookie.
#   2. Rotating ``security_stamp`` (logout / password change / 2FA reset)
#      did not invalidate outstanding step-up tokens, contradicting the
#      service docstring's promised behaviour.
#
# These three cases lock that contract in:
#
#   - cross-user replay → 401 ``step_up_token_user_mismatch``
#   - post-rotation replay → 401 ``step_up_token_security_stamp_rotated``
#   - matching user + matching stamp → gate transparent (202/409)
# ===========================================================================


@pytest.mark.asyncio
async def test_step_up_token_from_different_user_rejected(
    admin_app: FastAPI,
    db_session: AsyncSession,
    superuser_user: User,
    target_superuser: Superuser,
) -> None:
    """Token minted for user A + session for user B → 401 user_mismatch.

    A fresh, signed, unexpired, correctly-scoped token must still be
    refused when the JWT's ``sub`` claim does not equal the current
    session user's id.  This blocks the "stolen token from another
    superuser" replay vector identified in Codex 6g final review.
    """
    # session is bound to ``superuser_user`` — but the token below is
    # minted for a *different* user with a *different* security stamp.
    _override_user(admin_app, db_session, superuser_user)

    foreign_user_id = uuid4()
    token, _ = issue_step_up_token(
        user_id=foreign_user_id,
        security_stamp="ff" * 32,  # any non-empty stamp; mismatch on user_id alone is enough
        assertion_id="cross-user-replay",
    )
    url = f"/web-api/v1/admin/superusers/{target_superuser.id}/revoke"
    transport = ASGITransport(app=admin_app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.request(
            "POST", url, headers={"X-Step-Up-Token": token}
        )
    assert response.status_code == 401, response.text
    detail = response.json().get("detail", {})
    assert detail.get("error_code") == "step_up_token_user_mismatch", detail


@pytest.mark.asyncio
async def test_step_up_token_after_security_stamp_rotation_rejected(
    admin_app: FastAPI,
    db_session: AsyncSession,
    superuser_user: User,
    target_superuser: Superuser,
) -> None:
    """Token issued with stamp S1, then user.security_stamp rotates to S2 → 401.

    Mirrors the production behaviour where
    :func:`AuthService._rotate_security_stamp` is invoked on logout,
    password change, or 2FA enrol/reset — every outstanding step-up
    token must be invalidated immediately.
    """
    # 1. Mint a token bound to the user's *current* stamp.
    original_stamp = superuser_user.security_stamp
    token, _ = issue_step_up_token(
        user_id=superuser_user.id,
        security_stamp=original_stamp,
        assertion_id="pre-rotation",
    )

    # 2. Rotate the stamp directly on the row (simulates the post-issuance
    #    logout / password change / 2FA reset path). Refresh the user row
    #    so the test fixture observes the new stamp before the override
    #    captures it.
    superuser_user.security_stamp = "1" * 64
    db_session.add(superuser_user)
    await db_session.commit()
    await db_session.refresh(superuser_user)

    # 3. Wire the override AFTER the rotation so the dependency sees the
    #    refreshed user (stamp = "1" * 64), but use the token from step 1
    #    (stamp = original).
    _override_user(admin_app, db_session, superuser_user)

    url = f"/web-api/v1/admin/superusers/{target_superuser.id}/revoke"
    transport = ASGITransport(app=admin_app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.request(
            "POST", url, headers={"X-Step-Up-Token": token}
        )
    assert response.status_code == 401, response.text
    detail = response.json().get("detail", {})
    assert detail.get("error_code") == "step_up_token_security_stamp_rotated", detail


@pytest.mark.asyncio
async def test_step_up_token_with_matching_user_and_stamp_accepted(
    admin_app: FastAPI,
    db_session: AsyncSession,
    superuser_user: User,
    target_superuser: Superuser,
) -> None:
    """Positive control: same-user + same-stamp token passes the binding gate.

    Distinct from
    :func:`test_destructive_endpoint_with_valid_token_passes_step_up_gate`
    in that this test specifically exists to guard the regression where
    the binding accidentally rejects valid tokens (e.g. UUID vs str
    comparison drift in ``StepUpTokenClaims.user_id``).
    """
    _override_user(admin_app, db_session, superuser_user)
    token, _ = issue_step_up_token(
        user_id=superuser_user.id,
        security_stamp=superuser_user.security_stamp,
        assertion_id="binding-positive-control",
    )
    url = f"/web-api/v1/admin/superusers/{target_superuser.id}/revoke"
    transport = ASGITransport(app=admin_app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.request(
            "POST", url, headers={"X-Step-Up-Token": token}
        )
    # 202 (ticket opened) or 409 (last-superuser protection) — anything
    # but 401/403 proves the binding gate did not short-circuit.
    assert response.status_code not in (401, 403), response.text
