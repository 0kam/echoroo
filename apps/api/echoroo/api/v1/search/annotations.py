"""Search annotation creation endpoint.

Provides an endpoint to create annotation records from similarity search matches.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from echoroo.api.v1.search.utils import _annotation_to_detection_response
from echoroo.core.database import DbSession
from echoroo.core.permissions import check_project_access
from echoroo.middleware.auth import CurrentUser
from echoroo.models.enums import DetectionSource, DetectionStatus
from echoroo.models.recording_annotation import (
    RecordingAnnotation as Annotation,  # Phase 14+ deferred (was rich-shape Annotation)
)
from echoroo.schemas.detection import DetectionResponse
from echoroo.schemas.search import SearchAnnotationCreate

logger = logging.getLogger(__name__)

annotations_router = APIRouter(prefix="/projects/{project_id}/annotations", tags=["search"])


@annotations_router.post(
    "",
    response_model=DetectionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create annotation from search match",
    description=(
        "Create an annotation record from a similarity search match. "
        "If an annotation already exists for the same recording, tag, and time range "
        "(within 0.1 s tolerance), the existing annotation is returned instead of "
        "creating a duplicate."
    ),
)
async def create_search_annotation(
    project_id: UUID,
    request: SearchAnnotationCreate,
    current_user: CurrentUser,
    db: DbSession,
) -> DetectionResponse:
    """Create an annotation from a similarity search match.

    Checks for an existing annotation with the same recording_id, tag_id, and
    overlapping time range (start_time and end_time within 0.1 s) to avoid
    duplicate records. Returns the existing annotation if a duplicate is found.

    Args:
        project_id: Project UUID (path parameter)
        request: Annotation creation data
        current_user: Current authenticated user
        db: Database session

    Returns:
        Created or existing annotation

    Raises:
        403: Access denied to project
        422: Invalid source or status value
    """
    await check_project_access(project_id, current_user.id, db)

    # Validate source enum
    try:
        source = DetectionSource(request.source)
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid source value: {request.source!r}. "
            f"Valid values: {[e.value for e in DetectionSource]}",
        ) from err

    # Validate review_status enum
    try:
        ann_status = DetectionStatus(request.review_status)
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid review_status value: {request.review_status!r}. "
            f"Valid values: {[e.value for e in DetectionStatus]}",
        ) from err

    # Check for existing annotation with same recording, tag, and time range
    # (within 0.1 s tolerance to avoid floating point issues)
    TOLERANCE = 0.1

    duplicate_check = await db.execute(
        select(Annotation)
        .where(Annotation.recording_id == request.recording_id)
        .where(Annotation.tag_id == request.tag_id)
        .where(Annotation.start_time >= request.start_time - TOLERANCE)
        .where(Annotation.start_time <= request.start_time + TOLERANCE)
        .where(Annotation.end_time >= request.end_time - TOLERANCE)
        .where(Annotation.end_time <= request.end_time + TOLERANCE)
        .options(
            selectinload(Annotation.recording),
            selectinload(Annotation.tag),
            selectinload(Annotation.detection_run),
            selectinload(Annotation.reviewed_by),
        )
        .limit(1)
    )
    existing = duplicate_check.scalar_one_or_none()

    if existing is not None:
        return _annotation_to_detection_response(existing)

    # Create new annotation
    annotation = Annotation(
        recording_id=request.recording_id,
        tag_id=request.tag_id,
        detection_run_id=None,
        source=source,
        status=ann_status,
        confidence=request.confidence,
        start_time=request.start_time,
        end_time=request.end_time,
        search_session_id=request.search_session_id,
    )
    db.add(annotation)

    # Flush to obtain the annotation ID without committing, then update review
    # counts within the same transaction so both changes land in a single commit.
    await db.flush()

    if request.search_session_id is not None:
        from echoroo.services.search_session import SearchSessionService

        session_svc = SearchSessionService(db)
        await session_svc.update_review_counts(request.search_session_id)

    # Refresh relationships before committing so the response is fully populated.
    await db.refresh(annotation, ["recording", "tag", "detection_run", "reviewed_by"])
    await db.commit()

    return _annotation_to_detection_response(annotation)
