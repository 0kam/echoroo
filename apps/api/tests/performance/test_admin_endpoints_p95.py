"""T992b — Admin endpoint p95 < 200 ms for Phase 15 admin surfaces.

Methodology
-----------
Phase 15 admin endpoints operate on small data sets (superuser list, approval
requests, break-glass status). The p95 budget is 200 ms — tighter than
NFR-004's 800 ms for bulk data endpoints because these tables are small and
results should be near-instant.

Endpoints under test
--------------------
* ``GET /web-api/v1/admin/superusers/break-glass/status``
* ``GET /web-api/v1/admin/superusers/approval-requests``
* ``GET /web-api/v1/admin/superusers``

Phase 16 Batch 6g-2 R2 (Codex Minor 2)
--------------------------------------
The previous version pointed an ``AsyncClient`` at the production
``create_app()`` and authenticated via a Bearer JWT. The
``AuthRouter`` middleware rejects Bearer tokens against ``/web-api/v1``
(it requires session cookie + access cookie) so every request returned
401 — yet the assertion (``status_code < 500``) accepted that, hiding
**any** success-path regression behind a fast 401.

We now mount the admin router on a *minimal* FastAPI app and stub
:func:`get_current_user_optional` directly via ``dependency_overrides``
— exactly the pattern used by ``test_admin_step_up_required.py`` (the
positive-control suite). The app has no auth middleware so the request
flows straight into the route handler, which executes
``_require_authenticated_superuser`` against the test DB. The fixture
promotes the test user to superuser by inserting a row into the
``superusers`` table (FR-112a single source of truth), so the gate
returns the 200 path and the latency assertion measures real work.

Tests now ``assert resp.status_code in (200, 204)``; a 401/403/5xx
fails the test loudly. The GET endpoints under test do NOT carry the
``Depends(require_step_up_token(...))`` Phase 16 Batch 6g-3 added —
that gate covers destructive POST/PATCH only.

CI skip
-------
``@pytest.mark.skipif(os.getenv("RUN_PERF_LATENCY") != "true", ...)`` for latency tests.
The ``performance`` marker is registered in ``pyproject.toml``; CI
deselects it via ``pytest -m "not performance"`` (see the ``backend-tests``
job in ``.github/workflows/ci.yml``) so these latency tests only run when
explicitly opted in.
"""

from __future__ import annotations

import os
import statistics
import time
from collections.abc import AsyncGenerator

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.api.web_v1.admin import router as admin_router
from echoroo.core.database import get_db
from echoroo.middleware.auth import get_current_user_optional
from echoroo.models.user import User

_NUM_ITERATIONS = 20
_P95_BUDGET_MS = 200.0

_ADMIN_ENDPOINTS = [
    "/web-api/v1/admin/superusers/break-glass/status",
    "/web-api/v1/admin/superusers/approval-requests",
    "/web-api/v1/admin/superusers",
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def t992b_user(db_session: AsyncSession) -> User:
    """Authenticated user promoted to superuser via the ``superusers`` table.

    Mirrors the ``superuser_user`` fixture in
    ``tests/security/authentication/test_admin_step_up_required.py``.
    The test calls bypass the production AuthRouter middleware via
    a custom FastAPI app + ``dependency_overrides``, but the route
    handler still executes ``_require_authenticated_superuser``
    against the real DB — so the row in ``superusers`` is what
    proves the user is a superuser.
    """
    user = User(
        email="t992b_user@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T992b User",
        security_stamp="t992b" + "u" * 59,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    # Insert the active ``superusers`` row so the admin gate returns 200.
    await db_session.execute(
        sa.text(
            "INSERT INTO superusers (user_id, added_at) VALUES (:uid, now())"
        ),
        {"uid": user.id},
    )
    await db_session.commit()
    return user


@pytest.fixture
async def admin_perf_client(
    db_session: AsyncSession,
    t992b_user: User,
) -> AsyncGenerator[AsyncClient, None]:
    """Minimal FastAPI app that mounts only the admin router.

    Production middleware (CSRF, AuthRouter, IP allow-list) is intentionally
    *not* mounted — the destination of the test is the admin handler's
    success-path latency, not the production transport stack. To keep the
    handler honest we still execute ``_require_authenticated_superuser``
    (which probes the real ``superusers`` table) by overriding
    :func:`get_current_user_optional` to return the seeded superuser
    instead of stubbing the helper itself.
    """
    app = FastAPI()
    app.include_router(admin_router, prefix="/web-api/v1")

    async def _override_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    async def _override_user() -> User:
        # Mirror the production middleware: stamp ``is_superuser`` and
        # ``_superuser_id`` directly off the live ``superusers`` row so
        # downstream gates short-circuit through the
        # SUPERUSER_PROJECT_SCOPE_ALLOWLIST branch in ``is_allowed``.
        probe = await db_session.execute(
            sa.text(
                "SELECT id FROM superusers "
                "WHERE user_id = :uid AND revoked_at IS NULL LIMIT 1"
            ),
            {"uid": t992b_user.id},
        )
        row = probe.scalar_one_or_none()
        t992b_user.is_superuser = row is not None  # type: ignore[attr-defined]
        t992b_user._superuser_id = row  # type: ignore[attr-defined]
        return t992b_user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user_optional] = _override_user

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


# ---------------------------------------------------------------------------
# Performance tests
# ---------------------------------------------------------------------------


@pytest.mark.performance
@pytest.mark.skipif(
    os.getenv("RUN_PERF_LATENCY") != "true",
    reason="Latency assertions are environment-sensitive; run locally only",
)
@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", _ADMIN_ENDPOINTS)
async def test_admin_endpoint_p95_under_budget(
    admin_perf_client: AsyncClient,
    endpoint: str,
) -> None:
    """p95 < 200 ms for admin endpoints (success path).

    Phase 16 Batch 6g-2 R2 (Codex Minor 2): the previous version
    accepted any non-5xx response, so a 401 from the production
    AuthRouter middleware (which rejects Bearer tokens against
    ``/web-api/v1``) trivially satisfied the budget. The fixture now
    mounts a minimal app + overrides ``get_current_user_optional`` to
    return the seeded superuser, so the assertion measures real work
    and any regression in ``_require_authenticated_superuser`` /
    ``_gate_platform_superuser_action`` is fail-loud.
    """
    latencies: list[float] = []
    for _ in range(_NUM_ITERATIONS):
        start = time.perf_counter()
        resp = await admin_perf_client.get(endpoint)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        latencies.append(elapsed_ms)
        assert resp.status_code in (200, 204), (
            f"Admin endpoint {endpoint} returned {resp.status_code} "
            f"(expected 200/204 — superuser fixture should have produced "
            f"the success path): {resp.text[:200]}"
        )

    p95 = sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)]
    p50 = statistics.median(latencies)

    print(f"\n{endpoint}: p50={p50:.1f}ms  p95={p95:.1f}ms")
    assert p95 < _P95_BUDGET_MS, (
        f"Admin endpoint p95 budget exceeded for {endpoint}: "
        f"p95={p95:.1f}ms > {_P95_BUDGET_MS}ms"
    )


@pytest.mark.performance
@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", _ADMIN_ENDPOINTS)
async def test_admin_endpoint_non_5xx(
    admin_perf_client: AsyncClient,
    endpoint: str,
) -> None:
    """Admin endpoints must return success for an authenticated superuser.

    Phase 16 Batch 6g-2 R2 (Codex Minor 2): tightened from ``< 500`` to
    ``in (200, 204)`` so a 401/403 regression fails the test rather
    than passing silently behind a fast auth-failure response.
    """
    resp = await admin_perf_client.get(endpoint)
    assert resp.status_code in (200, 204), (
        f"{endpoint} returned {resp.status_code} (expected 200/204): "
        f"{resp.text[:200]}"
    )
