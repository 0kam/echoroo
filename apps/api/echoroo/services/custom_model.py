"""Service layer for CustomModel lifecycle management."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import text

from echoroo.models.custom_model import CustomModel, CustomModelStatus
from echoroo.models.detection_run import DetectionRun
from echoroo.models.enums import DetectionRunStatus
from echoroo.models.sampling_round import SamplingRound
from echoroo.repositories.custom_model import CustomModelRepository
from echoroo.repositories.sampling_round import SamplingRoundRepository
from echoroo.schemas.custom_model import CustomModelCreate, CustomModelTrainRequest
from echoroo.schemas.sampling import SeedSamplingRequest

logger = logging.getLogger(__name__)


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

    async def list_models(
        self,
        project_id: UUID,
        limit: int = 50,
        offset: int = 0,
        tag_id: UUID | None = None,
    ) -> tuple[list[CustomModel], int]:
        """List custom models for a project with optional filters.

        Args:
            project_id: Project's UUID
            limit: Maximum number of results to return
            offset: Number of results to skip
            tag_id: Optional target tag filter

        Returns:
            Tuple of (models list, total count)
        """
        return await self._repo.list_for_project(
            project_id=project_id,
            limit=limit,
            offset=offset,
            tag_id=tag_id,
        )

    async def create_model(
        self,
        project_id: UUID,
        user_id: UUID,
        request: CustomModelCreate,
    ) -> CustomModel:
        """Create a new CustomModel in DRAFT status.

        Args:
            project_id: Project's UUID
            user_id: ID of the user creating the model
            request: Custom model creation data

        Returns:
            Created CustomModel instance
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
        updated_config["reference_embedding_ids"] = [
            str(eid) for eid in reference_embedding_ids
        ]
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
        sampling_config_data: dict[str, Any] | None = updated_config.get(
            "sampling_config"
        )
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
        (at least 5 positive + 5 negative confirmed/rejected annotations) before
        dispatching the active learning Celery task.

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

    async def create_audit_set(
        self,
        model: CustomModel,
    ) -> None:
        """Dispatch the generate_audit_set Celery task for a trained model.

        The model must be in TRAINED status. The task itself handles the full
        lifecycle: loading the S3 artifact, scoring embeddings, sampling, and
        creating Annotation + AuditSetItem records.

        Args:
            model: CustomModel instance in TRAINED status

        Raises:
            ValueError: If model.status is not TRAINED
        """
        from echoroo.workers.classifier_tasks import (  # noqa: PLC0415
            generate_audit_set as audit_task,
        )

        audit_task.delay(str(model.id))

    async def get_audit_items(
        self,
        model_id: UUID,
    ) -> list[Any]:
        """List AuditSetItems with annotation status and embedding metadata.

        Returns items ordered by predicted_proba descending (highest confidence
        first) so reviewers see the most interesting examples at the top.

        Args:
            model_id: CustomModel UUID

        Returns:
            List of row objects with audit item fields, annotation review_status,
            start_time, and end_time.
        """
        from sqlalchemy import text  # noqa: PLC0415

        sql = text("""
            SELECT
                asi.id,
                asi.embedding_id,
                asi.recording_id,
                asi.predicted_proba,
                asi.annotation_id,
                asi.created_at,
                a.status AS review_status,
                e.start_time,
                e.end_time
            FROM audit_set_items asi
            JOIN annotations a ON a.id = asi.annotation_id
            JOIN embeddings e ON e.id = asi.embedding_id
            WHERE asi.custom_model_id = :model_id
            ORDER BY asi.predicted_proba DESC NULLS LAST
        """)

        result = await self.db.execute(sql, {"model_id": str(model_id)})
        return list(result.fetchall())

    async def evaluate_audit_set(
        self,
        model: CustomModel,
    ) -> dict[str, Any]:
        """Compute metrics from human-audited audit set labels and persist them.

        Collects all AuditSetItems for the model whose linked annotation has
        been reviewed (confirmed or rejected), calls evaluate_on_audit_set(),
        stores the result in model.audit_metrics, and returns the metrics dict.

        Args:
            model: CustomModel instance

        Returns:
            Computed audit metrics dict (accuracy, precision, recall, f1, etc.)

        Raises:
            ValueError: If fewer than 2 audited items are found (not computable)
        """
        from echoroo.ml.evaluation import evaluate_on_audit_set  # noqa: PLC0415

        rows = await self.get_audit_items(model.id)

        true_labels: list[int] = []
        predicted_probas: list[float] = []

        for row in rows:
            status_str = str(row.review_status)
            if status_str == "confirmed":
                true_labels.append(1)
            elif status_str == "rejected":
                true_labels.append(0)
            else:
                # Skip unreviewed items
                continue
            predicted_probas.append(float(row.predicted_proba) if row.predicted_proba is not None else 0.5)

        if len(true_labels) < 2:
            raise ValueError(
                f"Not enough reviewed audit items to compute metrics: "
                f"found {len(true_labels)} reviewed items (minimum 2 required)."
            )

        metrics = evaluate_on_audit_set(
            true_labels=true_labels,
            predicted_probas=predicted_probas,
        )

        # Override n_audited / n_total with the correct counts
        metrics["n_audited"] = len(true_labels)
        metrics["n_total"] = len(rows)

        # Persist metrics to the model record
        model.audit_metrics = metrics
        await self.db.commit()

        return metrics
