"""API helpers for detection visualization."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from uuid import UUID

from sqlalchemy import extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo import exceptions, models
from echoroo.schemas.detection_visualization import (
    DetectionTemporalData,
    HourlyDetection,
    SpeciesTemporalData,
)

__all__ = ["get_detection_temporal_data"]


async def get_detection_temporal_data(
    session: AsyncSession,
    run_uuid: UUID,
    *,
    filter_application_uuid: UUID | None = None,
    locale: str = "en",
    user: models.User | None = None,
) -> DetectionTemporalData:
    """Get temporal detection data for polar heatmap visualization.

    Queries ClipPrediction joined with ModelRunPrediction and aggregates
    detection counts by hour (0-23) and date, grouped by species.

    Parameters
    ----------
    session : AsyncSession
        Database session.
    run_uuid : UUID
        Foundation model run UUID.
    filter_application_uuid : UUID | None
        If provided, only include detections that passed the filter
        (is_included=true in SpeciesFilterMask).
    locale : str
        Locale for common names (default: 'en').
    user : models.User | None
        Current user for permission checks (reserved for future use).

    Returns
    -------
    DetectionTemporalData
        Aggregated temporal data for all detected species.
    """
    # Get the foundation model run
    run_stmt = select(models.FoundationModelRun).where(
        models.FoundationModelRun.uuid == run_uuid
    )
    run = await session.scalar(run_stmt)
    if run is None:
        raise exceptions.NotFoundError("Foundation model run not found")

    # Resolve model_run_id
    model_run_id = run.model_run_id
    if model_run_id is None:
        return DetectionTemporalData(
            run_uuid=str(run_uuid),
            filter_application_uuid=str(filter_application_uuid) if filter_application_uuid else None,
            date_range=None,
            species=[],
        )

    # Get filter application if specified
    filter_application: models.SpeciesFilterApplication | None = None
    if filter_application_uuid is not None:
        filter_stmt = select(models.SpeciesFilterApplication).where(
            models.SpeciesFilterApplication.uuid == filter_application_uuid,
            models.SpeciesFilterApplication.foundation_model_run_id == run.id,
        )
        filter_application = await session.scalar(filter_stmt)
        if filter_application is None:
            raise exceptions.NotFoundError(
                f"Species filter application with uuid {filter_application_uuid} not found for this run"
            )

    # Build the aggregation query
    # We need to group by: species (tag.canonical_name), date, and hour
    # Extract date and hour from recording.datetime
    # Use AT TIME ZONE to convert to Japan time before extracting date/hour

    # Base query: ClipPrediction -> ModelRunPrediction -> Clip -> Recording
    # Also join ClipPredictionTag -> Tag to get species info
    # Convert to Asia/Tokyo timezone before extracting date and hour
    datetime_jst = func.timezone("Asia/Tokyo", models.Recording.datetime)

    query = (
        select(
            models.Tag.canonical_name.label("scientific_name"),
            models.Tag.vernacular_name.label("common_name"),
            func.date(datetime_jst).label("detection_date"),
            extract("hour", datetime_jst).label("detection_hour"),
            func.count(models.ClipPrediction.id.distinct()).label("count"),
        )
        .select_from(models.ClipPrediction)
        .join(
            models.ModelRunPrediction,
            models.ClipPrediction.id == models.ModelRunPrediction.clip_prediction_id,
        )
        .join(
            models.Clip,
            models.ClipPrediction.clip_id == models.Clip.id,
        )
        .join(
            models.Recording,
            models.Clip.recording_id == models.Recording.id,
        )
        .join(
            models.ClipPredictionTag,
            models.ClipPrediction.id == models.ClipPredictionTag.clip_prediction_id,
        )
        .join(
            models.Tag,
            models.ClipPredictionTag.tag_id == models.Tag.id,
        )
        .where(
            models.ModelRunPrediction.model_run_id == model_run_id,
            models.Recording.datetime.isnot(None),
            models.Tag.key == "species",
            models.ClipPredictionTag.score >= run.confidence_threshold,
        )
    )

    # Apply species filter if specified
    # SpeciesFilterMask is keyed by (clip_prediction_id, tag_id), so we need to
    # join on both columns to correctly filter by tag
    if filter_application is not None:
        query = query.join(
            models.SpeciesFilterMask,
            (models.ClipPrediction.id == models.SpeciesFilterMask.clip_prediction_id)
            & (models.Tag.id == models.SpeciesFilterMask.tag_id)
            & (models.SpeciesFilterMask.species_filter_application_id == filter_application.id),
        ).where(models.SpeciesFilterMask.is_included.is_(True))

    # Group by species, date, and hour
    query = query.group_by(
        models.Tag.canonical_name,
        models.Tag.vernacular_name,
        func.date(datetime_jst),
        extract("hour", datetime_jst),
    ).order_by(
        models.Tag.canonical_name,
        func.date(datetime_jst),
        extract("hour", datetime_jst),
    )

    result = await session.execute(query)
    rows = result.all()

    if not rows:
        return DetectionTemporalData(
            run_uuid=str(run_uuid),
            filter_application_uuid=str(filter_application_uuid) if filter_application_uuid else None,
            date_range=None,
            species=[],
        )

    # Aggregate results by species
    species_data: dict[str, dict] = defaultdict(lambda: {
        "common_name": None,
        "total_detections": 0,
        "detections": [],
        "dates": set(),
    })

    all_dates: set[dt.date] = set()

    for row in rows:
        scientific_name = row.scientific_name
        common_name = row.common_name
        detection_date = row.detection_date
        detection_hour = int(row.detection_hour)
        count = row.count

        # Update species data
        species_data[scientific_name]["common_name"] = common_name
        species_data[scientific_name]["total_detections"] += count
        species_data[scientific_name]["detections"].append(
            HourlyDetection(
                date=detection_date,
                hour=detection_hour,
                count=count,
            )
        )
        species_data[scientific_name]["dates"].add(detection_date)
        all_dates.add(detection_date)

    # Build species temporal data list
    species_list: list[SpeciesTemporalData] = []
    for scientific_name, data in sorted(
        species_data.items(),
        key=lambda x: -x[1]["total_detections"],  # Sort by total detections desc
    ):
        species_list.append(
            SpeciesTemporalData(
                scientific_name=scientific_name,
                common_name=data["common_name"],
                total_detections=data["total_detections"],
                detections=data["detections"],
            )
        )

    # Compute date range
    date_range: tuple[dt.date, dt.date] | None = None
    if all_dates:
        date_range = (min(all_dates), max(all_dates))

    return DetectionTemporalData(
        run_uuid=str(run_uuid),
        filter_application_uuid=str(filter_application_uuid) if filter_application_uuid else None,
        date_range=date_range,
        species=species_list,
    )
