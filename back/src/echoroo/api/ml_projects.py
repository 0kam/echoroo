"""Python API for ML Projects."""

from typing import Sequence
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import ColumnElement, ColumnExpressionArgument

from echoroo import exceptions, models, schemas
from echoroo.api import common
from echoroo.api.common import BaseAPI
from echoroo.api.common.permissions import can_manage_project
from echoroo.filters.base import Filter

__all__ = [
    "MLProjectAPI",
    "ml_projects",
    "dataset_scope_to_schema",
]


async def _get_project_membership(
    session: AsyncSession,
    project_id: str,
    user: models.User | None,
) -> models.ProjectMember | None:
    """Get user's membership in a project."""
    if user is None:
        return None

    return await session.scalar(
        select(models.ProjectMember).where(
            models.ProjectMember.project_id == project_id,
            models.ProjectMember.user_id == user.id,
        )
    )


async def can_view_ml_project(
    session: AsyncSession,
    ml_project: models.MLProject | schemas.MLProject,
    user: models.User | None,
) -> bool:
    """Return True if the user can view the ML project."""
    if user is None:
        return False

    if user.is_superuser:
        return True

    project_id = ml_project.project_id
    if hasattr(ml_project, "created_by_id") and ml_project.created_by_id == user.id:
        return True

    membership = await _get_project_membership(session, project_id, user)
    return membership is not None


async def can_edit_ml_project(
    session: AsyncSession,
    ml_project: models.MLProject | schemas.MLProject,
    user: models.User | None,
) -> bool:
    """Return True if the user can edit the ML project."""
    if user is None:
        return False

    if user.is_superuser:
        return True

    if hasattr(ml_project, "created_by_id") and ml_project.created_by_id == user.id:
        return True

    return await can_manage_project(session, ml_project.project_id, user)


async def can_delete_ml_project(
    session: AsyncSession,
    ml_project: models.MLProject | schemas.MLProject,
    user: models.User | None,
) -> bool:
    """Return True if the user can delete the ML project."""
    if user is None:
        return False

    if user.is_superuser:
        return True

    if hasattr(ml_project, "created_by_id") and ml_project.created_by_id == user.id:
        return True

    return await can_manage_project(session, ml_project.project_id, user)


async def filter_ml_projects_by_access(
    session: AsyncSession,
    user: models.User | None,
) -> list[ColumnElement[bool]]:
    """Return filter conditions limiting ML projects accessible to the user."""
    if user is None:
        return [models.MLProject.id == -1]  # No access for anonymous users

    if user.is_superuser:
        return []

    # Get project IDs user has membership in
    project_ids = (
        await session.scalars(
            select(models.ProjectMember.project_id).where(
                models.ProjectMember.user_id == user.id
            )
        )
    ).all()

    conditions: list[ColumnElement[bool]] = [
        models.MLProject.created_by_id == user.id,
    ]

    if project_ids:
        conditions.append(models.MLProject.project_id.in_(project_ids))

    return [or_(*conditions)]


class MLProjectAPI(
    BaseAPI[
        UUID,
        models.MLProject,
        schemas.MLProject,
        schemas.MLProjectCreate,
        schemas.MLProjectUpdate,
    ]
):
    """API for managing ML Projects."""

    _model = models.MLProject
    _schema = schemas.MLProject

    async def _resolve_user(
        self,
        session: AsyncSession,
        user: models.User | schemas.SimpleUser | None,
    ) -> models.User | None:
        """Resolve a user schema to a user model."""
        if user is None:
            return None
        if isinstance(user, models.User):
            return user
        db_user = await session.get(models.User, user.id)
        if db_user is None:
            raise exceptions.NotFoundError(f"User with id {user.id} not found")
        return db_user

    async def _eager_load_relationships(
        self,
        session: AsyncSession,
        db_obj: models.MLProject,
    ) -> models.MLProject:
        """Eagerly load relationships needed for MLProject schema validation."""
        stmt = (
            select(self._model)
            .where(self._model.uuid == db_obj.uuid)
            .options(
                selectinload(self._model.dataset).options(
                    selectinload(models.Dataset.project).options(
                        selectinload(models.Project.memberships)
                    ),
                    selectinload(models.Dataset.primary_site).options(
                        selectinload(models.Site.images)
                    ),
                    selectinload(models.Dataset.primary_recorder),
                    selectinload(models.Dataset.license),
                ),
                selectinload(self._model.embedding_model_run),
                selectinload(self._model.foundation_model),
                selectinload(self._model.tags),
                selectinload(self._model.created_by),
            )
        )
        result = await session.execute(stmt)
        return result.scalar_one()

    async def _build_schema(
        self,
        session: AsyncSession,
        db_obj: models.MLProject,
    ) -> schemas.MLProject:
        """Build schema with computed counts."""
        db_obj = await self._eager_load_relationships(session, db_obj)

        # Get counts
        dataset_scope_count = await session.scalar(
            select(func.count(models.MLProjectDatasetScope.id)).where(
                models.MLProjectDatasetScope.ml_project_id == db_obj.id
            )
        )
        ref_sound_count = await session.scalar(
            select(func.count(models.ReferenceSound.id)).where(
                models.ReferenceSound.ml_project_id == db_obj.id
            )
        )
        search_session_count = await session.scalar(
            select(func.count(models.SearchSession.id)).where(
                models.SearchSession.ml_project_id == db_obj.id
            )
        )
        custom_model_count = await session.scalar(
            select(func.count(models.CustomModel.id)).where(
                models.CustomModel.ml_project_id == db_obj.id
            )
        )
        inference_batch_count = await session.scalar(
            select(func.count(models.InferenceBatch.id)).where(
                models.InferenceBatch.ml_project_id == db_obj.id
            )
        )

        # Map model status to schema status
        status_map = {
            models.MLProjectStatus.SETUP: schemas.MLProjectStatus.DRAFT,
            models.MLProjectStatus.SEARCHING: schemas.MLProjectStatus.ACTIVE,
            models.MLProjectStatus.LABELING: schemas.MLProjectStatus.ACTIVE,
            models.MLProjectStatus.TRAINING: schemas.MLProjectStatus.TRAINING,
            models.MLProjectStatus.INFERENCE: schemas.MLProjectStatus.INFERENCE,
            models.MLProjectStatus.REVIEW: schemas.MLProjectStatus.ACTIVE,
            models.MLProjectStatus.COMPLETED: schemas.MLProjectStatus.COMPLETED,
            models.MLProjectStatus.ARCHIVED: schemas.MLProjectStatus.ARCHIVED,
        }
        schema_status = status_map.get(db_obj.status, schemas.MLProjectStatus.DRAFT)

        # Build base schema
        base_data = {
            "uuid": db_obj.uuid,
            "id": db_obj.id,
            "name": db_obj.name,
            "description": db_obj.description,
            "status": schema_status,
            "project_id": db_obj.project_id,
            "dataset_id": db_obj.dataset_id,
            "dataset": (
                schemas.Dataset.model_validate(db_obj.dataset)
                if db_obj.dataset
                else None
            ),
            "foundation_model_id": db_obj.foundation_model_id,
            "foundation_model": (
                schemas.FoundationModel.model_validate(db_obj.foundation_model)
                if db_obj.foundation_model
                else None
            ),
            "embedding_model_run_id": db_obj.embedding_model_run_id,
            "embedding_model_run": (
                schemas.ModelRun.model_validate(db_obj.embedding_model_run)
                if db_obj.embedding_model_run
                else None
            ),
            "default_similarity_threshold": db_obj.default_similarity_threshold,
            "created_by_id": db_obj.created_by_id,
            "target_tags": [schemas.Tag.model_validate(t) for t in db_obj.tags],
            "dataset_scope_count": dataset_scope_count or 0,
            "reference_sound_count": ref_sound_count or 0,
            "search_session_count": search_session_count or 0,
            "custom_model_count": custom_model_count or 0,
            "inference_batch_count": inference_batch_count or 0,
            "created_on": db_obj.created_on,
        }

        return schemas.MLProject.model_validate(base_data)

    async def get(
        self,
        session: AsyncSession,
        pk: UUID,
        user: models.User | None = None,
    ) -> schemas.MLProject:
        """Get an ML project by UUID."""
        db_user = await self._resolve_user(session, user)

        db_obj = await common.get_object(
            session,
            self._model,
            self._get_pk_condition(pk),
        )

        if not await can_view_ml_project(session, db_obj, db_user):
            raise exceptions.NotFoundError(
                f"ML Project with uuid {pk} not found"
            )

        return await self._build_schema(session, db_obj)

    async def get_many(
        self,
        session: AsyncSession,
        *,
        limit: int | None = 1000,
        offset: int | None = 0,
        filters: Sequence[Filter | ColumnExpressionArgument] | None = None,
        sort_by: ColumnExpressionArgument | str | None = "-created_on",
        user: models.User | None = None,
    ) -> tuple[Sequence[schemas.MLProject], int]:
        """Get multiple ML projects with access control."""
        db_user = await self._resolve_user(session, user)
        access_filters = await filter_ml_projects_by_access(session, db_user)

        combined_filters: list[Filter | ColumnExpressionArgument] = []
        if filters:
            combined_filters.extend(filters)
        combined_filters.extend(access_filters)

        db_objs, count = await common.get_objects(
            session,
            self._model,
            limit=limit,
            offset=offset,
            filters=combined_filters or None,
            sort_by=sort_by,
        )

        projects = []
        for db_obj in db_objs:
            schema_obj = await self._build_schema(session, db_obj)
            projects.append(schema_obj)

        return projects, count

    async def create(
        self,
        session: AsyncSession,
        data: schemas.MLProjectCreate,
        *,
        user: models.User | schemas.SimpleUser,
    ) -> schemas.MLProject:
        """Create a new ML project.

        ML Projects are created without a dataset. Datasets are added
        later via the dataset_scopes relationship in the Datasets tab.
        """
        db_user = await self._resolve_user(session, user)
        if db_user is None:
            raise exceptions.PermissionDeniedError(
                "Authentication required to create ML projects"
            )

        # Get the user's first project where they are a manager
        project_membership = await session.scalar(
            select(models.ProjectMember).where(
                models.ProjectMember.user_id == db_user.id,
                models.ProjectMember.role == models.ProjectMemberRole.MANAGER,
            )
        )

        if project_membership is None:
            # Create a default project for the user
            project_id = f"user_{db_user.id}"
            existing_project = await session.scalar(
                select(models.Project).where(
                    models.Project.project_id == project_id
                )
            )
            if existing_project is None:
                new_project = models.Project(
                    project_id=project_id,
                    project_name=f"{db_user.username}'s Project",
                )
                session.add(new_project)
                # Add user as manager
                membership = models.ProjectMember(
                    project_id=project_id,
                    user_id=db_user.id,
                    role=models.ProjectMemberRole.MANAGER,
                )
                session.add(membership)
                await session.flush()
        else:
            project_id = project_membership.project_id

        # Create the ML project
        db_obj = await common.create_object(
            session,
            self._model,
            name=data.name,
            description=data.description,
            dataset_id=None,
            project_id=project_id,
            created_by_id=db_user.id,
        )

        return await self._build_schema(session, db_obj)

    async def update(
        self,
        session: AsyncSession,
        obj: schemas.MLProject,
        data: schemas.MLProjectUpdate,
        *,
        user: models.User | schemas.SimpleUser | None = None,
    ) -> schemas.MLProject:
        """Update an ML project."""
        db_user = await self._resolve_user(session, user)

        if not await can_edit_ml_project(session, obj, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to update this ML project"
            )

        # Build update data
        update_data = {}
        if data.name is not None:
            update_data["name"] = data.name
        if data.description is not None:
            update_data["description"] = data.description
        if data.status is not None:
            # Map schema status to model status
            reverse_status_map = {
                schemas.MLProjectStatus.DRAFT: models.MLProjectStatus.SETUP,
                schemas.MLProjectStatus.ACTIVE: models.MLProjectStatus.LABELING,
                schemas.MLProjectStatus.TRAINING: models.MLProjectStatus.TRAINING,
                schemas.MLProjectStatus.INFERENCE: models.MLProjectStatus.INFERENCE,
                schemas.MLProjectStatus.COMPLETED: models.MLProjectStatus.COMPLETED,
                schemas.MLProjectStatus.ARCHIVED: models.MLProjectStatus.ARCHIVED,
            }
            update_data["status"] = reverse_status_map.get(
                data.status, models.MLProjectStatus.SETUP
            )
        if data.embedding_model_run_id is not None:
            update_data["embedding_model_run_id"] = data.embedding_model_run_id
        if data.default_similarity_threshold is not None:
            update_data["default_similarity_threshold"] = (
                data.default_similarity_threshold
            )

        if update_data:
            db_obj = await common.update_object(
                session,
                self._model,
                self._get_pk_condition(obj.uuid),
                update_data,
            )
        else:
            db_obj = await common.get_object(
                session,
                self._model,
                self._get_pk_condition(obj.uuid),
            )

        return await self._build_schema(session, db_obj)

    async def delete(
        self,
        session: AsyncSession,
        obj: schemas.MLProject,
        *,
        user: models.User | schemas.SimpleUser | None = None,
    ) -> schemas.MLProject:
        """Delete an ML project."""
        db_user = await self._resolve_user(session, user)

        if not await can_delete_ml_project(session, obj, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to delete this ML project"
            )

        # Get the object for return before deletion
        db_obj = await common.get_object(
            session,
            self._model,
            self._get_pk_condition(obj.uuid),
        )
        result = await self._build_schema(session, db_obj)

        # Delete
        await common.delete_object(
            session,
            self._model,
            self._get_pk_condition(obj.uuid),
        )

        return result

    async def add_target_tag(
        self,
        session: AsyncSession,
        obj: schemas.MLProject,
        tag_id: int,
        *,
        user: models.User | schemas.SimpleUser | None = None,
    ) -> schemas.MLProject:
        """Add a target tag to the ML project."""
        db_user = await self._resolve_user(session, user)

        if not await can_edit_ml_project(session, obj, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to modify this ML project"
            )

        # Check if tag exists
        tag = await session.get(models.Tag, tag_id)
        if tag is None:
            raise exceptions.NotFoundError(f"Tag with id {tag_id} not found")

        # Check if already associated
        for t in obj.target_tags:
            if t.id == tag_id:
                raise exceptions.DuplicateObjectError(
                    f"Tag {tag_id} is already associated with ML project {obj.id}"
                )

        # Create association
        await common.create_object(
            session,
            models.MLProjectTag,
            ml_project_id=obj.id,
            tag_id=tag_id,
        )

        # Return updated project
        db_obj = await common.get_object(
            session,
            self._model,
            self._get_pk_condition(obj.uuid),
        )
        return await self._build_schema(session, db_obj)

    async def remove_target_tag(
        self,
        session: AsyncSession,
        obj: schemas.MLProject,
        tag_id: int,
        *,
        user: models.User | schemas.SimpleUser | None = None,
    ) -> schemas.MLProject:
        """Remove a target tag from the ML project."""
        db_user = await self._resolve_user(session, user)

        if not await can_edit_ml_project(session, obj, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to modify this ML project"
            )

        # Check if tag is associated
        found = False
        for t in obj.target_tags:
            if t.id == tag_id:
                found = True
                break

        if not found:
            raise exceptions.NotFoundError(
                f"Tag {tag_id} is not associated with ML project {obj.id}"
            )

        # Delete association
        await common.delete_object(
            session,
            models.MLProjectTag,
            and_(
                models.MLProjectTag.ml_project_id == obj.id,
                models.MLProjectTag.tag_id == tag_id,
            ),
        )

        # Return updated project
        db_obj = await common.get_object(
            session,
            self._model,
            self._get_pk_condition(obj.uuid),
        )
        return await self._build_schema(session, db_obj)

    async def get_stats(
        self,
        session: AsyncSession,
        obj: schemas.MLProject,
        user: models.User | None = None,
    ) -> schemas.MLProjectStats:
        """Get aggregate statistics for an ML project."""
        db_user = await self._resolve_user(session, user)

        if not await can_view_ml_project(session, obj, db_user):
            raise exceptions.NotFoundError(
                f"ML Project with uuid {obj.uuid} not found"
            )

        # Total reference sounds
        total_ref_sounds = await session.scalar(
            select(func.count(models.ReferenceSound.id)).where(
                models.ReferenceSound.ml_project_id == obj.id
            )
        )

        # Reference sounds by tag
        ref_by_tag_query = (
            select(
                models.Tag.key,
                models.Tag.value,
                func.count(models.ReferenceSound.id),
            )
            .join(models.ReferenceSound.tag)
            .where(models.ReferenceSound.ml_project_id == obj.id)
            .group_by(models.Tag.key, models.Tag.value)
        )
        ref_by_tag_results = await session.execute(ref_by_tag_query)
        ref_sounds_by_tag = {
            f"{row[0]}:{row[1]}": row[2] for row in ref_by_tag_results.all()
        }

        # Search sessions and labeled results
        total_search_sessions = await session.scalar(
            select(func.count(models.SearchSession.id)).where(
                models.SearchSession.ml_project_id == obj.id
            )
        )

        # Get search session IDs for this project
        session_ids_query = select(models.SearchSession.id).where(
            models.SearchSession.ml_project_id == obj.id
        )
        session_ids = (await session.scalars(session_ids_query)).all()

        total_labeled = 0
        positive_labels = 0
        negative_labels = 0

        if session_ids:
            # Total labeled results
            labeled_query = (
                select(func.count(models.SearchResult.id))
                .where(models.SearchResult.search_session_id.in_(session_ids))
                .where(
                    models.SearchResult.label
                    != models.SearchResultLabel.UNLABELED
                )
            )
            total_labeled = (await session.scalar(labeled_query)) or 0

            # Positive labels
            pos_query = (
                select(func.count(models.SearchResult.id))
                .where(models.SearchResult.search_session_id.in_(session_ids))
                .where(
                    models.SearchResult.label == models.SearchResultLabel.POSITIVE
                )
            )
            positive_labels = (await session.scalar(pos_query)) or 0

            # Negative labels
            neg_query = (
                select(func.count(models.SearchResult.id))
                .where(models.SearchResult.search_session_id.in_(session_ids))
                .where(
                    models.SearchResult.label == models.SearchResultLabel.NEGATIVE
                )
            )
            negative_labels = (await session.scalar(neg_query)) or 0

        # Custom models
        total_custom_models = await session.scalar(
            select(func.count(models.CustomModel.id)).where(
                models.CustomModel.ml_project_id == obj.id
            )
        )

        # Best F1 score
        best_f1_query = (
            select(func.max(models.CustomModel.f1_score))
            .where(models.CustomModel.ml_project_id == obj.id)
            .where(models.CustomModel.f1_score.isnot(None))
        )
        best_f1 = await session.scalar(best_f1_query)

        # Inference batches and predictions
        total_inference_batches = await session.scalar(
            select(func.count(models.InferenceBatch.id)).where(
                models.InferenceBatch.ml_project_id == obj.id
            )
        )

        batch_ids_query = select(models.InferenceBatch.id).where(
            models.InferenceBatch.ml_project_id == obj.id
        )
        batch_ids = (await session.scalars(batch_ids_query)).all()

        total_predictions = 0
        reviewed_predictions = 0

        if batch_ids:
            total_predictions = (
                await session.scalar(
                    select(func.count(models.InferencePrediction.id)).where(
                        models.InferencePrediction.inference_batch_id.in_(batch_ids)
                    )
                )
            ) or 0

            reviewed_predictions = (
                await session.scalar(
                    select(func.count(models.InferencePrediction.id))
                    .where(
                        models.InferencePrediction.inference_batch_id.in_(batch_ids)
                    )
                    .where(
                        models.InferencePrediction.review_status
                        != models.InferencePredictionReviewStatus.UNREVIEWED
                    )
                )
            ) or 0

        # Last activity - get most recent updated_on from the ML project
        db_obj = await common.get_object(
            session,
            self._model,
            self._get_pk_condition(obj.uuid),
        )
        last_activity = db_obj.updated_on or db_obj.created_on

        return schemas.MLProjectStats(
            total_reference_sounds=total_ref_sounds or 0,
            reference_sounds_by_tag=ref_sounds_by_tag,
            total_search_sessions=total_search_sessions or 0,
            total_labeled_results=total_labeled,
            positive_labels=positive_labels,
            negative_labels=negative_labels,
            total_custom_models=total_custom_models or 0,
            best_model_f1=best_f1,
            total_inference_batches=total_inference_batches or 0,
            total_predictions=total_predictions,
            reviewed_predictions=reviewed_predictions,
            last_activity=last_activity,
        )

    # =========================================================================
    # Dataset Scope Methods
    # =========================================================================

    async def add_dataset_scope(
        self,
        session: AsyncSession,
        ml_project: schemas.MLProject,
        dataset: schemas.Dataset,
        foundation_model_run: schemas.FoundationModelRun,
        *,
        user: models.User | schemas.SimpleUser | None = None,
    ) -> schemas.MLProjectDatasetScope:
        """Add a dataset scope to an ML project.

        Args:
            session: Database session.
            ml_project: The ML project to add the scope to.
            dataset: The dataset to add.
            foundation_model_run: The foundation model run providing embeddings.
            user: The user performing the action.

        Returns:
            The created dataset scope.

        Raises:
            PermissionDeniedError: If the user cannot edit the project.
            DuplicateObjectError: If the dataset is already in the project.
        """
        db_user = await self._resolve_user(session, user)

        if not await can_edit_ml_project(session, ml_project, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to modify this ML project"
            )

        # Check if dataset scope already exists
        existing = await session.scalar(
            select(models.MLProjectDatasetScope).where(
                and_(
                    models.MLProjectDatasetScope.ml_project_id == ml_project.id,
                    models.MLProjectDatasetScope.dataset_id == dataset.id,
                )
            )
        )
        if existing:
            raise exceptions.DuplicateObjectError(
                f"Dataset {dataset.uuid} is already in ML project {ml_project.uuid}"
            )

        # Create the dataset scope
        db_scope = await common.create_object(
            session,
            models.MLProjectDatasetScope,
            ml_project_id=ml_project.id,
            dataset_id=dataset.id,
            foundation_model_run_id=foundation_model_run.id,
        )

        # Reload with all necessary relationships for serialization
        db_scope = await session.scalar(
            select(models.MLProjectDatasetScope)
            .where(models.MLProjectDatasetScope.id == db_scope.id)
            .options(
                selectinload(models.MLProjectDatasetScope.dataset).options(
                    selectinload(models.Dataset.project).options(
                        selectinload(models.Project.memberships)
                    ),
                    selectinload(models.Dataset.primary_site).options(
                        selectinload(models.Site.images)
                    ),
                    selectinload(models.Dataset.primary_recorder),
                    selectinload(models.Dataset.license),
                ),
                selectinload(models.MLProjectDatasetScope.foundation_model_run).options(
                    selectinload(models.FoundationModelRun.foundation_model),
                    selectinload(models.FoundationModelRun.dataset),
                    selectinload(models.FoundationModelRun.species),
                ),
            )
        )

        return await dataset_scope_to_schema(session, db_scope)

    async def remove_dataset_scope(
        self,
        session: AsyncSession,
        ml_project: schemas.MLProject,
        scope_uuid: UUID,
        *,
        user: models.User | schemas.SimpleUser | None = None,
    ) -> schemas.MLProjectDatasetScope:
        """Remove a dataset scope from an ML project.

        Args:
            session: Database session.
            ml_project: The ML project to remove the scope from.
            scope_uuid: UUID of the scope to remove.
            user: The user performing the action.

        Returns:
            The removed dataset scope.

        Raises:
            PermissionDeniedError: If the user cannot edit the project.
            NotFoundError: If the scope is not found.
        """
        db_user = await self._resolve_user(session, user)

        if not await can_edit_ml_project(session, ml_project, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to modify this ML project"
            )

        # Get the scope
        db_scope = await session.scalar(
            select(models.MLProjectDatasetScope)
            .where(
                and_(
                    models.MLProjectDatasetScope.ml_project_id == ml_project.id,
                    models.MLProjectDatasetScope.uuid == scope_uuid,
                )
            )
            .options(
                selectinload(models.MLProjectDatasetScope.dataset).options(
                    selectinload(models.Dataset.project).options(
                        selectinload(models.Project.memberships)
                    ),
                    selectinload(models.Dataset.primary_site).options(
                        selectinload(models.Site.images)
                    ),
                    selectinload(models.Dataset.primary_recorder),
                    selectinload(models.Dataset.license),
                ),
                selectinload(models.MLProjectDatasetScope.foundation_model_run).options(
                    selectinload(models.FoundationModelRun.foundation_model),
                    selectinload(models.FoundationModelRun.dataset),
                    selectinload(models.FoundationModelRun.species),
                ),
            )
        )
        if db_scope is None:
            raise exceptions.NotFoundError(
                f"Dataset scope with uuid {scope_uuid} not found in ML project"
            )

        # Build schema before deletion
        result = await dataset_scope_to_schema(session, db_scope)

        # Delete the scope
        await session.delete(db_scope)

        return result

    async def get_dataset_scopes(
        self,
        session: AsyncSession,
        ml_project: schemas.MLProject,
        *,
        user: models.User | schemas.SimpleUser | None = None,
    ) -> list[schemas.MLProjectDatasetScope]:
        """Get all dataset scopes for an ML project.

        Args:
            session: Database session.
            ml_project: The ML project to get scopes for.
            user: The user performing the action.

        Returns:
            List of dataset scopes.

        Raises:
            NotFoundError: If the project is not accessible.
        """
        db_user = await self._resolve_user(session, user)

        if not await can_view_ml_project(session, ml_project, db_user):
            raise exceptions.NotFoundError(
                f"ML Project with uuid {ml_project.uuid} not found"
            )

        # Get all scopes
        stmt = (
            select(models.MLProjectDatasetScope)
            .where(models.MLProjectDatasetScope.ml_project_id == ml_project.id)
            .options(
                selectinload(models.MLProjectDatasetScope.dataset).options(
                    selectinload(models.Dataset.project).options(
                        selectinload(models.Project.memberships)
                    ),
                    selectinload(models.Dataset.primary_site).options(
                        selectinload(models.Site.images)
                    ),
                    selectinload(models.Dataset.primary_recorder),
                    selectinload(models.Dataset.license),
                ),
                selectinload(models.MLProjectDatasetScope.foundation_model_run).options(
                    selectinload(models.FoundationModelRun.foundation_model),
                    selectinload(models.FoundationModelRun.dataset),
                    selectinload(models.FoundationModelRun.species),
                ),
            )
            .order_by(
                models.MLProjectDatasetScope.created_on,
            )
        )
        result = await session.execute(stmt)
        db_scopes = result.scalars().all()

        return [await dataset_scope_to_schema(session, s) for s in db_scopes]

    async def get_dataset_scope(
        self,
        session: AsyncSession,
        ml_project: schemas.MLProject,
        scope_uuid: UUID,
        *,
        user: models.User | schemas.SimpleUser | None = None,
    ) -> schemas.MLProjectDatasetScope:
        """Get a specific dataset scope by UUID.

        Args:
            session: Database session.
            ml_project: The ML project the scope belongs to.
            scope_uuid: UUID of the scope to get.
            user: The user performing the action.

        Returns:
            The dataset scope.

        Raises:
            NotFoundError: If the scope is not found.
        """
        db_user = await self._resolve_user(session, user)

        if not await can_view_ml_project(session, ml_project, db_user):
            raise exceptions.NotFoundError(
                f"ML Project with uuid {ml_project.uuid} not found"
            )

        # Get the scope
        db_scope = await session.scalar(
            select(models.MLProjectDatasetScope)
            .where(
                and_(
                    models.MLProjectDatasetScope.ml_project_id == ml_project.id,
                    models.MLProjectDatasetScope.uuid == scope_uuid,
                )
            )
            .options(
                selectinload(models.MLProjectDatasetScope.dataset).options(
                    selectinload(models.Dataset.project).options(
                        selectinload(models.Project.memberships)
                    ),
                    selectinload(models.Dataset.primary_site).options(
                        selectinload(models.Site.images)
                    ),
                    selectinload(models.Dataset.primary_recorder),
                    selectinload(models.Dataset.license),
                ),
                selectinload(models.MLProjectDatasetScope.foundation_model_run).options(
                    selectinload(models.FoundationModelRun.foundation_model),
                    selectinload(models.FoundationModelRun.dataset),
                    selectinload(models.FoundationModelRun.species),
                ),
            )
        )
        if db_scope is None:
            raise exceptions.NotFoundError(
                f"Dataset scope with uuid {scope_uuid} not found"
            )

        return await dataset_scope_to_schema(session, db_scope)


async def dataset_scope_to_schema(
    session: AsyncSession,
    db_scope: models.MLProjectDatasetScope,
) -> schemas.MLProjectDatasetScope:
    """Convert a database dataset scope to a schema.

    Args:
        session: Database session.
        db_scope: The database model to convert.

    Returns:
        The schema representation.
    """
    return schemas.MLProjectDatasetScope(
        uuid=db_scope.uuid,
        dataset=schemas.Dataset.model_validate(db_scope.dataset),
        foundation_model_run=schemas.FoundationModelRun.model_validate(
            db_scope.foundation_model_run
        ),
        created_on=db_scope.created_on,
    )


ml_projects = MLProjectAPI()
