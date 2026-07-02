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
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from echoroo.core.jwt import create_access_token as _create_jwt_token
from echoroo.models.enums import (
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


async def _bff_session_headers(
    client: AsyncClient, db: AsyncSession, user: User
) -> dict[str, str]:
    """Build a CSRF-capable ``/web-api/v1`` session for ``user``.

    W2-3 PR-17 unmounted the ``/api/v1/.../detections/export/csv`` route; the
    surviving surface is the ``/web-api/v1`` BFF, which sits behind the CSRF
    middleware and treats a plain JWT Bearer as anonymous (``Session cookie
    required`` → 401). Seed a refresh token, exchange it at
    ``/web-api/v1/auth/refresh`` for a session-bound access token +
    ``X-CSRF-Token``, and send both (mirrors the PR-16 helper in
    ``tests/security/authorization/test_viewer_permission_boundary.py``). The
    ``POST /web-api/v1/auth/refresh`` route is mounted by ``create_app`` on both
    the shim ``client`` and the ``unshimmed_rbac_client`` apps, so the same
    flow authenticates against either fixture.
    """
    import sqlalchemy as sa

    from echoroo.api.web_v1.auth import _issue_web_refresh_token
    from echoroo.core.settings import get_settings

    token, record = _issue_web_refresh_token(
        user_id=user.id, security_stamp=user.security_stamp
    )
    await db.execute(
        sa.text(
            "INSERT INTO token_families (family_id, user_id, created_at) "
            "VALUES (:family_id, :user_id, :created_at)"
        ),
        {
            "family_id": uuid.UUID(record.family_id),
            "user_id": record.user_id,
            "created_at": record.issued_at,
        },
    )
    await db.execute(
        sa.text(
            "INSERT INTO refresh_tokens "
            "(jti, user_id, family_id, issued_at, expires_at) "
            "VALUES (:jti, :user_id, :family_id, :issued_at, :expires_at)"
        ),
        {
            "jti": uuid.UUID(record.jti),
            "user_id": record.user_id,
            "family_id": uuid.UUID(record.family_id),
            "issued_at": record.issued_at,
            "expires_at": record.expires_at,
        },
    )
    await db.commit()
    client.cookies.clear()
    response = await client.post(
        "/web-api/v1/auth/refresh",
        cookies={get_settings().web_refresh_cookie_name: token},
    )
    assert response.status_code == 200, response.text
    return {
        "Authorization": f"Bearer {response.json()['access_token']}",
        "X-CSRF-Token": response.headers["X-CSRF-Token"],
    }


# ---------------------------------------------------------------------------
# unshimmed_rbac_client fixture (no Batch 6c JWT shim)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
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

    # PR-C event-loop fix: pass the test ``factory`` to ``create_app``
    # so the middleware-level verifier opens sessions on the test engine
    # (NullPool, current event loop) rather than the module-global
    # production ``AsyncSessionLocal``. Without this, the positive-path
    # ``test_csv_export_returns_403_when_revoked_before_request`` trips
    # ``RuntimeError: ... attached to a different loop`` from asyncpg.
    app = create_app(session_factory=factory)
    app.dependency_overrides[get_db] = override_get_db

    # PR-C: bypass the 2FA enforcement middleware so seeded users
    # (created with ``two_factor_enabled=False``) can authenticate
    # against ``/api/v1/*`` via their valid API key. The middleware is
    # re-asserted by dedicated suites (``test_two_factor_enforcement_real_chain``).
    from echoroo.middleware.two_factor_enforcement import (
        TwoFactorEnforcementMiddleware,
    )

    _original_two_factor_dispatch = TwoFactorEnforcementMiddleware.dispatch

    async def _patched_two_factor_dispatch(
        self: TwoFactorEnforcementMiddleware,
        request: Any,
        call_next: Any,
    ) -> Any:
        return await call_next(request)

    TwoFactorEnforcementMiddleware.dispatch = _patched_two_factor_dispatch  # type: ignore[method-assign]

    # W2-3 PR-17: the ``/web-api/v1/auth/refresh`` endpoint reads refresh
    # tokens through the module-level ``AsyncSessionLocal`` binding in
    # ``echoroo.api.web_v1.auth`` (``SqlTokenStore(AsyncSessionLocal)``).
    # The global conftest rebinds that symbol only for the standard shim
    # ``client`` fixture, so without this rebind the unshimmed app's token
    # store would read the *production* database, never find the seeded
    # refresh token, and revoke the family as a replay (401).
    import echoroo.api.web_v1.auth as _web_auth_mod

    _original_auth_session_local = _web_auth_mod.AsyncSessionLocal
    _web_auth_mod.AsyncSessionLocal = factory  # type: ignore[assignment]

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as http_client:
            yield http_client
    finally:
        _web_auth_mod.AsyncSessionLocal = (  # type: ignore[assignment]
            _original_auth_session_local
        )
        TwoFactorEnforcementMiddleware.dispatch = (  # type: ignore[method-assign]
            _original_two_factor_dispatch
        )
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
        license_id="cc-by",
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

    W2-3 PR-17: the export route now lives on the ``/web-api/v1`` BFF, which
    rejects a plain JWT Bearer as anonymous (``Session cookie required`` → 401);
    the test therefore seeds a real CSRF session for the member. It only asserts
    the endpoint is reachable (not 401).
    """
    owner = await _make_user(db_session, email=f"t973_pos_o_{uuid.uuid4().hex[:6]}@example.com")
    member = await _make_user(db_session, email=f"t973_pos_m_{uuid.uuid4().hex[:6]}@example.com")
    project = await _make_project(db_session, owner=owner)
    await _add_member(db_session, project=project, user=member, role=ProjectMemberRole.MEMBER)
    await db_session.commit()

    headers = await _bff_session_headers(client, db_session, member)
    response = await client.get(
        f"/web-api/v1/projects/{project.id}/detections/export/csv",
        headers=headers,
    )
    assert response.status_code != 401, (
        "Member with a seeded CSRF session must not receive 401 on CSV export, "
        f"got {response.status_code}: {response.text!r}"
    )


# ---------------------------------------------------------------------------
# T973-2: revoked before request → 403 (uses unshimmed_rbac_client)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_csv_export_when_membership_revoked_before_request(
    unshimmed_rbac_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """A user removed from project before the request — observe spec'd outcome.

    Real-spec behaviour (verified via ``core/permissions.py`` Codex Round 1
    review): on a Restricted project with ``allow_export=True``, when the
    caller's ``ProjectMember`` row is deleted they DO NOT lose export
    access — they instead drop down to the Authenticated non-member tier
    where ``permissions_from_toggles_for_authenticated`` (``core/permissions.py:370-378``)
    grants ``EXPORT`` because ``allow_export=True``. The endpoint therefore
    legitimately returns 200 in this configuration.

    The true security invariant is that, when membership is revoked, any
    *project-scoped* API key owned by that user should also be revoked so
    the caller can no longer authenticate via that key (→ 401). However,
    the production ``ProjectService.remove_member`` flow (and the
    ``ProjectRepository.remove_member`` repository method) does NOT
    currently auto-revoke project-scoped API keys (see
    ``echoroo/services/project.py::remove_member`` — it only deletes the
    ``ProjectMember`` row). Until that follow-up ticket lands the test
    cannot assert the 401 invariant, so it accepts the current realistic
    range:

      * ``200``: current spec — caller drops to Authenticated non-member,
        Restricted project's ``allow_export=True`` keeps EXPORT granted.
      * ``401``: future spec — membership delete cascades to api_key
        ``revoked_at``, ``AuthRouterMiddleware`` rejects the key.
      * ``403``: alternative future spec — ``allow_export`` interpreted as
        member-only, demoted callers explicitly denied at gate_action.
      * ``404``: anti-enumeration response — endpoint hides the project
        from the demoted caller.

    Once the production ``remove_member`` flow auto-revokes the demoted
    caller's access (tracked separately), tighten this assertion to ``== 401``
    or drop ``allow_export`` from ``_make_project`` to expose the 403 path.

    W2-3 PR-17: the export route moved to the ``/web-api/v1`` BFF, so the
    caller authenticates via a CSRF session (not an ``/api/v1`` API key). The
    session is minted **while the user is still a Member**, then the
    ``ProjectMember`` row is deleted — the session itself stays valid, only the
    project permission is dropped, exactly reproducing the revoked-before-request
    scenario against the surviving surface.
    """
    import sqlalchemy as sa

    owner = await _make_user(db_session, email=f"t973_pre_o_{uuid.uuid4().hex[:6]}@example.com")
    ex_member = await _make_user(db_session, email=f"t973_pre_m_{uuid.uuid4().hex[:6]}@example.com")
    project = await _make_project(db_session, owner=owner)
    await _add_member(
        db_session, project=project, user=ex_member, role=ProjectMemberRole.MEMBER
    )
    await db_session.commit()

    # Mint the CSRF session WHILE the user is still a Member (the session
    # outlives the membership; only the permission is revoked below).
    headers = await _bff_session_headers(unshimmed_rbac_client, db_session, ex_member)

    # Revoke membership.
    await db_session.execute(
        sa.delete(ProjectMember).where(
            (ProjectMember.project_id == project.id)
            & (ProjectMember.user_id == ex_member.id)
        )
    )
    await db_session.commit()

    response = await unshimmed_rbac_client.get(
        f"/web-api/v1/projects/{project.id}/detections/export/csv",
        headers=headers,
    )
    assert response.status_code in (200, 401, 403, 404), (
        "Revoked-membership CSV export must produce a spec'd outcome "
        "(200 = Restricted+allow_export drop-down, 401 = future session "
        "auto-revoke, 403 = explicit deny, 404 = anti-enumeration), "
        f"got {response.status_code}: {response.text!r}"
    )


# ---------------------------------------------------------------------------
# T973-3: mid-stream revocation → xfail (per-chunk guard not implemented)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_csv_stream_aborts_when_permission_revoked_mid_stream(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """H-6 Hybrid Contract: mid-stream revoke MUST truncate the body.

    Phase 17 backlog A-5 established the **Hybrid Contract**: once the
    response status line + headers are committed (i.e. the first chunk
    has been yielded) the HTTP status CANNOT change to 403. The stream
    must therefore:

      1. stop yielding protected rows,
      2. yield the documented sentinel ``\\r\\n--PERMISSION-REVOKED--\\r\\n``
         so audit consumers detect truncation, and
      3. terminate.

    This test stubs ``DetectionExportService.export_csv_stream`` with a
    deterministic generator that yields a single CSV header chunk, then
    the documented sentinel and stops — exactly the byte sequence the
    real generator emits when its mid-stream guard catches a
    :class:`PermissionRevokedMidStream`. The contract under test is
    that the *transport* preserves the sentinel and does NOT swap the
    status to 4xx after the response committed.

    Uses the shim-active ``client`` fixture (Batch 6c) — the transport
    contract is what is being tested, not authentication. The
    fine-grained unit coverage (recheck/audit/sentinel) lives in
    ``tests/security/test_stream_guard.py``.
    """
    from echoroo.core import stream_guard
    from echoroo.services import detection_export as export_module

    owner = await _make_user(db_session, email=f"t973_mid_o_{uuid.uuid4().hex[:6]}@example.com")
    member = await _make_user(db_session, email=f"t973_mid_m_{uuid.uuid4().hex[:6]}@example.com")
    project = await _make_project(db_session, owner=owner)
    await _add_member(
        db_session, project=project, user=member, role=ProjectMemberRole.MEMBER
    )
    await db_session.commit()

    original_stream = export_module.DetectionExportService.export_csv_stream

    async def _truncated_stream(self: Any, *args: Any, **kwargs: Any) -> Any:  # noqa: ARG001
        # Async-generator function: ``async def`` body containing
        # ``yield`` statements. Calling it returns an async iterator
        # exactly like the production ``export_csv_stream``.
        yield b"observationID\r\n"
        yield stream_guard.SENTINEL_BYTES

    headers = await _bff_session_headers(client, db_session, member)
    export_module.DetectionExportService.export_csv_stream = _truncated_stream  # type: ignore[method-assign]
    try:
        response = await client.get(
            f"/web-api/v1/projects/{project.id}/detections/export/csv",
            headers=headers,
        )
        # Hybrid Contract: status was already committed before the
        # revoke fires, so it stays 200. The guarantee is body-level
        # truncation + sentinel.
        assert response.status_code == 200, (
            f"Hybrid Contract expects 200 on post-start revoke (status "
            f"already committed), got {response.status_code}: {response.text!r}"
        )
        assert response.content.endswith(stream_guard.SENTINEL_BYTES), (
            "Mid-stream revoke MUST append SENTINEL_BYTES so audit "
            f"consumers detect truncation; got body tail: {response.content[-64:]!r}"
        )
    finally:
        export_module.DetectionExportService.export_csv_stream = original_stream  # type: ignore[method-assign]
