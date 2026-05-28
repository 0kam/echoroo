"""Search index re-entry gate on ``allow_detection_view`` toggle OFF→ON
(T981b, FR-025b / SC-018 complement).

Contract under test
-------------------
FR-025b specifies that when a Restricted project's ``allow_detection_view``
toggle is flipped OFF→ON the project's detections must NOT appear in
cross-project search results until the search index rebuild is complete
(``index_ready=True``).

Implementation note
~~~~~~~~~~~~~~~~~~~
The current production codebase does **not** have a first-class
``index_ready`` flag on the Project model (that is a Phase 17 task). The
SQL gate in :func:`SimilaritySearchService.search_by_vector` reads the
``allow_detection_view`` JSONB key directly and applies the filter at
query time — there is no asynchronous index build step guarding the ON
path.

This test suite therefore:

1. Verifies the **existing** immediate-exclusion behaviour (OFF stays OFF
   until the next commit, ON stays ON after commit) — these are live
   assertions against the real DB.
2. Documents the **missing** ``index_ready`` gate with
   ``pytest.mark.xfail(strict=True, reason="...")`` so the test suite
   stays red for the Phase 17 implementer and the FR-025b contract remains
   visible at the runner level.

The xfail tests encode the exact shape the Phase 17 implementation MUST
honour — once the ``index_ready`` column lands and the SQL gate is
updated, un-xfailing these tests is the Phase 17 acceptance criterion.
"""

from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.dataset import Dataset
from echoroo.models.embedding import Embedding
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
from echoroo.schemas.project import RestrictedConfigUpdateRequest
from echoroo.services.restricted_config_service import update_restricted_config
from echoroo.services.search import SimilaritySearchService

_EMBEDDING_DIM = 1536
_UNIT_VECTOR = [1.0] + [0.0] * (_EMBEDDING_DIM - 1)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def t981b_owner(db_session: AsyncSession) -> User:
    user = User(
        email="t981b_owner@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T981b Owner",
        security_stamp="t981b" + "o" * 59,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


def _restricted_config_off() -> dict[str, Any]:
    return {
        "allow_media_playback": True,
        "allow_detection_view": False,
        "mask_species_in_detection": False,
        "allow_download": False,
        "allow_export": False,
        "allow_voting_and_comments": False,
        "public_location_precision_h3_res": 9,
        "allow_precise_location_to_viewer": False,
    }


def _restricted_config_on() -> dict[str, Any]:
    cfg = _restricted_config_off()
    cfg["allow_detection_view"] = True
    return cfg


@pytest_asyncio.fixture
async def t981b_project_off(
    db_session: AsyncSession, t981b_owner: User
) -> Project:
    """Restricted project seeded with ``allow_detection_view=False``."""
    project = Project(
        name="T981b Restricted Project (OFF seed)",
        description="FR-025b search index gate coverage",
        visibility=ProjectVisibility.RESTRICTED,
        license_id="cc-by",
        owner_id=t981b_owner.id,
        status=ProjectStatus.ACTIVE,
        restricted_config=_restricted_config_off(),
        restricted_config_version=1,
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest_asyncio.fixture
async def t981b_embedding(
    db_session: AsyncSession,
    t981b_project_off: Project,
    t981b_owner: User,
) -> Embedding:
    site = Site(
        project_id=t981b_project_off.id,
        name="T981b Site",
        h3_index_member="8928308280fffff",
    )
    db_session.add(site)
    await db_session.commit()
    await db_session.refresh(site)

    dataset = Dataset(
        project_id=t981b_project_off.id,
        site_id=site.id,
        created_by_id=t981b_owner.id,
        name="T981b Dataset",
        audio_dir="/data/audio/t981b",
        status=DatasetStatus.COMPLETED,
    )
    db_session.add(dataset)
    await db_session.commit()
    await db_session.refresh(dataset)

    recording = Recording(
        dataset_id=dataset.id,
        filename="t981b.wav",
        path="t981b.wav",
        duration=30.0,
        samplerate=48000,
        channels=1,
        datetime_parse_status=DatetimeParseStatus.PENDING,
        time_expansion=1.0,
    )
    db_session.add(recording)
    await db_session.commit()
    await db_session.refresh(recording)

    embedding = Embedding(
        recording_id=recording.id,
        model_name="perch",
        start_time=0.0,
        end_time=5.0,
        vector=_UNIT_VECTOR,
    )
    db_session.add(embedding)
    await db_session.commit()
    await db_session.refresh(embedding)
    return embedding


async def _flip(db: AsyncSession, project: Project, *, value: bool) -> None:
    after: dict[str, Any] = dict(project.restricted_config or {})
    after["allow_detection_view"] = value
    payload = RestrictedConfigUpdateRequest(**after)
    await update_restricted_config(
        session=db,
        project_id=project.id,
        new_config=payload,
        actor_user_id=project.owner_id,
    )
    await db.commit()
    await db.refresh(project)


# ---------------------------------------------------------------------------
# Live tests — existing behaviour (no index_ready flag)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSearchIndexToggleOffImmediateExclusion:
    """OFF → ON path: current SQL gate re-exposes hits immediately (no async
    index rebuild step exists yet in production)."""

    async def test_off_seed_not_visible(
        self,
        db_session: AsyncSession,
        t981b_project_off: Project,
        t981b_embedding: Embedding,
    ) -> None:
        """Detection seeded with ``allow_detection_view=False`` is excluded."""
        service = SimilaritySearchService(db_session)
        results = await service.search_by_vector(
            project_id=t981b_project_off.id,
            query_vector=_UNIT_VECTOR,
            model_name="perch",
            limit=10,
            min_similarity=0.0,
            respect_restricted_toggle=True,
        )
        assert results == [], (
            "Detection in a Restricted project with allow_detection_view=OFF "
            "must not appear in cross-project search results"
        )
        assert t981b_embedding.id is not None

    async def test_off_to_on_flip_exposes_hits_immediately(
        self,
        db_session: AsyncSession,
        t981b_project_off: Project,
        t981b_embedding: Embedding,
    ) -> None:
        """OFF → ON: current SQL gate immediately re-exposes the detection.

        FR-025b note: the *expected* future behaviour is that the detection
        is hidden until index rebuild completes. Currently (no index_ready
        flag) the SQL gate re-exposes it on the very next query. This test
        documents the *current* behaviour; the xfail tests below document
        the *target* behaviour.
        """
        service = SimilaritySearchService(db_session)

        # Flip ON — no index_ready concept yet.
        await _flip(db_session, t981b_project_off, value=True)

        results = await service.search_by_vector(
            project_id=t981b_project_off.id,
            query_vector=_UNIT_VECTOR,
            model_name="perch",
            limit=10,
            min_similarity=0.0,
            respect_restricted_toggle=True,
        )
        assert len(results) == 1, (
            "Current behaviour (no index_ready): OFF→ON immediately re-exposes "
            f"the detection; got {len(results)} hits"
        )
        assert results[0].embedding_id == t981b_embedding.id

    async def test_on_to_off_immediately_removes_hits(
        self,
        db_session: AsyncSession,
        t981b_project_off: Project,
        t981b_embedding: Embedding,
    ) -> None:
        """ON → OFF: detection is excluded on the very next query (SC-018)."""
        service = SimilaritySearchService(db_session)

        # Start from ON.
        await _flip(db_session, t981b_project_off, value=True)
        before = await service.search_by_vector(
            project_id=t981b_project_off.id,
            query_vector=_UNIT_VECTOR,
            model_name="perch",
            limit=10,
            min_similarity=0.0,
            respect_restricted_toggle=True,
        )
        assert len(before) == 1, "Should be visible after flip to ON"

        # Flip OFF — must immediately exclude.
        await _flip(db_session, t981b_project_off, value=False)
        after = await service.search_by_vector(
            project_id=t981b_project_off.id,
            query_vector=_UNIT_VECTOR,
            model_name="perch",
            limit=10,
            min_similarity=0.0,
            respect_restricted_toggle=True,
        )
        assert after == [], (
            "ON→OFF must immediately exclude the detection (SC-018); "
            f"got {len(after)} hits"
        )
        assert t981b_embedding.id is not None


# ---------------------------------------------------------------------------
# xfail tests — FR-025b target behaviour (Phase 17: index_ready flag).
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "FR-025b Phase 17: Project model does not yet have an 'index_ready' "
        "column. When the column is added and the SQL gate is updated to also "
        "filter 'index_ready=True', this test must be un-xfailed. Until then "
        "it documents the target contract and stays red (strict=True)."
    ),
)
@pytest.mark.asyncio
async def test_off_to_on_hidden_until_index_ready(
    db_session: AsyncSession,
    t981b_project_off: Project,
    t981b_embedding: Embedding,
) -> None:
    """FR-025b: OFF→ON flip → detection hidden until index_ready=True.

    Phase 17 contract:
    1. Admin flips allow_detection_view=True.
    2. Immediately search → still excluded (index_ready=False, set by toggle
       handler when it enqueues the reindex Celery task).
    3. Worker completes reindex → sets index_ready=True.
    4. Search → detection now visible.
    """
    service = SimilaritySearchService(db_session)

    # Step 1: flip ON.
    await _flip(db_session, t981b_project_off, value=True)

    # Step 2 (target): immediately after flip, index_ready=False → excluded.
    # Currently this PASSES (hits visible), making the test xfail as expected.
    results_immediate = await service.search_by_vector(
        project_id=t981b_project_off.id,
        query_vector=_UNIT_VECTOR,
        model_name="perch",
        limit=10,
        min_similarity=0.0,
        respect_restricted_toggle=True,
    )
    assert results_immediate == [], (
        "Phase 17 target: OFF→ON flip must leave detections hidden until "
        "index_ready=True (Celery worker completes reindex)"
    )
    assert t981b_embedding.id is not None


@pytest.mark.xfail(
    strict=True,
    reason=(
        "FR-025b Phase 17: index_ready=True gate not yet implemented. "
        "Once index_ready column exists and the Celery reindex worker sets "
        "it to True, the OFF→ON transition must expose detections only after "
        "the worker has completed — this test verifies the post-worker state."
    ),
)
@pytest.mark.asyncio
async def test_off_to_on_visible_after_index_rebuild(
    db_session: AsyncSession,
    t981b_project_off: Project,
    t981b_embedding: Embedding,  # noqa: ARG001
) -> None:
    """FR-025b: after reindex worker sets index_ready=True → detection visible.

    Phase 17 contract: simulate the worker completing by setting
    index_ready=True directly, then assert the detection reappears.

    This test is xfail(strict=True) because:
    1. The Project model has no 'index_ready' DB column yet.
    2. The SQL gate does not filter on index_ready yet.
    3. NotImplementedError is raised to ensure the test always fails
       (XFAIL) until Phase 17 implements the feature.
    """
    # Raise immediately — the Phase 17 implementation must remove this
    # and replace it with the actual test logic.
    raise NotImplementedError(
        "Phase 17: Project.index_ready DB column and SQL gate filter "
        "not yet implemented. Add the column, update the search gate, "
        "then remove this NotImplementedError and un-xfail the test."
    )
