"""Admin-recovery endpoints require an ``admin_recovery`` step-up token.

spec/011 §FR-011-206 + tasks.md T312.

Every admin-recovery endpoint MUST be gated by
:func:`require_step_up_token(SCOPE_ADMIN_RECOVERY)`. This is the
negative-control suite for that contract: it exercises the gate's
refusal envelope when the request:

* omits the ``X-Step-Up-Token`` header entirely (→ 401
  ``step_up_token_required``);
* presents a valid token under the *wrong* scope —
  ``admin_destructive`` from the spec/006 path (→ 403
  ``step_up_token_scope_mismatch``);
* presents a token whose ``factors`` claim is structurally absent
  (→ 401 ``step_up_token_invalid``);
* presents a token whose ``factors.password`` is literally ``False``
  (→ 401 ``step_up_token_invalid``);
* presents a valid ``admin_recovery`` token with a fresh WebAuthn
  second factor (→ gate transparent, handler returns 200);
* presents a valid ``admin_recovery`` token with a fresh TOTP second
  factor (→ gate transparent, handler returns 200).

Endpoints under coverage:

* ``POST /web-api/v1/admin/users/{user_id}/reset-password`` (T311,
  FR-011-201).

The Phase 7 admin 2FA disable endpoint (T400, FR-011-306) is NOT yet
wired — a ``TODO`` placeholder marks the spot for future cases.

Token-minting strategy
~~~~~~~~~~~~~~~~~~~~~~

Tests mint tokens directly via
:func:`echoroo.services.step_up_token_service.issue_admin_recovery_step_up_token`
(and :func:`issue_step_up_token` for the ``admin_destructive``
mismatch case). T300/T301/T302 — the step-up begin / complete API
endpoints — are NOT in scope for the spec/011 Step 5 increment; they
arrive in a later step and these tests will continue to exercise the
*gate*, not the issuance path.

Header injection
~~~~~~~~~~~~~~~~

The admin endpoint depends on :func:`get_current_user_optional` (via
the ``OptionalCurrentUser`` alias) so we override that dependency in
``admin_app`` with a fixture that returns the test superuser. This
mirrors the pattern used by
``tests/security/authentication/test_admin_step_up_required.py``
(the spec/006 ``admin_destructive`` negative-control suite this file
is modelled on).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt
import pytest
import pytest_asyncio
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
    SCOPE_ADMIN_RECOVERY,
    STEP_UP_TOKEN_TYPE,
    issue_admin_recovery_step_up_token,
    issue_step_up_token,
)

# ---------------------------------------------------------------------------
# Helpers — mirror the admin_app pattern from the spec/006 step-up suite.
# ---------------------------------------------------------------------------


async def _create_user(
    db: AsyncSession,
    *,
    email: str,
    security_stamp: str | None = None,
) -> User:
    user = User(
        email=email,
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$step-up-admin-recovery-test",
        display_name=f"User {email}",
        security_stamp=security_stamp or ("0" * 64),
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


@pytest_asyncio.fixture
async def admin_app(db_session: AsyncSession) -> FastAPI:
    app = FastAPI()
    app.include_router(admin_router, prefix="/web-api/v1")

    async def _override_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    return app


@pytest_asyncio.fixture
async def superuser_user(db_session: AsyncSession) -> User:
    user = await _create_user(db_session, email="t312_admin_recovery_su@example.com")
    await _create_superuser(db_session, user=user)
    return user


@pytest_asyncio.fixture
async def target_user(db_session: AsyncSession) -> User:
    return await _create_user(
        db_session,
        email="t312_admin_recovery_target@example.com",
        security_stamp="1" * 64,
    )


def _override_user(app: FastAPI, db: AsyncSession, user: User) -> None:
    """Stamp the test superuser on the auth dependency for the request.

    Mirrors :func:`_override_user` in
    ``tests/security/authentication/test_admin_step_up_required.py``.
    The auth middleware in production decorates every authenticated
    user with ``_superuser_id`` (the active ``superusers.id``) and
    ``is_superuser`` (transient bool) — we re-derive both here so
    :func:`_require_authenticated_superuser` and
    :func:`_gate_platform_superuser_action` both pass.
    """
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


def _reset_password_url(target_user_id: UUID) -> str:
    return f"/web-api/v1/admin/users/{target_user_id}/reset-password"


# ---------------------------------------------------------------------------
# 1. Missing header → 401 step_up_token_required
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_password_reset_without_step_up_header_returns_401(
    admin_app: FastAPI,
    db_session: AsyncSession,
    superuser_user: User,
    target_user: User,
) -> None:
    """No ``X-Step-Up-Token`` header → 401 ``step_up_token_required``."""
    _override_user(admin_app, db_session, superuser_user)
    url = _reset_password_url(target_user.id)
    transport = ASGITransport(app=admin_app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.post(url, json={"reason": "audit drill"})
    assert response.status_code == 401, response.text
    detail = response.json().get("detail", {})
    assert detail.get("error_code") == "step_up_token_required", detail


# ---------------------------------------------------------------------------
# 2. Wrong scope (admin_destructive token) → 403 scope mismatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_password_reset_with_admin_destructive_token_returns_403(
    admin_app: FastAPI,
    db_session: AsyncSession,
    superuser_user: User,
    target_user: User,
) -> None:
    """admin_destructive scope (spec/006) is refused by the admin_recovery gate.

    Mints a properly-signed, properly-bound (sub == session user, ss ==
    current security_stamp) ``admin_destructive`` token and asserts the
    spec/006 scope is NOT a substitute for the spec/011 ``admin_recovery``
    scope. The verifier uses :func:`secrets.compare_digest` so the
    mismatch is reported without leaking position via timing.
    """
    _override_user(admin_app, db_session, superuser_user)

    # Mint a token that satisfies every other gate invariant except
    # scope — so the only way this can fail is on scope.
    token, _ = issue_step_up_token(
        user_id=superuser_user.id,
        security_stamp=superuser_user.security_stamp,
        assertion_id="t312-admin-destructive-vs-recovery",
        # default scope = SCOPE_ADMIN_DESTRUCTIVE
    )
    url = _reset_password_url(target_user.id)
    transport = ASGITransport(app=admin_app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.post(
            url,
            json={"reason": "scope-mismatch test"},
            headers={"X-Step-Up-Token": token},
        )
    assert response.status_code == 403, response.text
    detail = response.json().get("detail", {})
    assert detail.get("error_code") == "step_up_token_scope_mismatch", detail


# ---------------------------------------------------------------------------
# 3. admin_recovery token with factors claim missing → 401 invalid
# ---------------------------------------------------------------------------
#
# We hand-craft this token (rather than minting via
# :func:`issue_admin_recovery_step_up_token`) because the issuer
# ALWAYS sets ``factors``. The only way to reach the "factors absent"
# arm of the verifier is to encode the payload directly. The token is
# signed with the same secret + algorithm so signature / type / scope /
# expiry all pass — only the missing factors claim should trip the
# verifier.


def _craft_admin_recovery_token_without_factors(
    *, user_id: UUID, security_stamp: str
) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "type": STEP_UP_TOKEN_TYPE,
        "scope": SCOPE_ADMIN_RECOVERY,
        "ss": security_stamp,
        "aid": "t312-missing-factors",
        "jti": "00000000-0000-4000-8000-000000000312",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=300)).timestamp()),
        # ``factors`` deliberately absent.
    }
    return jwt.encode(
        payload, settings.web_session_secret, algorithm=settings.JWT_ALGORITHM
    )


def _craft_admin_recovery_token_with_factors(
    *,
    user_id: UUID,
    security_stamp: str,
    factors: dict[str, Any],
) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "type": STEP_UP_TOKEN_TYPE,
        "scope": SCOPE_ADMIN_RECOVERY,
        "ss": security_stamp,
        "aid": "t312-custom-factors",
        "jti": "00000000-0000-4000-8000-000000000313",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=300)).timestamp()),
        "factors": factors,
    }
    return jwt.encode(
        payload, settings.web_session_secret, algorithm=settings.JWT_ALGORITHM
    )


@pytest.mark.asyncio
async def test_admin_password_reset_with_admin_recovery_missing_factors_returns_401(
    admin_app: FastAPI,
    db_session: AsyncSession,
    superuser_user: User,
    target_user: User,
) -> None:
    """admin_recovery token without ``factors`` claim → 401 invalid."""
    _override_user(admin_app, db_session, superuser_user)
    token = _craft_admin_recovery_token_without_factors(
        user_id=superuser_user.id,
        security_stamp=superuser_user.security_stamp,
    )
    url = _reset_password_url(target_user.id)
    transport = ASGITransport(app=admin_app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.post(
            url,
            json={"reason": "factors-missing test"},
            headers={"X-Step-Up-Token": token},
        )
    assert response.status_code == 401, response.text
    detail = response.json().get("detail", {})
    assert detail.get("error_code") == "step_up_token_invalid", detail


@pytest.mark.asyncio
async def test_admin_password_reset_with_admin_recovery_factors_password_false_returns_401(
    admin_app: FastAPI,
    db_session: AsyncSession,
    superuser_user: User,
    target_user: User,
) -> None:
    """admin_recovery token with ``factors.password=False`` → 401 invalid.

    spec/011 §FR-011-206 AND-condition: the password factor MUST be
    verified server-side before the token is minted. A token with
    ``factors.password=False`` represents a half-completed challenge
    and the verifier MUST refuse it. We deliberately craft the token
    (bypassing the issuer's strict ``bool`` type guard) so the failure
    mode is enforced at the gate, not just at issuance.
    """
    _override_user(admin_app, db_session, superuser_user)
    token = _craft_admin_recovery_token_with_factors(
        user_id=superuser_user.id,
        security_stamp=superuser_user.security_stamp,
        factors={"password": False, "second_factor": "totp"},
    )
    url = _reset_password_url(target_user.id)
    transport = ASGITransport(app=admin_app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.post(
            url,
            json={"reason": "factors.password=false test"},
            headers={"X-Step-Up-Token": token},
        )
    assert response.status_code == 401, response.text
    detail = response.json().get("detail", {})
    assert detail.get("error_code") == "step_up_token_invalid", detail


# ---------------------------------------------------------------------------
# 4. admin_recovery + WebAuthn second factor → gate transparent → 200
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_password_reset_with_webauthn_second_factor_returns_200(
    admin_app: FastAPI,
    db_session: AsyncSession,
    superuser_user: User,
    target_user: User,
) -> None:
    """admin_recovery + ``factors.second_factor=webauthn`` → gate transparent.

    Positive control. The token is minted via the canonical issuer so
    every invariant (scope, factors, security_stamp binding, sub
    binding) is satisfied. The handler executes the reset and returns
    200 with a click-to-reveal payload.

    We additionally assert the FR-011-202 response headers are set,
    since this is the single ingress point for the temp password and
    the spec invariant lives at the handler boundary.
    """
    _override_user(admin_app, db_session, superuser_user)
    token, _ = issue_admin_recovery_step_up_token(
        user_id=superuser_user.id,
        security_stamp=superuser_user.security_stamp,
        assertion_id="t312-positive-webauthn",
        password_verified=True,
        second_factor="webauthn",
    )
    url = _reset_password_url(target_user.id)
    transport = ASGITransport(app=admin_app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.post(
            url,
            json={"reason": "webauthn-positive test"},
            headers={"X-Step-Up-Token": token},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "temporary_password" in body and body["temporary_password"], body
    assert "expires_at" in body and body["expires_at"], body
    # FR-011-202 response-header invariant.
    assert "no-store" in (response.headers.get("cache-control") or ""), response.headers
    assert response.headers.get("referrer-policy") == "no-referrer", response.headers


# ---------------------------------------------------------------------------
# 5. admin_recovery + TOTP second factor → gate transparent → 200
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_password_reset_with_totp_second_factor_returns_200(
    admin_app: FastAPI,
    db_session: AsyncSession,
    superuser_user: User,
    target_user: User,
) -> None:
    """admin_recovery + ``factors.second_factor=totp`` → gate transparent.

    Second positive control. Distinct from the WebAuthn case so a
    future refactor that accidentally narrows the verifier's
    second-factor allowlist to only WebAuthn (or only TOTP) is caught
    here.
    """
    _override_user(admin_app, db_session, superuser_user)
    token, _ = issue_admin_recovery_step_up_token(
        user_id=superuser_user.id,
        security_stamp=superuser_user.security_stamp,
        assertion_id="t312-positive-totp",
        password_verified=True,
        second_factor="totp",
    )
    url = _reset_password_url(target_user.id)
    transport = ASGITransport(app=admin_app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.post(
            url,
            json={"reason": "totp-positive test"},
            headers={"X-Step-Up-Token": token},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "temporary_password" in body and body["temporary_password"], body
    assert "expires_at" in body and body["expires_at"], body
    # FR-011-202 response-header invariant — repeated here so a future
    # refactor that accidentally drops the header on the TOTP branch is
    # caught (Codex R1 P1 #2: headers must be asserted on every happy
    # path, not just one).
    assert "no-store" in (response.headers.get("cache-control") or ""), response.headers
    assert response.headers.get("referrer-policy") == "no-referrer", response.headers


# ---------------------------------------------------------------------------
# 6. A-13 PII detector on ``reason`` body field → 422
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_password_reset_rejects_reason_with_pii(
    admin_app: FastAPI,
    db_session: AsyncSession,
    superuser_user: User,
    target_user: User,
) -> None:
    """``reason`` body must reject free-form PII (A-13 + FR-011-202).

    The endpoint wires the canonical ``reject_if_pii`` AfterValidator on
    ``AdminPasswordResetBody.reason`` (see ``schemas/admin.py``). This
    test guards the wire-up: a reason containing an email address must
    yield a 422 *before* any reset state mutation, even when the caller
    presents a fully valid ``admin_recovery`` step-up token.

    Codex R1 P1 #1 — without this case a future refactor that drops the
    ``AfterValidator`` annotation would silently land an operator-PII
    leakage regression (the value would be persisted in the audit row
    detail JSON downstream).
    """
    _override_user(admin_app, db_session, superuser_user)
    token, _ = issue_admin_recovery_step_up_token(
        user_id=superuser_user.id,
        security_stamp=superuser_user.security_stamp,
        assertion_id="t312-pii-reject",
        password_verified=True,
        second_factor="totp",
    )
    url = _reset_password_url(target_user.id)
    transport = ASGITransport(app=admin_app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.post(
            url,
            json={"reason": "compromise from foo@example.com last week"},
            headers={"X-Step-Up-Token": token},
        )
    # FastAPI / pydantic returns 422 for AfterValidator failures.
    assert response.status_code == 422, response.text
    # Sanity: the response error mentions the PII rejection so an
    # operator can self-correct without ambiguity.
    assert "pii" in response.text.lower() or "personally" in response.text.lower(), response.text


# ---------------------------------------------------------------------------
# TODO(spec/011 Phase 7 / T400): when the admin 2FA disable endpoint
# (FR-011-306) is wired with ``require_step_up_token(SCOPE_ADMIN_RECOVERY)``,
# extend this suite with the same six cases against the new path. The
# existing /admin/users/{user_id}/reset-2fa endpoint is currently gated
# by ``SCOPE_ADMIN_DESTRUCTIVE`` and is covered by
# tests/security/authentication/test_admin_step_up_required.py — the
# Phase 7 work in T400 is to flip that gate to ``SCOPE_ADMIN_RECOVERY``.
# ---------------------------------------------------------------------------
