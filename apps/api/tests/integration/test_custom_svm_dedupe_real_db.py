"""Real-DB regression test for the custom-SVM dedupe guard (P-dedupe).

Regression guard for the DB-level idempotency fix on the *custom_svm*
inference write path. Before this fix the custom-SVM inference writers
(``echoroo.workers.ml.utils._bulk_insert_annotations`` and the two batch
inserts in ``echoroo.workers.classifier_tasks._run_custom_model_inference``)
used ``pg_insert(...).on_conflict_do_nothing()`` WITHOUT a conflict target, so
PostgreSQL arbitrated on the primary key only. Each inference run mints fresh
``uuid4`` ids, so the PK conflict never fired and re-running the same
``detection_run`` DUPLICATED every detection row.

Migration 0031 adds the PARTIAL UNIQUE index
``uq_recording_annotations_custom_svm`` ON
``(recording_id, tag_id, start_time, end_time, detection_run_id)``
``WHERE source = 'custom_svm' AND detection_run_id IS NOT NULL``. The custom-SVM
writers name this index as their ON CONFLICT arbiter
(``index_elements`` + matching ``index_where``).

CRITICAL: like the P4 sampling suite (``test_sampling_fk_repoint_real_db.py``)
this suite uses NO monkeypatch of the code under test. It drives the REAL
``_bulk_insert_annotations`` insert path (the one the inference pipeline calls)
against real seeded rows, and asserts directly against the live partial unique
index.

Coverage:
  (a) IDEMPOTENT RE-RUN — inserting the same custom_svm tuple twice via the real
      ``_bulk_insert_annotations`` arbiter is a no-op on the second pass (still
      exactly one row, no IntegrityError).
  (b) INDEX ENFORCEMENT (raw) — a bare ``pg_insert`` WITHOUT the arbiter of a
      duplicate custom_svm row raises IntegrityError, proving the partial unique
      index is actually present and enforcing.
  (c) OTHER SOURCES UNAFFECTED — two ``sampling_round`` rows with identical
      ``(recording_id, tag_id, start_time, end_time)`` and NULL
      ``detection_run_id`` both persist (the partial predicate excludes them).
  (d) API 409 — a duplicate custom_svm create through the generic
      ``DetectionService.create`` path raises HTTPException 409 ("Duplicate
      detection"), proving the service-layer IntegrityError -> 409 mapping.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.dataset import Dataset
from echoroo.models.detection_run import DetectionRun
from echoroo.models.enums import (
    DatasetStatus,
    DatasetVisibility,
    DetectionRunStatus,
    DetectionSource,
    DetectionStatus,
    ProjectVisibility,
    TagCategory,
)
from echoroo.models.project import Project
from echoroo.models.recording import Recording
from echoroo.models.recording_annotation import RecordingAnnotation
from echoroo.models.site import Site
from echoroo.models.tag import Tag
from echoroo.models.user import User
from echoroo.repositories.annotation import AnnotationRepository
from echoroo.repositories.confirmed_region import ConfirmedRegionRepository
from echoroo.schemas.detection import DetectionCreate
from echoroo.services.detection import DetectionService
from echoroo.workers.ml.utils import _bulk_insert_annotations

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------


async def _make_user(db: AsyncSession) -> User:
    user = User(
        email="custom_svm_dedupe_owner@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="custom_svm_dedupe_owner",
        security_stamp="s" * 64,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _make_project(db: AsyncSession, owner: User) -> Project:
    project = Project(
        name="Custom-SVM Dedupe Project",
        description="custom_svm dedupe real-DB test",
        visibility=ProjectVisibility.PUBLIC,
        license_id="cc-by",
        owner_id=owner.id,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


async def _make_recording(db: AsyncSession, project: Project, owner: User) -> Recording:
    site = Site(
        project_id=project.id,
        name=f"Site {project.name}",
        h3_index_member="8928308280fffff",
    )
    db.add(site)
    await db.commit()
    await db.refresh(site)

    dataset = Dataset(
        project_id=project.id,
        site_id=site.id,
        created_by_id=owner.id,
        name=f"Dataset {project.name}",
        visibility=DatasetVisibility.PRIVATE,
        status=DatasetStatus.COMPLETED,
    )
    db.add(dataset)
    await db.commit()
    await db.refresh(dataset)

    recording = Recording(
        dataset_id=dataset.id,
        filename="custom_svm_test.wav",
        path=f"recordings/{project.id}/{dataset.id}/custom_svm_test.wav",
        duration=60.0,
        samplerate=44100,
        channels=1,
    )
    db.add(recording)
    await db.commit()
    await db.refresh(recording)
    return recording


async def _make_tag(db: AsyncSession, project: Project) -> Tag:
    tag = Tag(
        project_id=project.id,
        name="Test Species",
        category=TagCategory.SPECIES,
    )
    db.add(tag)
    await db.commit()
    await db.refresh(tag)
    return tag


async def _make_detection_run(db: AsyncSession, project: Project) -> DetectionRun:
    run = DetectionRun(
        project_id=project.id,
        model_name="custom_svm_dedupe_model",
        model_version="1",
        status=DetectionRunStatus.RUNNING,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run


def _custom_svm_dict(
    recording: Recording,
    tag: Tag,
    run: DetectionRun,
    *,
    start_time: float = 3.0,
    end_time: float = 6.0,
) -> dict[str, object]:
    """A custom_svm annotation dict shaped exactly like the inference writer's."""
    return {
        "id": uuid4(),
        "recording_id": recording.id,
        "tag_id": tag.id,
        "detection_run_id": run.id,
        "source": DetectionSource.CUSTOM_SVM,
        "status": DetectionStatus.UNREVIEWED,
        "confidence": 0.91,
        "start_time": start_time,
        "end_time": end_time,
    }


async def _count_custom_svm(db: AsyncSession, run_id: UUID) -> int:
    # Takes a plain UUID (not the ORM instance) so callers can count AFTER a
    # rollback has expired the fixture objects without triggering a synchronous
    # lazy reload (``MissingGreenlet``).
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(RecordingAnnotation)
                .where(
                    RecordingAnnotation.detection_run_id == run_id,
                    RecordingAnnotation.source == DetectionSource.CUSTOM_SVM,
                )
            )
        ).scalar_one()
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def owner(db_session: AsyncSession) -> User:
    return await _make_user(db_session)


@pytest_asyncio.fixture
async def project(db_session: AsyncSession, owner: User) -> Project:
    return await _make_project(db_session, owner)


@pytest_asyncio.fixture
async def recording(
    db_session: AsyncSession, project: Project, owner: User
) -> Recording:
    return await _make_recording(db_session, project, owner)


@pytest_asyncio.fixture
async def tag(db_session: AsyncSession, project: Project) -> Tag:
    return await _make_tag(db_session, project)


@pytest_asyncio.fixture
async def detection_run(db_session: AsyncSession, project: Project) -> DetectionRun:
    return await _make_detection_run(db_session, project)


# ---------------------------------------------------------------------------
# (a) Idempotent re-run via the real inference insert path
# ---------------------------------------------------------------------------


async def test_bulk_insert_same_custom_svm_tuple_twice_is_idempotent(
    db_session: AsyncSession,
    recording: Recording,
    tag: Tag,
    detection_run: DetectionRun,
) -> None:
    """Re-inserting the same custom_svm tuple via the real arbiter is a no-op.

    Drives ``_bulk_insert_annotations`` (the exact code the inference pipeline
    calls) twice with the SAME
    ``(recording_id, tag_id, start_time, end_time, detection_run_id)`` tuple.
    The partial unique index + ON CONFLICT arbiter must skip the second insert:
    exactly one row, and NO IntegrityError.
    """
    run_id = detection_run.id

    first = await _bulk_insert_annotations(
        db_session, [_custom_svm_dict(recording, tag, detection_run)]
    )
    await db_session.commit()
    assert first == 1

    # Second pass: distinct uuid4 id, identical conflict tuple -> ON CONFLICT
    # DO NOTHING via the partial-index arbiter.
    second = await _bulk_insert_annotations(
        db_session, [_custom_svm_dict(recording, tag, detection_run)]
    )
    await db_session.commit()
    assert second == 0, "the duplicate custom_svm row must be skipped (no-op)"

    assert await _count_custom_svm(db_session, run_id) == 1


# ---------------------------------------------------------------------------
# (b) Index enforcement — raw duplicate WITHOUT the arbiter raises
# ---------------------------------------------------------------------------


async def test_raw_duplicate_custom_svm_without_arbiter_raises_integrity_error(
    db_session: AsyncSession,
    recording: Recording,
    tag: Tag,
    detection_run: DetectionRun,
) -> None:
    """A bare insert of a duplicate custom_svm row violates the unique index.

    Proves migration 0031's partial unique index is actually present and
    enforcing: with NO ON CONFLICT clause, a second row sharing the conflict
    tuple must raise IntegrityError.
    """
    await _bulk_insert_annotations(
        db_session, [_custom_svm_dict(recording, tag, detection_run)]
    )
    await db_session.commit()

    with pytest.raises(IntegrityError):
        await db_session.execute(
            pg_insert(RecordingAnnotation).values(
                [_custom_svm_dict(recording, tag, detection_run)]
            )
        )
        await db_session.flush()
    await db_session.rollback()


# ---------------------------------------------------------------------------
# (c) Other sources unaffected — sampling_round bare insert is not blocked
# ---------------------------------------------------------------------------


async def test_two_sampling_round_rows_with_identical_tuple_both_persist(
    db_session: AsyncSession,
    recording: Recording,
    tag: Tag,
) -> None:
    """Two sampling_round rows with the same tuple + NULL run both persist.

    The partial index predicate (``source = 'custom_svm' AND detection_run_id
    IS NOT NULL``) excludes sampling_round rows, so the seed-sampling / AL bare
    ``db.add`` path is NOT blocked by the dedupe guard.
    """
    for _ in range(2):
        db_session.add(
            RecordingAnnotation(
                recording_id=recording.id,
                tag_id=tag.id,
                detection_run_id=None,
                source=DetectionSource.SAMPLING_ROUND,
                status=DetectionStatus.UNREVIEWED,
                start_time=3.0,
                end_time=6.0,
            )
        )
    await db_session.commit()

    count = int(
        (
            await db_session.execute(
                select(func.count())
                .select_from(RecordingAnnotation)
                .where(
                    RecordingAnnotation.recording_id == recording.id,
                    RecordingAnnotation.source == DetectionSource.SAMPLING_ROUND,
                )
            )
        ).scalar_one()
    )
    assert count == 2, "both sampling_round rows must persist (predicate excludes them)"


# ---------------------------------------------------------------------------
# (d) API path — duplicate custom_svm create returns 409
# ---------------------------------------------------------------------------


async def test_detection_service_create_duplicate_custom_svm_returns_409(
    db_session: AsyncSession,
    recording: Recording,
    tag: Tag,
    detection_run: DetectionRun,
    project: Project,
) -> None:
    """A duplicate custom_svm create via DetectionService maps to HTTP 409.

    ``DetectionCreate.source`` accepts ``CUSTOM_SVM``, so the generic create
    path can produce a custom_svm row. With the partial unique index live, an
    exact-duplicate create raises IntegrityError on flush; the service maps it
    to a clean 409 instead of a 500.
    """
    service = DetectionService(
        annotation_repo=AnnotationRepository(db_session),
        confirmed_region_repo=ConfirmedRegionRepository(db_session),
    )
    run_id = detection_run.id
    project_id = project.id
    create_req = DetectionCreate(
        recording_id=recording.id,
        tag_id=tag.id,
        detection_run_id=run_id,
        source=DetectionSource.CUSTOM_SVM,
        confidence=0.91,
        start_time=3.0,
        end_time=6.0,
    )

    first = await service.create(project_id=project_id, request=create_req)
    await db_session.commit()
    assert first.source == DetectionSource.CUSTOM_SVM

    # Exact-duplicate custom_svm create -> 409 (not 500). The service rolls the
    # session back on IntegrityError, which expires the fixture ORM objects;
    # ids were captured above so the post-rollback count below does not trigger
    # a synchronous lazy reload.
    with pytest.raises(HTTPException) as exc_info:
        await service.create(project_id=project_id, request=create_req)
    assert exc_info.value.status_code == status.HTTP_409_CONFLICT
    assert exc_info.value.detail == "Duplicate detection"

    # No phantom row was committed by the failed create.
    assert await _count_custom_svm(db_session, run_id) == 1
