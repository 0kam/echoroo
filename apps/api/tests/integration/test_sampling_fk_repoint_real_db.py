"""Real-DB regression test for the sampling id-space fix (P4 — Slice 2).

This suite is the regression guard for the P4 annotation-consolidation fix on
the *sampling* id-space. Before P4, ``sampling_round_items.annotation_id``
pointed at the minimal ``annotations`` table, while the active-learning /
seed-sampling pipeline and the SVM training reader keyed everything on the
canonical ``recording_annotations`` id-space. Migration 0030 clears
``sampling_round_items``, repoints its ``annotation_id`` FK to
``recording_annotations(id) ON DELETE CASCADE``, and drops the minimal
``annotations`` table. The ORM (``SamplingRoundItem.annotation_id``) now
references ``recording_annotations`` directly.

CRITICAL: like the P2 vote suite (``test_detection_votes_real_db.py``) this
suite uses NO monkeypatch of the code under test. It seeds real rows through
the live ORM (whose FK is what migration 0030 repointed) and the real
``SamplingRoundRepository.add_items`` path, then drives the real training reader
``_fetch_training_embeddings`` SQL against the seeded rows. The bug would have
shipped precisely because nothing exercised the FK against
``recording_annotations``; this test catches it.

Coverage:
  (a) FK satisfaction — add_items with a RecordingAnnotation.id flushes and the
      row reads back.
  (b) FK enforcement — add_items with a random (unknown) id raises
      IntegrityError, proving the FK points at ``recording_annotations``.
  (c) Fixed reader — a ``confirmed`` RecordingAnnotation linked via a completed
      sampling round + a pgvector embedding is returned by the real
      ``_fetch_training_embeddings`` JOIN (status / tag_id column compatibility
      and enum comparison verified end-to-end).
"""

from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.custom_model import CustomModel, CustomModelStatus
from echoroo.models.dataset import Dataset
from echoroo.models.embedding import Embedding
from echoroo.models.enums import (
    DatasetStatus,
    DatasetVisibility,
    DetectionSource,
    DetectionStatus,
    ProjectVisibility,
    TagCategory,
)
from echoroo.models.project import Project
from echoroo.models.recording import Recording
from echoroo.models.recording_annotation import RecordingAnnotation
from echoroo.models.sampling_round import SamplingRound, SamplingRoundItem
from echoroo.models.site import Site
from echoroo.models.tag import Tag
from echoroo.models.user import User
from echoroo.repositories.sampling_round import SamplingRoundRepository
from echoroo.workers.classifier_tasks import _fetch_training_embeddings

pytestmark = pytest.mark.asyncio

_EMBEDDING_DIM = 1536
_EMBEDDING_MODEL_NAME = "perch"


# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------


async def _make_user(db: AsyncSession) -> User:
    user = User(
        email="p4sampling_owner@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="p4sampling_owner",
        security_stamp="s" * 64,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _make_project(db: AsyncSession, owner: User) -> Project:
    project = Project(
        name="P4 Sampling Project",
        description="P4 sampling FK repoint real-DB test",
        # PUBLIC keeps the empty default restricted_config valid under the
        # ck_projects_restricted_config_shape CHECK (full key-set only required
        # for RESTRICTED). Visibility is irrelevant to the sampling FK chain.
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
        filename="sampling_test.wav",
        path=f"recordings/{project.id}/{dataset.id}/sampling_test.wav",
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


async def _make_recording_annotation(
    db: AsyncSession,
    recording: Recording,
    *,
    tag: Tag | None = None,
    status: DetectionStatus = DetectionStatus.UNREVIEWED,
) -> RecordingAnnotation:
    annotation = RecordingAnnotation(
        recording_id=recording.id,
        tag_id=tag.id if tag is not None else None,
        source=DetectionSource.HUMAN,
        status=status,
        start_time=0.0,
        end_time=3.0,
        confidence=0.9,
    )
    db.add(annotation)
    await db.commit()
    await db.refresh(annotation)
    return annotation


async def _make_embedding(db: AsyncSession, recording: Recording) -> Embedding:
    embedding = Embedding(
        recording_id=recording.id,
        model_name=_EMBEDDING_MODEL_NAME,
        start_time=0.0,
        end_time=3.0,
        vector=[1.0] + [0.0] * (_EMBEDDING_DIM - 1),
    )
    db.add(embedding)
    await db.commit()
    await db.refresh(embedding)
    return embedding


async def _make_custom_model(
    db: AsyncSession, project: Project, tag: Tag
) -> CustomModel:
    model = CustomModel(
        project_id=project.id,
        name="P4 sampling model",
        target_tag_id=tag.id,
        status=CustomModelStatus.DRAFT,
        embedding_model_name=_EMBEDDING_MODEL_NAME,
    )
    db.add(model)
    await db.commit()
    await db.refresh(model)
    return model


async def _make_sampling_round(
    db: AsyncSession, model: CustomModel, *, status: str = "completed"
) -> SamplingRound:
    round_ = SamplingRound(
        custom_model_id=model.id,
        round_number=0,
        round_type="seed",
        sample_count=0,
        status=status,
    )
    db.add(round_)
    await db.commit()
    await db.refresh(round_)
    return round_


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
async def custom_model(
    db_session: AsyncSession, project: Project, tag: Tag
) -> CustomModel:
    return await _make_custom_model(db_session, project, tag)


# ---------------------------------------------------------------------------
# (a) FK satisfaction
# ---------------------------------------------------------------------------


async def test_add_items_with_recording_annotation_id_satisfies_fk(
    db_session: AsyncSession,
    recording: Recording,
    custom_model: CustomModel,
) -> None:
    """add_items keyed on a RecordingAnnotation.id flushes and reads back.

    Proves ``sampling_round_items.annotation_id`` now satisfies the FK against
    ``recording_annotations`` (the row the canonical pipeline owns).
    """
    annotation = await _make_recording_annotation(db_session, recording)
    embedding = await _make_embedding(db_session, recording)
    round_ = await _make_sampling_round(db_session, custom_model)

    repo = SamplingRoundRepository(db_session)
    created = await repo.add_items(
        round_.id,
        [
            {
                "embedding_id": embedding.id,
                "sample_type": "easy_positive",
                "annotation_id": annotation.id,
            }
        ],
    )
    await db_session.commit()

    assert len(created) == 1
    assert created[0].annotation_id == annotation.id

    row = (
        await db_session.execute(
            select(SamplingRoundItem).where(
                SamplingRoundItem.sampling_round_id == round_.id
            )
        )
    ).scalar_one_or_none()
    assert row is not None, "sampling_round_item must persist keyed on the rad id"
    assert row.annotation_id == annotation.id
    assert row.embedding_id == embedding.id


# ---------------------------------------------------------------------------
# (b) FK enforcement
# ---------------------------------------------------------------------------


async def test_add_items_with_unknown_annotation_id_raises_integrity_error(
    db_session: AsyncSession,
    recording: Recording,
    custom_model: CustomModel,
) -> None:
    """add_items with an unknown id violates the FK to recording_annotations.

    A random UUID has no matching ``recording_annotations`` row, so the flush
    must raise IntegrityError — proving the FK actually points at
    ``recording_annotations`` (not the dropped ``annotations`` table).
    """
    embedding = await _make_embedding(db_session, recording)
    round_ = await _make_sampling_round(db_session, custom_model)

    repo = SamplingRoundRepository(db_session)
    with pytest.raises(IntegrityError):
        await repo.add_items(
            round_.id,
            [
                {
                    "embedding_id": embedding.id,
                    "sample_type": "easy_positive",
                    "annotation_id": uuid4(),
                }
            ],
        )
    await db_session.rollback()


# ---------------------------------------------------------------------------
# (c) Fixed reader returns rows
# ---------------------------------------------------------------------------


async def test_fetch_training_embeddings_returns_confirmed_rad_rows(
    db_session: AsyncSession,
    recording: Recording,
    tag: Tag,
    custom_model: CustomModel,
) -> None:
    """The training reader JOINs sampling_round_items -> recording_annotations.

    Seeds a ``confirmed`` RecordingAnnotation (matching ``tag``) linked to a
    completed sampling round + a real pgvector embedding, then runs the actual
    ``_fetch_training_embeddings`` SQL. Asserts the seeded item is returned with
    label 1 — proving the status / tag_id columns exist on
    ``recording_annotations`` and the enum comparison
    (``status IN ('confirmed', 'rejected')`` / ``tag_id = :target_tag_id``)
    works end-to-end against the repointed id-space.
    """
    annotation = await _make_recording_annotation(
        db_session, recording, tag=tag, status=DetectionStatus.CONFIRMED
    )
    embedding = await _make_embedding(db_session, recording)
    round_ = await _make_sampling_round(db_session, custom_model)

    repo = SamplingRoundRepository(db_session)
    await repo.add_items(
        round_.id,
        [
            {
                "embedding_id": embedding.id,
                "sample_type": "easy_positive",
                "annotation_id": annotation.id,
            }
        ],
    )
    await db_session.commit()

    # target_tag_id path — confirmed + matching tag -> label 1 (positive).
    rows = await _fetch_training_embeddings(
        db_session,
        custom_model.id,
        _EMBEDDING_MODEL_NAME,
        target_tag_id=tag.id,
    )
    assert len(rows) == 1, "the confirmed recording_annotation must be returned"
    row = rows[0]
    # The reader stringifies the UUID columns in its result dicts.
    assert row["annotation_id"] == str(annotation.id)
    assert row["embedding_id"] == str(embedding.id)
    assert row["recording_id"] == str(recording.id)
    assert row["label"] == 1
    assert len(row["vector"]) == _EMBEDDING_DIM

    # untargeted path — confirmed (any tag) is still returned by the JOIN.
    untargeted = await _fetch_training_embeddings(
        db_session,
        custom_model.id,
        _EMBEDDING_MODEL_NAME,
        target_tag_id=None,
    )
    assert len(untargeted) == 1
    assert untargeted[0]["annotation_id"] == str(annotation.id)
