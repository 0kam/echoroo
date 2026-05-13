"""Fixtures for spec/009 BFF integration tests.

Two fixtures are exported:

  * ``unshimmed_client`` — yields an ``httpx.AsyncClient`` bound to the
    FastAPI app built WITHOUT the integration-suite default
    Bearer-JWT shim that patches
    ``AuthRouterMiddleware._authenticate_api_key`` to synthesise a
    full-scope ``Principal`` from any plain JWT. With the shim active
    the legacy ``/api/v1/*`` mount silently accepts BFF-issued access
    tokens — convenient for legacy test ergonomics, but it masks the
    production rejection that
    :func:`_helpers.assert_legacy_v1_rejects_bff_token` (T009a, FR-006)
    is verifying. The 2FA enforcement middleware is similarly
    short-circuited so authentication unit-cases reach the verifier
    layer.

  * ``bff_jwt_factory`` — returns a callable that builds a BFF-style
    access token for a given user. Used by T009a to feed
    ``assert_legacy_v1_rejects_bff_token`` a token shaped exactly like
    one issued by the BFF login flow.

Both fixtures mirror the sibling implementations in
``apps/api/tests/contract/test_auth_separation.py`` and
``apps/api/tests/security/csrf/test_api_v1_no_cookie.py`` so the
behaviour is byte-equivalent. See those files for the original design
rationale (Phase 17 PR-C event-loop wiring, 2FA bypass scope, etc.).
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator, Callable
from typing import Any
from uuid import UUID

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from echoroo.core.jwt import create_access_token as _create_jwt_token

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://echoroo:echoroo@localhost:5432/echoroo_test",
)


# ---------------------------------------------------------------------------
# unshimmed_client (T009b)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def unshimmed_client(
    db_session: AsyncSession,  # noqa: ARG001 — schema-setup trigger
) -> AsyncGenerator[AsyncClient, None]:
    """Build the FastAPI app WITHOUT the integration-suite JWT shim.

    The integration-suite default ``client`` (provided by the root
    ``tests/conftest.py``) installs the Batch 6c JWT shim, which
    monkey-patches
    :meth:`echoroo.middleware.auth_router.AuthRouterMiddleware._authenticate_api_key`
    to accept plain JWT access tokens on ``/api/v1/*``. The shim is
    test-ergonomic — it lets legacy suites exercise RBAC without
    seeding ``api_keys`` rows — but it masks the production rejection
    FR-006 / T009a / :func:`_helpers.assert_legacy_v1_rejects_bff_token`
    are testing.

    The fixture also patches
    :class:`echoroo.middleware.two_factor_enforcement.TwoFactorEnforcementMiddleware`
    to a passthrough for the duration of the test (mirror of
    ``test_api_v1_no_cookie.py`` PR-C). Seeded users default to
    ``two_factor_enabled=False`` so the production middleware would
    short-circuit anyway, but the explicit patch removes any noise
    when a test seeds a 2FA-enrolled identity.
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

    # Pass the test ``factory`` into ``create_app`` so the middleware
    # verifier opens DB sessions on the test engine (matches the PR-C
    # event-loop fix in ``test_api_v1_no_cookie.py``).
    app = create_app(session_factory=factory)
    app.dependency_overrides[get_db] = override_get_db

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
# bff_jwt_factory (T009b)
# ---------------------------------------------------------------------------


BffJwtFactory = Callable[..., str]


@pytest_asyncio.fixture
async def bff_jwt_factory() -> BffJwtFactory:
    """Return a callable that mints BFF-style access tokens.

    Wire shape matches the access token the BFF login flow issues:
    a plain JWT signed by :func:`echoroo.core.jwt.create_access_token`
    with the user UUID under ``sub``. Callers may pass additional
    claims via keyword arguments (e.g. ``security_stamp=...``) to
    exercise stamp-mismatch / scope variations in their per-PR tests.

    Usage::

        token = bff_jwt_factory(user_id=user.id)
        await assert_legacy_v1_rejects_bff_token(
            unshimmed_client, "GET",
            f"/api/v1/projects/{project_id}/members",
            bff_token=token,
        )
    """

    def _factory(
        *,
        user_id: UUID | str,
        **extra_claims: Any,
    ) -> str:
        claims: dict[str, Any] = {"sub": str(user_id)}
        claims.update(extra_claims)
        return _create_jwt_token(claims)

    return _factory


__all__ = [
    "BffJwtFactory",
    "bff_jwt_factory",
    "unshimmed_client",
]
