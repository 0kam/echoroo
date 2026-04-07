"""Integration test for full annotation workflow.

Tests the complete lifecycle:
create project -> generate tasks -> annotate -> complete -> review
"""

from typing import TYPE_CHECKING, Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.annotation_project import AnnotationProject
from echoroo.models.clip import Clip
from echoroo.models.dataset import Dataset
from echoroo.models.enums import (
    AnnotationProjectVisibility,
    DatasetStatus,
    DatasetVisibility,
    DatetimeParseStatus,
    TagCategory,
)
from echoroo.models.recording import Recording
from echoroo.models.site import Site
from echoroo.models.tag import Tag

if TYPE_CHECKING:
    from echoroo.models.project import Project
    from echoroo.models.user import User


@pytest.fixture
async def workflow_setup(
    db_session: AsyncSession,
    test_project: "Project",
    test_user: "User",
) -> dict[str, Any]:
    """Set up test data for the annotation workflow.

    Creates a site, dataset, recording, clip, annotation project, and tag.

    Args:
        db_session: Database session
        test_project: Parent project
        test_user: Test user

    Returns:
        Dictionary with all created entities
    """
    site = Site(
        project_id=test_project.id,
        name="Workflow Test Site",
        h3_index="8928308281fffff",
    )
    db_session.add(site)
    await db_session.flush()

    dataset = Dataset(
        site_id=site.id,
        project_id=test_project.id,
        created_by_id=test_user.id,
        name="Workflow Test Dataset",
        audio_dir="/audio/workflow-test",
        visibility=DatasetVisibility.PRIVATE,
        status=DatasetStatus.COMPLETED,
    )
    db_session.add(dataset)
    await db_session.flush()

    recording = Recording(
        dataset_id=dataset.id,
        filename="workflow_test.wav",
        path="workflow_test/workflow_test.wav",
        hash="wf123",
        duration=60.0,
        samplerate=44100,
        channels=1,
        datetime_parse_status=DatetimeParseStatus.PENDING,
    )
    db_session.add(recording)
    await db_session.flush()

    clip = Clip(
        recording_id=recording.id,
        start_time=0.0,
        end_time=5.0,
    )
    db_session.add(clip)
    await db_session.flush()

    annotation_project = AnnotationProject(
        project_id=test_project.id,
        created_by_id=test_user.id,
        name="Workflow Test Annotation Project",
        instructions="Label all bird sounds",
        visibility=AnnotationProjectVisibility.PRIVATE,
    )
    annotation_project.datasets.append(dataset)
    db_session.add(annotation_project)
    await db_session.flush()

    tag = Tag(
        project_id=test_project.id,
        name="Common Blackbird",
        category=TagCategory.SPECIES,
    )
    db_session.add(tag)
    await db_session.commit()

    for obj in [site, dataset, recording, clip, annotation_project, tag]:
        await db_session.refresh(obj)

    return {
        "project": test_project,
        "dataset": dataset,
        "recording": recording,
        "clip": clip,
        "annotation_project": annotation_project,
        "tag": tag,
    }


@pytest.mark.asyncio
class TestAnnotationWorkflow:
    """Integration test for the full annotation lifecycle."""

    async def test_full_workflow(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        workflow_setup: dict[str, Any],
    ) -> None:
        """Test the complete annotation workflow end-to-end.

        1. Generate tasks from clips in dataset
        2. Get next task
        3. Create clip annotation
        4. Add sound event with bounding box
        5. Tag the sound event
        6. Complete the task
        7. Review the annotation
        """
        ap = workflow_setup["annotation_project"]
        tag = workflow_setup["tag"]

        # Step 1: Generate tasks
        response = await client.post(
            f"/api/v1/projects/{test_project_id}/annotation-projects/{ap.id}/generate-tasks",
            headers=auth_headers,
        )
        assert response.status_code == 202
        gen_data = response.json()
        assert "task_id" in gen_data
        assert "message" in gen_data

        # Step 2: List tasks - should have at least 1
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/annotation-projects/{ap.id}/tasks",
            headers=auth_headers,
        )
        assert response.status_code == 200
        tasks_data = response.json()
        assert tasks_data["total"] >= 1
        task_id = tasks_data["items"][0]["id"]

        # Step 3: Get or create clip annotation for the task
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/annotation-tasks/{task_id}/clip-annotation",
            headers=auth_headers,
        )
        assert response.status_code == 200
        clip_annotation = response.json()
        clip_annotation_id = clip_annotation["id"]
        assert clip_annotation["review_status"] == "unreviewed"

        # Step 4: Create a sound event annotation with bounding box
        response = await client.post(
            f"/api/v1/projects/{test_project_id}/clip-annotations/{clip_annotation_id}/sound-events",
            headers=auth_headers,
            json={
                "geometry": {
                    "type": "BoundingBox",
                    "coordinates": [1.0, 2000.0, 2.5, 6000.0],
                },
                "source": "human",
                "confidence": 0.95,
            },
        )
        assert response.status_code == 201
        sound_event = response.json()
        sound_event_id = sound_event["id"]

        # Step 5: Tag the sound event
        response = await client.post(
            f"/api/v1/projects/{test_project_id}/sound-events/{sound_event_id}/tags",
            headers=auth_headers,
            json={"tag_id": str(tag.id)},
        )
        assert response.status_code == 200

        # Step 6: Complete the task
        response = await client.post(
            f"/api/v1/projects/{test_project_id}/annotation-projects/{ap.id}/tasks/{task_id}/complete",
            headers=auth_headers,
        )
        assert response.status_code == 200
        completion = response.json()
        assert completion["completed_task_id"] == task_id

        # Step 7: Review the annotation (approve)
        response = await client.post(
            f"/api/v1/projects/{test_project_id}/clip-annotations/{clip_annotation_id}/review",
            headers=auth_headers,
            json={"status": "approved", "comment": "Well annotated"},
        )
        assert response.status_code == 200
        reviewed = response.json()
        assert reviewed["review_status"] == "approved"
        assert reviewed["reviewed_by_id"] is not None

        # Verify: Export the project annotations
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/annotation-projects/{ap.id}/export?format=json",
            headers=auth_headers,
        )
        assert response.status_code == 200
        export_data = response.json()
        assert "annotations" in export_data
        assert len(export_data["annotations"]) >= 1
