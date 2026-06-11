"""Service layer for CustomModel lifecycle management."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.custom_model import CustomModel, CustomModelStatus
from echoroo.models.detection_run import DetectionRun
from echoroo.models.enums import DetectionRunStatus
from echoroo.models.sampling_round import SamplingRound
from echoroo.repositories.custom_model import CustomModelRepository
from echoroo.repositories.sampling_round import SamplingRoundRepository
from echoroo.schemas.custom_model import CustomModelCreate, CustomModelTrainRequest
from echoroo.schemas.sampling import SeedSamplingRequest

logger = logging.getLogger(__name__)

# Minimum number of confirmed and rejected annotations required (for the
# model's target tag) before an active-learning round can be dispatched.
# Kept intentionally below the 15/15 training threshold so users whose seed
# rounds are unbalanced can keep iterating via additional AL rounds. Must stay
# in sync with `MIN_LABELS_FOR_AL_ROUND` in the frontend components
# (ReviewTab.svelte, TrainingMeter.svelte).
_MIN_LABELS_FOR_AL_ROUND = 5


class CustomModelService:
    """Service for creating and managing CustomModel records.

    Encapsulates all business logic and database interactions related to
    custom ML classifier lifecycle: creation, update, deletion, training
    dispatch, and inference run creation.
    """

    def __init__(self, db: AsyncSession) -> None:
        """Initialize service with database session.

        Args:
            db: SQLAlchemy async session
        """
        self.db = db
        self._repo = CustomModelRepository(db)
        self._round_repo = SamplingRoundRepository(db)

    async def get_model(
        self,
        model_id: UUID,
        project_id: UUID,
    ) -> CustomModel | None:
        """Fetch a CustomModel by ID, scoped to the given project.

        Args:
            model_id: CustomModel's UUID
            project_id: Project's UUID (used for scoping)

        Returns:
            CustomModel instance or None if not found
        """
        return await self._repo.get_by_id_and_project(model_id, project_id)

    async def get_model_or_404(
        self,
        model_id: UUID,
        project_id: UUID,
    ) -> CustomModel:
        """Fetch a CustomModel by ID, scoped to the given project.

        Args:
            model_id: CustomModel's UUID
            project_id: Project's UUID (used for scoping)

        Returns:
            CustomModel instance

        Raises:
            HTTPException: 404 if model not found in project
        """
        model = await self.get_model(model_id, project_id)
        if model is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Custom model not found",
            )
        return model

    async def list_models(
        self,
        project_id: UUID,
        limit: int = 50,
        offset: int = 0,
        tag_id: UUID | None = None,
        search_session_id: UUID | None = None,
    ) -> tuple[list[CustomModel], int]:
        """List custom models for a project with optional filters.

        Args:
            project_id: Project's UUID
            limit: Maximum number of results to return
            offset: Number of results to skip
            tag_id: Optional target tag filter
            search_session_id: Optional filter by source search session

        Returns:
            Tuple of (models list, total count)
        """
        return await self._repo.list_for_project(
            project_id=project_id,
            limit=limit,
            offset=offset,
            tag_id=tag_id,
            search_session_id=search_session_id,
        )

    async def create_model(
        self,
        project_id: UUID,
        user_id: UUID,
        request: CustomModelCreate,
    ) -> CustomModel:
        """Create a new CustomModel in DRAFT status.

        If request.search_session_id is provided, the corresponding SearchSession
        is loaded to extract the dataset_id from its parameters JSONB field. Both
        search_session_id and dataset_id are then stored on the model for later use
        during seed sampling and inference scoping.

        Args:
            project_id: Project's UUID
            user_id: ID of the user creating the model
            request: Custom model creation data

        Returns:
            Created CustomModel instance

        Raises:
            HTTPException 404: If search_session_id is provided but session not found
        """
        model = CustomModel(
            project_id=project_id,
            user_id=user_id,
            name=request.name,
            description=request.description,
            target_tag_id=request.target_tag_id,
            embedding_model_name=request.embedding_model_name,
            status=CustomModelStatus.DRAFT,
        )

        if request.search_session_id is not None:
            # noqa: PLC0415 — lazy imports to avoid circular dependencies
            from fastapi import HTTPException  # noqa: PLC0415

            from echoroo.models.search_session import (  # noqa: PLC0415
                SearchSession,
            )

            session = await self.db.get(SearchSession, request.search_session_id)
            if session is None:
                raise HTTPException(status_code=404, detail="Search session not found")
            model.search_session_id = request.search_session_id
            if session.parameters and isinstance(session.parameters, dict):
                dataset_id_val = session.parameters.get("dataset_id")
                if dataset_id_val is not None:
                    from uuid import UUID as _UUID  # noqa: PLC0415

                    model.dataset_id = _UUID(str(dataset_id_val))

        return await self._repo.create(model)

    async def update_model(
        self,
        model: CustomModel,
        name: str | None = None,
        description: str | None = None,
    ) -> CustomModel:
        """Update mutable fields on a CustomModel.

        Only applies changes for fields that are explicitly provided (not None).

        Args:
            model: Existing CustomModel instance to update
            name: New name, or None to leave unchanged
            description: New description, or None to leave unchanged

        Returns:
            Updated and refreshed CustomModel instance
        """
        if name is not None:
            model.name = name
        if description is not None:
            model.description = description
        return await self._repo.update(model)

    async def delete_model(
        self,
        model: CustomModel,
    ) -> None:
        """Delete a CustomModel, also cleaning up its S3 artifact if present.

        Args:
            model: CustomModel instance to delete
        """
        if model.model_artifact_key:
            try:
                from echoroo.core.s3 import get_s3_client  # noqa: PLC0415
                from echoroo.core.settings import get_settings  # noqa: PLC0415

                settings = get_settings()
                s3 = get_s3_client()
                s3.delete_object(Bucket=settings.S3_BUCKET, Key=model.model_artifact_key)
            except Exception:
                logger.warning(
                    "Failed to delete S3 artifact for custom model %s (key=%s)",
                    model.id,
                    model.model_artifact_key,
                )
        await self._repo.remove(model)

    async def start_training(
        self,
        model: CustomModel,
        train_request: CustomModelTrainRequest | None = None,
    ) -> CustomModel:
        """Transition a CustomModel to TRAINING status and dispatch the Celery task.

        Flushes the status change to the database before dispatching so the
        worker sees the updated state immediately. Stores training parameters
        from train_request into model.training_config before dispatching.

        Args:
            model: CustomModel instance in DRAFT or FAILED status
            train_request: Optional training parameters (use_unlabeled, max_unlabeled_samples)

        Returns:
            Updated CustomModel with TRAINING status
        """
        model.status = CustomModelStatus.TRAINING
        model.error_message = None

        if train_request is not None:
            model.training_config = {
                "use_unlabeled": train_request.use_unlabeled,
                "max_unlabeled_samples": train_request.max_unlabeled_samples,
            }

        updated = await self._repo.update(model)

        # Lazy import to avoid circular dependency issues
        from echoroo.workers.classifier_tasks import (  # noqa: PLC0415
            train_custom_model as train_task,
        )

        train_task.delay(str(model.id))
        return updated

    async def create_seed_sampling_round(
        self,
        model: CustomModel,
        reference_embedding_ids: list[UUID],
        seed_sampling_request: SeedSamplingRequest | None = None,
    ) -> SamplingRound:
        """Create a pending SamplingRound and dispatch the seed sampling Celery task.

        Stores reference_embedding_ids and optional sampling config overrides in
        model.training_config before creating the round record and dispatching.
        Commits before dispatch so the worker can load the records immediately.

        Args:
            model: CustomModel instance in DRAFT or FAILED status
            reference_embedding_ids: UUIDs of the reference embeddings to use as
                query vectors for seed sampling
            seed_sampling_request: Optional config overrides for sampling parameters

        Returns:
            Newly created SamplingRound with status='pending'
        """
        # Store reference embedding IDs and sampling config in training_config
        updated_config: dict[str, Any] = dict(model.training_config or {})
        updated_config["reference_embedding_ids"] = [str(eid) for eid in reference_embedding_ids]
        if seed_sampling_request is not None:
            updated_config["sampling_config"] = {
                "easy_positive_k": seed_sampling_request.easy_positive_k,
                "boundary_n": seed_sampling_request.boundary_n,
                "boundary_m": seed_sampling_request.boundary_m,
                "others_p": seed_sampling_request.others_p,
            }
        model.training_config = updated_config
        await self._repo.update(model)

        # Delete any pre-existing seed round (round_number=0) so retries don't hit
        # the UNIQUE (custom_model_id, round_number) constraint.
        existing_seed = await self._round_repo.get_round_by_number(model.id, 0)
        if existing_seed is not None:
            await self.db.execute(
                text("DELETE FROM sampling_rounds WHERE id = :id"),
                {"id": str(existing_seed.id)},
            )
            await self.db.flush()

        # Create the pending SamplingRound record
        sampling_config_data: dict[str, Any] | None = updated_config.get("sampling_config")
        round_ = await self._round_repo.create_round(
            custom_model_id=model.id,
            round_number=0,
            round_type="seed",
            sampling_config=sampling_config_data,
        )

        # Commit before dispatching so the worker can read the new record
        await self.db.commit()
        await self.db.refresh(round_)

        # Lazy import to avoid circular dependency issues
        from echoroo.workers.classifier_tasks import (  # noqa: PLC0415
            generate_seed_samples as seed_task,
        )

        seed_task.delay(str(model.id), str(round_.id))

        return round_

    async def list_sampling_rounds(
        self,
        model: CustomModel,
    ) -> list[SamplingRound]:
        """List all sampling rounds for a model, ordered by round_number.

        Args:
            model: CustomModel instance

        Returns:
            List of SamplingRound instances (items not loaded)
        """
        return await self._round_repo.list_rounds(model.id)

    async def get_sampling_round(
        self,
        round_id: UUID,
        model: CustomModel,
    ) -> SamplingRound | None:
        """Fetch a single SamplingRound with items eagerly loaded.

        Verifies the round belongs to the given model for scoping.

        Args:
            round_id: SamplingRound UUID
            model: CustomModel the round must belong to

        Returns:
            SamplingRound with items loaded, or None if not found / wrong model
        """
        round_ = await self._round_repo.get_round_with_items(round_id)
        if round_ is None or round_.custom_model_id != model.id:
            return None
        return round_

    async def suggest_next_samples(
        self,
        model: CustomModel,
    ) -> SamplingRound:
        """Validate, create a pending AL round, and dispatch the run_al_iteration task.

        Requires at least one completed sampling round with sufficient labeled data
        (at least _MIN_LABELS_FOR_AL_ROUND positive + _MIN_LABELS_FOR_AL_ROUND
        negative confirmed/rejected annotations on the model's target tag) before
        dispatching the active learning Celery task. This threshold is decoupled
        from — and lower than — the 15/15 training threshold enforced later so
        that users with unbalanced seed rounds can keep iterating.

        Commits the round record before dispatching so the worker can load it immediately.

        Args:
            model: CustomModel instance to run active learning for

        Returns:
            Newly created SamplingRound with status='pending'

        Raises:
            ValueError: If there are no completed rounds or insufficient labeled samples
        """
        # Validate that at least one completed round exists
        existing_rounds = await self._round_repo.list_rounds(model.id)
        completed_rounds = [r for r in existing_rounds if r.status == "completed"]

        if not completed_rounds:
            raise ValueError(
                "No completed sampling rounds found. "
                "Complete at least one sampling round with labeled data before "
                "running active learning."
            )

        # Enforce the documented minimum label count. We count annotations that
        # are attached to sampling-round items of completed rounds for this
        # model, scoped to the model's target_tag_id (same scope used by
        # classifier_tasks._fetch_labeled_embeddings during training).
        count_sql = text("""
            SELECT
                COUNT(*) FILTER (WHERE a.status = 'confirmed') AS confirmed_count,
                COUNT(*) FILTER (WHERE a.status = 'rejected')  AS rejected_count
            FROM sampling_round_items sri
            JOIN sampling_rounds sr
                ON sr.id = sri.sampling_round_id
                AND sr.custom_model_id = :model_id
                AND sr.status = 'completed'
            JOIN recording_annotations a
                ON a.id = sri.annotation_id
                AND a.status IN ('confirmed', 'rejected')
                AND a.tag_id = :target_tag_id
        """)
        count_row = (
            await self.db.execute(
                count_sql,
                {
                    "model_id": str(model.id),
                    "target_tag_id": str(model.target_tag_id),
                },
            )
        ).one()
        confirmed_count = int(count_row.confirmed_count or 0)
        rejected_count = int(count_row.rejected_count or 0)

        if confirmed_count < _MIN_LABELS_FOR_AL_ROUND or rejected_count < _MIN_LABELS_FOR_AL_ROUND:
            raise ValueError(
                "Insufficient labeled data: need at least "
                f"{_MIN_LABELS_FOR_AL_ROUND} confirmed and "
                f"{_MIN_LABELS_FOR_AL_ROUND} rejected "
                f"(have {confirmed_count} confirmed, {rejected_count} rejected)."
            )

        next_round_number = max((r.round_number for r in existing_rounds), default=-1) + 1

        # Create the pending SamplingRound record
        round_ = await self._round_repo.create_round(
            custom_model_id=model.id,
            round_number=next_round_number,
            round_type="active_learning",
        )

        # Commit before dispatching so the worker can read the new record
        await self.db.commit()
        await self.db.refresh(round_)

        # Lazy import to avoid circular dependency issues
        from echoroo.workers.classifier_tasks import (  # noqa: PLC0415
            run_al_iteration as al_task,
        )

        al_task.delay(str(model.id), str(round_.id))

        return round_

    async def list_detection_runs(
        self,
        model: CustomModel,
        limit: int = 5,
    ) -> list[DetectionRun]:
        """List recent DetectionRuns created by applying a custom model.

        Detection runs created via `apply_custom_model` set `model_version` to
        the model's UUID (as string), so we filter on that column. Results are
        ordered most-recent-first.

        Args:
            model: CustomModel instance
            limit: Maximum number of runs to return

        Returns:
            List of DetectionRun instances for this model, newest first
        """
        from sqlalchemy import select as _select  # noqa: PLC0415
        from sqlalchemy.orm import selectinload as _selectinload  # noqa: PLC0415

        result = await self.db.execute(
            _select(DetectionRun)
            .where(DetectionRun.project_id == model.project_id)
            .where(DetectionRun.model_name == "custom_svm")
            .where(DetectionRun.model_version == str(model.id))
            .options(_selectinload(DetectionRun.dataset))
            .order_by(DetectionRun.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def create_detection_run(
        self,
        project_id: UUID,
        dataset_id: UUID,
        model: CustomModel,
        threshold: float,
    ) -> DetectionRun:
        """Create a DetectionRun record for a custom model inference job.

        Commits the record before returning so that the Celery worker can load
        it as soon as it starts.

        Args:
            project_id: Project's UUID
            dataset_id: Dataset to run inference on
            model: CustomModel to apply
            threshold: Confidence threshold for annotation creation

        Returns:
            Persisted DetectionRun with PENDING status
        """
        detection_run = DetectionRun(
            project_id=project_id,
            dataset_id=dataset_id,
            model_name="custom_svm",
            model_version=str(model.id),
            parameters={
                "custom_model_id": str(model.id),
                "threshold": threshold,
                "embedding_model_name": model.embedding_model_name,
            },
            status=DetectionRunStatus.PENDING,
            annotation_count=0,
        )
        self.db.add(detection_run)
        await self.db.flush()
        await self.db.refresh(detection_run)

        # Commit before dispatching the Celery task so the worker can load the run
        await self.db.commit()

        return detection_run
