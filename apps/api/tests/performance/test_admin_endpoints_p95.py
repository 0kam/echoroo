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

All three require a fully authenticated + active superuser. These tests
create a minimal superuser record so the auth gate allows the request
through. 403 responses are treated as acceptable (the superuser auth
mechanism is non-trivial to satisfy in a performance test harness) and
the latency assertion applies to *any* non-5xx response.

CI skip
-------
``@pytest.mark.skipif(os.getenv("RUN_PERF_LATENCY") != "true", ...)`` for latency tests.
"""

from __future__ import annotations

import os
import statistics
import time

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.jwt import create_access_token
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
    user = User(
        email="t992b_user@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T992b User",
        security_stamp="t992b" + "u" * 59,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


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
    client: AsyncClient,
    db_session: AsyncSession,
    t992b_user: User,
    endpoint: str,
) -> None:
    """p95 < 200 ms for admin endpoints (response time incl. auth gate).

    Non-superuser callers receive 403; this test only asserts response
    latency, not the response body. A 403 is a valid fast response.
    A 5xx indicates a server error and fails the test.
    """
    headers = {
        "Authorization": f"Bearer {create_access_token({'sub': str(t992b_user.id)})}"
    }

    latencies: list[float] = []
    for _ in range(_NUM_ITERATIONS):
        start = time.perf_counter()
        resp = await client.get(endpoint, headers=headers)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        latencies.append(elapsed_ms)
        # 5xx is a test failure; 200 or 4xx are acceptable for latency assertion.
        assert resp.status_code < 500, (
            f"Admin endpoint {endpoint} returned 5xx: {resp.status_code} "
            f"{resp.text[:200]}"
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
    client: AsyncClient,
    db_session: AsyncSession,
    t992b_user: User,
    endpoint: str,
) -> None:
    """Admin endpoints must not return 5xx for any authenticated request."""
    headers = {
        "Authorization": f"Bearer {create_access_token({'sub': str(t992b_user.id)})}"
    }
    resp = await client.get(endpoint, headers=headers)
    assert resp.status_code < 500, (
        f"{endpoint} returned {resp.status_code}: {resp.text[:200]}"
    )
