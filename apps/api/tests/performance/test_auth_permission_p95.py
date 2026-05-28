"""T992 — Auth + permission gate p95 < 30 ms, query count p95 ≤ 4
(NFR-001 + NFR-001a / SC-015).

Methodology
-----------
* Cookie/JWT session with a valid project OWNER.
* ``GET /web-api/v1/projects/{id}`` fired 100 times.
* Measure wall-clock latency per iteration.
* Assert p95 < 30 ms (NFR-001 single-endpoint auth budget).

Query count
-----------
The query count budget (p95 ≤ 4) is documented as an xfail because the
SQLAlchemy event listener instrumentation is non-trivial in the async
ASGI test client context (requires hooking the underlying engine bound to
the request, not the test db_session). This is deferred to Phase 17.

Bulk preload (NFR-001a)
-----------------------
The project list endpoint ``GET /web-api/v1/projects/`` is used to assert
the bulk-preload path. Same p95 budget applied.

CI skip
-------
``@pytest.mark.skipif(os.getenv("RUN_PERF_LATENCY") != "true", ...)`` for latency
assertions. Query-count test is xfail for Phase 17.
"""

from __future__ import annotations

import os
import statistics
import time

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.jwt import create_access_token
from echoroo.models.enums import (
    ProjectLicense,
    ProjectStatus,
    ProjectVisibility,
)
from echoroo.models.project import Project
from echoroo.models.user import User

_NUM_ITERATIONS = 100
_P95_BUDGET_MS = 30.0
_P50_BUDGET_MS = 15.0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def t992_owner(db_session: AsyncSession) -> User:
    user = User(
        email="t992_owner@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T992 Owner",
        security_stamp="t992" + "o" * 60,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def t992_project(
    db_session: AsyncSession, t992_owner: User
) -> Project:
    project = Project(
        name="T992 Auth Perf Project",
        description="NFR-001 auth+permission p95 test",
        visibility=ProjectVisibility.PUBLIC,
        license_id="cc-by",
        owner_id=t992_owner.id,
        status=ProjectStatus.ACTIVE,
        restricted_config={},
        restricted_config_version=1,
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


# ---------------------------------------------------------------------------
# Performance tests
# ---------------------------------------------------------------------------


@pytest.mark.performance
@pytest.mark.skipif(
    os.getenv("RUN_PERF_LATENCY") != "true",
    reason="Latency assertions skipped unless RUN_PERF_LATENCY=true",
)
@pytest.mark.asyncio
async def test_auth_permission_single_project_p95(
    client: AsyncClient,
    db_session: AsyncSession,
    t992_project: Project,
    t992_owner: User,
) -> None:
    """p95 < 30 ms for auth + permission on GET /web-api/v1/projects/{id}."""
    headers = {
        "Authorization": f"Bearer {create_access_token({'sub': str(t992_owner.id)})}"
    }
    url = f"/web-api/v1/projects/{t992_project.id}"

    latencies: list[float] = []
    for _ in range(_NUM_ITERATIONS):
        start = time.perf_counter()
        resp = await client.get(url, headers=headers)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        latencies.append(elapsed_ms)
        assert resp.status_code == 200, (
            f"Project GET returned {resp.status_code}: {resp.text[:200]}"
        )

    p50 = statistics.median(latencies)
    sorted_l = sorted(latencies)
    p95 = sorted_l[max(0, int(len(sorted_l) * 0.95) - 1)]
    p99 = sorted_l[max(0, int(len(sorted_l) * 0.99) - 1)]

    print(
        f"\nAuth+permission latencies ({_NUM_ITERATIONS} iterations): "
        f"p50={p50:.1f}ms  p95={p95:.1f}ms  p99={p99:.1f}ms"
    )

    assert p95 < _P95_BUDGET_MS, (
        f"NFR-001 p95 budget exceeded: p95={p95:.1f}ms > {_P95_BUDGET_MS}ms"
    )
    assert p50 < _P50_BUDGET_MS, (
        f"p50 unexpectedly high: p50={p50:.1f}ms > {_P50_BUDGET_MS}ms"
    )


@pytest.mark.performance
@pytest.mark.skipif(
    os.getenv("RUN_PERF_LATENCY") != "true",
    reason="Latency assertions are environment-sensitive; run locally only",
)
@pytest.mark.asyncio
async def test_auth_permission_project_list_p95(
    client: AsyncClient,
    db_session: AsyncSession,
    t992_project: Project,
    t992_owner: User,
) -> None:
    """NFR-001a: p95 < 30 ms for project list (bulk preload path)."""
    headers = {
        "Authorization": f"Bearer {create_access_token({'sub': str(t992_owner.id)})}"
    }
    url = "/web-api/v1/projects/"

    latencies: list[float] = []
    for _ in range(_NUM_ITERATIONS):
        start = time.perf_counter()
        resp = await client.get(url, headers=headers)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        latencies.append(elapsed_ms)
        assert resp.status_code == 200, (
            f"Project list returned {resp.status_code}: {resp.text[:200]}"
        )

    p95 = sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)]

    print(f"\nProject list p95={p95:.1f}ms")
    assert p95 < _P95_BUDGET_MS, (
        f"NFR-001a project list p95 budget exceeded: {p95:.1f}ms > {_P95_BUDGET_MS}ms"
    )


@pytest.mark.performance
@pytest.mark.asyncio
async def test_auth_permission_returns_200_for_owner(
    client: AsyncClient,
    db_session: AsyncSession,
    t992_project: Project,
    t992_owner: User,
) -> None:
    """Sanity: project owner gets 200 from the project detail endpoint."""
    headers = {
        "Authorization": f"Bearer {create_access_token({'sub': str(t992_owner.id)})}"
    }
    resp = await client.get(f"/web-api/v1/projects/{t992_project.id}", headers=headers)
    assert resp.status_code == 200, resp.text


@pytest.mark.xfail(
    strict=True,
    reason=(
        "NFR-001 Phase 17: SQLAlchemy query-count measurement in the async "
        "ASGI test client context requires hooking the engine bound to the "
        "test request, not the test db_session. Implementation deferred to "
        "Phase 17 — once the instrumentation helper is wired, un-xfail this "
        "test and assert p95 ≤ 4 DB queries per auth+permission check."
    ),
)
@pytest.mark.performance
@pytest.mark.asyncio
async def test_auth_permission_query_count_p95(
    client: AsyncClient,
    db_session: AsyncSession,
    t992_project: Project,
    t992_owner: User,
) -> None:
    """NFR-001 / SC-015: DB query count p95 ≤ 4 per auth+permission check.

    Phase 17 will wire ``sqlalchemy.event.listen("after_cursor_execute")``
    against the engine used by the request-scoped session factory, not the
    test db_session. This is the acceptance criterion.
    """
    # This test is xfail(strict=True): reaching this line without the
    # instrumentation helper means we cannot assert query counts, so we
    # raise NotImplementedError to produce the expected failure.
    raise NotImplementedError(
        "Query count instrumentation requires Phase 17 engine hook"
    )
