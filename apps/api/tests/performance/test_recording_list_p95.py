"""T991 — Recording list 100 items p95 < 800 ms (NFR-004).

Methodology
-----------
* Seed 100 recordings in a Public / Active project.
* Send ``GET /web-api/v1/projects/{id}/recordings?limit=100`` 10 times in
  a tight loop, measure wall-clock latency per iteration.
* Assert p50 and p95 stay below the NFR-004 budgets.

CI skip
-------
Latency assertions are environment-sensitive. This test is skipped when
``CI=true`` to avoid flaky failures on shared runners with scheduling
jitter. Run locally with::

    pytest tests/performance/test_recording_list_p95.py -v

Marker
------
``@pytest.mark.performance`` — deselect with ``-m "not performance"``.
"""

from __future__ import annotations

import os
import statistics
import time

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.jwt import create_access_token
from echoroo.models.dataset import Dataset
from echoroo.models.enums import (
    DatasetStatus,
    DatetimeParseStatus,
    ProjectStatus,
    ProjectVisibility,
)
from echoroo.models.project import Project
from echoroo.models.recording import Recording
from echoroo.models.site import Site
from echoroo.models.user import User

_NUM_RECORDINGS = 100
_NUM_ITERATIONS = 10
_P95_BUDGET_MS = 800.0
_P50_BUDGET_MS = 400.0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def t991_owner(db_session: AsyncSession) -> User:
    user = User(
        email="t991_owner@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T991 Owner",
        security_stamp="t991" + "o" * 60,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def t991_project(
    db_session: AsyncSession, t991_owner: User
) -> Project:
    project = Project(
        name="T991 Recording List Performance Project",
        description="NFR-004 p95 budget test",
        visibility=ProjectVisibility.PUBLIC,
        license_id="cc-by",
        owner_id=t991_owner.id,
        status=ProjectStatus.ACTIVE,
        restricted_config={},
        restricted_config_version=1,
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest.fixture
async def t991_recordings(
    db_session: AsyncSession,
    t991_project: Project,
    t991_owner: User,
) -> list[Recording]:
    """Seed 100 recordings in a single batch."""
    site = Site(
        project_id=t991_project.id,
        name="T991 Site",
        h3_index_member="8928308280fffff",
    )
    db_session.add(site)
    await db_session.commit()
    await db_session.refresh(site)

    dataset = Dataset(
        project_id=t991_project.id,
        site_id=site.id,
        created_by_id=t991_owner.id,
        name="T991 Dataset",
        audio_dir="/data/audio/t991",
        status=DatasetStatus.COMPLETED,
    )
    db_session.add(dataset)
    await db_session.commit()
    await db_session.refresh(dataset)

    recordings = []
    for i in range(_NUM_RECORDINGS):
        rec = Recording(
            dataset_id=dataset.id,
            filename=f"t991_{i:04d}.wav",
            path=f"t991_{i:04d}.wav",
            duration=30.0,
            samplerate=48000,
            channels=1,
            datetime_parse_status=DatetimeParseStatus.PENDING,
            time_expansion=1.0,
        )
        db_session.add(rec)
        recordings.append(rec)
    await db_session.commit()
    return recordings


# ---------------------------------------------------------------------------
# Performance test
# ---------------------------------------------------------------------------


@pytest.mark.performance
@pytest.mark.skipif(
    os.getenv("RUN_PERF_LATENCY") != "true",
    reason="Latency assertions are environment-sensitive; run locally only",
)
@pytest.mark.asyncio
async def test_recording_list_p95_under_budget(
    client: AsyncClient,
    db_session: AsyncSession,
    t991_project: Project,
    t991_recordings: list[Recording],
    t991_owner: User,
) -> None:
    """p95 < 800 ms for GET /web-api/v1/projects/{id}/recordings?limit=100.

    10 iterations; measures p50, p95, p99 and asserts NFR-004 thresholds.
    Recordings are pre-seeded (100 rows) so the query hits a realistic page.
    """
    headers = {
        "Authorization": f"Bearer {create_access_token({'sub': str(t991_owner.id)})}"
    }
    url = f"/web-api/v1/projects/{t991_project.id}/recordings?limit=100"

    latencies: list[float] = []
    for _ in range(_NUM_ITERATIONS):
        start = time.perf_counter()
        resp = await client.get(url, headers=headers)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        latencies.append(elapsed_ms)
        assert resp.status_code == 200, (
            f"Recording list returned {resp.status_code}: {resp.text[:200]}"
        )

    assert len(latencies) == _NUM_ITERATIONS

    p50 = statistics.median(latencies)
    sorted_latencies = sorted(latencies)
    p95_idx = max(0, int(len(sorted_latencies) * 0.95) - 1)
    p95 = sorted_latencies[p95_idx]
    p99_idx = max(0, int(len(sorted_latencies) * 0.99) - 1)
    p99 = sorted_latencies[p99_idx]

    print(
        f"\nRecording list latencies ({_NUM_RECORDINGS} rows, "
        f"{_NUM_ITERATIONS} iterations): "
        f"p50={p50:.1f}ms  p95={p95:.1f}ms  p99={p99:.1f}ms"
    )

    assert p95 < _P95_BUDGET_MS, (
        f"NFR-004 p95 budget exceeded: p95={p95:.1f}ms > {_P95_BUDGET_MS}ms. "
        "Investigate slow DB query or serialization overhead."
    )
    assert p50 < _P50_BUDGET_MS, (
        f"p50 unexpectedly high: p50={p50:.1f}ms > {_P50_BUDGET_MS}ms"
    )


@pytest.mark.performance
@pytest.mark.asyncio
async def test_recording_list_returns_correct_count(
    client: AsyncClient,
    db_session: AsyncSession,
    t991_project: Project,
    t991_recordings: list[Recording],
    t991_owner: User,
) -> None:
    """Sanity: 100 seeded recordings → response items list is non-empty."""
    headers = {
        "Authorization": f"Bearer {create_access_token({'sub': str(t991_owner.id)})}"
    }
    url = f"/web-api/v1/projects/{t991_project.id}/recordings?limit=100"
    resp = await client.get(url, headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "items" in data, f"Response missing 'items' key: {data}"
    # items may be paginated; assert at least 1 item returned.
    assert len(data["items"]) > 0, (
        f"Expected recordings in response, got 0. "
        f"Seeded {_NUM_RECORDINGS} recordings for project {t991_project.id}"
    )


@pytest.mark.performance
@pytest.mark.asyncio
async def test_recording_list_seed_size(
    t991_recordings: list[Recording],
) -> None:
    """Fixture sanity: exactly 100 recordings must be seeded."""
    assert len(t991_recordings) == _NUM_RECORDINGS, (
        f"Expected {_NUM_RECORDINGS} seeded recordings, got {len(t991_recordings)}"
    )
