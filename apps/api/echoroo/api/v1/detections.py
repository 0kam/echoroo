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
from echoroo.services.annotation_vote import (
    AnnotationVoteService,
    classify_voter_source,
    resolve_viewer_role,
)
from echoroo.services.detection import DetectionService
from echoroo.services.detection_export import DetectionExportService
from echoroo.services.taxon_sensitivity_service import (
    bulk_load_override_map,
    bulk_load_sensitivity_map,
    is_iucn_fail_safe_active,
)

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


def _detection_taxon_key(item: object) -> str | None:
    """Return the GBIF species key embedded in a DetectionResponse, if any.

    Round 1 review C1 / FR-029 / FR-032 / FR-033: Phase 11's auto-obscure
    pipeline is keyed on the GBIF species key (a string) — that is the
    discriminator stored in :class:`TaxonSensitivity.taxon_id` and
    :class:`ProjectTaxonSensitivityOverride.taxon_id`. The DetectionResponse
    surface exposes it as ``tag.gbif_taxon_key`` (an ``int``); we coerce to
    ``str`` so the bulk preloaders see the same shape the maps are keyed by.
    Detections without a tag (or with a tag that has not been resolved to
    GBIF yet) return ``None`` and are excluded from the preload set.
    """
    tag = getattr(item, "tag", None)
    if tag is None:
        return None
    gbif_key = getattr(tag, "gbif_taxon_key", None)
    if gbif_key is None:
        return None
    return str(gbif_key)


def _detection_filter_resource(item: object) -> object:
    """Wrap a DetectionResponse so the response filter can read ``taxon_id``.

    The Stage-2 filter (and ``compute_effective_resolution``) keys off
    ``resource.taxon_id`` (str). DetectionResponse itself does not surface
    that key directly, so we expose a SimpleNamespace that mirrors the
    handful of attributes the filter touches: ``taxon_id`` from the tag's
    GBIF key, ``h3_index_member`` (currently absent on DetectionResponse —
    None falls through cleanly) and ``h3_index_member_resolution`` (defaults
    to :data:`H3_RES_15` so the filter's ``_compute_withheld_reason`` does
    not blow up on a None comparison).
    """
    from types import SimpleNamespace

    from echoroo.core.permissions import H3_RES_15

    return SimpleNamespace(
        taxon_id=_detection_taxon_key(item),
        h3_index_member=getattr(item, "h3_index_member", None),
        h3_index_member_resolution=(
            getattr(item, "h3_index_member_resolution", None) or H3_RES_15
        ),
    )


async def _build_detection_filter_maps(
    *,
    db: object,
    project_id: UUID,
    items: list[object],
) -> tuple[dict[str, int], dict[tuple[UUID, str], object]]:
    """Bulk-preload sensitivity + override maps for a list of detections.

    Round 1 review C1: the Stage-2 filter is only as accurate as the maps
    fed to it — passing the canonical empty dicts shipped pre-Round-1
    silently disabled FR-029 / FR-032 / FR-033 / FR-034 / FR-035 in the
    live API. This helper collects every GBIF taxon key surfaced by the
    response items, fires ONE sensitivity SELECT and ONE override SELECT
    (NFR-001a), and returns the two maps the filter expects.

    The sensitivity preload also consults the IUCN 14-day fail-safe flag
    (FR-036) so unknown taxa default to :data:`H3_RES_7` instead of the
    permissive :data:`H3_RES_9` while the upstream Red List sync is down.
    """
    taxon_ids = {key for key in (_detection_taxon_key(item) for item in items) if key}
    if not taxon_ids:
        return {}, {}
    fail_safe_active = await is_iucn_fail_safe_active()
    sensitivity_map = await bulk_load_sensitivity_map(
        db,  # type: ignore[arg-type]
        taxon_ids,
        iucn_fail_safe_active=fail_safe_active,
    )
    override_map = await bulk_load_override_map(
        db,  # type: ignore[arg-type]
        project_id,
        taxon_ids,
    )
    # ``override_map`` is typed as dict[tuple[UUID, str], ProjectTaxonSensitivityOverride]
    # by the loader; the response filter accepts the broader
    # ``Mapping[tuple[Any, str], Any]`` so the cast below is purely for typing.
    return sensitivity_map, dict(override_map)


async def _apply_detection_response_filter(
    obj: ResponseT,
    *,
    request: Request,
    project: object,
    db: object | None = None,
    project_id: UUID | None = None,
    sensitivity_map: dict[str, int] | None = None,
    override_map: dict[tuple[UUID, str], object] | None = None,
) -> ResponseT:
    """Apply FR-011 response filtering with Phase 11 sensitivity wiring.

    Round 1 review C1: callers MUST either (a) supply pre-loaded maps via
    ``sensitivity_map`` / ``override_map`` (the list-endpoint hot path), or
    (b) supply ``db`` + ``project_id`` so this helper can run the bulk
    preloaders itself for the single-item path. Passing both maps and
    db/project_id is harmless — the maps win. The request-scope cache
    (NFR-001a) makes a redundant preload call O(1) inside the same request.
    """
    state = request.state
    effective: frozenset[Permission] = getattr(state, "effective_permissions", frozenset())
    role: str = getattr(state, "normalized_role", "Guest")

    if (
        sensitivity_map is None
        and override_map is None
        and db is not None
        and project_id is not None
    ):
        sensitivity_map, override_map = await _build_detection_filter_maps(
            db=db,
            project_id=project_id,
            items=[obj],
        )

    apply_response_filter(
        obj=obj,
        effective_permissions=effective,
        normalized_role=role,
        project=project,
        resource=_detection_filter_resource(obj),
        taxon_sensitivity_map=sensitivity_map or {},
        override_map=override_map or {},
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
    for field in ("tag_name", "scientific_name", "common_name", "vernacular_name"):
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
    # Round 1 review C1: bulk-preload sensitivity + override maps once,
    # then apply Stage-2 filter per-item using the populated maps.
    sensitivity_map, override_map = await _build_detection_filter_maps(
        db=db,
        project_id=project_id,
        items=list(result.items),
    )
    for item in result.items:
        apply_response_filter(
            obj=item,
            effective_permissions=effective,
            normalized_role=role,
            project=project,
            resource=_detection_filter_resource(item),
            taxon_sensitivity_map=sensitivity_map,
            override_map=override_map,
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
    # Species summary aggregates have no per-row coordinate to generalise
    # (they are counts grouped by tag), so the empty-maps form of the
    # filter is sufficient. The companion ``_mask_species_summary_item_names``
    # call applies the FR-020 mask_species_in_detection toggle.
    for item in result.items:
        await _apply_detection_response_filter(
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
    # Phase 17 backlog A-5 (Hybrid Contract): switch from buffered
    # ``export_csv() -> str`` + ``io.BytesIO`` wrapper to row-by-row
    # streaming so :func:`recheck_action_permission` can fire every
    # ``CSV_RECHECK_INTERVAL`` rows. Pre-start gating remains via
    # ``gate_action`` above; mid-stream revoke truncates the body and
    # appends ``SENTINEL_BYTES``.
    body_iterator = service.export_csv_stream(
        project_id=project_id,
        action=DETECTION_EXPORT_CSV_ACTION,
        current_user=current_user,
        request=request,
        stream_type="csv_export",
        status=status,
        tag_id=tag_id,
        dataset_id=dataset_id,
        detection_run_id=detection_run_id,
    )
    return StreamingResponse(
        body_iterator,
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
        await _apply_detection_response_filter(
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
    # Round 1 review C1: even single-detection paths must run through the
    # bulk preloaders so the sensitivity / override maps are populated. The
    # request-scope cache (NFR-001a) makes this a no-op cost when the same
    # taxon was already loaded earlier in the request.
    sensitivity_map, override_map = await _build_detection_filter_maps(
        db=db,
        project_id=project_id,
        items=[result],
    )
    apply_response_filter(
        obj=result,
        effective_permissions=effective,
        normalized_role=role,
        project=project,
        resource=_detection_filter_resource(result),
        taxon_sensitivity_map=sensitivity_map,
        override_map=override_map,
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
    return await _apply_detection_response_filter(
        detection,
        request=http_request,
        project=project,
        db=db,
        project_id=project_id,
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
    return await _apply_detection_response_filter(
        detection,
        request=http_request,
        project=project,
        db=db,
        project_id=project_id,
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
    return await _apply_detection_response_filter(
        detection,
        request=http_request,
        project=project,
        db=db,
        project_id=project_id,
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
    return await _apply_detection_response_filter(
        detection,
        request=http_request,
        project=project,
        db=db,
        project_id=project_id,
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
    project = await gate_action(
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

    # FR-039: voter-id masking is driven by the viewer's normalised role.
    viewer_user_id = getattr(current_user, "id", None) if current_user is not None else None
    viewer_role = await resolve_viewer_role(
        project_id=project_id,
        project=project,
        user_id=viewer_user_id,
        db=db,
    )
    return await vote_service.get_vote_summary(
        annotation_id=detection_id,
        current_user_id=viewer_user_id,
        viewer_role=viewer_role,
        # Phase 13 P1.5 R3 (Codex follow-up): pass project-specific
        # consensus thresholds so GET summary computes status the same
        # way ``cast_vote`` does. Defaulting to 2 / 0.667 silently
        # disagrees with projects that override either field.
        min_votes=project.review_min_votes,
        threshold=project.review_consensus_threshold,
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

    # FR-037: classify the voter's source + role snapshot. Persisted only on
    # first creation by ``AnnotationVoteRepository.upsert`` — re-votes preserve
    # the original source / role per FR-037 immutability.
    source, role_at_vote = await classify_voter_source(
        project_id=project_id,
        project=project,
        user_id=current_user.id,
        db=db,
    )
    viewer_role = await resolve_viewer_role(
        project_id=project_id,
        project=project,
        user_id=current_user.id,
        db=db,
    )

    summary = await vote_service.cast_vote(
        annotation_id=detection_id,
        user_id=current_user.id,
        request=request,
        source=source,
        project_role_at_vote=role_at_vote,
        # Phase 13 P1.5 (T804): project_id is required on the vote row.
        project_id=project_id,
        viewer_role=viewer_role,
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

    viewer_role = await resolve_viewer_role(
        project_id=project_id,
        project=project,
        user_id=current_user.id,
        db=db,
    )

    summary = await vote_service.delete_vote(
        annotation_id=detection_id,
        user_id=current_user.id,
        viewer_role=viewer_role,
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
