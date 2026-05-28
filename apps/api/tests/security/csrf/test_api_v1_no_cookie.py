"""Security test: /api/v1/* rejects cookie-session auth (T972, FR-077, SC-2).

The programmatic surface ``/api/v1/*`` is designed for machine-to-machine
access authenticated via ``Bearer echoroo_<prefix>_<secret>`` API keys.
It MUST NOT accept the first-party session cookie (``echoroo_session``) as
authentication — that cookie is meaningful only on ``/web-api/v1/*``.

Acceptance criteria verified here:
  * Cookie-only request to /api/v1/projects/{id} → 401
  * No-credential request                        → 401
  * Bearer JWT (plain JWT access token)          → 401 (DbApiKeyVerifier rejects
      non-``echoroo_*`` Bearer credentials; the JWT shim is OFF here)
  * Bearer echoroo_* API key that does NOT exist → 401 (invalid key)

Note on Bearer JWT case:
  In the global test fixture (tests/conftest.py) the Batch 6c JWT shim
  patches ``AuthRouterMiddleware._authenticate_api_key`` to accept plain
  JWTs and synthesise a full-scope Principal. This shim exists to let
  legacy test suites exercise the RBAC surface without having to insert
  real ``api_keys`` rows. For T972 the shim MUST be disabled — the test
  subject is the transport layer itself, and the shim would mask the
  exact 401 we are testing for. A custom fixture builds the app without
  the shim.

Note on valid API key → 200:
  Verifying a *valid* ``echoroo_*`` key requires inserting a row into the
  ``api_keys`` table; that in turn requires a real PostgreSQL schema. This
  test suite uses the project-level test database (TEST_DATABASE_URL, same
  as ``tests/conftest.py``) rather than a fresh testcontainer so that it
  runs in the standard CI suite without extra infrastructure. The
  ``api_key_for_project_member`` fixture seeds the minimal rows needed and
  tears them down after the test.
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
from echoroo.models.enums import ProjectLicense, ProjectVisibility
from echoroo.models.project import Project
from echoroo.models.user import User


def _make_bearer_token(user_id: Any) -> str:
    """Create a plain JWT access token using the legacy dict form."""
    return _create_jwt_token({"sub": str(user_id)})

# ---------------------------------------------------------------------------
# Test DB URL (mirrors tests/conftest.py)
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://echoroo:echoroo@localhost:5432/echoroo_test",
)

# ---------------------------------------------------------------------------
# Custom app fixture — NO Batch 6c JWT shim, NO 2FA bypass
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def unshimmed_client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:  # noqa: ARG001
    """Build the real app without the Batch 6c JWT shim.

    The db_session fixture is accepted to trigger DB setup (cleanup,
    schema check) but we build our own session override so the app
    instance uses the same test database.

    The 2FA enforcement middleware IS present but we seed users with
    ``two_factor_enabled=False`` so authenticated endpoints will proceed
    without 2FA checks (the middleware only blocks endpoints when
    ``two_factor_enabled=True`` but no verified TOTP session is active).
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

    # Build app WITHOUT monkeypatching _authenticate_api_key — the
    # production DbApiKeyVerifier is the subject under test.
    #
    # PR-C event-loop fix: pass the test ``factory`` to ``create_app`` so
    # the middleware verifier opens sessions on the test engine (NullPool,
    # current event loop) rather than the module-global production
    # ``AsyncSessionLocal``. Without this, the positive-path test
    # (``test_api_v1_with_valid_api_key_returns_200``) trips
    # ``RuntimeError: ... attached to a different loop`` from asyncpg.
    app = create_app(session_factory=factory)
    app.dependency_overrides[get_db] = override_get_db

    # PR-C: bypass the 2FA enforcement middleware. The seeded users are
    # created with ``two_factor_enabled=False`` (default), but the
    # production :class:`TwoFactorEnforcementMiddleware` (Phase 4 / Phase
    # 15 T155b) blocks any authenticated ``/api/v1/*`` request from a user
    # who has not enrolled in 2FA with a 403 ``2FA enrollment required``
    # payload — even when the API key itself is valid. This fixture
    # exercises the transport / verifier layer only, so we replace the
    # middleware dispatch with a passthrough for the duration of the test.
    # Production behaviour and dedicated 2FA enforcement suites
    # (``test_two_factor_enforcement_real_chain.py``) are unaffected
    # because they build their own apps.
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

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as http_client:
            yield http_client
    finally:
        TwoFactorEnforcementMiddleware.dispatch = (  # type: ignore[method-assign]
            _original_two_factor_dispatch
        )
        app.dependency_overrides.clear()
        await engine.dispose()


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


async def _seed_user_and_project(db_session: AsyncSession) -> tuple[User, Project]:
    """Insert a minimal owner + public project and return both."""
    owner = User(
        email=f"t972_{uuid.uuid4().hex[:8]}@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T972 Owner",
        security_stamp="t" * 64,
    )
    db_session.add(owner)
    await db_session.flush()
    await db_session.refresh(owner)

    project = Project(
        name="T972 Test Project",
        description="api/v1 cookie-isolation test",
        visibility=ProjectVisibility.PUBLIC,
        license_id="cc-by",
        owner_id=owner.id,
    )
    db_session.add(project)
    await db_session.flush()
    await db_session.refresh(project)
    return owner, project


async def _seed_api_key(
    db_session: AsyncSession,
    *,
    user: User,
    project: Project,
) -> str:
    """Insert a minimal api_keys row and return the raw wire key.

    Wire format: ``echoroo_<8-char-hex>_<url-safe-secret>``

    The prefix random part uses ``secrets.token_hex(4)`` (8 lowercase hex
    characters) to guarantee the 8-char ``[A-Za-z0-9]`` regex constraint in
    :func:`echoroo.services.api_key_verification.parse_api_key`.
    ``token_urlsafe`` can produce ``-`` or ``_`` within the first 8 characters
    which would cause ``parse_api_key`` to return ``None`` and the test to fail
    with an unrelated 401 rather than a 200.
    """
    from datetime import UTC, datetime, timedelta

    from echoroo.models.api_key import ApiKey

    raw_secret = secrets.token_urlsafe(32)
    prefix_random = secrets.token_hex(4)  # exactly 8 lowercase hex chars [0-9a-f]
    prefix = f"echoroo_{prefix_random}"
    hashed = hashlib.sha256(raw_secret.encode()).hexdigest()

    key = ApiKey(
        id=uuid.uuid4(),
        user_id=user.id,
        project_id=project.id,
        prefix=prefix,
        hashed_secret=hashed,
        granted_permissions=["view_project_metadata"],
        expires_at=datetime.now(UTC) + timedelta(days=365),
    )
    db_session.add(key)
    await db_session.flush()
    await db_session.refresh(key)
    return f"{prefix}_{raw_secret}"


# ---------------------------------------------------------------------------
# T972-1: cookie-only request → 401
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_v1_cookie_only_returns_401(
    unshimmed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """GET /api/v1/projects/{id} with echoroo_session cookie → 401.

    The programmatic prefix MUST NOT interpret the first-party session
    cookie as a valid credential (FR-077, SC-2).
    """
    _, project = await _seed_user_and_project(db_session)
    await db_session.commit()

    response = await unshimmed_client.get(
        f"/api/v1/projects/{project.id}",
        cookies={"echoroo_session": "fake-session-family-id"},
    )
    assert response.status_code == 401, (
        f"/api/v1/projects with echoroo_session cookie must return 401, "
        f"got {response.status_code}: {response.text!r}"
    )


# ---------------------------------------------------------------------------
# T972-2: no credential → 401
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_v1_no_credential_returns_401(
    unshimmed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """GET /api/v1/projects/{id} with no auth → 401.

    Unauthenticated request to the programmatic surface must be rejected.
    """
    _, project = await _seed_user_and_project(db_session)
    await db_session.commit()

    response = await unshimmed_client.get(f"/api/v1/projects/{project.id}")
    assert response.status_code == 401, (
        f"/api/v1/projects with no credential must return 401, "
        f"got {response.status_code}: {response.text!r}"
    )


# ---------------------------------------------------------------------------
# T972-3: Bearer JWT (plain JWT, no echoroo_* prefix) → 401
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_v1_bearer_jwt_returns_401_without_shim(
    unshimmed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """GET /api/v1/projects/{id} with Bearer JWT → 401 (shim off).

    In production, DbApiKeyVerifier parses only ``echoroo_<prefix>_<secret>``
    credentials. A plain JWT access token does not match that pattern so
    verify() returns None → 401 auth_invalid. (The Batch 6c shim in
    tests/conftest.py makes JWTs pass — that shim is intentionally off
    here.)
    """
    owner, project = await _seed_user_and_project(db_session)
    await db_session.commit()

    access_token = _make_bearer_token(owner.id)
    response = await unshimmed_client.get(
        f"/api/v1/projects/{project.id}",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert response.status_code == 401, (
        f"/api/v1/projects with plain JWT Bearer must return 401 "
        f"(DbApiKeyVerifier only accepts echoroo_* keys), "
        f"got {response.status_code}: {response.text!r}"
    )


# ---------------------------------------------------------------------------
# T972-4: Bearer echoroo_* key that does NOT exist → 401
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_v1_nonexistent_api_key_returns_401(
    unshimmed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """GET /api/v1/projects/{id} with an echoroo_* key not in DB → 401.

    The verifier performs a DB lookup; a syntactically valid but unknown
    key must be rejected with 401 auth_invalid.
    """
    _, project = await _seed_user_and_project(db_session)
    await db_session.commit()

    # Construct a syntactically valid but non-existent key.
    fake_key = f"echoroo_abcdef12_{secrets.token_urlsafe(32)}"

    response = await unshimmed_client.get(
        f"/api/v1/projects/{project.id}",
        headers={"Authorization": f"Bearer {fake_key}"},
    )
    assert response.status_code == 401, (
        f"/api/v1/projects with unknown echoroo_* key must return 401, "
        f"got {response.status_code}: {response.text!r}"
    )


# ---------------------------------------------------------------------------
# T972-5: both cookie + JWT → 401 (cookie is ignored, JWT is rejected)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_v1_cookie_plus_jwt_returns_401(
    unshimmed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Cookie + Bearer JWT combination → 401 (shim off).

    Even when the request carries both a session cookie and a Bearer JWT
    the programmatic prefix must reject both — only an echoroo_* API key
    is accepted.
    """
    owner, project = await _seed_user_and_project(db_session)
    await db_session.commit()

    access_token = _make_bearer_token(owner.id)
    response = await unshimmed_client.get(
        f"/api/v1/projects/{project.id}",
        cookies={"echoroo_session": "fake-family-id"},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert response.status_code == 401, (
        f"/api/v1/projects with cookie+JWT must return 401, "
        f"got {response.status_code}: {response.text!r}"
    )


# ---------------------------------------------------------------------------
# T972-6: valid echoroo_* API key → 200 (positive test)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_v1_with_valid_api_key_returns_200(
    unshimmed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """GET /api/v1/projects/{id} with a valid echoroo_* API key → 200.

    This is the positive-path counterpart to T972-1 through T972-5.  It
    demonstrates that the production :class:`DbApiKeyVerifier` (no JWT shim)
    correctly accepts a well-formed ``echoroo_<prefix>_<secret>`` credential
    when the matching ``api_keys`` row exists in the database, is not revoked,
    and has not expired.

    The constant-time compare in :func:`hmac.compare_digest` operates on the
    SHA-256 hex digest of ``raw_secret``.  The fixture uses
    ``secrets.token_hex(4)`` for the 8-character prefix segment to guarantee
    the ``[A-Za-z0-9]{8}`` constraint in the wire-format regex; the secret
    half is a ``token_urlsafe(32)`` string whose ``-`` / ``_`` characters are
    permitted by the ``[A-Za-z0-9_\\-]+`` secret group.
    """
    owner, project = await _seed_user_and_project(db_session)
    raw_key = await _seed_api_key(db_session, user=owner, project=project)
    await db_session.commit()

    response = await unshimmed_client.get(
        f"/api/v1/projects/{project.id}",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 200, (
        f"GET /api/v1/projects with valid echoroo_* API key must return 200, "
        f"got {response.status_code}: {response.text!r}"
    )
