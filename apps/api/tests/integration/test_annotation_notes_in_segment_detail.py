"""Real-DB regression test: per-annotation notes are exposed in segment detail.

Trial feedback (2026-08-21) reported that notes attached to a
``TimeRangeAnnotation`` were persisted but never rendered. The root cause was
two-fold; this suite guards the backend half:

``AnnotationSegmentService.get_detail()`` hard-coded ``note_count=0`` and the
``TimeRangeAnnotationResponse`` schema carried no ``notes`` field at all, so
the annotation-editor payload could not show annotation notes even though the
rows existed in ``time_range_annotation_notes``.

Coverage:
  (a) ``get_detail()`` returns every annotation note (content / issue flag /
      author) with ``note_count`` matching the list length.
  (b) Notes are ordered oldest-first and scoped to the owning annotation — a
      note on annotation A never leaks into annotation B.
  (c) No N+1: a segment with two note-carrying annotations issues exactly ONE
      SELECT against ``time_range_annotation_notes`` (nested ``selectinload``).
  (d) ``TimeRangeAnnotationService.update()`` also round-trips the notes, so
      species corrections do not blank the panel.

Like the other ``*_real_db`` suites this seeds rows through the live ORM and
drives the real service objects — no monkeypatching of the code under test.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.annotation_set import (
    AnnotationSegment,
    AnnotationSet,
    TimeRangeAnnotation,
)
from echoroo.models.dataset import Dataset
from echoroo.models.enums import (
    AnnotationSetStatus,
    DatasetStatus,
    DatasetVisibility,
    ProjectVisibility,
)
from echoroo.models.project import Project
from echoroo.models.recording import Recording
from echoroo.models.site import Site
from echoroo.models.taxon import Taxon
from echoroo.models.user import User
from echoroo.repositories.annotation_set import (
    AnnotationSegmentRepository,
    AnnotationSetRepository,
    TimeRangeAnnotationRepository,
)
from echoroo.schemas.annotation_set import (
    AnnotationNoteCreate,
    TimeRangeAnnotationUpdate,
)
from echoroo.services.annotation_segment import AnnotationSegmentService
from echoroo.services.annotation_set import AnnotationSetService
from echoroo.services.time_range_annotation import TimeRangeAnnotationService

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------


class _Fixture:
    """Container for the seeded object graph used by every test below."""

    def __init__(
        self,
        *,
        user: User,
        segment: AnnotationSegment,
        annotation_a: TimeRangeAnnotation,
        annotation_b: TimeRangeAnnotation,
    ) -> None:
        self.user = user
        self.segment = segment
        self.annotation_a = annotation_a
        self.annotation_b = annotation_b


def _segment_service(db: AsyncSession) -> AnnotationSegmentService:
    set_repo = AnnotationSetRepository(db)
    segment_repo = AnnotationSegmentRepository(db)
    annotation_repo = TimeRangeAnnotationRepository(db)
    return AnnotationSegmentService(
        segment_repo=segment_repo,
        annotation_repo=annotation_repo,
        set_service=AnnotationSetService(set_repo=set_repo, segment_repo=segment_repo),
    )


def _annotation_service(db: AsyncSession) -> TimeRangeAnnotationService:
    set_repo = AnnotationSetRepository(db)
    segment_repo = AnnotationSegmentRepository(db)
    annotation_repo = TimeRangeAnnotationRepository(db)
    return TimeRangeAnnotationService(
        annotation_repo=annotation_repo,
        segment_repo=segment_repo,
        set_service=AnnotationSetService(set_repo=set_repo, segment_repo=segment_repo),
    )


@pytest_asyncio.fixture
async def seeded(db_session: AsyncSession) -> _Fixture:
    """Seed user → project → dataset → recording → set → segment → 2 annotations."""
    user = User(
        email="annotation_notes_owner@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="annotation_notes_owner",
        security_stamp="s" * 64,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    project = Project(
        name="Annotation Notes Project",
        description="Regression guard for per-annotation notes",
        # PUBLIC keeps the empty default restricted_config valid under the
        # ck_projects_restricted_config_shape CHECK; visibility is irrelevant here.
        visibility=ProjectVisibility.PUBLIC,
        license_id="cc-by",
        owner_id=user.id,
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    site = Site(
        project_id=project.id,
        name="Annotation Notes Site",
        h3_index_member="8928308280fffff",
    )
    db_session.add(site)
    await db_session.commit()
    await db_session.refresh(site)

    dataset = Dataset(
        project_id=project.id,
        site_id=site.id,
        created_by_id=user.id,
        name="Annotation Notes Dataset",
        visibility=DatasetVisibility.PRIVATE,
        status=DatasetStatus.COMPLETED,
    )
    db_session.add(dataset)
    await db_session.commit()
    await db_session.refresh(dataset)

    recording = Recording(
        dataset_id=dataset.id,
        filename="annotation_notes.wav",
        path=f"recordings/{project.id}/{dataset.id}/annotation_notes.wav",
        duration=60.0,
        samplerate=44100,
        channels=1,
    )
    db_session.add(recording)
    await db_session.commit()
    await db_session.refresh(recording)

    taxon = Taxon(scientific_name="Turdus merula (annotation-notes test)")
    db_session.add(taxon)
    await db_session.commit()
    await db_session.refresh(taxon)

    annotation_set = AnnotationSet(
        project_id=project.id,
        dataset_id=dataset.id,
        created_by_id=user.id,
        name="Annotation Notes Set",
        segment_length_sec=30,
        num_segments=1,
        status=AnnotationSetStatus.READY,
    )
    db_session.add(annotation_set)
    await db_session.commit()
    await db_session.refresh(annotation_set)

    segment = AnnotationSegment(
        annotation_set_id=annotation_set.id,
        recording_id=recording.id,
        start_time_sec=0.0,
        end_time_sec=30.0,
    )
    db_session.add(segment)
    await db_session.commit()
    await db_session.refresh(segment)

    annotation_a = TimeRangeAnnotation(
        segment_id=segment.id,
        start_time_sec=1.0,
        end_time_sec=3.0,
        taxon_id=taxon.id,
        created_by_id=user.id,
    )
    annotation_b = TimeRangeAnnotation(
        segment_id=segment.id,
        start_time_sec=10.0,
        end_time_sec=12.0,
        taxon_id=taxon.id,
        created_by_id=user.id,
    )
    db_session.add_all([annotation_a, annotation_b])
    await db_session.commit()
    await db_session.refresh(annotation_a)
    await db_session.refresh(annotation_b)

    return _Fixture(
        user=user,
        segment=segment,
        annotation_a=annotation_a,
        annotation_b=annotation_b,
    )


# ---------------------------------------------------------------------------
# (a) + (b) payload content and scoping
# ---------------------------------------------------------------------------


async def test_get_detail_returns_per_annotation_notes(
    db_session: AsyncSession, seeded: _Fixture,
) -> None:
    """Annotation notes reach the detail payload with a matching note_count."""
    service = _annotation_service(db_session)

    await service.create_note(
        seeded.annotation_a.id,
        user_id=seeded.user.id,
        request=AnnotationNoteCreate(content="first note on A", is_issue=False),
    )
    await service.create_note(
        seeded.annotation_a.id,
        user_id=seeded.user.id,
        request=AnnotationNoteCreate(content="second note on A", is_issue=True),
    )
    await service.create_note(
        seeded.annotation_b.id,
        user_id=seeded.user.id,
        request=AnnotationNoteCreate(content="only note on B", is_issue=False),
    )
    await db_session.commit()
    # Drop identity-map state so get_detail() re-reads through the real query.
    db_session.expunge_all()

    detail = await _segment_service(db_session).get_detail(seeded.segment.id)

    by_id = {a.id: a for a in detail.annotations}
    a = by_id[seeded.annotation_a.id]
    b = by_id[seeded.annotation_b.id]

    # (a) notes present and note_count agrees with the list length.
    assert [n.content for n in a.notes] == ["first note on A", "second note on A"]
    assert a.note_count == 2
    assert [n.is_issue for n in a.notes] == [False, True]
    assert {n.created_by_id for n in a.notes} == {seeded.user.id}

    # (b) scoping: B only sees its own note.
    assert [n.content for n in b.notes] == ["only note on B"]
    assert b.note_count == 1


async def test_get_detail_orders_annotation_notes_oldest_first(
    db_session: AsyncSession, seeded: _Fixture,
) -> None:
    """Notes come back oldest-first even when inserted out of chronological order."""
    service = _annotation_service(db_session)

    newer = await service.create_note(
        seeded.annotation_a.id,
        user_id=seeded.user.id,
        request=AnnotationNoteCreate(content="newer", is_issue=False),
    )
    older = await service.create_note(
        seeded.annotation_a.id,
        user_id=seeded.user.id,
        request=AnnotationNoteCreate(content="older", is_issue=False),
    )
    # Backdate the second insert so wall-clock order contradicts insert order.
    from echoroo.models.note import Note  # noqa: PLC0415

    older_row = await db_session.get(Note, older.id)
    assert older_row is not None
    newer_row = await db_session.get(Note, newer.id)
    assert newer_row is not None
    base = datetime.now(UTC)
    older_row.created_at = base - timedelta(hours=2)
    newer_row.created_at = base
    await db_session.commit()
    db_session.expunge_all()

    detail = await _segment_service(db_session).get_detail(seeded.segment.id)
    annotation = next(
        a for a in detail.annotations if a.id == seeded.annotation_a.id
    )
    assert [n.content for n in annotation.notes] == ["older", "newer"]


# ---------------------------------------------------------------------------
# (c) N+1 guard
# ---------------------------------------------------------------------------


async def test_get_detail_loads_annotation_notes_without_n_plus_one(
    db_session: AsyncSession, seeded: _Fixture,
) -> None:
    """Two note-carrying annotations cost exactly one note SELECT, not two."""
    service = _annotation_service(db_session)
    for annotation in (seeded.annotation_a, seeded.annotation_b):
        await service.create_note(
            annotation.id,
            user_id=seeded.user.id,
            request=AnnotationNoteCreate(content="n", is_issue=False),
        )
    await db_session.commit()
    db_session.expunge_all()

    statements: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001, ANN202, ARG001
        statements.append(statement)

    sync_engine = db_session.get_bind().engine  # type: ignore[union-attr]
    event.listen(sync_engine, "before_cursor_execute", _record)
    try:
        await _segment_service(db_session).get_detail(seeded.segment.id)
    finally:
        event.remove(sync_engine, "before_cursor_execute", _record)

    note_selects = [
        s for s in statements if "time_range_annotation_notes" in s
    ]
    assert len(note_selects) == 1, (
        "expected a single batched SELECT for annotation notes, got "
        f"{len(note_selects)}:\n" + "\n".join(note_selects)
    )


# ---------------------------------------------------------------------------
# (d) update round-trip
# ---------------------------------------------------------------------------


async def test_update_annotation_keeps_notes_in_response(
    db_session: AsyncSession, seeded: _Fixture,
) -> None:
    """A species/time correction returns the annotation with its notes intact."""
    service = _annotation_service(db_session)
    await service.create_note(
        seeded.annotation_a.id,
        user_id=seeded.user.id,
        request=AnnotationNoteCreate(content="survives the edit", is_issue=True),
    )
    await db_session.commit()

    updated = await service.update(
        seeded.annotation_a.id,
        TimeRangeAnnotationUpdate(start_time_sec=1.5, end_time_sec=3.5),
    )

    assert updated.note_count == 1
    assert [n.content for n in updated.notes] == ["survives the edit"]
    assert updated.notes[0].is_issue is True
