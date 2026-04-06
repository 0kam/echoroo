"""DetectionRun service for business logic."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select

from echoroo.core.pagination import paginate
from echoroo.models.dataset import Dataset
from echoroo.models.detection_run import DetectionRun
from echoroo.models.enums import DetectionRunStatus
from echoroo.repositories.annotation import AnnotationRepository
from echoroo.repositories.detection_run import DetectionRunRepository
from echoroo.schemas.detection_run import (
    DetectionRunCreate,
    DetectionRunListResponse,
    DetectionRunResponse,
    DetectionRunUpdate,
)


class DetectionRunService:
    """Service for detection run management business logic."""

    def __init__(
        self,
        detection_run_repo: DetectionRunRepository,
        annotation_repo: AnnotationRepository | None = None,
    ) -> None:
        """Initialize service with repository.

        Args:
            detection_run_repo: DetectionRun repository instance
            annotation_repo: Optional Annotation repository instance (required for retry)
        """
        self.detection_run_repo = detection_run_repo
        self.annotation_repo = annotation_repo

    async def list_by_project(
        self,
        project_id: UUID,
        page: int = 1,
        page_size: int = 50,
        dataset_id: UUID | None = None,
    ) -> DetectionRunListResponse:
        """List detection runs for a project.

        Args:
            project_id: Project's UUID
            page: Page number (1-indexed)
            page_size: Items per page
            dataset_id: Optional filter by dataset UUID

        Returns:
            Paginated detection run list response
        """
        pagination = paginate(page, page_size)

        runs, total = await self.detection_run_repo.list_by_project(
            project_id=project_id,
            page=pagination.page,
            page_size=pagination.page_size,
            dataset_id=dataset_id,
        )

        return DetectionRunListResponse(
            items=[DetectionRunResponse.model_validate(r) for r in runs],
            total=total,
            page=pagination.page,
            page_size=pagination.page_size,
            pages=pagination.total_pages(total),
        )

    async def get(self, run_id: UUID, project_id: UUID | None = None) -> DetectionRunResponse:
        """Get a detection run by ID.

        Args:
            run_id: DetectionRun's UUID
            project_id: Optional project UUID for ownership verification

        Returns:
            Detection run response

        Raises:
            HTTPException: If run not found or project_id mismatch
        """
        run = await self.detection_run_repo.get_by_id(run_id)
        if not run:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Detection run not found",
            )
        if project_id is not None and run.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Detection run not found",
            )
        return DetectionRunResponse.model_validate(run)

    async def create(
        self,
        project_id: UUID,
        request: DetectionRunCreate,
    ) -> DetectionRunResponse:
        """Create a new detection run and queue the Celery detection task.

        Dispatches to `run_detection` for all supported models. The model_name
        is passed through to the Celery task so the worker can load the
        appropriate inference engine via ModelRegistry.

        Args:
            project_id: Project's UUID
            request: Detection run creation data

        Returns:
            Created detection run response
        """
        import logging

        from echoroo.workers.ml_tasks import run_detection

        logger = logging.getLogger(__name__)

        # Validate model_name against the registry before creating the DB record.
        # Import lazily inside the method because ml modules load heavy
        # model packages at import time.
        try:
            import echoroo.ml.birdnet  # noqa: F401
            import echoroo.ml.perch  # noqa: F401
            from echoroo.ml.registry import ModelRegistry

            if not ModelRegistry.is_registered(request.model_name):
                available = ModelRegistry.available_models()
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unknown model: '{request.model_name}'. Available: {available}",
                )
        except ImportError:
            # If ml packages are not installed (e.g. lightweight API container),
            # skip validation and let the Celery worker surface the error.
            logger.warning(
                "Could not import ML registry to validate model_name='%s'; "
                "skipping pre-flight check",
                request.model_name,
            )

        # Validate that the dataset belongs to the specified project before
        # creating the run, to prevent cross-project data processing.
        dataset_result = await self.detection_run_repo.db.execute(
            select(Dataset).where(
                Dataset.id == request.dataset_id,
                Dataset.project_id == project_id,
            )
        )
        if dataset_result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dataset not found",
            )

        # Merge embedding_only flag into parameters so retry() can reconstruct
        # the correct task type without requiring a schema change to DetectionRun.
        merged_parameters: dict[str, object] = dict(request.parameters or {})
        if request.embedding_only:
            merged_parameters["embedding_only"] = True

        run = DetectionRun(
            project_id=project_id,
            dataset_id=request.dataset_id,
            model_name=request.model_name,
            model_version=request.model_version,
            parameters=merged_parameters if merged_parameters else None,
            status=DetectionRunStatus.PENDING,
        )

        created = await self.detection_run_repo.create(run)

        # Commit before dispatching Celery task to avoid a race condition where
        # the worker starts before the DB transaction is visible to other connections.
        await self.detection_run_repo.db.commit()

        response = DetectionRunResponse.model_validate(created)

        # Queue the Celery task after the record is committed to the database.
        # If dispatch fails, mark the run as FAILED so it is not stuck in PENDING
        # with no task queued.
        try:
            if request.embedding_only:
                from echoroo.workers.ml_tasks import run_embedding_generation

                run_embedding_generation.delay(
                    str(created.dataset_id),
                    str(project_id),
                    str(created.id),
                    request.model_name,
                )
                logger.info(
                    "Queued %s embedding-only task for detection run %s (dataset %s)",
                    request.model_name,
                    created.id,
                    created.dataset_id,
                )
            else:
                run_detection.delay(
                    str(created.dataset_id),
                    str(project_id),
                    str(created.id),
                    request.model_name,
                )
                logger.info(
                    "Queued %s detection task for detection run %s (dataset %s)",
                    request.model_name,
                    created.id,
                    created.dataset_id,
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Failed to queue %s task for detection run %s",
                request.model_name,
                created.id,
            )
            run.status = DetectionRunStatus.FAILED
            run.error_message = f"Failed to queue detection task: {exc}"
            await self.detection_run_repo.update(run)
            await self.detection_run_repo.db.commit()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to queue detection task",
            ) from exc

        return response

    async def update(
        self,
        run_id: UUID,
        request: DetectionRunUpdate,
        project_id: UUID | None = None,
    ) -> DetectionRunResponse:
        """Update a detection run's status and metadata.

        Args:
            run_id: DetectionRun's UUID
            request: Update data
            project_id: Optional project UUID for ownership verification

        Returns:
            Updated detection run response

        Raises:
            HTTPException: If run not found or project_id mismatch
        """
        run = await self.detection_run_repo.get_by_id(run_id)
        if not run:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Detection run not found",
            )
        if project_id is not None and run.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Detection run not found",
            )

        if request.status is not None:
            run.status = request.status
            # Auto-set timestamps based on status transitions
            if request.status == DetectionRunStatus.RUNNING and run.started_at is None:
                run.started_at = datetime.now(UTC)
            elif request.status in (DetectionRunStatus.COMPLETED, DetectionRunStatus.FAILED):
                run.completed_at = datetime.now(UTC)

        if request.annotation_count is not None:
            run.annotation_count = request.annotation_count

        if request.error_message is not None:
            run.error_message = request.error_message

        updated = await self.detection_run_repo.update(run)
        return DetectionRunResponse.model_validate(updated)

    async def retry(self, project_id: UUID, run_id: UUID) -> DetectionRunResponse:
        """Retry a completed or failed detection run.

        Deletes all existing annotations and embeddings for the run, resets
        the run to PENDING, and re-queues the Celery detection task.

        Args:
            project_id: Project's UUID (used to validate ownership and queue task)
            run_id: DetectionRun's UUID

        Returns:
            Updated detection run response

        Raises:
            HTTPException: If run not found or status does not allow retry
        """
        import logging

        from echoroo.repositories.embedding import EmbeddingRepository
        from echoroo.workers.ml_tasks import run_detection

        logger = logging.getLogger(__name__)

        run = await self.detection_run_repo.get_by_id(run_id)
        if not run or run.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Detection run not found",
            )

        # Validate that the dataset still belongs to this project (defense-in-depth).
        dataset_result = await self.detection_run_repo.db.execute(
            select(Dataset).where(
                Dataset.id == run.dataset_id,
                Dataset.project_id == project_id,
            )
        )
        if dataset_result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dataset not found",
            )

        if run.status not in (DetectionRunStatus.COMPLETED, DetectionRunStatus.FAILED):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot retry a detection run with status '{run.status.value}'. "
                       "Only COMPLETED or FAILED runs can be retried.",
            )

        if self.annotation_repo is None:
            raise RuntimeError("AnnotationRepository is required for retry operation")

        # Delete all existing annotations for this run
        await self.annotation_repo.delete_by_detection_run(run_id)

        # Delete all existing embeddings for this run
        embedding_repo = EmbeddingRepository(self.detection_run_repo.db)
        await embedding_repo.delete_by_run(run_id)

        # Reset run fields
        run.status = DetectionRunStatus.PENDING
        run.annotation_count = 0
        run.error_message = None
        run.started_at = None
        run.completed_at = None

        updated = await self.detection_run_repo.update(run)

        # Commit before dispatching Celery task to avoid a race condition where
        # the worker starts before the DB transaction is visible to other connections.
        await self.detection_run_repo.db.commit()

        # Determine whether to dispatch an embedding-only or full detection task
        # based on the flag stored in the parameters dict at creation time.
        is_embedding_only = bool(
            run.parameters and run.parameters.get("embedding_only")
        )

        # Queue Celery task with the existing run_id and model_name.
        # If dispatch fails, mark the run as FAILED so it is not stuck in PENDING
        # with its data already deleted and no task queued.
        try:
            if is_embedding_only:
                from echoroo.workers.ml_tasks import run_embedding_generation

                run_embedding_generation.delay(
                    str(run.dataset_id),
                    str(project_id),
                    str(run_id),
                    run.model_name,
                )
                logger.info(
                    "Queued %s embedding-only task for retry of detection run %s (dataset %s)",
                    run.model_name,
                    run_id,
                    run.dataset_id,
                )
            else:
                run_detection.delay(
                    str(run.dataset_id),
                    str(project_id),
                    str(run_id),
                    run.model_name,
                )
                logger.info(
                    "Queued %s detection task for retry of detection run %s (dataset %s)",
                    run.model_name,
                    run_id,
                    run.dataset_id,
                )
        except Exception as exc:  # noqa: BLE001
            run.status = DetectionRunStatus.FAILED
            run.error_message = f"Failed to queue retry task: {exc}"
            await self.detection_run_repo.update(run)
            await self.detection_run_repo.db.commit()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to queue retry task",
            ) from exc

        return DetectionRunResponse.model_validate(updated)

    async def cancel(self, project_id: UUID, run_id: UUID) -> DetectionRunResponse:
        """Cancel a pending or running detection run.

        Sets the run status to FAILED with a cancellation message. The Celery
        worker checks for FAILED status before each recording and will stop
        processing when it detects the cancellation.

        Args:
            project_id: Project's UUID for ownership verification
            run_id: DetectionRun's UUID

        Returns:
            Updated detection run response

        Raises:
            HTTPException: If run not found, project_id mismatch, or status does not allow cancellation
        """
        run = await self.detection_run_repo.get_by_id(run_id)
        if not run or run.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Detection run not found",
            )

        if run.status not in (DetectionRunStatus.PENDING, DetectionRunStatus.RUNNING):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot cancel a detection run with status '{run.status.value}'. "
                       "Only PENDING or RUNNING runs can be cancelled.",
            )

        run.status = DetectionRunStatus.FAILED
        run.error_message = "Cancelled by user"

        updated = await self.detection_run_repo.update(run)
        return DetectionRunResponse.model_validate(updated)
