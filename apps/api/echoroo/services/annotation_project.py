"""AnnotationProject service for business logic."""

import math
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import select

from echoroo.models.annotation_project import AnnotationProject
from echoroo.models.annotation_task import AnnotationTask
from echoroo.models.clip import Clip
from echoroo.models.recording import Recording
from echoroo.repositories.annotation_project import AnnotationProjectRepository
from echoroo.repositories.annotation_task import AnnotationTaskRepository
from echoroo.schemas.annotation_project import (
    AnnotationProgress,
    AnnotationProjectCreate,
    AnnotationProjectDetailResponse,
    AnnotationProjectListResponse,
    AnnotationProjectUpdate,
    DatasetSummary,
    TagSummary,
    TaskGenerationResponse,
)


class AnnotationProjectService:
    """Service for annotation project management business logic."""

    def __init__(
        self,
        annotation_project_repo: AnnotationProjectRepository,
        annotation_task_repo: AnnotationTaskRepository,
    ) -> None:
        """Initialize service with repositories.

        Args:
            annotation_project_repo: AnnotationProject repository instance
            annotation_task_repo: AnnotationTask repository instance
        """
        self.annotation_project_repo = annotation_project_repo
        self.annotation_task_repo = annotation_task_repo

    def _build_progress(self, counts: dict[str, int]) -> AnnotationProgress:
        """Build AnnotationProgress from status count dictionary.

        Args:
            counts: Dictionary mapping status values to counts

        Returns:
            AnnotationProgress with computed totals
        """
        completed = counts.get("completed", 0)
        in_progress = counts.get("in_progress", 0)
        pending = counts.get("pending", 0)
        review_pending = counts.get("review_pending", 0)
        total = completed + in_progress + pending + review_pending

        return AnnotationProgress(
            total_tasks=total,
            completed_tasks=completed,
            in_progress_tasks=in_progress,
            pending_tasks=pending,
            review_pending_tasks=review_pending,
        )

    def _build_detail_response(
        self,
        annotation_project: AnnotationProject,
        progress: AnnotationProgress,
    ) -> AnnotationProjectDetailResponse:
        """Build AnnotationProjectDetailResponse from model and progress data.

        Args:
            annotation_project: AnnotationProject ORM instance
            progress: Computed annotation progress

        Returns:
            AnnotationProjectDetailResponse schema instance
        """
        datasets = [DatasetSummary.model_validate(d) for d in annotation_project.datasets]
        tags = [TagSummary.model_validate(t) for t in annotation_project.tags]

        return AnnotationProjectDetailResponse(
            id=annotation_project.id,
            project_id=annotation_project.project_id,
            created_by_id=annotation_project.created_by_id,
            name=annotation_project.name,
            description=annotation_project.description,
            instructions=annotation_project.instructions,
            visibility=annotation_project.visibility,
            created_at=annotation_project.created_at,
            updated_at=annotation_project.updated_at,
            datasets=datasets,
            tags=tags,
            progress=progress,
        )

    async def list_projects(
        self,
        project_id: UUID,
        page: int = 1,
        page_size: int = 20,
    ) -> AnnotationProjectListResponse:
        """List annotation projects for a project with pagination.

        Args:
            project_id: Parent project's UUID
            page: Page number (1-indexed)
            page_size: Items per page

        Returns:
            Paginated AnnotationProjectListResponse
        """
        if page < 1:
            page = 1
        if page_size < 1 or page_size > 100:
            page_size = 20

        annotation_projects, total = await self.annotation_project_repo.list_by_project(
            project_id, page, page_size
        )

        pages = math.ceil(total / page_size) if total > 0 else 0

        items = []
        for ap in annotation_projects:
            counts = await self.annotation_task_repo.count_by_status(ap.id)
            progress = self._build_progress(counts)
            items.append(self._build_detail_response(ap, progress))

        return AnnotationProjectListResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
        )

    async def create(
        self,
        project_id: UUID,
        user_id: UUID,
        request: AnnotationProjectCreate,
    ) -> AnnotationProjectDetailResponse:
        """Create a new annotation project.

        Args:
            project_id: Parent project's UUID
            user_id: User creating the annotation project
            request: Annotation project creation data

        Returns:
            Created annotation project with detail response
        """
        from echoroo.models.dataset import Dataset
        from echoroo.models.tag import Tag
        from sqlalchemy import select

        annotation_project = AnnotationProject(
            project_id=project_id,
            created_by_id=user_id,
            name=request.name,
            description=request.description,
            instructions=request.instructions,
            visibility=request.visibility,
        )

        # Handle dataset associations
        if request.dataset_ids:
            dataset_result = await self.annotation_project_repo.db.execute(
                select(Dataset).where(Dataset.id.in_(request.dataset_ids))
            )
            annotation_project.datasets = list(dataset_result.scalars().all())

        # Handle tag associations
        if request.tag_ids:
            tag_result = await self.annotation_project_repo.db.execute(
                select(Tag).where(Tag.id.in_(request.tag_ids))
            )
            annotation_project.tags = list(tag_result.scalars().all())

        created = await self.annotation_project_repo.create(annotation_project)

        # New project has no tasks yet
        empty_progress = AnnotationProgress(
            total_tasks=0,
            completed_tasks=0,
            in_progress_tasks=0,
            pending_tasks=0,
            review_pending_tasks=0,
        )

        return self._build_detail_response(created, empty_progress)

    async def get_detail(
        self,
        annotation_project_id: UUID,
    ) -> AnnotationProjectDetailResponse:
        """Get annotation project details with progress.

        Args:
            annotation_project_id: AnnotationProject's UUID

        Returns:
            Annotation project detail response

        Raises:
            HTTPException: 404 if annotation project not found
        """
        annotation_project = await self.annotation_project_repo.get_by_id(annotation_project_id)
        if not annotation_project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Annotation project not found",
            )

        counts = await self.annotation_task_repo.count_by_status(annotation_project_id)
        progress = self._build_progress(counts)

        return self._build_detail_response(annotation_project, progress)

    async def update(
        self,
        annotation_project_id: UUID,
        request: AnnotationProjectUpdate,
    ) -> AnnotationProjectDetailResponse:
        """Update an annotation project.

        Args:
            annotation_project_id: AnnotationProject's UUID
            request: Update data

        Returns:
            Updated annotation project detail response

        Raises:
            HTTPException: 404 if annotation project not found
        """
        from echoroo.models.dataset import Dataset
        from echoroo.models.tag import Tag
        from sqlalchemy import select

        annotation_project = await self.annotation_project_repo.get_by_id(annotation_project_id)
        if not annotation_project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Annotation project not found",
            )

        # Update scalar fields
        if request.name is not None:
            annotation_project.name = request.name
        if request.description is not None:
            annotation_project.description = request.description
        if request.instructions is not None:
            annotation_project.instructions = request.instructions
        if request.visibility is not None:
            annotation_project.visibility = request.visibility

        # Update dataset associations if provided
        if request.dataset_ids is not None:
            dataset_result = await self.annotation_project_repo.db.execute(
                select(Dataset).where(Dataset.id.in_(request.dataset_ids))
            )
            annotation_project.datasets = list(dataset_result.scalars().all())

        # Update tag associations if provided
        if request.tag_ids is not None:
            tag_result = await self.annotation_project_repo.db.execute(
                select(Tag).where(Tag.id.in_(request.tag_ids))
            )
            annotation_project.tags = list(tag_result.scalars().all())

        updated = await self.annotation_project_repo.update(annotation_project)

        counts = await self.annotation_task_repo.count_by_status(annotation_project_id)
        progress = self._build_progress(counts)

        return self._build_detail_response(updated, progress)

    async def delete(self, annotation_project_id: UUID) -> None:
        """Delete an annotation project.

        Args:
            annotation_project_id: AnnotationProject's UUID

        Raises:
            HTTPException: 404 if annotation project not found
        """
        annotation_project = await self.annotation_project_repo.get_by_id(annotation_project_id)
        if not annotation_project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Annotation project not found",
            )

        await self.annotation_project_repo.delete(annotation_project_id)

    async def generate_tasks(self, annotation_project_id: UUID) -> TaskGenerationResponse:
        """Generate annotation tasks for all clips in associated datasets.

        For each clip belonging to datasets linked to the annotation project,
        creates an AnnotationTask if one does not already exist for that
        clip and project combination.

        Args:
            annotation_project_id: AnnotationProject's UUID

        Returns:
            TaskGenerationResponse with a task ID and count of tasks created

        Raises:
            HTTPException: 404 if annotation project not found
        """
        annotation_project = await self.annotation_project_repo.get_by_id(annotation_project_id)
        if not annotation_project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Annotation project not found",
            )

        dataset_ids = [d.id for d in annotation_project.datasets]

        if not dataset_ids:
            return TaskGenerationResponse(
                task_id=str(uuid4()),
                message="Tasks generated: 0",
            )

        db = self.annotation_project_repo.db

        # Fetch all clip IDs that belong to recordings in the associated datasets
        clips_result = await db.execute(
            select(Clip.id)
            .join(Recording, Clip.recording_id == Recording.id)
            .where(Recording.dataset_id.in_(dataset_ids))
        )
        clip_ids = [row[0] for row in clips_result.all()]

        if not clip_ids:
            return TaskGenerationResponse(
                task_id=str(uuid4()),
                message="Tasks generated: 0",
            )

        # Fetch clip IDs that already have a task for this annotation project
        existing_result = await db.execute(
            select(AnnotationTask.clip_id).where(
                AnnotationTask.annotation_project_id == annotation_project_id
            )
        )
        existing_clip_ids = {row[0] for row in existing_result.all()}

        # Build new tasks only for clips without an existing task
        new_tasks = [
            AnnotationTask(
                annotation_project_id=annotation_project_id,
                clip_id=clip_id,
            )
            for clip_id in clip_ids
            if clip_id not in existing_clip_ids
        ]

        if new_tasks:
            await self.annotation_task_repo.create_batch(new_tasks)

        return TaskGenerationResponse(
            task_id=str(uuid4()),
            message=f"Tasks generated: {len(new_tasks)}",
        )
