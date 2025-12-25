"""API helpers for species filters."""

from __future__ import annotations

import datetime
from typing import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from echoroo import exceptions, models, schemas
from echoroo.api import foundation_models
from echoroo.api.foundation_models import (
    can_edit_foundation_model_run,
    can_view_foundation_model_run,
)

__all__ = ["species_filters"]


class SpeciesFilterAPI:
    """Service for managing species filters."""

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

    async def list_filters(
        self,
        session: AsyncSession,
        *,
        include_inactive: bool = False,
    ) -> list[schemas.SpeciesFilter]:
        """List available species filters.

        Args:
            session: Database session.
            include_inactive: Whether to include inactive filters.

        Returns:
            List of available species filters.
        """
        stmt = select(models.SpeciesFilter)
        if not include_inactive:
            stmt = stmt.where(models.SpeciesFilter.is_active.is_(True))
        stmt = stmt.order_by(models.SpeciesFilter.display_name.asc())
        result = await session.scalars(stmt)
        return [
            schemas.SpeciesFilter.model_validate(obj)
            for obj in result.unique().all()
        ]

    async def get_filter_by_slug(
        self,
        session: AsyncSession,
        slug: str,
    ) -> models.SpeciesFilter:
        """Get a species filter by slug.

        Args:
            session: Database session.
            slug: Filter slug identifier.

        Returns:
            The species filter model.

        Raises:
            NotFoundError: If filter not found.
        """
        stmt = select(models.SpeciesFilter).where(
            models.SpeciesFilter.slug == slug,
        )
        filter_obj = await session.scalar(stmt)
        if filter_obj is None:
            raise exceptions.NotFoundError(f"Species filter {slug} not found")
        return filter_obj

    async def apply_filter(
        self,
        session: AsyncSession,
        run_uuid: UUID,
        filter_slug: str,
        threshold: float,
        *,
        user: models.User | schemas.SimpleUser,
        apply_to_all_detections: bool = True,
    ) -> schemas.SpeciesFilterApplication:
        """Apply a species filter to a foundation model run.

        Args:
            session: Database session.
            run_uuid: UUID of the foundation model run.
            filter_slug: Slug of the filter to apply.
            threshold: Probability threshold for species inclusion.
            user: User initiating the filter application.
            apply_to_all_detections: Whether to apply to all detections.

        Returns:
            The created filter application.

        Raises:
            NotFoundError: If run or filter not found.
            PermissionDeniedError: If user lacks permission.
            InvalidDataError: If filter already applied.
        """
        db_user = await self._resolve_user(session, user)
        if db_user is None:
            raise exceptions.PermissionDeniedError("Authentication required")

        # Get the foundation model run
        run = await foundation_models.get_run_with_relations(session, run_uuid)

        if not await can_edit_foundation_model_run(session, run, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to apply filters to this run"
            )

        # Get the run model
        db_run = await foundation_models.get_run(session, run_uuid)

        # Get the species filter
        species_filter = await self.get_filter_by_slug(session, filter_slug)

        # Check if filter already applied
        existing = await session.scalar(
            select(models.SpeciesFilterApplication).where(
                models.SpeciesFilterApplication.foundation_model_run_id == db_run.id,
                models.SpeciesFilterApplication.species_filter_id == species_filter.id,
            )
        )
        if existing is not None:
            raise exceptions.InvalidDataError(
                f"Filter {filter_slug} is already applied to this run"
            )

        # Create the filter application
        application = models.SpeciesFilterApplication(
            foundation_model_run_id=db_run.id,
            species_filter_id=species_filter.id,
            threshold=threshold,
            apply_to_all_detections=apply_to_all_detections,
            applied_by_id=db_user.id,
            status=models.SpeciesFilterApplicationStatus.PENDING,
        )
        session.add(application)
        await session.flush()

        # Return with relations loaded
        return await self.get_application(session, application.uuid)

    async def list_applications(
        self,
        session: AsyncSession,
        run_uuid: UUID,
        *,
        user: models.User | schemas.SimpleUser | None = None,
    ) -> list[schemas.SpeciesFilterApplication]:
        """List filter applications for a foundation model run.

        Args:
            session: Database session.
            run_uuid: UUID of the foundation model run.
            user: User making the request.

        Returns:
            List of filter applications for the run.

        Raises:
            NotFoundError: If run not found.
            PermissionDeniedError: If user lacks permission.
        """
        db_user = await self._resolve_user(session, user)

        # Get the foundation model run
        run = await foundation_models.get_run_with_relations(session, run_uuid)

        if not await can_view_foundation_model_run(session, run, db_user):
            raise exceptions.NotFoundError("Foundation model run not found")

        db_run = await foundation_models.get_run(session, run_uuid)

        stmt = (
            select(models.SpeciesFilterApplication)
            .options(
                joinedload(models.SpeciesFilterApplication.species_filter),
                joinedload(models.SpeciesFilterApplication.applied_by),
            )
            .where(
                models.SpeciesFilterApplication.foundation_model_run_id == db_run.id,
            )
            .order_by(models.SpeciesFilterApplication.id.desc())
        )
        result = await session.scalars(stmt)

        applications = []
        for app in result.unique().all():
            applications.append(
                schemas.SpeciesFilterApplication(
                    uuid=app.uuid,
                    species_filter=schemas.SpeciesFilter.model_validate(
                        app.species_filter
                    ) if app.species_filter else None,
                    threshold=app.threshold,
                    apply_to_all_detections=app.apply_to_all_detections,
                    status=schemas.SpeciesFilterApplicationStatus(app.status.value),
                    progress=app.progress,
                    total_detections=app.total_detections,
                    filtered_detections=app.filtered_detections,
                    excluded_detections=app.excluded_detections,
                    started_on=app.started_on,
                    completed_on=app.completed_on,
                    error=app.error,
                )
            )
        return applications

    async def get_application(
        self,
        session: AsyncSession,
        application_uuid: UUID,
    ) -> schemas.SpeciesFilterApplication:
        """Get a filter application by UUID.

        Args:
            session: Database session.
            application_uuid: UUID of the filter application.

        Returns:
            The filter application.

        Raises:
            NotFoundError: If application not found.
        """
        stmt = (
            select(models.SpeciesFilterApplication)
            .options(
                joinedload(models.SpeciesFilterApplication.species_filter),
                joinedload(models.SpeciesFilterApplication.applied_by),
            )
            .where(models.SpeciesFilterApplication.uuid == application_uuid)
        )
        app = await session.scalar(stmt)
        if app is None:
            raise exceptions.NotFoundError("Filter application not found")

        return schemas.SpeciesFilterApplication(
            uuid=app.uuid,
            species_filter=schemas.SpeciesFilter.model_validate(
                app.species_filter
            ) if app.species_filter else None,
            threshold=app.threshold,
            apply_to_all_detections=app.apply_to_all_detections,
            status=schemas.SpeciesFilterApplicationStatus(app.status.value),
            progress=app.progress,
            total_detections=app.total_detections,
            filtered_detections=app.filtered_detections,
            excluded_detections=app.excluded_detections,
            started_on=app.started_on,
            completed_on=app.completed_on,
            error=app.error,
        )

    async def get_application_by_run_and_uuid(
        self,
        session: AsyncSession,
        run_uuid: UUID,
        application_uuid: UUID,
        *,
        user: models.User | schemas.SimpleUser | None = None,
    ) -> schemas.SpeciesFilterApplication:
        """Get a filter application by run UUID and application UUID.

        Args:
            session: Database session.
            run_uuid: UUID of the foundation model run.
            application_uuid: UUID of the filter application.
            user: User making the request.

        Returns:
            The filter application.

        Raises:
            NotFoundError: If run or application not found.
            PermissionDeniedError: If user lacks permission.
        """
        db_user = await self._resolve_user(session, user)

        # Get the foundation model run
        run = await foundation_models.get_run_with_relations(session, run_uuid)

        if not await can_view_foundation_model_run(session, run, db_user):
            raise exceptions.NotFoundError("Foundation model run not found")

        db_run = await foundation_models.get_run(session, run_uuid)

        stmt = (
            select(models.SpeciesFilterApplication)
            .options(
                joinedload(models.SpeciesFilterApplication.species_filter),
                joinedload(models.SpeciesFilterApplication.applied_by),
            )
            .where(
                models.SpeciesFilterApplication.uuid == application_uuid,
                models.SpeciesFilterApplication.foundation_model_run_id == db_run.id,
            )
        )
        app = await session.scalar(stmt)
        if app is None:
            raise exceptions.NotFoundError("Filter application not found")

        return schemas.SpeciesFilterApplication(
            uuid=app.uuid,
            species_filter=schemas.SpeciesFilter.model_validate(
                app.species_filter
            ) if app.species_filter else None,
            threshold=app.threshold,
            apply_to_all_detections=app.apply_to_all_detections,
            status=schemas.SpeciesFilterApplicationStatus(app.status.value),
            progress=app.progress,
            total_detections=app.total_detections,
            filtered_detections=app.filtered_detections,
            excluded_detections=app.excluded_detections,
            started_on=app.started_on,
            completed_on=app.completed_on,
            error=app.error,
        )

    async def get_application_progress(
        self,
        session: AsyncSession,
        run_uuid: UUID,
        application_uuid: UUID,
        *,
        user: models.User | schemas.SimpleUser | None = None,
    ) -> schemas.SpeciesFilterApplicationProgress:
        """Get progress for a filter application.

        Args:
            session: Database session.
            run_uuid: UUID of the foundation model run.
            application_uuid: UUID of the filter application.
            user: User making the request.

        Returns:
            Progress information for the filter application.

        Raises:
            NotFoundError: If run or application not found.
            PermissionDeniedError: If user lacks permission.
        """
        db_user = await self._resolve_user(session, user)

        # Get the foundation model run
        run = await foundation_models.get_run_with_relations(session, run_uuid)

        if not await can_view_foundation_model_run(session, run, db_user):
            raise exceptions.NotFoundError("Foundation model run not found")

        db_run = await foundation_models.get_run(session, run_uuid)

        stmt = select(models.SpeciesFilterApplication).where(
            models.SpeciesFilterApplication.uuid == application_uuid,
            models.SpeciesFilterApplication.foundation_model_run_id == db_run.id,
        )
        app = await session.scalar(stmt)
        if app is None:
            raise exceptions.NotFoundError("Filter application not found")

        return schemas.SpeciesFilterApplicationProgress(
            uuid=app.uuid,
            status=schemas.SpeciesFilterApplicationStatus(app.status.value),
            progress=app.progress,
            total_detections=app.total_detections,
            filtered_detections=app.filtered_detections,
            excluded_detections=app.excluded_detections,
        )


species_filters = SpeciesFilterAPI()
