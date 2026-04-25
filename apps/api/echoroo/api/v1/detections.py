"""Detection annotation management API endpoints.

Phase 3 (T120, FR-006 / FR-008 / FR-008a): every read / export path operation
now routes through the central :func:`is_allowed` gate using the Action catalog
in :mod:`echoroo.core.actions`. Mutating endpoints (create / confirm / reject /
change-species / votes / delete) are guarded in subsequent tasks; until then
they keep the legacy :func:`check_project_access` membership check so the
existing test suite continues to pass.
"""

from __future__ import annotations

import io
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select as sa_select

from echoroo.core.actions import (
    DETECTION_EXPORT_CSV_ACTION,
    DETECTION_EXPORT_ML_DATASET_ACTION,
    DETECTION_GET_ACTION,
    DETECTION_LIST_ACTION,
)
from echoroo.core.database import DbSession
from echoroo.core.permissions import (
    Action,
    check_project_access,
    is_allowed,
)
from echoroo.middleware.auth import CurrentUser
from echoroo.models.enums import DetectionStatus
from echoroo.models.project import Project
from echoroo.repositories.annotation import AnnotationRepository
from echoroo.repositories.annotation_vote import AnnotationVoteRepository
from echoroo.repositories.confirmed_region import ConfirmedRegionRepository
from echoroo.schemas.annotation_vote import VoteCastRequest, VoteSummaryResponse
from echoroo.schemas.detection import (
    ChangeSpeciesRequest,
    ConfirmRequest,
    DetectionCreate,
    DetectionListResponse,
    DetectionResponse,
    DetectionTemporalDataResponse,
    RejectRequest,
    SpeciesSummaryResponse,
)
from echoroo.services.annotation_vote import AnnotationVoteService
from echoroo.services.detection import DetectionService
from echoroo.services.detection_export import DetectionExportService

router = APIRouter(prefix="/projects/{project_id}/detections", tags=["detections"])


def get_detection_service(db: DbSession) -> DetectionService:
    """Get DetectionService instance.

    Args:
        db: Database session

    Returns:
        DetectionService instance
    """
    return DetectionService(
        annotation_repo=AnnotationRepository(db),
        confirmed_region_repo=ConfirmedRegionRepository(db),
        vote_repo=AnnotationVoteRepository(db),
    )


def get_vote_service(db: DbSession) -> AnnotationVoteService:
    """Get AnnotationVoteService instance.

    Args:
        db: Database session

    Returns:
        AnnotationVoteService instance
    """
    return AnnotationVoteService(
        vote_repo=AnnotationVoteRepository(db),
        annotation_repo=AnnotationRepository(db),
    )


DetectionServiceDep = Annotated[DetectionService, Depends(get_detection_service)]
VoteServiceDep = Annotated[AnnotationVoteService, Depends(get_vote_service)]


# ---------------------------------------------------------------------------
# Internal helpers (Phase 3 permission gate)
# ---------------------------------------------------------------------------


async def _load_project(db: DbSession, project_id: UUID) -> Project:
    """Load the Project ORM row needed by :func:`is_allowed`.

    The gate reads ``visibility`` / ``restricted_config`` / ``status`` /
    ``owner_id`` from the row, so a regular ORM load is sufficient.
    """
    project_result = await db.execute(sa_select(Project).where(Project.id == project_id))
    project = project_result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="project not found")
    return project


async def _gate(
    *,
    action: Action,
    project_id: UUID,
    current_user: Any,
    request: Request,
    db: DbSession,
) -> Project:
    """Run the Stage-1 :func:`is_allowed` gate for ``action`` on ``project_id``.

    Returns the loaded :class:`Project` row so callers can pass it through to
    the service layer (e.g. for response filtering / restricted_config reads)
    without issuing a second SELECT.
    """
    project = await _load_project(db, project_id)
    allowed, _ = is_allowed(
        action=action,
        user=current_user,
        project=project,
        request=request,
    )
    if not allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="action denied")
    return project


@router.get(
    "",
    response_model=DetectionListResponse,
    summary="List detections",
    description="List detection annotations for a project with optional filters",
)
async def list_detections(
    project_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: DetectionServiceDep,
    db: DbSession,
    tag_id: UUID | None = None,
    status: DetectionStatus | None = None,
    confidence_min: float | None = None,
    confidence_max: float | None = None,
    dataset_id: UUID | None = None,
    recording_id: UUID | None = None,
    detection_run_id: UUID | None = None,
    page: int = 1,
    page_size: int = 50,
    locale: str = Query(
        "en",
        pattern="^(en|ja)$",
        description="Locale code for vernacular name resolution (en, ja)",
    ),
) -> DetectionListResponse:
    """List detection annotations for a project.

    Guarded by :data:`DETECTION_LIST_ACTION`
    (:data:`Permission.VIEW_DETECTION`). Public / Restricted projects allow
    Guest reads via the canonical matrix; the gate enforces it.

    Args:
        project_id: Project's UUID
        request: FastAPI request (used by ``is_allowed`` to stash stage-1 state)
        current_user: Current authenticated user
        service: Detection service instance
        db: Database session
        tag_id: Optional tag filter
        status: Optional review status filter
        confidence_min: Optional minimum confidence filter
        confidence_max: Optional maximum confidence filter
        dataset_id: Optional dataset filter
        recording_id: Optional recording filter
        detection_run_id: Optional detection run filter
        page: Page number (default: 1)
        page_size: Items per page (default: 50)
        locale: Locale code used to populate ``vernacular_name`` on embedded tags

    Returns:
        Paginated list of detections

    Raises:
        401: Not authenticated
        403: Permission denied
    """
    project = await _gate(
        action=DETECTION_LIST_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    min_votes = project.review_min_votes
    threshold = project.review_consensus_threshold

    # TODO(T130-T134, FR-006/011/016): apply Stage-2 response filter
    # (mask_species_in_detection / H3 generalisation) using the
    # ``effective_permissions`` + ``normalized_role`` stashed on
    # ``request.state`` by ``is_allowed``. Pending the bulk taxon
    # sensitivity preload utility.
    return await service.list_detections(
        project_id=project_id,
        tag_id=tag_id,
        status=status,
        confidence_min=confidence_min,
        confidence_max=confidence_max,
        dataset_id=dataset_id,
        recording_id=recording_id,
        detection_run_id=detection_run_id,
        page=page,
        page_size=page_size,
        current_user_id=current_user.id,
        min_votes=min_votes,
        threshold=threshold,
        locale=locale,
    )


@router.get(
    "/species-summary",
    response_model=SpeciesSummaryResponse,
    summary="Species detection summary",
    description="Get detection counts and statistics grouped by species tag",
)
async def get_species_summary(
    project_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: DetectionServiceDep,
    db: DbSession,
    dataset_id: UUID | None = None,
    detection_run_id: UUID | None = None,
    locale: str = Query(
        "en",
        pattern="^(en|ja)$",
        description="Locale code for vernacular name resolution (en, ja)",
    ),
) -> SpeciesSummaryResponse:
    """Get species detection summary.

    NOTE: This route must appear before /{detection_id} to avoid routing conflicts.

    Guarded by :data:`DETECTION_LIST_ACTION` (this is a list-shaped read of
    detections aggregated per species, so it shares the LIST permission).

    Args:
        project_id: Project's UUID
        request: FastAPI request
        current_user: Current authenticated user
        service: Detection service instance
        db: Database session
        dataset_id: Optional dataset filter
        detection_run_id: Optional detection run filter
        locale: Locale code for common name resolution (default: "en")

    Returns:
        Species summary with per-species detection statistics

    Raises:
        401: Not authenticated
        403: Permission denied
    """
    await _gate(
        action=DETECTION_LIST_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await service.get_species_summary(
        project_id=project_id,
        dataset_id=dataset_id,
        detection_run_id=detection_run_id,
        locale=locale,
    )


@router.get(
    "/export/csv",
    summary="Export detections as CSV",
    description="Export detection annotations as CSV with optional filters",
)
async def export_csv(
    project_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    status: DetectionStatus | None = None,
    tag_id: UUID | None = None,
    dataset_id: UUID | None = None,
    detection_run_id: UUID | None = None,
) -> StreamingResponse:
    """Export detections as a CSV file.

    NOTE: This route must appear before /{detection_id} to avoid routing conflicts.

    Guarded by :data:`DETECTION_EXPORT_CSV_ACTION`
    (:data:`Permission.EXPORT`). Restricted projects gate this on
    ``allow_export``.

    Args:
        project_id: Project's UUID
        request: FastAPI request
        current_user: Current authenticated user
        db: Database session
        status: Optional detection status filter
        tag_id: Optional tag UUID filter
        dataset_id: Optional dataset UUID filter
        detection_run_id: Optional detection run UUID filter

    Returns:
        StreamingResponse with CSV content (text/csv)

    Raises:
        401: Not authenticated
        403: Permission denied
    """
    await _gate(
        action=DETECTION_EXPORT_CSV_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    service = DetectionExportService(db)
    csv_content = await service.export_csv(
        project_id=project_id,
        status=status,
        tag_id=tag_id,
        dataset_id=dataset_id,
        detection_run_id=detection_run_id,
    )
    return StreamingResponse(
        io.BytesIO(csv_content.encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=detections.csv"},
    )


@router.get(
    "/export/ml-dataset",
    summary="Export ML training dataset",
    description="Export confirmed detections as a ZIP-archived ML training dataset",
)
async def export_ml_dataset(
    project_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    dataset_id: UUID | None = None,
    detection_run_id: UUID | None = None,
) -> StreamingResponse:
    """Export confirmed detections as a ZIP ML training dataset.

    The archive contains annotations.csv, metadata.json, and README.txt.
    Positive entries are confirmed annotations; negative entries are confirmed
    regions with no overlapping confirmed annotation.

    NOTE: This route must appear before /{detection_id} to avoid routing conflicts.

    Guarded by :data:`DETECTION_EXPORT_ML_DATASET_ACTION`
    (:data:`Permission.EXPORT`).

    Args:
        project_id: Project's UUID
        request: FastAPI request
        current_user: Current authenticated user
        db: Database session
        dataset_id: Optional dataset UUID filter
        detection_run_id: Optional detection run UUID filter

    Returns:
        StreamingResponse with ZIP content (application/zip)

    Raises:
        401: Not authenticated
        403: Permission denied
    """
    await _gate(
        action=DETECTION_EXPORT_ML_DATASET_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    service = DetectionExportService(db)
    zip_content = await service.export_ml_dataset(
        project_id=project_id,
        dataset_id=dataset_id,
        detection_run_id=detection_run_id,
    )
    return StreamingResponse(
        io.BytesIO(zip_content),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=ml-dataset.zip"},
    )


@router.get(
    "/temporal-data",
    response_model=DetectionTemporalDataResponse,
    summary="Detection temporal data",
    description="Get hourly detection counts grouped by species, date, and hour for visualization",
)
async def get_temporal_data(
    project_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: DetectionServiceDep,
    db: DbSession,
    dataset_id: UUID | None = None,
    detection_run_id: UUID | None = None,
    locale: str = Query(
        "en",
        pattern="^(en|ja)$",
        description="Locale code for vernacular name resolution (en, ja)",
    ),
) -> DetectionTemporalDataResponse:
    """Get temporal detection data for visualization.

    Returns hourly detection counts per species, suitable for heatmap or
    time-series visualizations.

    NOTE: This route must appear before /{detection_id} to avoid routing conflicts.

    Guarded by :data:`DETECTION_LIST_ACTION` (aggregate read of detections).

    Args:
        project_id: Project's UUID
        request: FastAPI request
        current_user: Current authenticated user
        service: Detection service instance
        db: Database session
        dataset_id: Optional dataset filter
        detection_run_id: Optional detection run filter
        locale: Locale code for common name resolution (default: "en")

    Returns:
        Temporal data response grouped by species with hourly counts

    Raises:
        401: Not authenticated
        403: Permission denied
    """
    await _gate(
        action=DETECTION_LIST_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await service.get_temporal_data(
        project_id=project_id,
        dataset_id=dataset_id,
        detection_run_id=detection_run_id,
        locale=locale,
    )


@router.get(
    "/{detection_id}",
    response_model=DetectionResponse,
    summary="Get detection",
    description="Get a detection annotation by ID",
)
async def get_detection(
    project_id: UUID,
    detection_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: DetectionServiceDep,
    db: DbSession,
    locale: str = Query(
        "en",
        pattern="^(en|ja)$",
        description="Locale code for vernacular name resolution (en, ja)",
    ),
) -> DetectionResponse:
    """Get detection by ID.

    Guarded by :data:`DETECTION_GET_ACTION`
    (:data:`Permission.VIEW_DETECTION`).

    Args:
        project_id: Project's UUID
        detection_id: Detection's UUID
        request: FastAPI request
        current_user: Current authenticated user
        service: Detection service instance
        db: Database session
        locale: Locale code used to populate ``vernacular_name`` on the embedded tag

    Returns:
        Detection annotation detail

    Raises:
        401: Not authenticated
        403: Permission denied
        404: Detection not found
    """
    project = await _gate(
        action=DETECTION_GET_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    min_votes = project.review_min_votes
    threshold = project.review_consensus_threshold

    # BOLA / IDOR guard (FR-008 / FR-008a): the detection (annotation) must
    # belong to the gated project — verify via
    # Annotation -> Recording -> Dataset -> Project before serving the row.
    if not await service.annotation_repo.exists_in_project(detection_id, project_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Detection not found",
        )

    # TODO(T130-T134, FR-006/011/016): apply Stage-2 response filter using
    # the stashed ``request.state.effective_permissions`` /
    # ``request.state.normalized_role`` once the bulk taxon-sensitivity
    # preloader is wired up.
    return await service.get(
        detection_id=detection_id,
        current_user_id=current_user.id,
        min_votes=min_votes,
        threshold=threshold,
        locale=locale,
    )


@router.post(
    "",
    response_model=DetectionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create detection",
    description="Create a new detection annotation",
)
async def create_detection(
    project_id: UUID,
    request: DetectionCreate,
    current_user: CurrentUser,
    service: DetectionServiceDep,
    db: DbSession,
) -> DetectionResponse:
    """Create a new detection annotation.

    Mutating endpoint — Phase 3 will introduce a dedicated DETECTION_CREATE
    Action; until then we keep the legacy membership check so contract tests
    still pass.

    Args:
        project_id: Project's UUID
        request: Detection creation data
        current_user: Current authenticated user
        service: Detection service instance
        db: Database session

    Returns:
        Created detection annotation

    Raises:
        401: Not authenticated
        403: Access denied to project
        422: Validation error
    """
    await check_project_access(project_id, current_user.id, db)
    detection = await service.create(project_id=project_id, request=request)
    await db.commit()
    return detection


@router.post(
    "/{detection_id}/confirm",
    response_model=DetectionResponse,
    summary="Confirm detection",
    description="Confirm a detection annotation and create a confirmed region",
)
async def confirm_detection(
    project_id: UUID,
    detection_id: UUID,
    current_user: CurrentUser,
    service: DetectionServiceDep,
    db: DbSession,
    request: ConfirmRequest | None = None,
) -> DetectionResponse:
    """Confirm a detection annotation.

    Sets the status to confirmed, records the reviewer, and creates a
    ConfirmedRegion for the confirmed time range.

    Args:
        project_id: Project's UUID
        detection_id: Detection's UUID
        request: Confirm request with time range
        current_user: Current authenticated user
        service: Detection service instance
        db: Database session

    Returns:
        Updated detection annotation

    Raises:
        401: Not authenticated
        403: Access denied to project
        404: Detection not found
    """
    await check_project_access(project_id, current_user.id, db)
    detection = await service.confirm(
        detection_id=detection_id,
        user_id=current_user.id,
        request=request,
    )
    await db.commit()
    return detection


@router.post(
    "/{detection_id}/reject",
    response_model=DetectionResponse,
    summary="Reject detection",
    description="Reject a detection annotation",
)
async def reject_detection(
    project_id: UUID,
    detection_id: UUID,
    current_user: CurrentUser,
    service: DetectionServiceDep,
    db: DbSession,
    request: RejectRequest | None = None,  # noqa: ARG001
) -> DetectionResponse:
    """Reject a detection annotation.

    Args:
        project_id: Project's UUID
        detection_id: Detection's UUID
        request: Reject request (no additional fields required)
        current_user: Current authenticated user
        service: Detection service instance
        db: Database session

    Returns:
        Updated detection annotation

    Raises:
        401: Not authenticated
        403: Access denied to project
        404: Detection not found
    """
    await check_project_access(project_id, current_user.id, db)
    detection = await service.reject(
        detection_id=detection_id,
        user_id=current_user.id,
    )
    await db.commit()
    return detection


@router.post(
    "/{detection_id}/change-species",
    response_model=DetectionResponse,
    summary="Change species",
    description="Change the species tag of a detection annotation",
)
async def change_species(
    project_id: UUID,
    detection_id: UUID,
    request: ChangeSpeciesRequest,
    current_user: CurrentUser,
    service: DetectionServiceDep,
    db: DbSession,
) -> DetectionResponse:
    """Change the species tag of a detection annotation.

    Args:
        project_id: Project's UUID
        detection_id: Detection's UUID
        request: Change species request with new tag and optional time range
        current_user: Current authenticated user
        service: Detection service instance
        db: Database session

    Returns:
        Updated detection annotation

    Raises:
        401: Not authenticated
        403: Access denied to project
        404: Detection not found
    """
    await check_project_access(project_id, current_user.id, db)
    detection = await service.change_species(
        detection_id=detection_id,
        request=request,
        user_id=current_user.id,
    )
    await db.commit()
    return detection


@router.get(
    "/{detection_id}/votes",
    response_model=VoteSummaryResponse,
    summary="Get vote summary",
    description="Get vote counts and individual votes for a detection annotation",
)
async def get_votes(
    project_id: UUID,
    detection_id: UUID,
    current_user: CurrentUser,
    vote_service: VoteServiceDep,
    db: DbSession,
) -> VoteSummaryResponse:
    """Get vote summary for a detection annotation.

    Returns aggregate agree/disagree/unsure counts, the current user's vote,
    the computed consensus status, and the full list of individual votes.

    Args:
        project_id: Project's UUID
        detection_id: Detection's UUID
        current_user: Current authenticated user
        vote_service: Vote service instance
        db: Database session

    Returns:
        Vote summary response

    Raises:
        401: Not authenticated
        403: Access denied to project
        404: Detection not found
    """
    await check_project_access(project_id, current_user.id, db)
    return await vote_service.get_vote_summary(
        annotation_id=detection_id,
        current_user_id=current_user.id,
    )


@router.post(
    "/{detection_id}/votes",
    response_model=VoteSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Cast vote",
    description="Cast or update a vote on a detection annotation",
)
async def cast_vote(
    project_id: UUID,
    detection_id: UUID,
    request: VoteCastRequest,
    current_user: CurrentUser,
    vote_service: VoteServiceDep,
    db: DbSession,
) -> VoteSummaryResponse:
    """Cast or update a vote on a detection annotation.

    If the current user has already voted on this annotation, their existing
    vote is replaced. The annotation status is recomputed from all votes
    after each cast.

    Args:
        project_id: Project's UUID
        detection_id: Detection's UUID
        request: Vote cast request (vote type, optional tag suggestion, note)
        current_user: Current authenticated user
        vote_service: Vote service instance
        db: Database session

    Returns:
        Updated vote summary response

    Raises:
        401: Not authenticated
        403: Access denied to project
        404: Detection not found
        422: Validation error
    """
    await check_project_access(project_id, current_user.id, db)

    # Retrieve project settings for consensus thresholds
    project_result = await db.execute(sa_select(Project).where(Project.id == project_id))
    project = project_result.scalar_one_or_none()
    min_votes = project.review_min_votes if project else 2
    threshold = project.review_consensus_threshold if project else 0.667

    summary = await vote_service.cast_vote(
        annotation_id=detection_id,
        user_id=current_user.id,
        request=request,
        min_votes=min_votes,
        threshold=threshold,
    )
    await db.commit()
    return summary


@router.delete(
    "/{detection_id}/votes",
    response_model=VoteSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Remove vote",
    description="Remove the current user's vote from a detection annotation",
)
async def delete_vote(
    project_id: UUID,
    detection_id: UUID,
    current_user: CurrentUser,
    vote_service: VoteServiceDep,
    db: DbSession,
) -> VoteSummaryResponse:
    """Remove the current user's vote from a detection annotation.

    The annotation status is recomputed from remaining votes after deletion.

    Args:
        project_id: Project's UUID
        detection_id: Detection's UUID
        current_user: Current authenticated user
        vote_service: Vote service instance
        db: Database session

    Returns:
        Updated vote summary response

    Raises:
        401: Not authenticated
        403: Access denied to project
        404: Detection not found or no vote to delete
    """
    await check_project_access(project_id, current_user.id, db)

    project_result = await db.execute(sa_select(Project).where(Project.id == project_id))
    project = project_result.scalar_one_or_none()
    min_votes = project.review_min_votes if project else 2
    threshold = project.review_consensus_threshold if project else 0.667

    summary = await vote_service.delete_vote(
        annotation_id=detection_id,
        user_id=current_user.id,
        min_votes=min_votes,
        threshold=threshold,
    )
    await db.commit()
    return summary


@router.delete(
    "/{detection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete detection",
    description="Delete a detection annotation by ID",
)
async def delete_detection(
    project_id: UUID,
    detection_id: UUID,
    current_user: CurrentUser,
    service: DetectionServiceDep,
    db: DbSession,
) -> None:
    """Delete detection annotation.

    Args:
        project_id: Project's UUID
        detection_id: Detection's UUID
        current_user: Current authenticated user
        service: Detection service instance
        db: Database session

    Raises:
        401: Not authenticated
        403: Access denied to project
        404: Detection not found
    """
    await check_project_access(project_id, current_user.id, db)
    await service.delete(detection_id=detection_id)
    await db.commit()
