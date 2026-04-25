"""Detection annotation management API endpoints.

Phase 3 (T120, FR-006 / FR-008 / FR-008a): every read, export, and mutating
path operation now routes through the central :func:`is_allowed` gate using the
Action catalog in :mod:`echoroo.core.actions`.
"""

from __future__ import annotations

import io
from typing import Annotated, TypeVar
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from echoroo.core.actions import (
    ANNOTATION_VOTE_CREATE_ACTION,
    ANNOTATION_VOTE_LIST_ACTION,
    DETECTION_CHANGE_SPECIES_ACTION,
    DETECTION_CONFIRM_ACTION,
    DETECTION_CREATE_ACTION,
    DETECTION_DELETE_ACTION,
    DETECTION_EXPORT_CSV_ACTION,
    DETECTION_EXPORT_ML_DATASET_ACTION,
    DETECTION_GET_ACTION,
    DETECTION_LIST_ACTION,
    DETECTION_REJECT_ACTION,
)
from echoroo.core.database import DbSession
from echoroo.core.permissions import Permission, gate_action
from echoroo.core.response_filter import (
    MASKED_SPECIES_LABEL,
    _should_mask_species,
    apply_response_filter,
)
from echoroo.middleware.auth import CurrentUser
from echoroo.models.enums import DetectionStatus
from echoroo.repositories.annotation import AnnotationRepository
from echoroo.repositories.annotation_vote import AnnotationVoteRepository
from echoroo.repositories.confirmed_region import ConfirmedRegionRepository
from echoroo.repositories.detection_run import DetectionRunRepository
from echoroo.repositories.recording import RecordingRepository
from echoroo.repositories.tag import TagRepository
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
        recording_repo=RecordingRepository(db),
        tag_repo=TagRepository(db),
        detection_run_repo=DetectionRunRepository(db),
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
ResponseT = TypeVar("ResponseT")


def _apply_detection_response_filter(
    obj: ResponseT,
    *,
    request: Request,
    project: object,
) -> ResponseT:
    """Apply FR-011 response filtering with Phase 11 sensitivity placeholders."""
    state = request.state
    effective: frozenset[Permission] = getattr(state, "effective_permissions", frozenset())
    role: str = getattr(state, "normalized_role", "Guest")

    # TODO(Phase 11): replace empty maps with taxon_sensitivity_map /
    # override_map bulk preloaders.
    apply_response_filter(
        obj=obj,
        effective_permissions=effective,
        normalized_role=role,
        project=project,
        resource=obj,
        taxon_sensitivity_map={},
        override_map={},
    )
    return obj


def _mask_species_summary_item_names(
    *,
    item: object,
    request: Request,
    project: object,
) -> None:
    """Mask aggregate species labels that are outside DetectionResponse shapes."""
    role: str = getattr(request.state, "normalized_role", "Guest")
    if not _should_mask_species(project, role):
        return
    for field in ("tag_name", "scientific_name", "common_name"):
        if hasattr(item, field):
            setattr(item, field, MASKED_SPECIES_LABEL)


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
    project = await gate_action(
        action=DETECTION_LIST_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    min_votes = project.review_min_votes
    threshold = project.review_consensus_threshold
    state = request.state
    effective: frozenset[Permission] = getattr(state, "effective_permissions", frozenset())
    role: str = getattr(state, "normalized_role", "Guest")

    result = await service.list_detections(
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
    # TODO(Phase 11): replace empty maps with taxon_sensitivity_map /
    # override_map bulk preloaders.
    for item in result.items:
        apply_response_filter(
            obj=item,
            effective_permissions=effective,
            normalized_role=role,
            project=project,
            resource=item,
            taxon_sensitivity_map={},
            override_map={},
        )
    return result


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
    project = await gate_action(
        action=DETECTION_LIST_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    result = await service.get_species_summary(
        project_id=project_id,
        dataset_id=dataset_id,
        detection_run_id=detection_run_id,
        locale=locale,
    )
    for item in result.items:
        _apply_detection_response_filter(
            item,
            request=request,
            project=project,
        )
        _mask_species_summary_item_names(
            item=item,
            request=request,
            project=project,
        )
    return result


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
    await gate_action(
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
    await gate_action(
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
    project = await gate_action(
        action=DETECTION_LIST_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    result = await service.get_temporal_data(
        project_id=project_id,
        dataset_id=dataset_id,
        detection_run_id=detection_run_id,
        locale=locale,
    )
    for item in result.species:
        _apply_detection_response_filter(
            item,
            request=request,
            project=project,
        )
    return result


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
    project = await gate_action(
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

    state = request.state
    effective: frozenset[Permission] = getattr(state, "effective_permissions", frozenset())
    role: str = getattr(state, "normalized_role", "Guest")

    result = await service.get(
        detection_id=detection_id,
        current_user_id=current_user.id,
        min_votes=min_votes,
        threshold=threshold,
        locale=locale,
    )
    # TODO(Phase 11): replace empty maps with taxon_sensitivity_map /
    # override_map bulk preloaders.
    apply_response_filter(
        obj=result,
        effective_permissions=effective,
        normalized_role=role,
        project=project,
        resource=result,
        taxon_sensitivity_map={},
        override_map={},
    )
    return result


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
    http_request: Request,
    current_user: CurrentUser,
    service: DetectionServiceDep,
    db: DbSession,
) -> DetectionResponse:
    """Create a new detection annotation.

    Guarded by :data:`DETECTION_CREATE_ACTION` (:data:`Permission.ANNOTATE`).

    Args:
        project_id: Project's UUID
        request: Detection creation data
        http_request: FastAPI request (used by ``is_allowed`` to stash stage-1 state)
        current_user: Current authenticated user
        service: Detection service instance
        db: Database session

    Returns:
        Created detection annotation

    Raises:
        401: Not authenticated
        403: Permission denied
        422: Validation error
    """
    project = await gate_action(
        action=DETECTION_CREATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    detection = await service.create(project_id=project_id, request=request)
    await db.commit()
    return _apply_detection_response_filter(
        detection,
        request=http_request,
        project=project,
    )


@router.post(
    "/{detection_id}/confirm",
    response_model=DetectionResponse,
    summary="Confirm detection",
    description="Confirm a detection annotation and create a confirmed region",
)
async def confirm_detection(
    project_id: UUID,
    detection_id: UUID,
    http_request: Request,
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
        http_request: FastAPI request (used by ``is_allowed`` to stash stage-1 state)
        request: Confirm request with time range
        current_user: Current authenticated user
        service: Detection service instance
        db: Database session

    Returns:
        Updated detection annotation

    Raises:
        401: Not authenticated
        403: Permission denied
        404: Detection not found
    """
    project = await gate_action(
        action=DETECTION_CONFIRM_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    if not await service.annotation_repo.exists_in_project(detection_id, project_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="detection not found",
        )

    detection = await service.confirm(
        detection_id=detection_id,
        user_id=current_user.id,
        request=request,
    )
    await db.commit()
    return _apply_detection_response_filter(
        detection,
        request=http_request,
        project=project,
    )


@router.post(
    "/{detection_id}/reject",
    response_model=DetectionResponse,
    summary="Reject detection",
    description="Reject a detection annotation",
)
async def reject_detection(
    project_id: UUID,
    detection_id: UUID,
    http_request: Request,
    current_user: CurrentUser,
    service: DetectionServiceDep,
    db: DbSession,
    request: RejectRequest | None = None,  # noqa: ARG001
) -> DetectionResponse:
    """Reject a detection annotation.

    Args:
        project_id: Project's UUID
        detection_id: Detection's UUID
        http_request: FastAPI request (used by ``is_allowed`` to stash stage-1 state)
        request: Reject request (no additional fields required)
        current_user: Current authenticated user
        service: Detection service instance
        db: Database session

    Returns:
        Updated detection annotation

    Raises:
        401: Not authenticated
        403: Permission denied
        404: Detection not found
    """
    project = await gate_action(
        action=DETECTION_REJECT_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    if not await service.annotation_repo.exists_in_project(detection_id, project_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="detection not found",
        )

    detection = await service.reject(
        detection_id=detection_id,
        user_id=current_user.id,
    )
    await db.commit()
    return _apply_detection_response_filter(
        detection,
        request=http_request,
        project=project,
    )


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
    http_request: Request,
    current_user: CurrentUser,
    service: DetectionServiceDep,
    db: DbSession,
) -> DetectionResponse:
    """Change the species tag of a detection annotation.

    Args:
        project_id: Project's UUID
        detection_id: Detection's UUID
        request: Change species request with new tag and optional time range
        http_request: FastAPI request (used by ``is_allowed`` to stash stage-1 state)
        current_user: Current authenticated user
        service: Detection service instance
        db: Database session

    Returns:
        Updated detection annotation

    Raises:
        401: Not authenticated
        403: Permission denied
        404: Detection not found
    """
    project = await gate_action(
        action=DETECTION_CHANGE_SPECIES_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    if not await service.annotation_repo.exists_in_project(detection_id, project_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="detection not found",
        )

    detection = await service.change_species(
        detection_id=detection_id,
        request=request,
        user_id=current_user.id,
        project_id=project_id,
    )
    await db.commit()
    return _apply_detection_response_filter(
        detection,
        request=http_request,
        project=project,
    )


@router.get(
    "/{detection_id}/votes",
    response_model=VoteSummaryResponse,
    summary="Get vote summary",
    description="Get vote counts and individual votes for a detection annotation",
)
async def get_votes(
    project_id: UUID,
    detection_id: UUID,
    request: Request,
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
        request: FastAPI request (used by ``is_allowed`` to stash stage-1 state)
        current_user: Current authenticated user
        vote_service: Vote service instance
        db: Database session

    Returns:
        Vote summary response

    Raises:
        401: Not authenticated
        403: Permission denied
        404: Detection not found
    """
    await gate_action(
        action=ANNOTATION_VOTE_LIST_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    if not await vote_service.annotation_repo.exists_in_project(detection_id, project_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="detection not found",
        )

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
    http_request: Request,
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
        http_request: FastAPI request (used by ``is_allowed`` to stash stage-1 state)
        current_user: Current authenticated user
        vote_service: Vote service instance
        db: Database session

    Returns:
        Updated vote summary response

    Raises:
        401: Not authenticated
        403: Permission denied
        404: Detection not found
        422: Validation error
    """
    project = await gate_action(
        action=ANNOTATION_VOTE_CREATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    if not await vote_service.annotation_repo.exists_in_project(detection_id, project_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="detection not found",
        )

    min_votes = project.review_min_votes
    threshold = project.review_consensus_threshold

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
    request: Request,
    current_user: CurrentUser,
    vote_service: VoteServiceDep,
    db: DbSession,
) -> VoteSummaryResponse:
    """Remove the current user's vote from a detection annotation.

    The annotation status is recomputed from remaining votes after deletion.

    Args:
        project_id: Project's UUID
        detection_id: Detection's UUID
        request: FastAPI request (used by ``is_allowed`` to stash stage-1 state)
        current_user: Current authenticated user
        vote_service: Vote service instance
        db: Database session

    Returns:
        Updated vote summary response

    Raises:
        401: Not authenticated
        403: Permission denied
        404: Detection not found or no vote to delete
    """
    project = await gate_action(
        action=ANNOTATION_VOTE_CREATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    if not await vote_service.annotation_repo.exists_in_project(detection_id, project_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="detection not found",
        )

    min_votes = project.review_min_votes
    threshold = project.review_consensus_threshold

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
    request: Request,
    current_user: CurrentUser,
    service: DetectionServiceDep,
    db: DbSession,
) -> None:
    """Delete detection annotation.

    Args:
        project_id: Project's UUID
        detection_id: Detection's UUID
        request: FastAPI request (used by ``is_allowed`` to stash stage-1 state)
        current_user: Current authenticated user
        service: Detection service instance
        db: Database session

    Raises:
        401: Not authenticated
        403: Permission denied
        404: Detection not found
    """
    await gate_action(
        action=DETECTION_DELETE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    if not await service.annotation_repo.exists_in_project(detection_id, project_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="detection not found",
        )

    await service.delete(detection_id=detection_id)
    await db.commit()
