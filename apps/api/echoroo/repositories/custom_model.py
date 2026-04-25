"""Repository for CustomModel database operations."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select

from echoroo.models.custom_model import CustomModel
from echoroo.repositories.base import BaseRepository


class CustomModelRepository(BaseRepository[CustomModel]):
    """Repository for CustomModel entity operations."""

    model = CustomModel

    async def get_by_id_and_project(
        self,
        model_id: UUID,
        project_id: UUID,
    ) -> CustomModel | None:
        """Get a CustomModel by ID, scoped to the given project.

        Args:
            model_id: CustomModel's UUID
            project_id: Project's UUID (used for scoping)

        Returns:
            CustomModel instance or None if not found
        """
        result = await self.db.execute(
            select(CustomModel).where(
                CustomModel.id == model_id,
                CustomModel.project_id == project_id,
            )
        )
        return result.scalar_one_or_none()

    async def exists_in_project(self, model_id: UUID, project_id: UUID) -> bool:
        """Return True when the custom model belongs to the project."""
        result = await self.db.execute(
            select(CustomModel.id)
            .where(CustomModel.id == model_id)
            .where(CustomModel.project_id == project_id)
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def list_for_project(
        self,
        project_id: UUID,
        limit: int = 50,
        offset: int = 0,
        tag_id: UUID | None = None,
        search_session_id: UUID | None = None,
    ) -> tuple[list[CustomModel], int]:
        """List custom models for a project with optional tag filter and pagination.

        Args:
            project_id: Project's UUID
            limit: Maximum number of results to return
            offset: Number of results to skip
            tag_id: Optional target tag filter
            search_session_id: Optional filter by source search session

        Returns:
            Tuple of (models list, total count)
        """
        query = select(CustomModel).where(CustomModel.project_id == project_id)
        count_query = (
            select(func.count())
            .select_from(CustomModel)
            .where(CustomModel.project_id == project_id)
        )

        if tag_id is not None:
            query = query.where(CustomModel.target_tag_id == tag_id)
            count_query = count_query.where(CustomModel.target_tag_id == tag_id)

        if search_session_id is not None:
            query = query.where(CustomModel.search_session_id == search_session_id)
            count_query = count_query.where(CustomModel.search_session_id == search_session_id)

        total_result = await self.db.execute(count_query)
        total = total_result.scalar_one()

        query = query.order_by(CustomModel.created_at.desc()).offset(offset).limit(limit)
        result = await self.db.execute(query)
        models = list(result.scalars().all())

        return models, total

    async def create(self, custom_model: CustomModel) -> CustomModel:
        """Persist a new CustomModel and flush to populate server-generated fields.

        Args:
            custom_model: CustomModel instance to create

        Returns:
            Persisted CustomModel instance with populated id and timestamps
        """
        self.db.add(custom_model)
        await self.db.flush()
        await self.db.refresh(custom_model)
        return custom_model

    async def update(self, custom_model: CustomModel) -> CustomModel:
        """Flush pending changes and refresh the given CustomModel from the database.

        Args:
            custom_model: CustomModel instance with updated fields

        Returns:
            Refreshed CustomModel instance
        """
        await self.db.flush()
        await self.db.refresh(custom_model)
        return custom_model

    async def remove(self, custom_model: CustomModel) -> None:
        """Delete a CustomModel instance from the database.

        Args:
            custom_model: CustomModel instance to delete
        """
        await self.db.delete(custom_model)
