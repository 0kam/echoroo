"""Production HTTP gate consults Trusted overlay (T532 follow-up — 致命 2 / 致命 1).

Phase 10 Batch 2 Round 2 polish: the Codex review flagged that the
Stage-1 :func:`echoroo.core.permissions.gate_action` previously only
resolved the caller's *member* role and never invoked
:func:`echoroo.services.trusted_service.get_active_trusted_capabilities`.
That meant an Authenticated principal who accepted a Trusted overlay
could not exercise the granted permissions on the live HTTP path —
``trusted_capabilities`` was always passed as the empty frozenset to
:func:`is_allowed` so the overlay union (FR-015 step 3) was a no-op.

This module pins the production fix at the HTTP layer:

1. **Trusted overlay grants VIEW_MEDIA** — an Authenticated user with
   an active Trusted row containing ``view_media`` may
   ``GET /web-api/v1/recordings/{id}/audio`` on a Restricted project
   that disables ``allow_media_playback``. Without the fix the gate
   would 403 because the Restricted toggle map alone produces an empty
   set for VIEW_MEDIA.
2. **Allowlist still bounds the overlay** — a Trusted row that names
   ``view_audit_log`` (NOT in TRUSTED_ALLOWED_PERMISSIONS) does NOT
   unlock the Audit Log endpoint. The runtime safety net in
   :func:`get_active_trusted_capabilities` filters the row out before
   it reaches :func:`is_allowed`.

Plus the Admin GET /trusted-users access matrix (致命 1):

3. **Admin GET /trusted-users → 200** — the contract spec says the
   list endpoint is Owner / Admin. The fix changed the list Action's
   required Permission from ``MANAGE_TRUSTED`` (Owner-only per L425
   Canonical Matrix) to ``MANAGE_MEMBERS`` (Owner + Admin) so Admin
   may enumerate without ability to mutate.
4. **Admin POST /trusted-users → 403** — INVITE remains Owner-only
   (FR-050) so the Admin still gets ``ERR_OWNER_ONLY``.
5. **Admin PATCH /trusted-users/{id} → 403** — same.
6. **Admin DELETE /trusted-users/{id} → 403** — same.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch as _patch
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from echoroo.core.jwt import create_access_token
from echoroo.models.enums import (
    ProjectInvitationKind,
    ProjectInvitationStatus,
    ProjectMemberRole,
    ProjectTrustedStatus,
)
from echoroo.models.project import (
    Project,
    ProjectInvitation,
    ProjectMember,
)
from echoroo.models.project_trusted_user import ProjectTrustedUser
from echoroo.models.user import User

_TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://echoroo:echoroo@localhost:5432/echoroo_test",
)


# ---------------------------------------------------------------------------
# Test harness — Bearer-principal middleware that mirrors the production
# auth chain enough to drive ``gate_action``.
# ---------------------------------------------------------------------------


def _bearer(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token({'sub': str(user.id)})}"}


@pytest_asyncio.fixture
async def web_client(
    db_session: AsyncSession,  # noqa: ARG001 — ensures the DB is initialised
) -> AsyncGenerator[AsyncClient, None]:
    """Mount the real ``/web-api/v1`` router behind a Bearer middleware.

    Mirrors the harness in :mod:`tests.contract.test_invitation_recipient_self_delete`
    so we drive the production routing + dependency chain.
    """
    from collections.abc import Awaitable, Callable

    from fastapi import FastAPI
    from fastapi.exceptions import RequestValidationError
    from starlette.exceptions import HTTPException as _StarletteHTTPException
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import Response
    from starlette.types import ASGIApp

    from echoroo.api.v1 import recordings as recordings_module
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
    # Phase 10 Batch 2 Round 3 fix (Major 1): mount the production
    # ``/api/v1/projects/{id}/recordings`` router so the Trusted-overlay
    # 致命 2 test reaches a real ``gate_action`` invocation. The
    # ``recordings.router`` defines its own ``/projects/{project_id}/
    # recordings`` prefix; we mount it under ``/api/v1`` so the test URL
    # mirrors the production layout.
    app.include_router(recordings_module.router, prefix="/api/v1")

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

    # PR-C7 (Phase 17 §C, 2026-05-07): override AudioService so the
    # ``recordings`` router does not try to mkdir ``/data/s3_audio_cache``
    # (Settings default), which fails on CI runners with PermissionError
    # on ``/data``. Mirrors the equivalent override in the main
    # ``client`` fixture (tests/conftest.py).
    import tempfile as _tempfile
    from pathlib import Path as _Path

    from echoroo.core.settings import get_settings as _get_settings
    from echoroo.services.audio.service import AudioService as _AudioService

    _settings = _get_settings()
    _audio_cache_tmp_root = (
        _Path(_tempfile.gettempdir()) / "echoroo-test-s3-audio-cache"
    )
    _audio_cache_tmp_root.mkdir(parents=True, exist_ok=True)

    def override_get_audio_service() -> _AudioService:
        return _AudioService(
            _settings.AUDIO_ROOT,
            _settings.AUDIO_CACHE_DIR,
            s3_audio_cache_dir=str(_audio_cache_tmp_root),
        )

    app.dependency_overrides[recordings_module.get_audio_service] = (
        override_get_audio_service
    )

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
# DB seed helpers
# ---------------------------------------------------------------------------


async def _purge(db: AsyncSession) -> None:
    await db.execute(sa.text("DELETE FROM project_trusted_users"))
    await db.execute(sa.text("DELETE FROM project_invitations"))
    await db.execute(sa.text("DELETE FROM project_members"))
    await db.execute(sa.text("DELETE FROM projects"))
    await db.commit()


async def _seed_user(
    db: AsyncSession, *, email_prefix: str, stamp_prefix: str
) -> User:
    user = User(
        email=f"{email_prefix}-{uuid4().hex[:8]}@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name=f"{email_prefix}",
        security_stamp=(stamp_prefix + "x" * 64)[:64],
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _seed_project(
    db: AsyncSession,
    owner_id: Any,
    *,
    allow_media_playback: bool = False,
) -> Project:
    """Seed a Restricted project (the FR-014 / 致命 2 happy path needs
    ``allow_media_playback=False`` so VIEW_MEDIA can only come from the
    Trusted overlay)."""
    from echoroo.models.enums import ProjectLicense, ProjectVisibility

    project = Project(
        name=f"T532HTTP {uuid4().hex[:8]}",
        visibility=ProjectVisibility.RESTRICTED,
        license_id="cc-by",
        owner_id=owner_id,
        restricted_config={
            "allow_media_playback": allow_media_playback,
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
    return project


async def _seed_admin_member(
    db: AsyncSession, *, project_id: Any, user_id: Any, owner_id: Any
) -> ProjectMember:
    member = ProjectMember(
        project_id=project_id,
        user_id=user_id,
        role=ProjectMemberRole.ADMIN,
        joined_at=datetime.now(UTC),
        invited_by_id=owner_id,
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)
    return member


async def _seed_trusted_overlay(
    db: AsyncSession,
    *,
    project_id: Any,
    user_id: Any,
    owner_id: Any,
    granted_permissions: list[str],
) -> ProjectTrustedUser:
    """Seed an active Trusted overlay row for ``user_id`` on ``project_id``."""
    expires_at = datetime.now(UTC) + timedelta(days=30)
    invitation = ProjectInvitation(
        project_id=project_id,
        kind=ProjectInvitationKind.TRUSTED,
        email="trusted-target@example.com",
        email_hash="0" * 64,
        granted_permissions=granted_permissions,
        trusted_duration_seconds=30 * 24 * 3600,
        token_hash=("a" * 32 + uuid4().hex)[:64],
        invited_by_id=owner_id,
        expires_at=expires_at,
        status=ProjectInvitationStatus.ACCEPTED,
        accepted_at=datetime.now(UTC),
    )
    db.add(invitation)
    await db.flush()
    overlay = ProjectTrustedUser(
        project_id=project_id,
        user_id=user_id,
        invitation_id=invitation.id,
        granted_by_id=owner_id,
        granted_at=datetime.now(UTC),
        expires_at=expires_at,
        status=ProjectTrustedStatus.ACTIVE,
        granted_permissions=granted_permissions,
        email_at_invitation="trusted-target@example.com",
        email_at_invitation_hash="0" * 64,
    )
    db.add(overlay)
    await db.commit()
    await db.refresh(overlay)
    return overlay


# ---------------------------------------------------------------------------
# 致命 2 — Trusted overlay routes through the production HTTP gate.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_can_list_trusted_users_via_http_gate(
    web_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """致命 1 happy path — Admin reaches GET /trusted-users with 200.

    Pins the Action change: ``PROJECT_TRUSTED_LIST_ACTION`` now requires
    ``MANAGE_MEMBERS`` (Owner + Admin) instead of ``MANAGE_TRUSTED``
    (Owner only). Without the change Admin would receive 403.
    """
    await _purge(db_session)
    owner = await _seed_user(
        db_session, email_prefix="t532http-owner", stamp_prefix="o"
    )
    admin = await _seed_user(
        db_session, email_prefix="t532http-admin", stamp_prefix="a"
    )
    project = await _seed_project(db_session, owner.id)
    await _seed_admin_member(
        db_session, project_id=project.id, user_id=admin.id, owner_id=owner.id
    )

    response = await web_client.get(
        f"/web-api/v1/projects/{project.id}/trusted-users",
        headers=_bearer(admin),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "items" in body
    assert "total" in body


@pytest.mark.asyncio
async def test_admin_post_trusted_user_invite_returns_403(
    web_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """致命 1 mutating leg — Admin POST /trusted-users → 403 (FR-050).

    The list Action is now ``MANAGE_MEMBERS`` (Owner + Admin) so the
    Stage-1 gate passes for Admin, but the endpoint's
    ``_require_owner`` second-line check still raises
    ``ERR_OWNER_ONLY``. We accept either 403 path (gate or guard); the
    contract is "Admin cannot mutate" regardless of which layer rejects.
    """
    await _purge(db_session)
    owner = await _seed_user(
        db_session, email_prefix="t532http-owner", stamp_prefix="o"
    )
    admin = await _seed_user(
        db_session, email_prefix="t532http-admin", stamp_prefix="a"
    )
    project = await _seed_project(db_session, owner.id)
    await _seed_admin_member(
        db_session, project_id=project.id, user_id=admin.id, owner_id=owner.id
    )

    response = await web_client.post(
        f"/web-api/v1/projects/{project.id}/trusted-users",
        headers=_bearer(admin),
        json={
            "email": "trusted-recipient@example.com",
            "granted_permissions": ["view_media"],
            "duration_seconds": 86400,
        },
    )
    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_admin_patch_trusted_user_returns_403(
    web_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """致命 1 mutating leg — Admin PATCH /trusted-users/{id} → 403."""
    await _purge(db_session)
    owner = await _seed_user(
        db_session, email_prefix="t532http-owner", stamp_prefix="o"
    )
    admin = await _seed_user(
        db_session, email_prefix="t532http-admin", stamp_prefix="a"
    )
    target = await _seed_user(
        db_session, email_prefix="t532http-target", stamp_prefix="t"
    )
    project = await _seed_project(db_session, owner.id)
    await _seed_admin_member(
        db_session, project_id=project.id, user_id=admin.id, owner_id=owner.id
    )
    overlay = await _seed_trusted_overlay(
        db_session,
        project_id=project.id,
        user_id=target.id,
        owner_id=owner.id,
        granted_permissions=["view_media"],
    )

    response = await web_client.patch(
        f"/web-api/v1/projects/{project.id}/trusted-users/{overlay.id}",
        headers=_bearer(admin),
        json={"extension_seconds": 86400},
    )
    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_admin_delete_trusted_user_returns_403(
    web_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """致命 1 mutating leg — Admin DELETE /trusted-users/{id} → 403."""
    await _purge(db_session)
    owner = await _seed_user(
        db_session, email_prefix="t532http-owner", stamp_prefix="o"
    )
    admin = await _seed_user(
        db_session, email_prefix="t532http-admin", stamp_prefix="a"
    )
    target = await _seed_user(
        db_session, email_prefix="t532http-target", stamp_prefix="t"
    )
    project = await _seed_project(db_session, owner.id)
    await _seed_admin_member(
        db_session, project_id=project.id, user_id=admin.id, owner_id=owner.id
    )
    overlay = await _seed_trusted_overlay(
        db_session,
        project_id=project.id,
        user_id=target.id,
        owner_id=owner.id,
        granted_permissions=["view_media"],
    )

    response = await web_client.delete(
        f"/web-api/v1/projects/{project.id}/trusted-users/{overlay.id}",
        headers=_bearer(admin),
    )
    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_owner_can_list_trusted_users_via_http_gate(
    web_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Sanity — Owner GET /trusted-users → 200 (regression guard)."""
    await _purge(db_session)
    owner = await _seed_user(
        db_session, email_prefix="t532http-owner", stamp_prefix="o"
    )
    project = await _seed_project(db_session, owner.id)

    response = await web_client.get(
        f"/web-api/v1/projects/{project.id}/trusted-users",
        headers=_bearer(owner),
    )
    assert response.status_code == 200, response.text


# ---------------------------------------------------------------------------
# 致命 2 (HTTP gate consults Trusted overlay) — assertion lives below.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trusted_overlay_grants_view_media_via_http_gate(
    web_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """致命 2: production HTTP gate UNIONs Trusted overlay perms.

    The Restricted project has ``allow_media_playback=False`` so an
    Authenticated principal without an overlay reaches the
    ``recording.audio`` Action with VIEW_MEDIA NOT in the effective
    set (Authenticated default for Restricted is empty for media). The
    overlay row contains ``view_media`` so after the fix
    :func:`gate_action` calls :func:`get_active_trusted_capabilities`
    and unions VIEW_MEDIA into the effective set; the gate returns 200
    (or 404 if the recording does not exist, but NEVER 403).

    Phase 10 Batch 2 Round 3 fix (Major 1): the previous version of
    this test hit
    ``/web-api/v1/projects/.../recordings/.../audio`` which is NOT a
    registered route on the Web router (recordings live on
    ``/api/v1``). The 404 from the unknown route gave the assertion a
    false positive — the gate was never executed. We now mount the
    production recordings router under ``/api/v1`` in the test app and
    drive the gate through the Bearer + ``?token=`` flexible auth path
    that production uses for media URLs.
    """
    await _purge(db_session)
    owner = await _seed_user(
        db_session, email_prefix="t532http-owner", stamp_prefix="o"
    )
    target = await _seed_user(
        db_session, email_prefix="t532http-target", stamp_prefix="t"
    )
    project = await _seed_project(
        db_session, owner.id, allow_media_playback=False
    )
    await _seed_trusted_overlay(
        db_session,
        project_id=project.id,
        user_id=target.id,
        owner_id=owner.id,
        granted_permissions=["view_media"],
    )

    # Hit the real production audio route. The recording row does not
    # exist, so the worst-case PASS path is 404 (the recording lookup
    # raises ``Recording not found``); a FAIL of the gate produces 403
    # from ``gate_action`` BEFORE the recording lookup runs. The pin is
    # specifically that 403 must NOT appear, and the response must be a
    # status code that proves the gate ran (200 or 404).
    nonexistent_recording_id = uuid4()
    response = await web_client.get(
        f"/api/v1/projects/{project.id}/recordings/{nonexistent_recording_id}/audio",
        headers=_bearer(target),
    )
    assert response.status_code != 403, (
        "Trusted overlay should grant VIEW_MEDIA — "
        f"gate denied with 403: {response.text}"
    )
    assert response.status_code in (200, 404), (
        "Expected the gate to pass through to the recording lookup "
        f"(200 / 404) — got {response.status_code}: {response.text}"
    )


@pytest.mark.asyncio
async def test_trusted_overlay_with_unauthorized_perm_does_not_unlock_audit(
    web_client: AsyncClient,  # noqa: ARG001 — fixture only provides DB engine setup
    db_session: AsyncSession,
) -> None:
    """致命 2 safety net: an out-of-allowlist row name
    (``view_audit_log``) in ``granted_permissions`` is filtered out by
    :func:`get_active_trusted_capabilities` before it can reach the gate
    (FR-014).

    Phase 10 Batch 2 Round 3 fix (Major 2): the previous HTTP-based
    version hit ``GET /web-api/v1/projects/{id}/trusted-users`` which is
    gated by ``MANAGE_MEMBERS`` (NOT ``VIEW_AUDIT_LOG``); the endpoint
    would have returned 403 even if the allowlist intersection were
    broken, so the test was a false positive on the runtime safety net.
    We now invoke the helper directly and assert the contract: a smuggled
    ``view_audit_log`` permission MUST NOT appear in the active
    capability set, and only the ``TRUSTED_ALLOWED_PERMISSIONS`` subset
    survives the intersection.
    """
    from echoroo.core.permissions import (
        TRUSTED_ALLOWED_PERMISSIONS,
        Permission,
    )
    from echoroo.services.trusted_service import (
        get_active_trusted_capabilities,
    )

    await _purge(db_session)
    owner = await _seed_user(
        db_session, email_prefix="t532http-owner", stamp_prefix="o"
    )
    target = await _seed_user(
        db_session, email_prefix="t532http-target", stamp_prefix="t"
    )
    project = await _seed_project(db_session, owner.id)
    await _seed_trusted_overlay(
        db_session,
        project_id=project.id,
        user_id=target.id,
        owner_id=owner.id,
        # Smuggle an Admin-only permission into the overlay row alongside
        # one that IS in the allowlist (``view_media``) so the assertion
        # cannot pass trivially via an empty intersection.
        granted_permissions=["view_media", "view_audit_log"],
    )

    capabilities = await get_active_trusted_capabilities(
        db_session, user_id=target.id, project_id=project.id
    )

    # FR-014 runtime safety net — VIEW_AUDIT_LOG must NOT survive
    # intersection with ``TRUSTED_ALLOWED_PERMISSIONS``.
    assert Permission.VIEW_AUDIT_LOG not in capabilities, (
        "FR-014: get_active_trusted_capabilities must drop "
        "view_audit_log via the TRUSTED_ALLOWED_PERMISSIONS "
        f"intersection, but it survived: {capabilities}"
    )
    # Sanity: the ``view_media`` permission DID survive (proving the
    # helper actually ran the row instead of returning empty for an
    # unrelated reason).
    assert Permission.VIEW_MEDIA in capabilities, (
        "Allowlist-permitted view_media should survive the "
        f"intersection but was dropped: {capabilities}"
    )
    # Defence-in-depth: every surviving permission MUST be in the
    # allowlist; the smuggled value must have been the only casualty.
    assert capabilities <= TRUSTED_ALLOWED_PERMISSIONS, (
        "Surviving capabilities exceeded TRUSTED_ALLOWED_PERMISSIONS: "
        f"{capabilities - TRUSTED_ALLOWED_PERMISSIONS}"
    )


@pytest.mark.asyncio
async def test_existing_membership_role_unicode_evasion(
    db_session: AsyncSession,
) -> None:
    """Phase 10 Batch 2 Round 3 fix (Major 3) regression: a Unicode
    equivalent of an existing member's email must still resolve through
    :func:`_existing_membership_role`.

    The DB stores the canonical ASCII address; the attacker sends a
    Unicode-equivalent variant (fullwidth ``Ａ``) that NFKC + casefold
    folds to the same canonical form. The helper must catch it via the
    Python-side comparison the fix introduced — the previous
    ``func.lower(User.email)`` SQL filter would silently miss the row
    because Postgres' ``LOWER`` does not normalise Unicode codepoints.
    """
    from echoroo.api.web_v1.trusted import (
        _canonicalise_email,
        _existing_membership_role,
    )

    await _purge(db_session)
    owner = await _seed_user(
        db_session, email_prefix="t532canon-owner", stamp_prefix="o"
    )
    # Stored email is ASCII canonical form.
    member = User(
        email="canon-target@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="canon-target",
        security_stamp="m" + "x" * 63,
    )
    db_session.add(member)
    await db_session.commit()
    await db_session.refresh(member)

    project = await _seed_project(db_session, owner.id)
    db_session.add(
        ProjectMember(
            project_id=project.id,
            user_id=member.id,
            role=ProjectMemberRole.MEMBER,
            joined_at=datetime.now(UTC),
            invited_by_id=owner.id,
        )
    )
    await db_session.commit()

    # Attacker-supplied address: fullwidth ``Ｃ`` + uppercase mix; NFKC +
    # casefold yields the same canonical form as ``canon-target@…``.
    attacker_input = "ｃanon-target@example.com"  # fullwidth 'c'
    canonical = _canonicalise_email(attacker_input)
    assert canonical == "canon-target@example.com", (
        "Sanity: NFKC casefold must collapse the variant into the "
        "ASCII canonical form before the helper runs."
    )

    role = await _existing_membership_role(
        db_session, project_id=project.id, canonical_email=canonical
    )
    assert role == ProjectMemberRole.MEMBER, (
        "Major 3 regression: Python-side NFKC + casefold compare must "
        "match the existing member regardless of the SQL casefold "
        "implementation."
    )


__all__ = [
    "test_admin_can_list_trusted_users_via_http_gate",
    "test_admin_delete_trusted_user_returns_403",
    "test_admin_patch_trusted_user_returns_403",
    "test_admin_post_trusted_user_invite_returns_403",
    "test_existing_membership_role_unicode_evasion",
    "test_owner_can_list_trusted_users_via_http_gate",
    "test_trusted_overlay_grants_view_media_via_http_gate",
    "test_trusted_overlay_with_unauthorized_perm_does_not_unlock_audit",
]
