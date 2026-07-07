"""Reliability tests for upload validate/import Celery tasks.

Covers two guarantees introduced to survive worker child-recycle / OOM /
SIGKILL without silently losing an in-flight upload task:

* Celery is configured so the messages are redelivered (``acks_late`` +
  ``reject_on_worker_lost``) and Redis' ``visibility_timeout`` comfortably
  exceeds the task time limit.
* A *redelivered* import is idempotent: the CAS status guard fails, the
  session is marked FAILED, and NO duplicate Recording rows are created —
  and the task terminates without an (always-doomed) retry.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import patch
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from echoroo.models.dataset import Dataset
from echoroo.models.enums import DatasetStatus, UploadSessionStatus
from echoroo.models.recording import Recording
from echoroo.models.site import Site
from echoroo.models.upload import UploadSession
from echoroo.workers import upload_tasks
from echoroo.workers.celery_app import app as celery_app
from tests.conftest import TEST_DATABASE_URL

if TYPE_CHECKING:
    from echoroo.models.project import Project


def test_celery_broker_visibility_timeout_exceeds_time_limit() -> None:
    """visibility_timeout must be > task_time_limit so long tasks aren't redelivered."""
    transport_options = celery_app.conf.broker_transport_options
    assert transport_options is not None
    assert transport_options["visibility_timeout"] == 1800
    # A legitimately long task must never be redelivered while still running.
    assert transport_options["visibility_timeout"] > celery_app.conf.task_time_limit


def test_upload_tasks_are_acks_late_and_reject_on_worker_lost() -> None:
    """Both upload tasks must redeliver on worker loss instead of silently vanishing."""
    for task in (
        upload_tasks.validate_upload_session,
        upload_tasks.import_from_upload_session,
    ):
        assert task.acks_late is True
        assert task.reject_on_worker_lost is True


@pytest.fixture
async def reliability_site(db_session: AsyncSession, test_project: Project) -> Site:
    """Create a site for the reliability dataset."""
    site = Site(
        project_id=test_project.id,
        name="Reliability Site",
        h3_index_member="8928308280fffff",
    )
    db_session.add(site)
    await db_session.commit()
    await db_session.refresh(site)
    return site


@pytest.fixture
async def reliability_dataset(
    db_session: AsyncSession,
    test_project: Project,
    reliability_site: Site,
) -> Dataset:
    """Create a dataset to import recordings into."""
    dataset = Dataset(
        project_id=test_project.id,
        site_id=reliability_site.id,
        created_by_id=test_project.owner_id,
        name="Reliability Dataset",
        audio_dir="/data/audio/reliability",
        status=DatasetStatus.COMPLETED,
    )
    db_session.add(dataset)
    await db_session.commit()
    await db_session.refresh(dataset)
    return dataset


def _worker_engine_and_session_factory() -> tuple[
    AsyncEngine, async_sessionmaker[AsyncSession]
]:
    """Build a fresh worker-style engine/session_factory bound to the test DB.

    Mirrors the production ``get_worker_engine_and_session_factory`` contract
    (a brand-new engine per call) so the task's own commits are visible to the
    test session on a separate connection.
    """
    engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


async def test_redelivered_import_is_idempotent_and_terminal(
    db_session: AsyncSession,
    test_project: Project,
    reliability_dataset: Dataset,
) -> None:
    """A redelivered import (session already IMPORTING) fails safely, no dup rows.

    Simulates the acks_late redelivery race: a worker died after the
    VALIDATED->IMPORTING CAS, and the message is redelivered. The second run
    finds the session in IMPORTING, the ``expected_status=VALIDATED`` CAS fails,
    the session is marked FAILED, and no Recording rows are created — and the
    task terminates without scheduling a (doomed) retry.
    """
    # Capture ids as plain values up front: the worker task commits on a
    # separate connection, and reading these off the ORM objects afterwards
    # could trigger a lazy refresh outside the async greenlet.
    dataset_id = reliability_dataset.id
    owner_id = test_project.owner_id

    upload_session = UploadSession(
        dataset_id=dataset_id,
        created_by_id=owner_id,
        status=UploadSessionStatus.IMPORTING,
        total_files=1,
        total_bytes=1024,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db_session.add(upload_session)
    await db_session.commit()
    await db_session.refresh(upload_session)
    session_id = upload_session.id

    async def _count_recordings() -> int:
        result = await db_session.execute(
            select(func.count())
            .select_from(Recording)
            .where(Recording.dataset_id == dataset_id)
        )
        return int(result.scalar_one())

    recordings_before = await _count_recordings()

    with (
        patch.object(
            upload_tasks,
            "get_worker_engine_and_session_factory",
            _worker_engine_and_session_factory,
        ),
        patch.object(upload_tasks.import_from_upload_session, "retry") as mock_retry,
    ):
        # apply() runs the task locally (eager). Run it in a separate thread so
        # the task body's asyncio.run() has no running loop (this test is itself
        # async). The guard-mismatch path raises Ignore, so no retry is invoked.
        await asyncio.to_thread(
            upload_tasks.import_from_upload_session.apply, args=[str(session_id)]
        )

    # NOT retried — a redelivered doomed task must not loop.
    mock_retry.assert_not_called()

    # The session ends FAILED, and no duplicate recordings were created.
    # Column-only selects read committed values directly from the DB (no ORM
    # identity-map caching), so the worker's cross-connection commit is visible.
    status_result = await db_session.execute(
        select(UploadSession.status).where(UploadSession.id == UUID(str(session_id)))
    )
    assert status_result.scalar_one() == UploadSessionStatus.FAILED
    assert await _count_recordings() == recordings_before
