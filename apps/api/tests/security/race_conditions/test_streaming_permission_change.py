"""Race-condition tests: mid-stream permission change during CSV export (T973, H-6).

Security contract (H-6):
  When a streaming CSV export is in progress and the caller's project
  membership is revoked mid-stream, the remaining chunks of the response
  MUST NOT be delivered. The endpoint must abort the stream with a 403 and
  discard any buffered partial content so that a user whose access has been
  revoked cannot exfiltrate data that is already being transferred.

Current implementation status:
  The ``export_csv`` endpoint in ``echoroo/api/v1/detections.py`` buffers the
  entire CSV into memory (``io.BytesIO``) BEFORE returning the
  ``StreamingResponse``. The ``gate_action()`` pre-check happens at the start
  of the request, not inside the streaming loop. This means:

    1. Permission is checked exactly once (before streaming starts).
    2. If membership is revoked *after* the pre-check passes but before the
       response bytes are sent, the buffered bytes will still be delivered
       because there is no per-chunk re-validation mechanism.

  The per-chunk guard (``check_permission_each_chunk()`` or equivalent) is
  therefore NOT implemented. The tests below document the expected contract,
  mark the per-chunk guard as ``xfail(strict=True)`` with a forward reference
  to a future task, and provide passing smoke tests that verify the pre-check
  gate works correctly.

Forward task:
  Implement per-chunk permission re-validation for true streaming exports.
  This is tracked as a separate task; until then the xfail marker keeps the
  TDD red phase visible without blocking the test suite.

Shim usage:
  T973-1 uses the global ``client`` fixture (Batch 6c shim active). The shim
  synthesises a full-scope Principal from JWT tokens so RBAC intersection is
  effectively a no-op — T973-1 only checks that the endpoint is reachable
  without 401. T973-2 and T973-3 use the ``unshimmed_rbac_client`` fixture
  which builds the app with the real ``DbApiKeyVerifier`` so that accurate
  membership-based RBAC decisions are observable.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from echoroo.core.jwt import create_access_token as _create_jwt_token
from echoroo.models.enums import (
    ProjectLicense,
    ProjectMemberRole,
    ProjectVisibility,
)
from echoroo.models.project import Project, ProjectMember
from echoroo.models.user import User

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://echoroo:echoroo@localhost:5432/echoroo_test",
)


def _make_bearer_token(user_id: Any) -> str:
    """Create a plain JWT access token in the legacy dict form."""
    return _create_jwt_token({"sub": str(user_id)})


# ---------------------------------------------------------------------------
# unshimmed_rbac_client fixture (no Batch 6c JWT shim)
# ---------------------------------------------------------------------------


@pytest.fixture
async def unshimmed_rbac_client(
    db_session: AsyncSession,  # noqa: ARG001
) -> AsyncGenerator[AsyncClient, None]:
    """App client WITHOUT the Batch 6c JWT shim, backed by the test DB.

    Builds the real application with ``DbApiKeyVerifier`` active so that
    JWT tokens are correctly rejected on ``/api/v1/*``. Callers must
    supply an ``echoroo_*`` API key (inserted via ``_seed_api_key``) to
    authenticate against the programmatic surface.

    The ``db_session`` fixture is accepted (but not directly used) solely
    to trigger DB setup (clean-up + schema check) before the test runs.
    """
    from echoroo.core.database import get_db
    from echoroo.main import create_app

    engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as http_client:
            yield http_client
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


async def _make_user(db: AsyncSession, *, email: str) -> User:
    user = User(
        email=email,
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name=f"T973 {email}",
        security_stamp="s" * 64,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


async def _make_project(db: AsyncSession, *, owner: User) -> Project:
    project = Project(
        name="T973 Stream Project",
        description="streaming permission race test",
        visibility=ProjectVisibility.RESTRICTED,
        license=ProjectLicense.CC_BY,
        owner_id=owner.id,
        restricted_config={
            "allow_media_playback": True,
            "allow_detection_view": True,
            "mask_species_in_detection": False,
            "allow_download": True,
            "allow_export": True,
            "allow_voting_and_comments": False,
            "public_location_precision_h3_res": 5,
            "allow_precise_location_to_viewer": False,
        },
    )
    db.add(project)
    await db.flush()
    await db.refresh(project)
    return project


async def _add_member(
    db: AsyncSession, *, project: Project, user: User, role: ProjectMemberRole
) -> ProjectMember:
    member = ProjectMember(
        project_id=project.id,
        user_id=user.id,
        role=role,
        invited_by_id=project.owner_id,
    )
    db.add(member)
    await db.flush()
    return member


async def _seed_api_key(
    db: AsyncSession,
    *,
    user: User,
    project: Project,
    permissions: list[str] | None = None,
) -> str:
    """Insert an api_keys row and return the raw ``echoroo_*`` wire key."""
    from echoroo.models.api_key import ApiKey

    raw_secret = secrets.token_urlsafe(32)
    prefix_random = secrets.token_urlsafe(6)[:8]
    prefix = f"echoroo_{prefix_random}"
    hashed = hashlib.sha256(raw_secret.encode()).hexdigest()

    from datetime import UTC, datetime, timedelta

    key = ApiKey(
        id=uuid.uuid4(),
        user_id=user.id,
        project_id=project.id,
        prefix=prefix,
        hashed_secret=hashed,
        granted_permissions=permissions or ["view_project_metadata", "export"],
        expires_at=datetime.now(UTC) + timedelta(days=365),
    )
    db.add(key)
    await db.flush()
    await db.refresh(key)
    return f"{prefix}_{raw_secret}"


# ---------------------------------------------------------------------------
# T973-1: positive smoke test — uses global client (shim active)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_csv_export_succeeds_when_member_at_call_time(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Member user can reach the CSV export endpoint — positive smoke test.

    Uses the shim-active client: a JWT Bearer token synthesises a
    full-scope Principal so the RBAC intersection is a no-op. The test
    only asserts the endpoint is reachable (not 401).
    """
    owner = await _make_user(db_session, email=f"t973_pos_o_{uuid.uuid4().hex[:6]}@example.com")
    member = await _make_user(db_session, email=f"t973_pos_m_{uuid.uuid4().hex[:6]}@example.com")
    project = await _make_project(db_session, owner=owner)
    await _add_member(db_session, project=project, user=member, role=ProjectMemberRole.MEMBER)
    await db_session.commit()

    token = _make_bearer_token(member.id)
    response = await client.get(
        f"/api/v1/projects/{project.id}/detections/export/csv",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code != 401, (
        "Member with JWT (shim active) must not receive 401 on CSV export, "
        f"got {response.status_code}: {response.text!r}"
    )


# ---------------------------------------------------------------------------
# T973-2: revoked before request → 403 (uses unshimmed_rbac_client)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_csv_export_returns_403_when_revoked_before_request(
    unshimmed_rbac_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """A user removed from project before the request → 403.

    Uses the unshimmed client so that real RBAC applies. The user's
    ProjectMember row is deleted before the request; gate_action must
    catch it and return 403.
    """
    import sqlalchemy as sa

    owner = await _make_user(db_session, email=f"t973_pre_o_{uuid.uuid4().hex[:6]}@example.com")
    ex_member = await _make_user(db_session, email=f"t973_pre_m_{uuid.uuid4().hex[:6]}@example.com")
    project = await _make_project(db_session, owner=owner)
    await _add_member(
        db_session, project=project, user=ex_member, role=ProjectMemberRole.MEMBER
    )
    # Seed an API key for ex_member so they can authenticate via /api/v1/*.
    raw_key = await _seed_api_key(db_session, user=ex_member, project=project)
    await db_session.commit()

    # Revoke membership.
    await db_session.execute(
        sa.delete(ProjectMember).where(
            (ProjectMember.project_id == project.id)
            & (ProjectMember.user_id == ex_member.id)
        )
    )
    await db_session.commit()

    response = await unshimmed_rbac_client.get(
        f"/api/v1/projects/{project.id}/detections/export/csv",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code in (403, 404), (
        "Revoked member must receive 403 or 404 on CSV export (anti-enumeration), "
        f"got {response.status_code}: {response.text!r}"
    )


# ---------------------------------------------------------------------------
# T973-3: mid-stream revocation → xfail (per-chunk guard not implemented)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Per-chunk permission re-validation not implemented. "
        "export_csv in echoroo/api/v1/detections.py buffers the entire CSV "
        "into io.BytesIO before returning StreamingResponse — there is no "
        "streaming loop in which to inject a per-chunk permission check. "
        "A true mid-stream revocation (permission change between gate_action "
        "pass and response delivery) cannot be detected with the current "
        "buffered implementation. "
        "To fix: refactor export_csv to an async generator with "
        "check_permission_each_chunk() called before yielding each row. "
        "Track as follow-up task."
    ),
)
@pytest.mark.asyncio
async def test_csv_stream_aborts_when_permission_revoked_mid_stream(
    unshimmed_rbac_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """H-6 contract: mid-stream revocation MUST abort the stream with 403.

    The test simulates the window where:
      1. Member starts a CSV export (gate_action passes — member row exists).
      2. *After* gate_action passes but *before* stream bytes are delivered,
         the member's role is demoted to VIEWER (no EXPORT permission).
      3. The endpoint must detect this mid-stream and abort with 403.

    With the current buffered implementation the gate_action call completes
    synchronously BEFORE the response is created; the demotion is done
    in-test after the request and cannot be intercepted in the stream.
    This test uses monkeypatching to inject the revocation between the
    gate_action pass and the StreamingResponse creation, demonstrating that
    no guard exists there.

    Expected outcome once implemented: 403 response with empty body.
    Current outcome: 200 (buffered CSV delivered regardless of post-gate
    revocation) — hence xfail.
    """
    import sqlalchemy as sa

    from echoroo.api.v1 import detections as det_module

    owner = await _make_user(db_session, email=f"t973_mid_o_{uuid.uuid4().hex[:6]}@example.com")
    member = await _make_user(db_session, email=f"t973_mid_m_{uuid.uuid4().hex[:6]}@example.com")
    project = await _make_project(db_session, owner=owner)
    await _add_member(
        db_session, project=project, user=member, role=ProjectMemberRole.MEMBER
    )
    raw_key = await _seed_api_key(db_session, user=member, project=project)
    await db_session.commit()

    # Capture the original gate_action to inject a revocation between gate
    # pass and StreamingResponse creation.
    original_gate_action = det_module.gate_action

    async def _gate_then_revoke(*args: Any, **kwargs: Any) -> Any:
        """Run gate_action then immediately revoke membership."""
        result = await original_gate_action(*args, **kwargs)
        # Simulate mid-stream revocation: demote member to VIEWER.
        engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with factory() as revoke_session:
                await revoke_session.execute(
                    sa.update(ProjectMember)
                    .where(
                        (ProjectMember.project_id == project.id)
                        & (ProjectMember.user_id == member.id)
                    )
                    .values(role=ProjectMemberRole.VIEWER)
                )
                await revoke_session.commit()
        finally:
            await engine.dispose()
        return result

    det_module.gate_action = _gate_then_revoke  # type: ignore[assignment]

    try:
        response = await unshimmed_rbac_client.get(
            f"/api/v1/projects/{project.id}/detections/export/csv",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        # This assertion will fail until per-chunk guard is implemented.
        assert response.status_code == 403, (
            f"Mid-stream permission revocation MUST abort the stream with 403 "
            f"(H-6 contract), but the current buffered implementation returned "
            f"{response.status_code}. "
            "Implement per-chunk permission re-validation to fix this."
        )
    finally:
        det_module.gate_action = original_gate_action  # type: ignore[assignment]
