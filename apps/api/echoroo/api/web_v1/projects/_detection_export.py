"""Project detection export BFF adapters (spec/009 PR 4).

Spec/009 PR 4 moves the two detection export endpoints from
``/api/v1`` to ``/web-api/v1``. The legacy ``/api/v1/detections.py``
handlers continue to own the streaming pipelines (CSV row-by-row +
mid-stream permission re-check for Hybrid Contract A-5, ZIP buffered
ML-dataset archive); the BFF layer is a thin adapter that lands the
request on the cookie + CSRF session boundary, fires
:func:`gate_action` once, and returns the legacy
:class:`fastapi.responses.StreamingResponse` unchanged.

Endpoints (2):

* GET ``/{pid}/detections/export/csv``        → ``DETECTION_EXPORT_CSV_ACTION``
* GET ``/{pid}/detections/export/ml-dataset`` → ``DETECTION_EXPORT_ML_DATASET_ACTION``

Both legacy handlers are already centrally gated through
:func:`gate_action`, so no entry is required in
``scripts/allowlists/permission_guard_allowlist.txt``. Both responses
return a binary stream (CSV / ZIP) and never name
``Recording`` / ``Detection`` / ``Site`` as a Pydantic response model,
so no ``response_filter`` allowlist entry is required either.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from echoroo.api.v1 import detections as legacy_detections
from echoroo.core.actions import (
    DETECTION_EXPORT_CSV_ACTION,
    DETECTION_EXPORT_ML_DATASET_ACTION,
)
from echoroo.core.database import DbSession
from echoroo.core.permissions import gate_action
from echoroo.middleware.auth import CurrentUser
from echoroo.models.enums import DetectionStatus

router = APIRouter()


@router.get(
    "/{project_id}/detections/export/csv",
    summary="Export detections as CSV",
    description="BFF adapter for the legacy detection CSV export endpoint.",
)
async def export_detections_csv(
    project_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    status: DetectionStatus | None = None,
    tag_id: UUID | None = None,
    dataset_id: UUID | None = None,
    detection_run_id: UUID | None = None,
) -> StreamingResponse:
    """Delegate detection CSV export to the legacy handler."""
    await gate_action(
        action=DETECTION_EXPORT_CSV_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_detections.export_csv(
        project_id=project_id,
        request=request,
        current_user=current_user,
        db=db,
        status=status,
        tag_id=tag_id,
        dataset_id=dataset_id,
        detection_run_id=detection_run_id,
    )


@router.get(
    "/{project_id}/detections/export/ml-dataset",
    summary="Export ML training dataset",
    description="BFF adapter for the legacy ML-dataset ZIP export endpoint.",
)
async def export_ml_dataset(
    project_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    dataset_id: UUID | None = None,
    detection_run_id: UUID | None = None,
) -> StreamingResponse:
    """Delegate ML-dataset ZIP export to the legacy handler."""
    await gate_action(
        action=DETECTION_EXPORT_ML_DATASET_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_detections.export_ml_dataset(
        project_id=project_id,
        request=request,
        current_user=current_user,
        db=db,
        dataset_id=dataset_id,
        detection_run_id=detection_run_id,
    )
