"""Detection annotation service for detection review business logic."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select as sa_select

from echoroo.core.pagination import paginate
from echoroo.models.annotation import Annotation
from echoroo.models.confirmed_region import ConfirmedRegion
from echoroo.models.enums import DetectionStatus
from echoroo.models.taxon_vernacular_name import TaxonVernacularName
from echoroo.repositories.annotation import AnnotationRepository, TemporalSummaryRow
from echoroo.repositories.confirmed_region import ConfirmedRegionRepository
from echoroo.schemas.detection import (
    ChangeSpeciesRequest,
    ConfirmRequest,
    DetectionCreate,
    DetectionListResponse,
    DetectionResponse,
    DetectionTemporalDataResponse,
    HourlyDetection,
    SpeciesSummaryItem,
    SpeciesSummaryResponse,
    SpeciesTemporalData,
)
from echoroo.schemas.tag import TagResponse


class DetectionService:
    """Service for detection annotation management business logic."""

    def __init__(
        self,
        annotation_repo: AnnotationRepository,
        confirmed_region_repo: ConfirmedRegionRepository,
    ) -> None:
        """Initialize service with repositories.

        Args:
            annotation_repo: Annotation repository instance
            confirmed_region_repo: ConfirmedRegion repository instance
        """
        self.annotation_repo = annotation_repo
        self.confirmed_region_repo = confirmed_region_repo

    async def list_detections(
        self,
        project_id: UUID,
        tag_id: UUID | None = None,
        status: DetectionStatus | None = None,
        confidence_min: float | None = None,
        confidence_max: float | None = None,
        dataset_id: UUID | None = None,
        recording_id: UUID | None = None,
        detection_run_id: UUID | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> DetectionListResponse:
        """List detections for a project with optional filtering and pagination.

        Args:
            project_id: Project's UUID
            tag_id: Optional tag filter
            status: Optional review status filter
            confidence_min: Optional minimum confidence filter
            confidence_max: Optional maximum confidence filter
            dataset_id: Optional dataset filter
            recording_id: Optional recording filter
            detection_run_id: Optional detection run filter
            page: Page number (1-indexed)
            page_size: Items per page

        Returns:
            Paginated detection list response
        """
        pagination = paginate(page, page_size)

        annotations, total = await self.annotation_repo.list_annotations(
            project_id=project_id,
            tag_id=tag_id,
            status=status,
            confidence_min=confidence_min,
            confidence_max=confidence_max,
            dataset_id=dataset_id,
            recording_id=recording_id,
            detection_run_id=detection_run_id,
            page=pagination.page,
            page_size=pagination.page_size,
        )

        items = [self._to_response(a) for a in annotations]

        return DetectionListResponse(
            items=items,
            total=total,
            page=pagination.page,
            page_size=pagination.page_size,
            pages=pagination.total_pages(total),
        )

    async def _resolve_vernacular_names(
        self,
        taxon_ids: list[UUID],
        locale: str,
    ) -> dict[UUID, str]:
        """Batch-resolve vernacular names for a list of taxon IDs.

        Fetches primary vernacular names in one query to avoid N+1 queries.
        Falls back to any vernacular name for the locale if no primary exists.

        Args:
            taxon_ids: List of taxon UUIDs to resolve
            locale: Locale code (e.g. "en", "ja")

        Returns:
            Mapping of taxon_id to vernacular name string
        """
        if not taxon_ids:
            return {}

        result = await self.annotation_repo.db.execute(
            sa_select(TaxonVernacularName)
            .where(TaxonVernacularName.taxon_id.in_(taxon_ids))
            .where(TaxonVernacularName.locale == locale)
            .order_by(
                TaxonVernacularName.taxon_id,
                TaxonVernacularName.is_primary.desc(),
            )
        )
        vernacular_names = result.scalars().all()

        # Build mapping: keep only the first (highest priority) entry per taxon_id
        mapping: dict[UUID, str] = {}
        for vn in vernacular_names:
            if vn.taxon_id not in mapping:
                mapping[vn.taxon_id] = vn.name

        return mapping

    async def get_species_summary(
        self,
        project_id: UUID,
        dataset_id: UUID | None = None,
        detection_run_id: UUID | None = None,
        locale: str = "en",
    ) -> SpeciesSummaryResponse:
        """Get species detection summary grouped by tag.

        When locale is specified, common names are resolved from TaxonVernacularName
        using a single batch query to avoid N+1 database calls.

        Args:
            project_id: Project's UUID
            dataset_id: Optional dataset filter
            detection_run_id: Optional detection run filter
            locale: Locale code for common name resolution (default: "en")

        Returns:
            Species summary response with per-species statistics
        """
        rows = await self.annotation_repo.species_summary(
            project_id=project_id,
            dataset_id=dataset_id,
            detection_run_id=detection_run_id,
        )

        # Collect taxon IDs for batch vernacular name resolution
        taxon_ids = [row["taxon_id"] for row in rows if row["taxon_id"] is not None]
        vernacular_map = await self._resolve_vernacular_names(taxon_ids, locale)

        items = [
            SpeciesSummaryItem(
                tag_id=row["tag_id"],
                tag_name=row["tag_name"],
                scientific_name=row["scientific_name"],
                common_name=(
                    vernacular_map.get(row["taxon_id"], row["common_name"])
                    if row["taxon_id"] is not None
                    else row["common_name"]
                ),
                taxon_id=row["taxon_id"],
                total_count=row["total_count"],
                unreviewed_count=row["unreviewed_count"],
                confirmed_count=row["confirmed_count"],
                rejected_count=row["rejected_count"],
                avg_confidence=row["avg_confidence"],
            )
            for row in rows
        ]

        return SpeciesSummaryResponse(
            items=items,
            total_species=len(items),
        )

    async def get_temporal_data(
        self,
        project_id: UUID,
        dataset_id: UUID | None = None,
        detection_run_id: UUID | None = None,
        locale: str = "en",
    ) -> DetectionTemporalDataResponse:
        """Get hourly detection counts grouped by species, date, and hour.

        When locale is specified, common names are resolved from TaxonVernacularName
        using a single batch query to avoid N+1 database calls.

        Args:
            project_id: Project's UUID
            dataset_id: Optional dataset filter
            detection_run_id: Optional detection run filter
            locale: Locale code for common name resolution (default: "en")

        Returns:
            Temporal data response with per-species hourly counts
        """
        from datetime import date as DateType

        from echoroo.models.tag import Tag

        rows = await self.annotation_repo.temporal_summary(
            project_id=project_id,
            dataset_id=dataset_id,
            detection_run_id=detection_run_id,
        )

        # Group rows by tag_id
        grouped: dict[UUID, list[TemporalSummaryRow]] = {}
        for row in rows:
            tag_id = row["tag_id"]
            if tag_id not in grouped:
                grouped[tag_id] = []
            grouped[tag_id].append(row)

        # Batch fetch all tag records in one query
        tag_ids = list(grouped.keys())
        if tag_ids:
            tags_result = await self.annotation_repo.db.execute(
                sa_select(Tag).where(Tag.id.in_(tag_ids))
            )
            tags_by_id: dict[UUID, Tag] = {tag.id: tag for tag in tags_result.scalars().all()}
        else:
            tags_by_id = {}

        # Batch resolve vernacular names for all taxon IDs
        taxon_ids = [tag.taxon_id for tag in tags_by_id.values() if tag.taxon_id is not None]
        vernacular_map = await self._resolve_vernacular_names(taxon_ids, locale)

        # Build response
        species_list: list[SpeciesTemporalData] = []
        all_dates: list[DateType] = []

        for tag_id, tag_rows in grouped.items():
            tag = tags_by_id.get(tag_id)
            if tag is None:
                continue

            # Resolve common name via vernacular map, fall back to tag.common_name
            resolved_common_name = (
                vernacular_map.get(tag.taxon_id, tag.common_name)
                if tag.taxon_id is not None
                else tag.common_name
            )

            hourly_detections = [
                HourlyDetection(
                    date=row["date"],
                    hour=row["hour"],
                    count=row["count"],
                )
                for row in tag_rows
            ]

            total_detections = sum(row["count"] for row in tag_rows)
            dates_for_tag = [row["date"] for row in tag_rows if isinstance(row["date"], DateType)]
            all_dates.extend(dates_for_tag)

            species_list.append(
                SpeciesTemporalData(
                    tag_id=tag.id,
                    scientific_name=tag.scientific_name or tag.name,
                    common_name=resolved_common_name,
                    total_detections=total_detections,
                    detections=hourly_detections,
                )
            )

        # Sort species by total detections descending
        species_list.sort(key=lambda s: s.total_detections, reverse=True)

        date_range: tuple[DateType, DateType] | None = None
        if all_dates:
            date_range = (min(all_dates), max(all_dates))

        return DetectionTemporalDataResponse(
            project_id=project_id,
            dataset_id=dataset_id,
            detection_run_id=detection_run_id,
            date_range=date_range,
            species=species_list,
        )

    async def get(self, detection_id: UUID) -> DetectionResponse:
        """Get a detection annotation by ID.

        Args:
            detection_id: Annotation's UUID

        Returns:
            Detection response

        Raises:
            HTTPException: If annotation not found
        """
        annotation = await self.annotation_repo.get_by_id(detection_id)
        if not annotation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Detection not found",
            )
        return self._to_response(annotation)

    async def create(
        self,
        project_id: UUID,  # noqa: ARG002 - used for future authorization
        request: DetectionCreate,
    ) -> DetectionResponse:
        """Create a new detection annotation.

        Args:
            project_id: Project's UUID (for authorization context)
            request: Detection creation data

        Returns:
            Created detection response
        """
        annotation = Annotation(
            recording_id=request.recording_id,
            tag_id=request.tag_id,
            detection_run_id=request.detection_run_id,
            source=request.source,
            confidence=request.confidence,
            start_time=request.start_time,
            end_time=request.end_time,
            freq_low=request.freq_low,
            freq_high=request.freq_high,
        )

        created = await self.annotation_repo.create(annotation)
        return self._to_response(created)

    async def confirm(
        self,
        detection_id: UUID,
        user_id: UUID,
        request: ConfirmRequest | None = None,
    ) -> DetectionResponse:
        """Confirm a detection annotation and create a confirmed region.

        Sets status to confirmed, records the reviewer, and creates a
        ConfirmedRegion for the confirmed time range. When *request* is
        ``None`` or its fields are ``None``, the annotation's existing
        start_time / end_time are preserved (quick-confirm).

        Args:
            detection_id: Annotation's UUID
            user_id: ID of the user confirming the detection
            request: Optional confirm request with adjusted time range

        Returns:
            Updated detection response

        Raises:
            HTTPException: If annotation not found
        """
        annotation = await self.annotation_repo.get_by_id(detection_id)
        if not annotation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Detection not found",
            )

        # Use provided times or fall back to the annotation's existing values
        start_time = (
            request.start_time
            if request is not None and request.start_time is not None
            else annotation.start_time
        )
        end_time = (
            request.end_time
            if request is not None and request.end_time is not None
            else annotation.end_time
        )

        annotation.status = DetectionStatus.CONFIRMED
        annotation.reviewed_by_id = user_id
        annotation.reviewed_at = datetime.now(UTC)
        annotation.start_time = start_time
        annotation.end_time = end_time

        updated = await self.annotation_repo.update(annotation)

        # Create a confirmed region for the confirmed time range
        confirmed_region = ConfirmedRegion(
            recording_id=annotation.recording_id,
            start_time=start_time,
            end_time=end_time,
            reviewed_by_id=user_id,
        )
        await self.confirmed_region_repo.create(confirmed_region)

        return self._to_response(updated)

    async def reject(
        self,
        detection_id: UUID,
        user_id: UUID,
    ) -> DetectionResponse:
        """Reject a detection annotation.

        Args:
            detection_id: Annotation's UUID
            user_id: ID of the user rejecting the detection

        Returns:
            Updated detection response

        Raises:
            HTTPException: If annotation not found
        """
        annotation = await self.annotation_repo.get_by_id(detection_id)
        if not annotation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Detection not found",
            )

        annotation.status = DetectionStatus.REJECTED
        annotation.reviewed_by_id = user_id
        annotation.reviewed_at = datetime.now(UTC)

        updated = await self.annotation_repo.update(annotation)
        return self._to_response(updated)

    async def change_species(
        self,
        detection_id: UUID,
        request: ChangeSpeciesRequest,
        user_id: UUID,
    ) -> DetectionResponse:
        """Change the species tag of a detection annotation.

        Also updates time range if provided, and records the reviewer.

        Args:
            detection_id: Annotation's UUID
            request: Change species request with new tag and optional time range
            user_id: ID of the user making the change

        Returns:
            Updated detection response

        Raises:
            HTTPException: If annotation not found
        """
        annotation = await self.annotation_repo.get_by_id(detection_id)
        if not annotation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Detection not found",
            )

        annotation.tag_id = request.new_tag_id
        annotation.reviewed_by_id = user_id
        annotation.reviewed_at = datetime.now(UTC)

        if request.start_time is not None:
            annotation.start_time = request.start_time
        if request.end_time is not None:
            annotation.end_time = request.end_time

        updated = await self.annotation_repo.update(annotation)
        return self._to_response(updated)

    async def delete(self, detection_id: UUID) -> None:
        """Delete a detection annotation.

        Args:
            detection_id: Annotation's UUID

        Raises:
            HTTPException: If annotation not found
        """
        annotation = await self.annotation_repo.get_by_id(detection_id)
        if not annotation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Detection not found",
            )

        await self.annotation_repo.delete(detection_id)

    @staticmethod
    def _to_response(annotation: Annotation) -> DetectionResponse:
        """Convert an Annotation model to a DetectionResponse schema.

        Args:
            annotation: Annotation model instance

        Returns:
            DetectionResponse instance
        """
        tag_response = None
        if annotation.tag is not None:
            tag_response = TagResponse.model_validate(annotation.tag)

        return DetectionResponse(
            id=annotation.id,
            recording_id=annotation.recording_id,
            tag_id=annotation.tag_id,
            detection_run_id=annotation.detection_run_id,
            source=annotation.source,
            status=annotation.status,
            confidence=annotation.confidence,
            start_time=annotation.start_time,
            end_time=annotation.end_time,
            freq_low=annotation.freq_low,
            freq_high=annotation.freq_high,
            reviewed_by_id=annotation.reviewed_by_id,
            reviewed_at=annotation.reviewed_at,
            created_at=annotation.created_at,
            updated_at=annotation.updated_at,
            tag=tag_response,
        )
