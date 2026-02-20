"""Contract tests for annotations API endpoints.

Tests verify that endpoints conform to the annotation specification.
"""

import json
from typing import TYPE_CHECKING

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.annotation_project import AnnotationProject
from echoroo.models.annotation_task import AnnotationTask
from echoroo.models.clip import Clip
from echoroo.models.clip_annotation import ClipAnnotation
from echoroo.models.dataset import Dataset
from echoroo.models.enums import (
    AnnotationProjectVisibility,
    AnnotationTaskStatus,
    DatasetStatus,
    DatasetVisibility,
    DatetimeParseStatus,
    ReviewStatus,
    TagCategory,
)
from echoroo.models.recording import Recording
from echoroo.models.site import Site
from echoroo.models.sound_event_annotation import SoundEventAnnotation
from echoroo.models.tag import Tag

if TYPE_CHECKING:
    from echoroo.models.project import Project
    from echoroo.models.user import User


@pytest.fixture
async def test_tag(
    db_session: AsyncSession,
    test_project: "Project",
) -> Tag:
    """Create a test tag.

    Args:
        db_session: Database session
        test_project: Parent project

    Returns:
        Tag instance
    """
    tag = Tag(
        project_id=test_project.id,
        name="Common Chaffinch",
        category=TagCategory.SPECIES,
    )
    db_session.add(tag)
    await db_session.commit()
    await db_session.refresh(tag)
    return tag


@pytest.fixture
async def test_annotation_project(
    db_session: AsyncSession,
    test_project: "Project",
    test_user: "User",
) -> AnnotationProject:
    """Create a test annotation project.

    Args:
        db_session: Database session
        test_project: Parent project
        test_user: Creator user

    Returns:
        AnnotationProject instance
    """
    annotation_project = AnnotationProject(
        project_id=test_project.id,
        created_by_id=test_user.id,
        name="Annotation Test Project",
        visibility=AnnotationProjectVisibility.PRIVATE,
    )
    db_session.add(annotation_project)
    await db_session.commit()
    await db_session.refresh(annotation_project)
    return annotation_project


@pytest.fixture
async def test_clip(
    db_session: AsyncSession,
    test_project: "Project",
    test_user: "User",
) -> Clip:
    """Create a test clip with its parent recording and dataset.

    Args:
        db_session: Database session
        test_project: Parent project
        test_user: Creator user

    Returns:
        Clip instance
    """
    site = Site(
        project_id=test_project.id,
        name="Annotations Test Site",
        h3_index="8928308281fffff",
    )
    db_session.add(site)
    await db_session.flush()

    dataset = Dataset(
        site_id=site.id,
        project_id=test_project.id,
        created_by_id=test_user.id,
        name="Annotations Test Dataset",
        audio_dir="/audio/annot-test",
        visibility=DatasetVisibility.PRIVATE,
        status=DatasetStatus.COMPLETED,
    )
    db_session.add(dataset)
    await db_session.flush()

    recording = Recording(
        dataset_id=dataset.id,
        filename="annot_test.wav",
        path="annot_test/annot_test.wav",
        hash="def456",
        duration=30.0,
        samplerate=44100,
        channels=1,
        datetime_parse_status=DatetimeParseStatus.PENDING,
    )
    db_session.add(recording)
    await db_session.flush()

    clip = Clip(
        recording_id=recording.id,
        start_time=0.0,
        end_time=3.0,
    )
    db_session.add(clip)
    await db_session.commit()
    await db_session.refresh(clip)
    return clip


@pytest.fixture
async def test_annotation_task(
    db_session: AsyncSession,
    test_annotation_project: AnnotationProject,
    test_clip: Clip,
) -> AnnotationTask:
    """Create a test annotation task.

    Args:
        db_session: Database session
        test_annotation_project: Parent annotation project
        test_clip: Clip to annotate

    Returns:
        AnnotationTask instance
    """
    task = AnnotationTask(
        annotation_project_id=test_annotation_project.id,
        clip_id=test_clip.id,
        status=AnnotationTaskStatus.PENDING,
        priority=0,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    return task


@pytest.fixture
async def test_clip_annotation(
    db_session: AsyncSession,
    test_annotation_task: AnnotationTask,
    test_clip: Clip,
    test_user: "User",
) -> ClipAnnotation:
    """Create a test clip annotation.

    Args:
        db_session: Database session
        test_annotation_task: Parent annotation task
        test_clip: Annotated clip
        test_user: Creator user

    Returns:
        ClipAnnotation instance
    """
    clip_annotation = ClipAnnotation(
        task_id=test_annotation_task.id,
        clip_id=test_clip.id,
        created_by_id=test_user.id,
        review_status=ReviewStatus.UNREVIEWED,
    )
    db_session.add(clip_annotation)
    await db_session.commit()
    await db_session.refresh(clip_annotation)
    return clip_annotation


@pytest.fixture
async def test_sound_event(
    db_session: AsyncSession,
    test_clip_annotation: ClipAnnotation,
    test_user: "User",
) -> SoundEventAnnotation:
    """Create a test sound event annotation.

    Args:
        db_session: Database session
        test_clip_annotation: Parent clip annotation
        test_user: Creator user

    Returns:
        SoundEventAnnotation instance
    """
    sound_event = SoundEventAnnotation(
        clip_annotation_id=test_clip_annotation.id,
        created_by_id=test_user.id,
        geometry={"type": "TimeInterval", "coordinates": [0.5, 1.5]},
    )
    db_session.add(sound_event)
    await db_session.commit()
    await db_session.refresh(sound_event)
    return sound_event


@pytest.mark.asyncio
class TestGetOrCreateClipAnnotationEndpoint:
    """Test GET /api/v1/projects/{project_id}/annotation-tasks/{task_id}/clip-annotation."""

    async def test_get_or_create_clip_annotation_creates_new(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_annotation_task: AnnotationTask,
    ) -> None:
        """Test GET creates a new clip annotation when none exists (200)."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/annotation-tasks/{test_annotation_task.id}/clip-annotation",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        assert "id" in data
        assert data["task_id"] == str(test_annotation_task.id)
        assert "tags" in data
        assert "sound_events" in data
        assert "notes" in data
        assert "review_status" in data
        assert data["review_status"] == "unreviewed"

    async def test_get_or_create_clip_annotation_returns_existing(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_annotation_task: AnnotationTask,
        test_clip_annotation: ClipAnnotation,
    ) -> None:
        """Test GET returns existing clip annotation (200)."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/annotation-tasks/{test_annotation_task.id}/clip-annotation",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(test_clip_annotation.id)

    async def test_get_or_create_clip_annotation_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_annotation_task: AnnotationTask,
    ) -> None:
        """Test GET requires authentication."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/annotation-tasks/{test_annotation_task.id}/clip-annotation",
        )

        assert response.status_code == 401


@pytest.mark.asyncio
class TestAddClipTagEndpoint:
    """Test POST /api/v1/projects/{project_id}/clip-annotations/{ca_id}/tags."""

    async def test_add_clip_tag_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_clip_annotation: ClipAnnotation,
        test_tag: Tag,
    ) -> None:
        """Test POST adds a tag to the clip annotation (200)."""
        response = await client.post(
            f"/api/v1/projects/{test_project_id}/clip-annotations/{test_clip_annotation.id}/tags",
            headers=auth_headers,
            json={"tag_id": str(test_tag.id)},
        )

        assert response.status_code == 200
        data = response.json()

        assert "tags" in data
        tag_ids = [t["id"] for t in data["tags"]]
        assert str(test_tag.id) in tag_ids

    async def test_add_clip_tag_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_clip_annotation: ClipAnnotation,
        test_tag: Tag,
    ) -> None:
        """Test POST requires authentication."""
        response = await client.post(
            f"/api/v1/projects/{test_project_id}/clip-annotations/{test_clip_annotation.id}/tags",
            json={"tag_id": str(test_tag.id)},
        )

        assert response.status_code == 401


@pytest.mark.asyncio
class TestRemoveClipTagEndpoint:
    """Test DELETE /api/v1/projects/{project_id}/clip-annotations/{ca_id}/tags."""

    async def test_remove_clip_tag_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_clip_annotation: ClipAnnotation,
        test_tag: Tag,
    ) -> None:
        """Test DELETE removes a tag from the clip annotation (200)."""
        # First add the tag
        await client.post(
            f"/api/v1/projects/{test_project_id}/clip-annotations/{test_clip_annotation.id}/tags",
            headers=auth_headers,
            json={"tag_id": str(test_tag.id)},
        )

        # Then remove it
        response = await client.delete(
            f"/api/v1/projects/{test_project_id}/clip-annotations/{test_clip_annotation.id}/tags/{test_tag.id}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        tag_ids = [t["id"] for t in data["tags"]]
        assert str(test_tag.id) not in tag_ids

    async def test_remove_clip_tag_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_clip_annotation: ClipAnnotation,
        test_tag: Tag,
    ) -> None:
        """Test DELETE requires authentication."""
        response = await client.delete(
            f"/api/v1/projects/{test_project_id}/clip-annotations/{test_clip_annotation.id}/tags/{test_tag.id}",
        )

        assert response.status_code == 401


@pytest.mark.asyncio
class TestCreateSoundEventEndpoint:
    """Test POST /api/v1/projects/{project_id}/clip-annotations/{ca_id}/sound-events."""

    async def test_create_sound_event_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_clip_annotation: ClipAnnotation,
    ) -> None:
        """Test POST creates a sound event annotation (201)."""
        payload = {
            "geometry": {
                "type": "TimeInterval",
                "coordinates": [0.5, 1.5],
            },
            "source": "human",
        }

        response = await client.post(
            f"/api/v1/projects/{test_project_id}/clip-annotations/{test_clip_annotation.id}/sound-events",
            headers=auth_headers,
            json=payload,
        )

        assert response.status_code == 201
        data = response.json()

        assert "id" in data
        assert data["clip_annotation_id"] == str(test_clip_annotation.id)
        assert data["geometry"]["type"] == "TimeInterval"
        assert data["source"] == "human"
        assert "tags" in data
        assert "created_at" in data

    async def test_create_sound_event_bounding_box(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_clip_annotation: ClipAnnotation,
    ) -> None:
        """Test POST creates a BoundingBox sound event (201)."""
        payload = {
            "geometry": {
                "type": "BoundingBox",
                "coordinates": [0.5, 1000.0, 1.5, 5000.0],
            },
            "confidence": 0.85,
        }

        response = await client.post(
            f"/api/v1/projects/{test_project_id}/clip-annotations/{test_clip_annotation.id}/sound-events",
            headers=auth_headers,
            json=payload,
        )

        assert response.status_code == 201
        data = response.json()

        assert data["geometry"]["type"] == "BoundingBox"
        assert data["confidence"] == 0.85

    async def test_create_sound_event_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_clip_annotation: ClipAnnotation,
    ) -> None:
        """Test POST requires authentication."""
        response = await client.post(
            f"/api/v1/projects/{test_project_id}/clip-annotations/{test_clip_annotation.id}/sound-events",
            json={
                "geometry": {"type": "TimeInterval", "coordinates": [0.0, 1.0]},
            },
        )

        assert response.status_code == 401


@pytest.mark.asyncio
class TestUpdateSoundEventEndpoint:
    """Test PATCH /api/v1/projects/{project_id}/sound-events/{se_id}."""

    async def test_update_sound_event_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_sound_event: SoundEventAnnotation,
    ) -> None:
        """Test PATCH updates a sound event annotation (200)."""
        update_payload = {
            "geometry": {
                "type": "TimeInterval",
                "coordinates": [1.0, 2.5],
            },
            "confidence": 0.9,
        }

        response = await client.patch(
            f"/api/v1/projects/{test_project_id}/sound-events/{test_sound_event.id}",
            headers=auth_headers,
            json=update_payload,
        )

        assert response.status_code == 200
        data = response.json()

        assert data["id"] == str(test_sound_event.id)
        assert data["geometry"]["coordinates"] == [1.0, 2.5]
        assert data["confidence"] == 0.9

    async def test_update_sound_event_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_sound_event: SoundEventAnnotation,
    ) -> None:
        """Test PATCH requires authentication."""
        response = await client.patch(
            f"/api/v1/projects/{test_project_id}/sound-events/{test_sound_event.id}",
            json={"confidence": 0.5},
        )

        assert response.status_code == 401


@pytest.mark.asyncio
class TestDeleteSoundEventEndpoint:
    """Test DELETE /api/v1/projects/{project_id}/sound-events/{se_id}."""

    async def test_delete_sound_event_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_sound_event: SoundEventAnnotation,
    ) -> None:
        """Test DELETE removes a sound event annotation (204)."""
        response = await client.delete(
            f"/api/v1/projects/{test_project_id}/sound-events/{test_sound_event.id}",
            headers=auth_headers,
        )

        assert response.status_code == 204

    async def test_delete_sound_event_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_sound_event: SoundEventAnnotation,
    ) -> None:
        """Test DELETE requires authentication."""
        response = await client.delete(
            f"/api/v1/projects/{test_project_id}/sound-events/{test_sound_event.id}",
        )

        assert response.status_code == 401


@pytest.mark.asyncio
class TestAddSoundEventTagEndpoint:
    """Test POST /api/v1/projects/{project_id}/sound-events/{se_id}/tags."""

    async def test_add_sound_event_tag_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_sound_event: SoundEventAnnotation,
        test_tag: Tag,
    ) -> None:
        """Test POST adds a tag to the sound event annotation (200)."""
        response = await client.post(
            f"/api/v1/projects/{test_project_id}/sound-events/{test_sound_event.id}/tags",
            headers=auth_headers,
            json={"tag_id": str(test_tag.id)},
        )

        assert response.status_code == 200

    async def test_add_sound_event_tag_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_sound_event: SoundEventAnnotation,
        test_tag: Tag,
    ) -> None:
        """Test POST requires authentication."""
        response = await client.post(
            f"/api/v1/projects/{test_project_id}/sound-events/{test_sound_event.id}/tags",
            json={"tag_id": str(test_tag.id)},
        )

        assert response.status_code == 401


@pytest.mark.asyncio
class TestRemoveSoundEventTagEndpoint:
    """Test DELETE /api/v1/projects/{project_id}/sound-events/{se_id}/tags."""

    async def test_remove_sound_event_tag_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_sound_event: SoundEventAnnotation,
        test_tag: Tag,
    ) -> None:
        """Test DELETE removes a tag from the sound event annotation (200)."""
        # First add the tag
        await client.post(
            f"/api/v1/projects/{test_project_id}/sound-events/{test_sound_event.id}/tags",
            headers=auth_headers,
            json={"tag_id": str(test_tag.id)},
        )

        # Then remove it
        response = await client.delete(
            f"/api/v1/projects/{test_project_id}/sound-events/{test_sound_event.id}/tags/{test_tag.id}",
            headers=auth_headers,
        )

        assert response.status_code == 200

    async def test_remove_sound_event_tag_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_sound_event: SoundEventAnnotation,
        test_tag: Tag,
    ) -> None:
        """Test DELETE requires authentication."""
        response = await client.delete(
            f"/api/v1/projects/{test_project_id}/sound-events/{test_sound_event.id}/tags/{test_tag.id}",
        )

        assert response.status_code == 401


@pytest.mark.asyncio
class TestAddNoteEndpoint:
    """Test POST /api/v1/projects/{project_id}/clip-annotations/{ca_id}/notes."""

    async def test_add_note_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_clip_annotation: ClipAnnotation,
    ) -> None:
        """Test POST creates a note on the clip annotation (201)."""
        payload = {
            "content": "This clip has a clear bird call at 1.5 seconds",
            "is_review": False,
        }

        response = await client.post(
            f"/api/v1/projects/{test_project_id}/clip-annotations/{test_clip_annotation.id}/notes",
            headers=auth_headers,
            json=payload,
        )

        assert response.status_code == 201
        data = response.json()

        assert "id" in data
        assert data["content"] == payload["content"]
        assert data["is_review"] is False
        assert "created_by_id" in data
        assert "created_at" in data

    async def test_add_review_note_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_clip_annotation: ClipAnnotation,
    ) -> None:
        """Test POST creates a review note on the clip annotation (201)."""
        payload = {
            "content": "Review: annotation looks correct",
            "is_review": True,
        }

        response = await client.post(
            f"/api/v1/projects/{test_project_id}/clip-annotations/{test_clip_annotation.id}/notes",
            headers=auth_headers,
            json=payload,
        )

        assert response.status_code == 201
        data = response.json()

        assert data["is_review"] is True

    async def test_add_note_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_clip_annotation: ClipAnnotation,
    ) -> None:
        """Test POST requires authentication."""
        response = await client.post(
            f"/api/v1/projects/{test_project_id}/clip-annotations/{test_clip_annotation.id}/notes",
            json={"content": "Unauthorized note"},
        )

        assert response.status_code == 401


@pytest.mark.asyncio
class TestBatchClipTagEndpoint:
    """Test POST /api/v1/projects/{project_id}/clip-annotations/batch-tag."""

    async def test_batch_tag_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_annotation_project: AnnotationProject,
        test_clip: Clip,
        test_tag: Tag,
        db_session: AsyncSession,
        test_user: "User",
    ) -> None:
        """Test POST batch tags multiple tasks (200)."""
        # Create a second clip with its recording (reuse the existing site/dataset by creating another recording)
        from echoroo.models.dataset import Dataset
        from echoroo.models.recording import Recording

        # Fetch an existing dataset to reuse
        from sqlalchemy import select

        dataset_result = await db_session.execute(select(Dataset).limit(1))
        dataset = dataset_result.scalar_one()

        recording2 = Recording(
            dataset_id=dataset.id,
            filename="batch_test2.wav",
            path="batch_test/batch_test2.wav",
            hash="abc999",
            duration=30.0,
            samplerate=44100,
            channels=1,
            datetime_parse_status=DatetimeParseStatus.PENDING,
        )
        db_session.add(recording2)
        await db_session.flush()

        clip2 = Clip(
            recording_id=recording2.id,
            start_time=0.0,
            end_time=3.0,
        )
        db_session.add(clip2)
        await db_session.flush()

        # Create two annotation tasks
        task1 = AnnotationTask(
            annotation_project_id=test_annotation_project.id,
            clip_id=test_clip.id,
            status=AnnotationTaskStatus.PENDING,
            priority=0,
        )
        task2 = AnnotationTask(
            annotation_project_id=test_annotation_project.id,
            clip_id=clip2.id,
            status=AnnotationTaskStatus.PENDING,
            priority=0,
        )
        db_session.add(task1)
        db_session.add(task2)
        await db_session.commit()
        await db_session.refresh(task1)
        await db_session.refresh(task2)

        response = await client.post(
            f"/api/v1/projects/{test_project_id}/clip-annotations/batch-tag",
            headers=auth_headers,
            json={
                "task_ids": [str(task1.id), str(task2.id)],
                "tag_id": str(test_tag.id),
            },
        )

        assert response.status_code == 200
        data = response.json()

        assert data["updated_count"] == 2
        assert "clip_annotations" in data
        assert len(data["clip_annotations"]) == 2

        # Verify each clip annotation has the tag
        for ca in data["clip_annotations"]:
            assert "tags" in ca
            tag_ids = [t["id"] for t in ca["tags"]]
            assert str(test_tag.id) in tag_ids

    async def test_batch_tag_empty_task_ids(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_tag: Tag,
    ) -> None:
        """Test POST with empty task_ids returns 422."""
        response = await client.post(
            f"/api/v1/projects/{test_project_id}/clip-annotations/batch-tag",
            headers=auth_headers,
            json={
                "task_ids": [],
                "tag_id": str(test_tag.id),
            },
        )

        assert response.status_code == 422

    async def test_batch_tag_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_tag: Tag,
        test_annotation_task: AnnotationTask,
    ) -> None:
        """Test POST requires authentication."""
        response = await client.post(
            f"/api/v1/projects/{test_project_id}/clip-annotations/batch-tag",
            json={
                "task_ids": [str(test_annotation_task.id)],
                "tag_id": str(test_tag.id),
            },
        )

        assert response.status_code == 401


@pytest.mark.asyncio
class TestReviewClipAnnotationEndpoint:
    """Test POST /api/v1/projects/{project_id}/clip-annotations/{id}/review."""

    async def test_approve_annotation_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_clip_annotation: ClipAnnotation,
    ) -> None:
        """Test POST approves a clip annotation (200)."""
        response = await client.post(
            f"/api/v1/projects/{test_project_id}/clip-annotations/{test_clip_annotation.id}/review",
            headers=auth_headers,
            json={"status": "approved", "comment": "Looks good"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["review_status"] == "approved"
        assert data["reviewed_by_id"] is not None

    async def test_reject_annotation_with_comment(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_clip_annotation: ClipAnnotation,
    ) -> None:
        """Test POST rejects with comment (200)."""
        response = await client.post(
            f"/api/v1/projects/{test_project_id}/clip-annotations/{test_clip_annotation.id}/review",
            headers=auth_headers,
            json={"status": "rejected", "comment": "Missing species tag"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["review_status"] == "rejected"
        assert data["reviewed_by_id"] is not None
        # Review comment should appear in notes
        assert any(n["content"] == "Missing species tag" and n["is_review"] is True for n in data["notes"])

    async def test_approve_annotation_without_comment(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_clip_annotation: ClipAnnotation,
    ) -> None:
        """Test POST approves without optional comment (200)."""
        response = await client.post(
            f"/api/v1/projects/{test_project_id}/clip-annotations/{test_clip_annotation.id}/review",
            headers=auth_headers,
            json={"status": "approved"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["review_status"] == "approved"
        assert data["reviewed_at"] is not None

    async def test_review_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_clip_annotation: ClipAnnotation,
    ) -> None:
        """Test POST requires authentication."""
        response = await client.post(
            f"/api/v1/projects/{test_project_id}/clip-annotations/{test_clip_annotation.id}/review",
            json={"status": "approved"},
        )

        assert response.status_code == 401

    async def test_review_not_found(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test POST with invalid clip annotation ID returns 404."""
        import uuid

        nonexistent_id = uuid.uuid4()
        response = await client.post(
            f"/api/v1/projects/{test_project_id}/clip-annotations/{nonexistent_id}/review",
            headers=auth_headers,
            json={"status": "approved"},
        )

        assert response.status_code == 404
