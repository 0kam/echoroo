"""Integration tests for the Phase 17 follow-up 2FA reset *stub* route.

Coverage:

* The stub returns ``HTTP 501 Not Implemented`` when called by an
  authenticated superuser with a syntactically valid body — pinning the
  Codex Round X "501 stub" decision so a future implementer cannot
  silently soften it to ``202`` / partial success.
* The stub still rejects unauthenticated callers with 401 and
  authenticated-but-not-superuser callers with 403, ensuring the
  endpoint does not become an off-the-books permission probe.
* The Pydantic body schema is enforced even on the stub (missing
  required fields → 422), so any future implementation cannot land on
  top of a relaxed schema by accident.

Out of scope:

* End-to-end CSRF / WebAuthn ceremony — exercised by the dedicated
  middleware suites (mirrors :mod:`tests.integration.api.web_v1.test_admin_superusers`
  scope rules).
* The full FR-072 4-factor verification + 24 h delay + 72 h cooldown +
  M-of-N approval flow — that lands with PHASE17_BACKLOG.md item A-11.

Spec references: FR-072 (2FA reset support workflow), admin.yaml
``operationId: reset2FA`` path, PHASE17_BACKLOG.md A-11.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.api.web_v1.admin import router as admin_router
from echoroo.core.database import get_db
from echoroo.middleware.auth import get_current_user_optional
from echoroo.models.superuser import Superuser
from echoroo.models.user import User
from echoroo.services.step_up_token_service import (
    SCOPE_ADMIN_DESTRUCTIVE,
    issue_step_up_token,
)

# ---------------------------------------------------------------------------
# DB / fixture helpers (mirror tests/integration/api/web_v1/test_admin_superusers)
# ---------------------------------------------------------------------------


async def _create_user(db: AsyncSession, *, email: str) -> User:
    user = User(
        email=email,
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$reset2fa-stub",
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


# ---------------------------------------------------------------------------
# App / client fixtures (mirror test_admin_superusers.admin_client_factory)
# ---------------------------------------------------------------------------


@pytest.fixture
async def admin_app(db_session: AsyncSession) -> FastAPI:
    """FastAPI app with the admin router and an overridable user dep.

    CSRF / AuthRouter middleware are intentionally omitted — they are
    exercised by the dedicated middleware suites; this fixture targets
    the application-layer guard (``_require_authenticated_superuser``)
    plus body validation.
    """
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
            # Mirror the production middleware: stamp ``is_superuser`` /
            # ``_superuser_id`` from the live ``superusers`` table so the
            # endpoint helper sees the same shape it would in production.
            from sqlalchemy import text as _sa_text

            probe = await captured_session.execute(
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

        admin_app.dependency_overrides[get_current_user_optional] = _override

    async def _factory(user: User | None) -> AsyncClient:
        _override_user(user)
        # Inject a valid step-up token header so the destructive admin
        # gate remains transparent for these tests (matches the pattern
        # used by ``test_admin_superusers.admin_client_factory``).
        token, _ = issue_step_up_token(
            user_id=user.id if user is not None else uuid4(),
            security_stamp=(
                user.security_stamp if user is not None else "0" * 64
            ),
            assertion_id="test-fixture-credential",
            scope=SCOPE_ADMIN_DESTRUCTIVE,
        )
        return AsyncClient(
            transport=transport,
            base_url="http://testserver",
            headers={"X-Step-Up-Token": token},
        )

    return _factory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_payload() -> dict[str, Any]:
    """Return a syntactically valid body for the stub.

    The four factor names mirror the spec (FR-072) so the future full
    implementation can lift this fixture wholesale; the stub only cares
    that the schema parses.
    """
    return {
        "support_ticket_id": "ZD-2FA-STUB-1",
        "confirmed_factors": [
            "registered_email_match",
            "current_password",
            "last_login_time",
            "last_api_key_prefix",
        ],
        "reason": "stub-route smoke test",
        "skip_delay": False,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reset_two_factor_anonymous_returns_401(
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    """Anonymous callers MUST be rejected with 401 (consistent with /admin)."""
    target_id = uuid4()
    async with await admin_client_factory(None) as client:
        response = await client.post(
            f"/web-api/v1/admin/users/{target_id}/reset-2fa",
            json=_valid_payload(),
        )
    assert response.status_code == 401, response.text


@pytest.mark.asyncio
async def test_reset_two_factor_non_superuser_returns_403(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    """Authenticated non-superusers MUST be rejected with 403.

    Otherwise the stub would leak whether the caller is privileged
    (501 vs 401) — a cheap permission probe we explicitly do not want
    to ship even before the full handler lands.
    """
    user = await _create_user(
        db_session, email="reset2fa_stub_nonsu@example.com"
    )
    target_id = uuid4()
    async with await admin_client_factory(user) as client:
        response = await client.post(
            f"/web-api/v1/admin/users/{target_id}/reset-2fa",
            json=_valid_payload(),
        )
    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_reset_two_factor_superuser_returns_501(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    """A valid superuser request MUST surface 501 Not Implemented.

    Pins the Codex Round X "stub-only" decision: until the full FR-072
    workflow lands, the endpoint must not pretend to do work.
    """
    su_user = await _create_user(
        db_session, email="reset2fa_stub_su@example.com"
    )
    await _create_superuser(db_session, user=su_user)
    target_id = uuid4()

    async with await admin_client_factory(su_user) as client:
        response = await client.post(
            f"/web-api/v1/admin/users/{target_id}/reset-2fa",
            json=_valid_payload(),
        )
    assert response.status_code == 501, response.text
    body = response.json()
    # The error envelope mirrors the standard admin endpoint shape so
    # FE clients can surface it through the existing handler.
    detail = body.get("detail")
    assert isinstance(detail, dict), body
    assert detail.get("error") == "ERR_NOT_IMPLEMENTED"
    # Backlog reference is intentionally embedded in the message so an
    # operator hitting this in logs can find the tracker quickly.
    assert "PHASE17_BACKLOG" in detail.get("message", "")


@pytest.mark.asyncio
async def test_reset_two_factor_superuser_missing_field_returns_422(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    """Pydantic body validation MUST run even though the handler stubs out.

    Otherwise the future full implementation could land on top of a
    relaxed schema and accidentally accept malformed payloads.
    """
    su_user = await _create_user(
        db_session, email="reset2fa_stub_su_422@example.com"
    )
    await _create_superuser(db_session, user=su_user)
    target_id = uuid4()

    bad_payload = _valid_payload()
    bad_payload.pop("support_ticket_id")  # required field

    async with await admin_client_factory(su_user) as client:
        response = await client.post(
            f"/web-api/v1/admin/users/{target_id}/reset-2fa",
            json=bad_payload,
        )
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_reset_two_factor_skip_delay_still_returns_501(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    """``skip_delay=true`` MUST NOT trip a different code path on the stub.

    The full implementation routes ``skip_delay=true`` through an
    M-of-N approval ticket; until that lands the stub must reject every
    invocation with 501 regardless of the flag.
    """
    su_user = await _create_user(
        db_session, email="reset2fa_stub_su_skip@example.com"
    )
    await _create_superuser(db_session, user=su_user)
    target_id = uuid4()

    payload = _valid_payload()
    payload["skip_delay"] = True

    async with await admin_client_factory(su_user) as client:
        response = await client.post(
            f"/web-api/v1/admin/users/{target_id}/reset-2fa",
            json=payload,
        )
    assert response.status_code == 501, response.text
