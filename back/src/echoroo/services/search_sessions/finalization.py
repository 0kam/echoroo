"""Search session finalization service for ML training."""

import datetime
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

import numpy as np
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo import exceptions, models, schemas
from echoroo.api import common
from echoroo.core.model_cache import get_model_cache
from echoroo.ml.active_learning import MIN_EMBEDDING_NORM
from echoroo.ml.classifiers import ClassifierType, UnifiedClassifier
from echoroo.ml.constants import MIN_NEGATIVE_SAMPLES, MIN_POSITIVE_SAMPLES
from echoroo.system.data import get_app_data_dir

if TYPE_CHECKING:
    pass

__all__ = ["SearchSessionFinalizationService"]

logger = logging.getLogger(__name__)


class SearchSessionFinalizationService:
    """Service for finalizing search sessions and training classifiers."""

    def __init__(self, session: AsyncSession):
        """Initialize the finalization service.

        Parameters
        ----------
        session
            SQLAlchemy AsyncSession for database operations.
        """
        self.session = session

    async def finalize(
        self,
        search_session: models.SearchSession,
        data: schemas.FinalizeRequest,
        user: models.User,
    ) -> schemas.FinalizeResponse:
        """Finalize search session and optionally train classifier.

        This method:
        1. Trains a UnifiedClassifier using all labeled data
        2. Saves the model to disk
        3. Creates a CustomModel record
        4. Optionally creates an AnnotationProject with labeled clips

        Parameters
        ----------
        search_session
            SearchSession model instance to finalize.
        data
            Finalization request with model name, type, and options.
        user
            User performing the finalization.

        Returns
        -------
        schemas.FinalizeResponse
            Finalization response with model details and sample counts.

        Raises
        ------
        exceptions.InvalidDataError
            If training data is insufficient, no target tags are found,
            or no labeled data exists.
        """
        # Get ML project
        ml_project = await self.session.get(
            models.MLProject,
            search_session.ml_project_id,
        )

        if ml_project is None:
            raise exceptions.NotFoundError("ML project not found")

        # Get all target tags
        await self.session.refresh(search_session, ["target_tags"])
        target_tag_ids = [tt.tag_id for tt in search_session.target_tags]
        if not target_tag_ids:
            raise exceptions.InvalidDataError(
                "No target tags found for this search session"
            )

        # For now, use the first target tag as the primary model target
        # Future enhancement: support multi-tag models
        primary_tag_id = target_tag_ids[0]

        # Get training data
        embeddings, labels, pos_count, neg_count = await self._get_training_data(
            search_session_id=search_session.id,
            ml_project_id=ml_project.id,
            primary_tag_id=primary_tag_id,
        )

        # Validate training data
        self._validate_training_data(pos_count, neg_count)

        # Train classifier (always use Self-Training+SVM)
        classifier = self._train_classifier(
            embeddings=embeddings,
            labels=labels,
        )

        # Save model
        custom_model = await self._save_model(
            search_session=search_session,
            ml_project=ml_project,
            classifier=classifier,
            model_name=data.model_name,
            description=data.description,
            primary_tag_id=primary_tag_id,
            positive_count=pos_count,
            negative_count=neg_count,
            user=user,
        )

        # Optionally create annotation project
        annotation_project_uuid: UUID | None = None
        annotation_project_name: str | None = None

        if data.create_annotation_project:
            annotation_project_uuid, annotation_project_name = (
                await self._create_annotation_project(
                    search_session=search_session,
                    ml_project=ml_project,
                    project_name=data.annotation_project_name or data.model_name,
                    description=data.description,
                    user=user,
                )
            )

        # Update ML Project status to INFERENCE after finalization
        await common.update_object(
            self.session,
            models.MLProject,
            models.MLProject.id == ml_project.id,
            status=models.MLProjectStatus.INFERENCE,
        )

        # Clean up all cached models for this session
        model_cache = get_model_cache(self.session)
        deleted_count = await model_cache.delete_all_models(search_session.uuid)
        logger.info(
            f"Deleted {deleted_count} cached models for session {search_session.uuid}"
        )

        logger.info(
            f"Search session {search_session.uuid} finalized: "
            f"model={custom_model.uuid}, positive={pos_count}, negative={neg_count}"
        )

        return schemas.FinalizeResponse(
            custom_model_uuid=custom_model.uuid,
            custom_model_name=custom_model.name,
            annotation_project_uuid=annotation_project_uuid,
            annotation_project_name=annotation_project_name,
            positive_count=pos_count,
            negative_count=neg_count,
            message=(
                f"Successfully trained Self-Training (SVM) model with "
                f"{pos_count} positive and {neg_count} negative samples."
            ),
        )

    async def _get_training_data(
        self,
        search_session_id: int,
        ml_project_id: int,
        primary_tag_id: int,
    ) -> tuple[np.ndarray, np.ndarray, int, int]:
        """Get training data from labeled search results.

        Parameters
        ----------
        search_session_id
            Search session database ID.
        ml_project_id
            ML project database ID.
        primary_tag_id
            Primary tag ID for this model.

        Returns
        -------
        tuple[np.ndarray, np.ndarray, int, int]
            Tuple of (embeddings, labels, positive_count, negative_count).

        Raises
        ------
        exceptions.InvalidDataError
            If no labeled data is found.
        """
        # Get labeled data from search session (same query as active_learning.py)
        labeled_query = """
            SELECT
                sr.id as search_result_id,
                sr.clip_id,
                sr.is_negative,
                ce.embedding,
                COALESCE(
                    array_agg(srt.tag_id) FILTER (WHERE srt.tag_id IS NOT NULL),
                    ARRAY[]::integer[]
                ) as assigned_tag_ids
            FROM search_result sr
            JOIN clip_embedding ce ON sr.clip_id = ce.clip_id
            LEFT JOIN search_result_tag srt ON sr.id = srt.search_result_id
            JOIN ml_project_dataset_scope mpds ON :ml_project_id = mpds.ml_project_id
            JOIN foundation_model_run fmr ON mpds.foundation_model_run_id = fmr.id
            WHERE sr.search_session_id = :search_session_id
              AND sr.is_uncertain = false
              AND sr.is_skipped = false
              AND fmr.model_run_id = ce.model_run_id
            GROUP BY sr.id, sr.clip_id, sr.is_negative, ce.embedding
            HAVING COUNT(srt.tag_id) > 0 OR sr.is_negative = true
        """

        result = await self.session.execute(
            text(labeled_query),
            {
                "search_session_id": search_session_id,
                "ml_project_id": ml_project_id,
            },
        )
        labeled_rows = result.fetchall()

        if not labeled_rows:
            raise exceptions.InvalidDataError(
                "No labeled data found. Label some results before finalizing."
            )

        # Collect training data for the primary tag
        embeddings_list: list[np.ndarray] = []
        labels_list: list[int] = []
        positive_count = 0
        negative_count = 0

        for row in labeled_rows:
            emb = row.embedding
            if isinstance(emb, str):
                emb = json.loads(emb)
            embedding = np.array(emb, dtype=np.float32)

            # Skip invalid embeddings
            if np.linalg.norm(embedding) < MIN_EMBEDDING_NORM:
                continue

            assigned_tag_ids_list = list(row.assigned_tag_ids) if row.assigned_tag_ids else []

            if primary_tag_id in assigned_tag_ids_list and not row.is_negative:
                # Positive sample for this tag
                embeddings_list.append(embedding)
                labels_list.append(1)
                positive_count += 1
            elif row.is_negative or (assigned_tag_ids_list and primary_tag_id not in assigned_tag_ids_list):
                # Negative sample: explicitly marked or assigned to other tag
                embeddings_list.append(embedding)
                labels_list.append(0)
                negative_count += 1

        if positive_count == 0:
            raise exceptions.InvalidDataError(
                f"No positive samples found for the target tag. "
                f"Please label some results with tag ID {primary_tag_id}."
            )

        if negative_count == 0:
            raise exceptions.InvalidDataError(
                "No negative samples found. Mark some results as negative (N key) "
                "or label with different tags."
            )

        embeddings_array = np.array(embeddings_list)
        labels_array = np.array(labels_list)

        return embeddings_array, labels_array, positive_count, negative_count

    def _validate_training_data(
        self,
        positive_count: int,
        negative_count: int,
    ) -> None:
        """Validate training data meets minimum requirements.

        Parameters
        ----------
        positive_count
            Number of positive samples.
        negative_count
            Number of negative samples.

        Raises
        ------
        exceptions.InvalidDataError
            If insufficient samples.
        """
        if positive_count < MIN_POSITIVE_SAMPLES:
            raise exceptions.InvalidDataError(
                f"Insufficient positive samples: {positive_count} < {MIN_POSITIVE_SAMPLES}"
            )

        if negative_count < MIN_NEGATIVE_SAMPLES:
            raise exceptions.InvalidDataError(
                f"Insufficient negative samples: {negative_count} < {MIN_NEGATIVE_SAMPLES}"
            )

    def _train_classifier(
        self,
        embeddings: np.ndarray,
        labels: np.ndarray,
    ) -> UnifiedClassifier:
        """Train a Self-Training+SVM classifier on the training data.

        Always uses Self-Training+SVM with automatic C parameter tuning.

        Parameters
        ----------
        embeddings
            Training embeddings array of shape (n_samples, embedding_dim).
        labels
            Training labels (0 or 1) of shape (n_samples,).

        Returns
        -------
        UnifiedClassifier
            Trained classifier instance.
        """
        logger.info(f"Training Self-Training+SVM classifier with {len(labels)} samples")

        classifier = UnifiedClassifier(ClassifierType.SELF_TRAINING_SVM)
        classifier.fit(embeddings, labels)

        logger.info("Self-Training+SVM classifier training complete")
        return classifier

    async def _save_model(
        self,
        search_session: models.SearchSession,
        ml_project: models.MLProject,
        classifier: UnifiedClassifier,
        model_name: str,
        description: str | None,
        primary_tag_id: int,
        positive_count: int,
        negative_count: int,
        user: models.User,
    ) -> models.CustomModel:
        """Save trained classifier to database and disk.

        Always saves as Self-Training+SVM model type.

        Parameters
        ----------
        search_session
            Source search session.
        ml_project
            ML project containing this session.
        classifier
            Trained classifier to save.
        model_name
            Name for the model.
        description
            Optional description.
        primary_tag_id
            Primary tag ID for this model.
        positive_count
            Number of positive training samples.
        negative_count
            Number of negative training samples.
        user
            User who trained the model.

        Returns
        -------
        models.CustomModel
            Saved CustomModel instance.
        """
        # Always use Self-Training+SVM model type
        db_model_type = models.CustomModelType.SELF_TRAINING_SVM

        # Create CustomModel record first to get UUID for file path
        custom_model = await common.create_object(
            self.session,
            models.CustomModel,
            name=model_name,
            description=description or None,
            target_tag_id=primary_tag_id,
            model_type=db_model_type,
            created_by_id=user.id,
            ml_project_id=ml_project.id,
            project_id=ml_project.project_id,
            source_search_session_id=search_session.id,
            status=models.CustomModelStatus.DEPLOYED,
            training_samples=positive_count + negative_count,
            training_started_on=datetime.datetime.now(datetime.UTC),
            training_completed_on=datetime.datetime.now(datetime.UTC),
        )

        # Save model to disk
        models_dir = get_app_data_dir() / "models"
        models_dir.mkdir(parents=True, exist_ok=True)
        model_path = models_dir / f"{custom_model.uuid}.joblib"
        classifier.save(model_path)

        # Update CustomModel with model path
        custom_model = await common.update_object(
            self.session,
            models.CustomModel,
            models.CustomModel.uuid == custom_model.uuid,
            None,
            model_path=str(model_path),
        )

        logger.info(f"Saved custom model {custom_model.uuid} to {model_path}")
        return custom_model

    async def _create_annotation_project(
        self,
        search_session: models.SearchSession,
        ml_project: models.MLProject,
        project_name: str,
        description: str | None,
        user: models.User,
    ) -> tuple[UUID, str]:
        """Create annotation project from search results.

        Parameters
        ----------
        search_session
            Search session to export.
        ml_project
            ML project containing this session.
        project_name
            Name for the annotation project.
        description
            Optional description.
        user
            User creating the annotation project.

        Returns
        -------
        tuple[UUID, str]
            Tuple of (annotation_project_uuid, annotation_project_name).
        """
        from echoroo.api.search_sessions import search_sessions

        # Build search session schema for the export method
        search_session_schema = await search_sessions._build_schema(
            self.session,
            search_session,
        )

        # Use existing export logic
        ap_description = description or f"Exported from search session: {search_session.name}"

        try:
            export_response = await search_sessions.export_to_annotation_project(
                session=self.session,
                search_session=search_session_schema,
                name=project_name,
                description=ap_description,
                include_labeled=True,
                include_tag_ids=None,
                user=user,
            )

            return export_response.annotation_project_uuid, export_response.annotation_project_name
        except exceptions.InvalidDataError as e:
            # Log but don't fail if export fails
            logger.warning(
                f"Failed to create annotation project during finalize: {e}"
            )
            # Re-raise to let caller handle
            raise
