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
from sqlalchemy import func, select, text
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


# ---------------------------------------------------------------------------
# (e) Migration dedup SQL — duplicates collapse to one deterministic survivor
# ---------------------------------------------------------------------------


# Migration 0031's dedup DELETE, copied verbatim from
# ``alembic/versions/0031_custom_svm_dedupe_partial_unique_index.py`` upgrade().
# Run here against a throwaway scratch table (the live ``recording_annotations``
# already carries the unique index, so duplicates cannot be seeded there) to
# regression-guard the dedup logic itself.
_MIGRATION_0031_DEDUP_DELETE = """
DELETE FROM {table} a
USING (
    SELECT id
    FROM (
        SELECT
            id,
            ROW_NUMBER() OVER (
                PARTITION BY
                    recording_id,
                    tag_id,
                    start_time,
                    end_time,
                    detection_run_id
                ORDER BY created_at ASC, id::text ASC
            ) AS rn
        FROM {table}
        WHERE source = 'custom_svm'
          AND detection_run_id IS NOT NULL
          -- NULL-distinct semantics: the partial UNIQUE index treats NULL
          -- tag_id rows as DISTINCT, so a NULL-tag_id custom_svm group is
          -- index-legal and must NOT be collapsed. Mirrors the migration.
          AND tag_id IS NOT NULL
    ) ranked
    WHERE ranked.rn > 1
) dup
WHERE a.id = dup.id
"""


async def test_migration_0031_dedup_collapses_duplicates_to_one(
    db_session: AsyncSession,
) -> None:
    """The migration's dedup DELETE keeps exactly one row per conflict group.

    Builds an isolated scratch table (mirroring the columns the migration's
    DELETE references but WITHOUT the unique index, so duplicates can be
    seeded), inserts two identical custom_svm rows plus control rows that must
    survive (a different source, a NULL-run custom_svm row, a distinct
    custom_svm tuple, and Group Q: two custom_svm rows identical except BOTH
    having a NULL tag_id), runs the migration's exact DELETE, and asserts: the
    duplicate group collapsed to the earliest-``created_at`` survivor, every
    control row persisted (including BOTH Group-Q NULL-tag_id rows, which the
    index's NULL-distinct semantics keep), and a second DELETE is a no-op
    (idempotent).
    """
    table = "scratch_ra_0031_dedup"
    await db_session.execute(text(f"DROP TABLE IF EXISTS {table}"))
    await db_session.execute(
        text(
            f"""
            CREATE TABLE {table} (
                id uuid PRIMARY KEY,
                recording_id uuid NOT NULL,
                tag_id uuid NULL,
                detection_run_id uuid NULL,
                source text NOT NULL,
                start_time double precision NOT NULL,
                end_time double precision NOT NULL,
                created_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
    )

    rec, tag_id, run = uuid4(), uuid4(), uuid4()
    dup_early, dup_late = uuid4(), uuid4()

    async def _insert(
        row_id: UUID,
        source: str,
        run_id: UUID | None,
        *,
        start: float = 3.0,
        end: float = 6.0,
        created_offset: str = "now()",
        tag: UUID | None = tag_id,
    ) -> None:
        await db_session.execute(
            text(
                f"INSERT INTO {table}"
                " (id, recording_id, tag_id, detection_run_id, source,"
                "  start_time, end_time, created_at)"
                " VALUES (:id, :rec, :tag, :run, :source, :start, :end,"
                f" {created_offset})"
            ),
            {
                "id": row_id,
                "rec": rec,
                "tag": tag,
                "run": run_id,
                "source": source,
                "start": start,
                "end": end,
            },
        )

    # Two identical custom_svm rows; dup_early has the earlier created_at.
    await _insert(
        dup_early, "custom_svm", run, created_offset="now() - interval '1 hour'"
    )
    await _insert(dup_late, "custom_svm", run)
    # Control rows that must survive the scoped DELETE.
    await _insert(uuid4(), "sampling_round", run)  # different source
    await _insert(uuid4(), "custom_svm", None)  # NULL run -> outside predicate
    await _insert(uuid4(), "custom_svm", run, start=9.0, end=12.0)  # distinct tuple

    # Group Q: two custom_svm rows identical on (recording, start, end, run) but
    # BOTH tag_id NULL. PostgreSQL unique indexes treat NULLs as DISTINCT, so the
    # partial index would NOT reject these — both are index-legal. The dedup
    # DELETE must therefore leave BOTH intact (regression for the NULL-distinct
    # over-delete bug: the unguarded PARTITION BY grouped NULL tag_ids together).
    q1, q2 = uuid4(), uuid4()
    await _insert(q1, "custom_svm", run, start=15.0, end=18.0, tag=None)
    await _insert(q2, "custom_svm", run, start=15.0, end=18.0, tag=None)

    before = (
        await db_session.execute(text(f"SELECT count(*) FROM {table}"))
    ).scalar_one()
    assert before == 7

    first = await db_session.execute(
        text(_MIGRATION_0031_DEDUP_DELETE.format(table=table))
    )
    assert first.rowcount == 1, "exactly one duplicate must be deleted"

    survivors = (
        await db_session.execute(
            text(
                f"SELECT id FROM {table}"
                " WHERE source = 'custom_svm' AND detection_run_id = :run"
                " AND start_time = 3.0 AND end_time = 6.0"
            ),
            {"run": run},
        )
    ).scalars().all()
    assert survivors == [dup_early], "earliest created_at row must survive"

    # Group Q: BOTH NULL-tag_id custom_svm rows must survive (NULL-distinct).
    group_q = (
        await db_session.execute(
            text(
                f"SELECT id FROM {table}"
                " WHERE source = 'custom_svm' AND detection_run_id = :run"
                " AND tag_id IS NULL AND start_time = 15.0 AND end_time = 18.0"
            ),
            {"run": run},
        )
    ).scalars().all()
    assert sorted(group_q) == sorted([q1, q2]), (
        "both NULL-tag_id custom_svm rows must survive (index treats NULLs as"
        " DISTINCT, so the dedup must not collapse them)"
    )

    total = (
        await db_session.execute(text(f"SELECT count(*) FROM {table}"))
    ).scalar_one()
    assert total == 6, "only the single duplicate is removed; controls persist"

    # Idempotent: a second DELETE on the now-clean table removes nothing.
    second = await db_session.execute(
        text(_MIGRATION_0031_DEDUP_DELETE.format(table=table))
    )
    assert second.rowcount == 0

    await db_session.execute(text(f"DROP TABLE IF EXISTS {table}"))
    await db_session.rollback()


# ---------------------------------------------------------------------------
# (f) 409 discrimination — only the custom_svm unique violation maps to 409
# ---------------------------------------------------------------------------


async def test_non_unique_integrity_error_is_not_mapped_to_409(
    db_session: AsyncSession,
    recording: Recording,
    tag: Tag,
) -> None:
    """A non-unique IntegrityError (FK violation) is NOT mislabeled as 409.

    Drives a genuine asyncpg foreign-key violation (a custom_svm row whose
    ``detection_run_id`` references a non-existent detection run) through the
    repository create path and asserts the service's discriminator
    (``_is_custom_svm_dedup_violation``) returns ``False`` for it — so the
    generic ``create`` would re-raise rather than return "Duplicate detection".
    The matching positive case (a real duplicate IS 409) is covered by
    ``test_detection_service_create_duplicate_custom_svm_returns_409`` above.
    """
    bogus_run_id = uuid4()  # no matching detection_runs row -> FK violation
    repo = AnnotationRepository(db_session)
    annotation = RecordingAnnotation(
        recording_id=recording.id,
        tag_id=tag.id,
        detection_run_id=bogus_run_id,
        source=DetectionSource.CUSTOM_SVM,
        status=DetectionStatus.UNREVIEWED,
        confidence=0.91,
        start_time=3.0,
        end_time=6.0,
    )

    with pytest.raises(IntegrityError) as exc_info:
        await repo.create(annotation)
    await db_session.rollback()

    # The discriminator must reject this FK violation (sqlstate 23503, not
    # 23505) so it is never mapped to the 409 "Duplicate detection".
    assert (
        DetectionService._is_custom_svm_dedup_violation(exc_info.value) is False
    )


# ---------------------------------------------------------------------------
# (g) custom_svm + NULL detection_run_id via the create path -> 422
# ---------------------------------------------------------------------------


async def test_detection_service_create_custom_svm_without_run_returns_422(
    db_session: AsyncSession,
    recording: Recording,
    tag: Tag,
    project: Project,
) -> None:
    """A custom_svm create with no detection_run_id is rejected with 422.

    The partial dedupe index's predicate requires ``detection_run_id IS NOT
    NULL``, so a custom_svm row with a NULL run would silently bypass the
    dedupe guard. ``DetectionService.create`` enforces the invariant up front,
    returning HTTP 422 before any DB write.
    """
    service = DetectionService(
        annotation_repo=AnnotationRepository(db_session),
        confirmed_region_repo=ConfirmedRegionRepository(db_session),
    )
    create_req = DetectionCreate(
        recording_id=recording.id,
        tag_id=tag.id,
        detection_run_id=None,
        source=DetectionSource.CUSTOM_SVM,
        confidence=0.91,
        start_time=3.0,
        end_time=6.0,
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.create(project_id=project.id, request=create_req)
    assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert "custom_svm" in str(exc_info.value.detail)
