"""Integration test for the full annotation review workflow.

Tests the complete lifecycle:
  create annotation → add sound events → complete task → review (approve/reject)

This validates status transitions and data consistency across the full pipeline.
"""

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
from echoroo.models.project import Project
from echoroo.models.recording import Recording
from echoroo.models.site import Site
from echoroo.models.tag import Tag
from echoroo.models.user import User


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def review_tag(db_session: AsyncSession, test_project: Project) -> Tag:
    """Create a species tag for review workflow tests.

    Args:
        db_session: Database session
        test_project: Parent project

    Returns:
        Tag instance
    """
    tag = Tag(
        project_id=test_project.id,
        name="Eurasian Blackbird",
        category=TagCategory.SPECIES,
    )
    db_session.add(tag)
    await db_session.commit()
    await db_session.refresh(tag)
    return tag


@pytest.fixture
async def review_annotation_project(
    db_session: AsyncSession,
    test_project: Project,
    test_user: User,
) -> AnnotationProject:
    """Create a test annotation project for review workflow tests.

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
        name="Review Workflow Test Project",
        visibility=AnnotationProjectVisibility.PRIVATE,
    )
    db_session.add(annotation_project)
    await db_session.commit()
    await db_session.refresh(annotation_project)
    return annotation_project


@pytest.fixture
async def review_clip(
    db_session: AsyncSession,
    test_project: Project,
    test_user: User,
) -> Clip:
    """Create a test clip with dependencies for review workflow tests.

    Args:
        db_session: Database session
        test_project: Parent project
        test_user: Creator user

    Returns:
        Clip instance
    """
    site = Site(
        project_id=test_project.id,
        name="Review Test Site",
        h3_index="8928308281fffff",
    )
    db_session.add(site)
    await db_session.flush()

    dataset = Dataset(
        site_id=site.id,
        project_id=test_project.id,
        created_by_id=test_user.id,
        name="Review Test Dataset",
        audio_dir="/audio/review-test",
        visibility=DatasetVisibility.PRIVATE,
        status=DatasetStatus.COMPLETED,
    )
    db_session.add(dataset)
    await db_session.flush()

    recording = Recording(
        dataset_id=dataset.id,
        filename="review_test.wav",
        path="review_test/review_test.wav",
        hash="rev001",
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
async def review_annotation_task(
    db_session: AsyncSession,
    review_annotation_project: AnnotationProject,
    review_clip: Clip,
) -> AnnotationTask:
    """Create a test annotation task for review workflow tests.

    Args:
        db_session: Database session
        review_annotation_project: Parent annotation project
        review_clip: Clip to annotate

    Returns:
        AnnotationTask instance
    """
    task = AnnotationTask(
        annotation_project_id=review_annotation_project.id,
        clip_id=review_clip.id,
        status=AnnotationTaskStatus.PENDING,
        priority=0,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    return task


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_annotation_review_approve_workflow(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_project: Project,
    review_annotation_task: AnnotationTask,
    review_tag: Tag,
) -> None:
    """Test the complete annotation lifecycle ending in approval.

    Flow:
    1. Get or create clip annotation for the task
    2. Add a species tag to the clip annotation
    3. Add a sound event with geometry
    4. Review the annotation (approve)
    5. Verify final state
    """
    project_id = str(test_project.id)
    task_id = str(review_annotation_task.id)

    # Step 1: Get or create clip annotation
    get_resp = await client.get(
        f"/api/v1/projects/{project_id}/annotation-tasks/{task_id}/clip-annotation",
        headers=auth_headers,
    )
    assert get_resp.status_code == 200
    clip_annotation_data = get_resp.json()
    clip_annotation_id = clip_annotation_data["id"]

    assert clip_annotation_data["review_status"] == "unreviewed"
    assert clip_annotation_data["reviewed_by_id"] is None
    assert clip_annotation_data["reviewed_at"] is None

    # Step 2: Add a species tag
    tag_resp = await client.post(
        f"/api/v1/projects/{project_id}/clip-annotations/{clip_annotation_id}/tags",
        headers=auth_headers,
        json={"tag_id": str(review_tag.id)},
    )
    assert tag_resp.status_code == 200
    tag_data = tag_resp.json()
    assert any(t["id"] == str(review_tag.id) for t in tag_data["tags"])

    # Step 3: Add a sound event
    se_resp = await client.post(
        f"/api/v1/projects/{project_id}/clip-annotations/{clip_annotation_id}/sound-events",
        headers=auth_headers,
        json={
            "geometry": {"type": "TimeInterval", "coordinates": [0.5, 1.5]},
            "source": "human",
        },
    )
    assert se_resp.status_code == 201
    se_data = se_resp.json()
    assert se_data["clip_annotation_id"] == clip_annotation_id

    # Step 4: Review and approve
    review_resp = await client.post(
        f"/api/v1/projects/{project_id}/clip-annotations/{clip_annotation_id}/review",
        headers=auth_headers,
        json={"status": "approved", "comment": "Annotation is correct"},
    )
    assert review_resp.status_code == 200
    review_data = review_resp.json()

    # Step 5: Verify final state
    assert review_data["review_status"] == "approved"
    assert review_data["reviewed_by_id"] is not None
    assert review_data["reviewed_at"] is not None
    # Review comment should appear as a review note
    review_notes = [n for n in review_data["notes"] if n["is_review"]]
    assert len(review_notes) == 1
    assert review_notes[0]["content"] == "Annotation is correct"


@pytest.mark.asyncio
async def test_full_annotation_review_reject_workflow(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_project: Project,
    review_annotation_task: AnnotationTask,
) -> None:
    """Test the complete annotation lifecycle ending in rejection.

    Flow:
    1. Get or create clip annotation for the task
    2. Review the annotation (reject with feedback)
    3. Verify rejection state and review note
    """
    project_id = str(test_project.id)
    task_id = str(review_annotation_task.id)

    # Step 1: Get or create clip annotation
    get_resp = await client.get(
        f"/api/v1/projects/{project_id}/annotation-tasks/{task_id}/clip-annotation",
        headers=auth_headers,
    )
    assert get_resp.status_code == 200
    clip_annotation_id = get_resp.json()["id"]

    # Step 2: Reject with feedback
    review_resp = await client.post(
        f"/api/v1/projects/{project_id}/clip-annotations/{clip_annotation_id}/review",
        headers=auth_headers,
        json={"status": "rejected", "comment": "Missing species tag, please re-annotate"},
    )
    assert review_resp.status_code == 200
    review_data = review_resp.json()

    # Step 3: Verify rejection state
    assert review_data["review_status"] == "rejected"
    assert review_data["reviewed_by_id"] is not None
    assert review_data["reviewed_at"] is not None

    rejection_notes = [n for n in review_data["notes"] if n["is_review"]]
    assert len(rejection_notes) == 1
    assert rejection_notes[0]["content"] == "Missing species tag, please re-annotate"


@pytest.mark.asyncio
async def test_review_without_comment(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_project: Project,
    review_annotation_task: AnnotationTask,
) -> None:
    """Test review approval without an optional comment does not create a note.

    Flow:
    1. Get or create clip annotation
    2. Approve without comment
    3. Verify no review notes were created
    """
    project_id = str(test_project.id)
    task_id = str(review_annotation_task.id)

    # Step 1: Get or create clip annotation
    get_resp = await client.get(
        f"/api/v1/projects/{project_id}/annotation-tasks/{task_id}/clip-annotation",
        headers=auth_headers,
    )
    assert get_resp.status_code == 200
    clip_annotation_id = get_resp.json()["id"]

    # Step 2: Approve without comment
    review_resp = await client.post(
        f"/api/v1/projects/{project_id}/clip-annotations/{clip_annotation_id}/review",
        headers=auth_headers,
        json={"status": "approved"},
    )
    assert review_resp.status_code == 200
    review_data = review_resp.json()

    # Step 3: No review notes should be created
    assert review_data["review_status"] == "approved"
    review_notes = [n for n in review_data["notes"] if n["is_review"]]
    assert len(review_notes) == 0


@pytest.mark.asyncio
async def test_review_can_be_overridden(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_project: Project,
    review_annotation_task: AnnotationTask,
) -> None:
    """Test that a review decision can be updated (e.g. approved then rejected).

    Flow:
    1. Get or create clip annotation
    2. Approve the annotation
    3. Override with rejection
    4. Verify the latest review status is reflected
    """
    project_id = str(test_project.id)
    task_id = str(review_annotation_task.id)

    # Step 1: Get or create clip annotation
    get_resp = await client.get(
        f"/api/v1/projects/{project_id}/annotation-tasks/{task_id}/clip-annotation",
        headers=auth_headers,
    )
    assert get_resp.status_code == 200
    clip_annotation_id = get_resp.json()["id"]

    # Step 2: Initial approval
    approve_resp = await client.post(
        f"/api/v1/projects/{project_id}/clip-annotations/{clip_annotation_id}/review",
        headers=auth_headers,
        json={"status": "approved"},
    )
    assert approve_resp.status_code == 200
    assert approve_resp.json()["review_status"] == "approved"

    # Step 3: Override with rejection
    reject_resp = await client.post(
        f"/api/v1/projects/{project_id}/clip-annotations/{clip_annotation_id}/review",
        headers=auth_headers,
        json={"status": "rejected", "comment": "On closer inspection, this is incorrect"},
    )
    assert reject_resp.status_code == 200
    reject_data = reject_resp.json()

    # Step 4: Verify the latest state
    assert reject_data["review_status"] == "rejected"
    review_notes = [n for n in reject_data["notes"] if n["is_review"]]
    assert any(n["content"] == "On closer inspection, this is incorrect" for n in review_notes)
