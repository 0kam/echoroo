"""API helpers for species filters."""

from __future__ import annotations

import asyncio
import datetime
from typing import Sequence
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from echoroo import exceptions, models, schemas
from echoroo.api import foundation_models, species
from echoroo.api.common import UserResolutionMixin
from echoroo.api.foundation_models import (
    can_edit_foundation_model_run,
    can_view_foundation_model_run,
)

__all__ = ["species_filters"]


class SpeciesFilterAPI(UserResolutionMixin):
    """Service for managing species filters."""

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

    async def _validate_filter_requirements(
        self,
        session: AsyncSession,
        run: models.FoundationModelRun,
        species_filter: models.SpeciesFilter,
    ) -> None:
        """Validate that recordings have required data for the filter.

        Args:
            session: Database session.
            run: The foundation model run.
            species_filter: The species filter to apply.

        Raises:
            InvalidDataError: If recordings are missing required data.
        """
        if not species_filter.requires_location and not species_filter.requires_date:
            return  # No validation needed

        # Get distinct recordings from the run's predictions
        # via clip_prediction -> clip -> recording
        from sqlalchemy.orm import joinedload

        stmt = (
            select(models.ClipPrediction)
            .join(models.ModelRunPrediction)
            .where(models.ModelRunPrediction.model_run_id == run.model_run_id)
            .options(
                joinedload(models.ClipPrediction.clip).joinedload(
                    models.Clip.recording
                )
            )
            .limit(100)  # Check a sample of recordings
        )
        result = await session.execute(stmt)
        predictions = result.unique().scalars().all()

        if not predictions:
            return  # No predictions to filter

        # Check unique recordings
        recordings_checked: set[int] = set()
        missing_location_count = 0
        missing_date_count = 0
        total_checked = 0

        for pred in predictions:
            if pred.clip and pred.clip.recording:
                rec = pred.clip.recording
                if rec.id in recordings_checked:
                    continue
                recordings_checked.add(rec.id)
                total_checked += 1

                # Check location (lat/lng or h3_index)
                has_location = (
                    (rec.latitude is not None and rec.longitude is not None)
                    or rec.h3_index is not None
                )
                if not has_location:
                    missing_location_count += 1

                # Check date (also accept datetime as fallback)
                has_date = rec.date is not None or rec.datetime is not None
                if not has_date:
                    missing_date_count += 1

        # Build error message if required data is missing
        errors: list[str] = []

        if species_filter.requires_location and missing_location_count > 0:
            pct = (missing_location_count / total_checked) * 100 if total_checked > 0 else 0
            errors.append(
                f"{missing_location_count}/{total_checked} recordings ({pct:.0f}%) "
                "are missing location data (latitude/longitude or site). "
                "Set a primary site with coordinates for the dataset, or add "
                "location metadata to recordings."
            )

        if species_filter.requires_date and missing_date_count > 0:
            pct = (missing_date_count / total_checked) * 100 if total_checked > 0 else 0
            errors.append(
                f"{missing_date_count}/{total_checked} recordings ({pct:.0f}%) "
                "are missing date information. The geo filter uses week of year "
                "to determine species occurrence. Add date metadata to recordings."
            )

        if errors:
            raise exceptions.InvalidDataError(
                "Cannot apply filter: " + " ".join(errors)
            )

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

        # Validate that recordings have required data for this filter
        await self._validate_filter_requirements(
            session, db_run, species_filter
        )

        # Delete any existing filter applications for this run
        # (user explicitly wants to re-apply, so remove old results)
        existing_apps = await session.scalars(
            select(models.SpeciesFilterApplication).where(
                models.SpeciesFilterApplication.foundation_model_run_id == db_run.id,
            )
        )
        for existing in existing_apps:
            # Delete associated mask data first
            await session.execute(
                delete(models.SpeciesFilterMask).where(
                    models.SpeciesFilterMask.species_filter_application_id == existing.id
                )
            )
            await session.delete(existing)
        await session.flush()

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

    async def get_application_species_results(
        self,
        session: AsyncSession,
        run_uuid: UUID,
        application_uuid: UUID,
        *,
        user: models.User | schemas.SimpleUser | None = None,
        locale: str = "ja",
    ) -> schemas.SpeciesFilterResults:
        """Get species results grouped by filter status.

        Queries species_filter_mask grouped by tag (species) and returns
        results sorted by detection_count descending.

        Args:
            session: Database session.
            run_uuid: UUID of the foundation model run.
            application_uuid: UUID of the filter application.
            user: User making the request.
            locale: Locale for vernacular names (e.g., "en", "ja").

        Returns:
            Species filter results grouped by status.

        Raises:
            NotFoundError: If run or application not found.
            PermissionDeniedError: If user lacks permission.
        """
        db_user = await self._resolve_user(session, user)

        # Get the foundation model run and check permission
        run = await foundation_models.get_run_with_relations(session, run_uuid)

        if not await can_view_foundation_model_run(session, run, db_user):
            raise exceptions.NotFoundError("Foundation model run not found")

        db_run = await foundation_models.get_run(session, run_uuid)

        # Get the filter application
        stmt = select(models.SpeciesFilterApplication).where(
            models.SpeciesFilterApplication.uuid == application_uuid,
            models.SpeciesFilterApplication.foundation_model_run_id == db_run.id,
        )
        app = await session.scalar(stmt)
        if app is None:
            raise exceptions.NotFoundError("Filter application not found")

        # Query species grouped by tag with detection counts
        # We group by tag_id, is_included to get counts per species per status
        # and also get the average occurrence_probability per species
        grouped_stmt = (
            select(
                models.SpeciesFilterMask.tag_id,
                models.SpeciesFilterMask.is_included,
                func.count(models.SpeciesFilterMask.id).label("detection_count"),
                func.avg(models.SpeciesFilterMask.occurrence_probability).label(
                    "avg_occurrence_probability"
                ),
            )
            .where(
                models.SpeciesFilterMask.species_filter_application_id == app.id,
            )
            .group_by(
                models.SpeciesFilterMask.tag_id,
                models.SpeciesFilterMask.is_included,
            )
        )
        result = await session.execute(grouped_stmt)
        grouped_rows = result.all()

        # Get unique tag IDs
        tag_ids = list(set(row.tag_id for row in grouped_rows))

        # Fetch tags for species names
        tags_by_id: dict[int, models.Tag] = {}
        if tag_ids:
            tags_stmt = select(models.Tag).where(models.Tag.id.in_(tag_ids))
            tags_result = await session.scalars(tags_stmt)
            for tag in tags_result:
                tags_by_id[tag.id] = tag

        # Collect gbif_taxon_keys that need vernacular name lookup (not in Tag)
        # Tags now store vernacular_name from GBIF, so we only need to fetch
        # for old tags that don't have it yet
        gbif_keys_to_fetch: list[str] = []
        for tag_id in tag_ids:
            tag = tags_by_id.get(tag_id)
            if tag and tag.value and not tag.vernacular_name:
                gbif_keys_to_fetch.append(tag.value)

        # Fetch vernacular names for tags that don't have them (legacy data)
        vernacular_names: dict[str, str | None] = {}
        if gbif_keys_to_fetch:
            tasks = [
                species.get_gbif_vernacular_name(key, locale) for key in gbif_keys_to_fetch
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for key, result in zip(gbif_keys_to_fetch, results):
                if isinstance(result, BaseException):
                    vernacular_names[key] = None
                else:
                    vernacular_names[key] = result  # type: ignore[assignment]

        # Build result items
        passed_items: list[schemas.SpeciesFilterResultItem] = []
        excluded_items: list[schemas.SpeciesFilterResultItem] = []

        for row in grouped_rows:
            tag = tags_by_id.get(row.tag_id)
            # Use tag.value as gbif_taxon_key (for species tags, value is GBIF usage key)
            gbif_taxon_key = tag.value if tag else str(row.tag_id)
            # Use canonical_name as species_name
            species_name = tag.canonical_name if tag else None
            # Get common name from Tag first, then fallback to GBIF API lookup
            common_name = (
                tag.vernacular_name if tag and tag.vernacular_name
                else vernacular_names.get(gbif_taxon_key) if gbif_taxon_key
                else None
            )

            item = schemas.SpeciesFilterResultItem(
                gbif_taxon_key=gbif_taxon_key,
                species_name=species_name,
                common_name=common_name,
                is_included=row.is_included,
                occurrence_probability=row.avg_occurrence_probability,
                detection_count=row.detection_count,
            )

            if row.is_included:
                passed_items.append(item)
            else:
                excluded_items.append(item)

        # Sort by detection_count descending
        passed_items.sort(key=lambda x: x.detection_count, reverse=True)
        excluded_items.sort(key=lambda x: x.detection_count, reverse=True)

        return schemas.SpeciesFilterResults(
            passed=passed_items,
            excluded=excluded_items,
            total_passed=len(passed_items),
            total_excluded=len(excluded_items),
        )

    async def cancel_application(
        self,
        session: AsyncSession,
        run_uuid: UUID,
        application_uuid: UUID,
        *,
        user: models.User | schemas.SimpleUser,
    ) -> schemas.SpeciesFilterApplication:
        """Cancel a running or queued species filter application.

        Args:
            session: Database session.
            run_uuid: UUID of the foundation model run.
            application_uuid: UUID of the filter application.
            user: User initiating the cancellation.

        Returns:
            The cancelled filter application.

        Raises:
            NotFoundError: If run or application not found.
            PermissionDeniedError: If user lacks permission.
            InvalidDataError: If application cannot be cancelled.
        """
        db_user = await self._resolve_user(session, user)
        if db_user is None:
            raise exceptions.PermissionDeniedError("Authentication required")

        # Get the foundation model run and check permission
        run = await foundation_models.get_run_with_relations(session, run_uuid)

        if not await can_edit_foundation_model_run(session, run, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to cancel this filter application"
            )

        db_run = await foundation_models.get_run(session, run_uuid)

        # Get the filter application
        stmt = select(models.SpeciesFilterApplication).where(
            models.SpeciesFilterApplication.uuid == application_uuid,
            models.SpeciesFilterApplication.foundation_model_run_id == db_run.id,
        )
        app = await session.scalar(stmt)
        if app is None:
            raise exceptions.NotFoundError("Filter application not found")

        # Check if the application can be cancelled
        if app.status not in (
            models.SpeciesFilterApplicationStatus.PENDING,
            models.SpeciesFilterApplicationStatus.RUNNING,
        ):
            raise exceptions.InvalidDataError(
                f"Cannot cancel application with status {app.status.value}"
            )

        # Cancel the application
        app.status = models.SpeciesFilterApplicationStatus.CANCELLED
        await session.flush()

        return await self.get_application(session, application_uuid)


species_filters = SpeciesFilterAPI()
