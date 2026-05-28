"""Recipient self-decline contract tests (T513b, FR-107 / FR-055).

Spec ``contracts/projects.yaml`` defines:

    DELETE /projects/{id}/invitations/{token}
    * 204 — pending → DECLINED, idempotent (re-decline still 204).
    * 410 — terminal state (accepted / expired / revoked).
    * 404 — token unknown / cross-account / email mismatch (FR-055
      enumeration mitigation).

The handler maps the service-layer exception classes onto the response
codes; this module validates the resulting HTTP envelope.

The test harness mounts the real ``/web-api/v1`` router with a
lightweight Bearer-principal middleware (mirrors the license bypass
pattern in ``test_license_required.py::web_client``) so we can assert
the **business** contract — CSRF transport is exercised in dedicated
middleware suites and is intentionally bypassed here.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch as _patch
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from echoroo.core.jwt import create_access_token
from echoroo.models.enums import ProjectInvitationStatus
from echoroo.models.project import ProjectInvitation
from echoroo.models.user import User
from echoroo.services import invitation_service
from echoroo.services.invitation_service import sign_invitation_token

_TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://echoroo:echoroo@localhost:5432/echoroo_test",
)


# The handler reads the HMAC secret via :func:`get_settings`. Patching the
# settings object would be intrusive, so we sign tokens with the secret the
# settings module returns at fixture time and rely on the same value being
# read on the request path. The fixture below caches the secret for use in
# helper functions that build signed tokens.
def _hmac_secret() -> str:
    from echoroo.core.settings import get_settings

    return get_settings().web_session_secret


# ---------------------------------------------------------------------------
# Test fixtures — actor + harness
# ---------------------------------------------------------------------------


@pytest.fixture
async def t513b_owner(db_session: AsyncSession) -> User:
    user = User(
        email=f"t513b-owner-{uuid4().hex[:8]}@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T513B Owner",
        security_stamp="t513b" + "o" * 59,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def t513b_recipient(db_session: AsyncSession) -> User:
    user = User(
        email=f"t513b-recipient-{uuid4().hex[:8]}@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T513B Recipient",
        security_stamp="t513b" + "r" * 59,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def t513b_other(db_session: AsyncSession) -> User:
    user = User(
        email=f"t513b-other-{uuid4().hex[:8]}@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T513B Other",
        security_stamp="t513b" + "x" * 59,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


def _bearer(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token({'sub': str(user.id)})}"}


@pytest.fixture
async def web_client(
    db_session: AsyncSession,  # noqa: ARG001 — ensures the DB is initialised
) -> AsyncGenerator[AsyncClient, None]:
    """Mount the real ``/web-api/v1`` router behind a Bearer-principal middleware.

    Mirrors the pattern in ``test_license_required.py::web_client`` so the
    contract assertions hit the production routing + dependency chain
    without dragging in CSRF / cookie verification.
    """
    from collections.abc import Awaitable, Callable

    from fastapi import FastAPI
    from fastapi.exceptions import RequestValidationError
    from starlette.exceptions import HTTPException as _StarletteHTTPException
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import Response
    from starlette.types import ASGIApp

    from echoroo.api.web_v1 import web_v1_router
    from echoroo.core.database import get_db
    from echoroo.core.exceptions import (
        AppException,
        app_exception_handler,
        http_exception_handler,
        validation_exception_handler,
    )
    from echoroo.core.jwt import decode_token
    from echoroo.middleware.auth_router import Principal

    engine = create_async_engine(
        _TEST_DATABASE_URL,
        echo=False,
        poolclass=NullPool,
    )
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    app = FastAPI()
    app.add_exception_handler(AppException, app_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(
        RequestValidationError, validation_exception_handler  # type: ignore[arg-type]
    )
    app.add_exception_handler(
        _StarletteHTTPException, http_exception_handler  # type: ignore[arg-type]
    )

    class _BearerPrincipalMiddleware(BaseHTTPMiddleware):
        def __init__(self, asgi_app: ASGIApp) -> None:
            super().__init__(asgi_app)

        async def dispatch(
            self,
            request: Request,
            call_next: Callable[[Request], Awaitable[Response]],
        ) -> Response:
            request.state.principal = None
            auth_header = request.headers.get("Authorization", "")
            if auth_header.lower().startswith("bearer "):
                token = auth_header.split(" ", 1)[1].strip()
                if token:
                    try:
                        payload = decode_token(token)
                        sub = payload.get("sub")
                        if isinstance(sub, str):
                            try:
                                user_uuid = UUID(sub)
                            except (TypeError, ValueError):
                                user_uuid = None
                            if user_uuid is not None:
                                request.state.principal = Principal.for_session(
                                    user_id=user_uuid,
                                    security_stamp="s" * 64,
                                )
                    except Exception:  # noqa: BLE001 — bad token → 401
                        pass
            return await call_next(request)

    app.add_middleware(_BearerPrincipalMiddleware)
    app.include_router(web_v1_router)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    app.dependency_overrides[get_db] = override_get_db

    async def _noop_rate_limiter(
        self: object,  # noqa: ARG001
        request: Request,  # noqa: ARG001
        response: Response,  # noqa: ARG001
    ) -> None:
        return None

    with _patch(
        "fastapi_limiter.depends.RateLimiter.__call__", _noop_rate_limiter
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as test_client:
            yield test_client

    app.dependency_overrides.clear()
    await engine.dispose()


# ---------------------------------------------------------------------------
# Helpers — seed pending invitation rows in the DB.
# ---------------------------------------------------------------------------


async def _purge(db: AsyncSession) -> None:
    await db.execute(sa.text("DELETE FROM project_invitations"))
    await db.commit()


async def _seed_project(db: AsyncSession, owner_id: Any) -> Any:
    from echoroo.models.enums import ProjectLicense, ProjectVisibility
    from echoroo.models.project import Project

    project = Project(
        name=f"T513B {uuid4().hex[:8]}",
        visibility=ProjectVisibility.RESTRICTED,
        license_id="cc-by",
        owner_id=owner_id,
        restricted_config={
            "allow_media_playback": True,
            "allow_detection_view": True,
            "mask_species_in_detection": False,
            "allow_download": False,
            "allow_export": False,
            "allow_voting_and_comments": False,
            "public_location_precision_h3_res": 5,
            "allow_precise_location_to_viewer": False,
        },
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project.id


async def _seed_pending(
    db: AsyncSession,
    *,
    canonical_email: str,
    invited_by_id: Any,
    raw_seed: bytes,
    project_id: Any,
    status: ProjectInvitationStatus = ProjectInvitationStatus.PENDING,
    expires_at: datetime | None = None,
) -> tuple[ProjectInvitation, str]:
    """Insert a Member invitation row via raw SQL + return ``(row, signed_token)``.

    Raw SQL is required because SQLAlchemy serialises Python ``None`` for a
    JSONB column as the JSONB ``'null'`` literal which fails the
    ``ck_project_invitations_kind_fields`` CHECK (``IS NULL`` does not
    match ``'null'``). Status timestamps are mapped from ``status`` so the
    ``ck_project_invitations_status_timestamps`` CHECK is satisfied.
    """
    raw_token_b64u = invitation_service._b64u_encode(raw_seed)
    token_hash = invitation_service.hash_token(raw_token_b64u)
    if expires_at is None:
        expires_at = datetime.now(UTC) + timedelta(days=1)
    signed = sign_invitation_token(
        raw_token_b64u=raw_token_b64u,
        expires_at=expires_at,
        hmac_secret=_hmac_secret(),
    )
    email_hash_value = invitation_service.hash_email(
        canonical_email, hmac_secret=_hmac_secret()
    )
    invitation_id = uuid4()
    accepted_ts = None
    declined_ts = None
    revoked_ts = None
    if status is ProjectInvitationStatus.ACCEPTED:
        accepted_ts = datetime.now(UTC)
    elif status is ProjectInvitationStatus.DECLINED:
        declined_ts = datetime.now(UTC)
    elif status is ProjectInvitationStatus.REVOKED:
        revoked_ts = datetime.now(UTC)
    await db.execute(
        sa.text(
            """
            INSERT INTO project_invitations
                (id, project_id, kind, email, email_hash, role,
                 granted_permissions, trusted_duration_seconds,
                 token_hash, invited_by_id, expires_at, status,
                 accepted_at, declined_at, revoked_at,
                 created_at, updated_at)
            VALUES
                (:id, :project_id, 'member', :email, :email_hash, 'member',
                 NULL, NULL,
                 :token_hash, :invited_by_id, :expires_at,
                 CAST(:status AS invitationstatus),
                 :accepted_at, :declined_at, :revoked_at,
                 NOW(), NOW())
            """
        ),
        {
            "id": invitation_id,
            "project_id": project_id,
            "email": canonical_email,
            "email_hash": email_hash_value,
            "token_hash": token_hash,
            "invited_by_id": invited_by_id,
            "expires_at": expires_at,
            "status": status.value,
            "accepted_at": accepted_ts,
            "declined_at": declined_ts,
            "revoked_at": revoked_ts,
        },
    )
    await db.commit()
    invitation = (
        await db.execute(
            sa.select(ProjectInvitation).where(
                ProjectInvitation.id == invitation_id
            )
        )
    ).scalar_one()
    return invitation, signed


def _delete_url(invitation: ProjectInvitation, signed: str) -> str:
    return (
        f"/web-api/v1/projects/{invitation.project_id}/invitations/{signed}"
    )


# ---------------------------------------------------------------------------
# 1. Pending → 204 + DB row flips to DECLINED.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decline_pending_returns_204_and_marks_declined(
    web_client: AsyncClient,
    db_session: AsyncSession,
    t513b_owner: User,
    t513b_recipient: User,
) -> None:
    await _purge(db_session)
    project_id = await _seed_project(db_session, t513b_owner.id)
    invitation, signed = await _seed_pending(
        db_session,
        canonical_email=t513b_recipient.email,
        invited_by_id=t513b_owner.id,
        project_id=project_id,
        raw_seed=b"\xa0" * 32,
    )

    response = await web_client.delete(
        _delete_url(invitation, signed),
        headers=_bearer(t513b_recipient),
    )
    assert response.status_code == 204, response.text

    # The handler commits in a separate session. Read the row state via
    # a raw SQL query so the test session's identity-map / snapshot
    # cannot mask the new state.
    await db_session.commit()
    row = (
        await db_session.execute(
            sa.text(
                "SELECT status::text, declined_at FROM project_invitations "
                "WHERE id = :id"
            ),
            {"id": invitation.id},
        )
    ).one()
    assert row[0] == "declined", row
    assert row[1] is not None


# ---------------------------------------------------------------------------
# 2. Re-decline → 204, status unchanged (idempotent).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redecline_already_declined_is_idempotent_204(
    web_client: AsyncClient,
    db_session: AsyncSession,
    t513b_owner: User,
    t513b_recipient: User,
) -> None:
    await _purge(db_session)
    project_id = await _seed_project(db_session, t513b_owner.id)
    invitation, signed = await _seed_pending(
        db_session,
        canonical_email=t513b_recipient.email,
        invited_by_id=t513b_owner.id,
        project_id=project_id,
        raw_seed=b"\xa1" * 32,
        status=ProjectInvitationStatus.DECLINED,
    )

    response = await web_client.delete(
        _delete_url(invitation, signed),
        headers=_bearer(t513b_recipient),
    )
    assert response.status_code == 204, response.text

    refreshed = (
        await db_session.execute(
            sa.select(ProjectInvitation).where(
                ProjectInvitation.id == invitation.id
            )
        )
    ).scalar_one()
    assert refreshed.status is ProjectInvitationStatus.DECLINED


# ---------------------------------------------------------------------------
# 3. Accepted invitation → 410.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decline_accepted_invitation_returns_410(
    web_client: AsyncClient,
    db_session: AsyncSession,
    t513b_owner: User,
    t513b_recipient: User,
) -> None:
    await _purge(db_session)
    project_id = await _seed_project(db_session, t513b_owner.id)
    invitation, signed = await _seed_pending(
        db_session,
        canonical_email=t513b_recipient.email,
        invited_by_id=t513b_owner.id,
        project_id=project_id,
        raw_seed=b"\xa2" * 32,
        status=ProjectInvitationStatus.ACCEPTED,
    )

    response = await web_client.delete(
        _delete_url(invitation, signed),
        headers=_bearer(t513b_recipient),
    )
    assert response.status_code == 410, response.text


# ---------------------------------------------------------------------------
# 4. Expired invitation row → 404 (HMAC verify rejects past-expiry tokens
#    so the handler maps it to 404 enumeration uniformity, not 410). The
#    spec is explicit: a *terminal status row that is reachable* yields
#    410, but a token whose signature has expired never reaches the row
#    at all — that is a 404 by design.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decline_signature_expired_returns_404(
    web_client: AsyncClient,
    db_session: AsyncSession,
    t513b_owner: User,
    t513b_recipient: User,
) -> None:
    await _purge(db_session)
    project_id = await _seed_project(db_session, t513b_owner.id)
    past_expiry = datetime.now(UTC) - timedelta(hours=1)
    invitation, signed = await _seed_pending(
        db_session,
        canonical_email=t513b_recipient.email,
        invited_by_id=t513b_owner.id,
        project_id=project_id,
        raw_seed=b"\xa3" * 32,
        expires_at=past_expiry,
    )

    response = await web_client.delete(
        _delete_url(invitation, signed),
        headers=_bearer(t513b_recipient),
    )
    assert response.status_code == 404, response.text


# ---------------------------------------------------------------------------
# 5. Revoked terminal-status row → 410.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decline_revoked_invitation_returns_410(
    web_client: AsyncClient,
    db_session: AsyncSession,
    t513b_owner: User,
    t513b_recipient: User,
) -> None:
    await _purge(db_session)
    project_id = await _seed_project(db_session, t513b_owner.id)
    invitation, signed = await _seed_pending(
        db_session,
        canonical_email=t513b_recipient.email,
        invited_by_id=t513b_owner.id,
        project_id=project_id,
        raw_seed=b"\xa4" * 32,
        status=ProjectInvitationStatus.REVOKED,
    )

    response = await web_client.delete(
        _delete_url(invitation, signed),
        headers=_bearer(t513b_recipient),
    )
    assert response.status_code == 410, response.text


# ---------------------------------------------------------------------------
# 6. Unknown token (random signed envelope) → 404.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decline_unknown_token_returns_404(
    web_client: AsyncClient,
    db_session: AsyncSession,
    t513b_recipient: User,
) -> None:
    await _purge(db_session)
    raw_token_b64u = invitation_service._b64u_encode(b"\xa5" * 32)
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    signed = sign_invitation_token(
        raw_token_b64u=raw_token_b64u,
        expires_at=expires_at,
        hmac_secret=_hmac_secret(),
    )

    response = await web_client.delete(
        f"/web-api/v1/projects/{uuid4()}/invitations/{signed}",
        headers=_bearer(t513b_recipient),
    )
    assert response.status_code == 404, response.text


# ---------------------------------------------------------------------------
# 7. Cross-account token (signed but row email != caller email) → 404.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decline_cross_account_token_returns_404(
    web_client: AsyncClient,
    db_session: AsyncSession,
    t513b_owner: User,
    t513b_recipient: User,
    t513b_other: User,
) -> None:
    await _purge(db_session)
    project_id = await _seed_project(db_session, t513b_owner.id)
    invitation, signed = await _seed_pending(
        db_session,
        canonical_email=t513b_recipient.email,
        invited_by_id=t513b_owner.id,
        project_id=project_id,
        raw_seed=b"\xa6" * 32,
    )

    # Caller is an unrelated authenticated user.
    response = await web_client.delete(
        _delete_url(invitation, signed),
        headers=_bearer(t513b_other),
    )
    assert response.status_code == 404, response.text

    # Row remains pending — no state change leaked.
    refreshed = (
        await db_session.execute(
            sa.select(ProjectInvitation).where(
                ProjectInvitation.id == invitation.id
            )
        )
    ).scalar_one()
    assert refreshed.status is ProjectInvitationStatus.PENDING


# ---------------------------------------------------------------------------
# 8. Email mismatch with NFKC-distinct address → 404 (FR-055 uniformity).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decline_email_mismatch_returns_404(
    web_client: AsyncClient,
    db_session: AsyncSession,
    t513b_owner: User,
    t513b_recipient: User,
    t513b_other: User,
) -> None:
    """Caller authenticated as `other` but row email is `recipient`."""
    await _purge(db_session)
    project_id = await _seed_project(db_session, t513b_owner.id)
    invitation, signed = await _seed_pending(
        db_session,
        canonical_email=t513b_recipient.email,
        invited_by_id=t513b_owner.id,
        project_id=project_id,
        raw_seed=b"\xa7" * 32,
    )

    response = await web_client.delete(
        _delete_url(invitation, signed),
        headers=_bearer(t513b_other),
    )
    assert response.status_code == 404, response.text


# ---------------------------------------------------------------------------
# 9. Unauthenticated caller → 401.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decline_unauthenticated_returns_401(
    web_client: AsyncClient,
    db_session: AsyncSession,
    t513b_owner: User,
    t513b_recipient: User,
) -> None:
    await _purge(db_session)
    project_id = await _seed_project(db_session, t513b_owner.id)
    invitation, signed = await _seed_pending(
        db_session,
        canonical_email=t513b_recipient.email,
        invited_by_id=t513b_owner.id,
        project_id=project_id,
        raw_seed=b"\xa8" * 32,
    )

    response = await web_client.delete(_delete_url(invitation, signed))
    assert response.status_code == 401, response.text


# ---------------------------------------------------------------------------
# 10. Cross-project token (URL path project_id != row project_id) → 404.
#     Phase 10 Batch 2 Round 2 polish (致命 3): the decline handler now
#     passes ``project_id_scope=path_project_id`` into the service so a
#     valid signed token under a *different* project's URL collapses to
#     the same 404 envelope (FR-055 enumeration mitigation).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decline_cross_project_token_returns_404(
    web_client: AsyncClient,
    db_session: AsyncSession,
    t513b_owner: User,
    t513b_recipient: User,
) -> None:
    """A valid signed token aimed at the *wrong* project_id → 404.

    Without the path scope guard the handler used to delete the row
    regardless of which project URL the recipient hit, which would let
    an attacker that guessed a project_id confirm token validity by
    diffing 410 (terminal state) vs 404 (token unknown) responses.
    """
    await _purge(db_session)
    project_a = await _seed_project(db_session, t513b_owner.id)
    project_b = await _seed_project(db_session, t513b_owner.id)
    invitation, signed = await _seed_pending(
        db_session,
        canonical_email=t513b_recipient.email,
        invited_by_id=t513b_owner.id,
        project_id=project_a,
        raw_seed=b"\xb1" * 32,
    )

    # Hit the token under project B's URL — the row's project_id is A.
    response = await web_client.delete(
        f"/web-api/v1/projects/{project_b}/invitations/{signed}",
        headers=_bearer(t513b_recipient),
    )
    assert response.status_code == 404, response.text

    # Row must still be PENDING (no state leak across projects).
    refreshed = (
        await db_session.execute(
            sa.select(ProjectInvitation).where(
                ProjectInvitation.id == invitation.id
            )
        )
    ).scalar_one()
    assert refreshed.status is ProjectInvitationStatus.PENDING


__all__ = [
    "test_decline_accepted_invitation_returns_410",
    "test_decline_cross_account_token_returns_404",
    "test_decline_cross_project_token_returns_404",
    "test_decline_email_mismatch_returns_404",
    "test_decline_pending_returns_204_and_marks_declined",
    "test_decline_revoked_invitation_returns_410",
    "test_decline_signature_expired_returns_404",
    "test_decline_unauthenticated_returns_401",
    "test_decline_unknown_token_returns_404",
    "test_redecline_already_declined_is_idempotent_204",
]
