"""Annotation-set CSV export BFF adapter (CamtrapDP + ToriTore).

Mirrors the detection CSV export adapter
(:mod:`echoroo.api.web_v1.projects._detection_export`): a thin endpoint on the
cookie + CSRF session boundary that fires :func:`gate_action` once with the
SAME set-view Action used by the annotation-set GET / eligibility endpoints
(``ANNOTATION_CLIP_GET_ACTION``), validates that the set exists and belongs to
the project (404 otherwise), then returns a
:class:`fastapi.responses.StreamingResponse` of the CamtrapDP observations CSV.

The CSV column shape equals the detection export's CamtrapDP + FR-086 block
plus three trailing ToriTore proficiency columns
(``annotator_species_score`` / ``annotator_total_score`` /
``annotator_test_reference``). See
:mod:`echoroo.services.annotation_set_export`.

Permission guard allowlist
--------------------------
This adapter fires ``gate_action`` before streaming, so
``scripts/lint_permission_guard.py`` is satisfied with no new entry.

Response filter allowlist
-------------------------
The response is a binary ``text/csv`` stream that never names
``Recording`` / ``Detection`` / ``Site`` as a Pydantic response model, so no
``response_filter`` allowlist entry is required.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from echoroo.core.actions import ANNOTATION_CLIP_GET_ACTION
from echoroo.core.database import DbSession
from echoroo.core.permissions import gate_action
from echoroo.middleware.auth import CurrentUser
from echoroo.services.annotation_set_export import AnnotationSetExportService

router = APIRouter()


@router.get(
    "/{project_id}/annotation-sets/{set_id}/export/csv",
    summary="Export annotation set as CSV",
    description=(
        "Export an annotation set's TimeRangeAnnotations as a CamtrapDP "
        "observations CSV (one row per annotation), including the ToriTore "
        "per-annotator proficiency columns. Gated by set-view access."
    ),
)
async def export_annotation_set_csv(
    project_id: UUID,
    set_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
) -> StreamingResponse:
    """Stream the annotation-set CamtrapDP + ToriTore CSV.

    Uses the SAME set-view gate as the annotation-set GET / eligibility
    endpoints — any member who can view the set may export it.
    """
    await gate_action(
        action=ANNOTATION_CLIP_GET_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )

    service = AnnotationSetExportService(db)
    # Validate existence + project scope BEFORE streaming so the response
    # status can still be a 404 (the stream commits the status on first yield).
    try:
        anno_set = await service._require_set(set_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Annotation set not found",
        ) from exc
    if anno_set.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Annotation set not found",
        )

    body_iterator = service.export_csv_stream(
        project_id=project_id,
        set_id=set_id,
    )
    return StreamingResponse(
        body_iterator,
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f"attachment; filename=annotation-set-{set_id}.csv"
            )
        },
    )
