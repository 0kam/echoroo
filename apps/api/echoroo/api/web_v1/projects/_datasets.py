"""Project dataset BFF adapters (read + spec/009 PR 2 write mutations).

Read adapters were introduced for the browser export smoke (PR D0). PR 2
extends the module with the dataset lifecycle write surface (create /
update / delete / import / import-status / datetime-config mutations) so
the frontend can finish migrating off ``/api/v1`` for dataset management.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, Request, status

from echoroo.api.v1 import datasets as legacy_datasets
from echoroo.core.actions import (
    DATASET_CREATE_ACTION,
    DATASET_DATETIME_APPLY_ACTION,
    DATASET_DATETIME_AUTODETECT_ACTION,
    DATASET_DATETIME_CONFIG_ACTION,
    DATASET_DATETIME_TEST_ACTION,
    DATASET_DELETE_ACTION,
    DATASET_GET_ACTION,
    DATASET_IMPORT_ACTION,
    DATASET_IMPORT_STATUS_ACTION,
    DATASET_LIST_ACTION,
    DATASET_STATISTICS_ACTION,
    DATASET_UPDATE_ACTION,
)
from echoroo.core.database import DbSession
from echoroo.core.permissions import gate_action
from echoroo.middleware.auth import CurrentUser
from echoroo.models.enums import DatasetStatus, DatasetVisibility
from echoroo.schemas.dataset import (
    DatasetCreate,
    DatasetUpdate,
    DatetimeApplyRequest,
    DatetimeTestRequest,
    ImportRequest,
)

router = APIRouter()


@router.get(
    "/{project_id}/datasets",
    response_model=legacy_datasets.DatasetListResponse,
    summary="List datasets",
    description="BFF adapter for the legacy project dataset list endpoint.",
)
async def list_datasets(
    project_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: legacy_datasets.DatasetServiceDep,
    db: DbSession,
    page: int = 1,
    page_size: int = 20,
    site_id: UUID | None = None,
    status_filter: DatasetStatus | None = Query(None, alias="status"),
    visibility: DatasetVisibility | None = None,
    search: str | None = None,
) -> legacy_datasets.DatasetListResponse:
    """Delegate dataset listing to the legacy handler."""
    await gate_action(
        action=DATASET_LIST_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_datasets.list_datasets(
        project_id=project_id,
        request=request,
        current_user=current_user,
        service=service,
        db=db,
        page=page,
        page_size=page_size,
        site_id=site_id,
        status_filter=status_filter,
        visibility=visibility,
        search=search,
    )


@router.get(
    "/{project_id}/datasets/{dataset_id}",
    response_model=legacy_datasets.DatasetDetailResponse,
    summary="Get dataset",
    description="BFF adapter for the legacy project dataset detail endpoint.",
)
async def get_dataset(
    project_id: UUID,
    dataset_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: legacy_datasets.DatasetServiceDep,
    db: DbSession,
) -> legacy_datasets.DatasetDetailResponse:
    """Delegate dataset detail reads to the legacy handler."""
    await gate_action(
        action=DATASET_GET_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_datasets.get_dataset(
        project_id=project_id,
        dataset_id=dataset_id,
        request=request,
        current_user=current_user,
        service=service,
        db=db,
    )


@router.get(
    "/{project_id}/datasets/{dataset_id}/statistics",
    response_model=legacy_datasets.DatasetStatisticsResponse,
    summary="Get dataset statistics",
    description="BFF adapter for the legacy project dataset statistics endpoint.",
)
async def get_dataset_statistics(
    project_id: UUID,
    dataset_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: legacy_datasets.DatasetServiceDep,
    db: DbSession,
) -> legacy_datasets.DatasetStatisticsResponse:
    """Delegate dataset statistics reads to the legacy handler."""
    await gate_action(
        action=DATASET_STATISTICS_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_datasets.get_dataset_statistics(
        project_id=project_id,
        dataset_id=dataset_id,
        request=request,
        current_user=current_user,
        service=service,
        db=db,
    )


@router.get(
    "/{project_id}/datasets/{dataset_id}/datetime-config",
    response_model=legacy_datasets.DatetimeConfigResponse,
    summary="Get dataset datetime config",
    description="BFF adapter for the legacy project dataset datetime config endpoint.",
)
async def get_datetime_config(
    project_id: UUID,
    dataset_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: legacy_datasets.DatasetServiceDep,
    db: DbSession,
) -> legacy_datasets.DatetimeConfigResponse:
    """Delegate dataset datetime-config reads to the legacy handler."""
    await gate_action(
        action=DATASET_DATETIME_CONFIG_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_datasets.get_datetime_config(
        project_id=project_id,
        dataset_id=dataset_id,
        request=request,
        current_user=current_user,
        service=service,
        db=db,
    )


# ---------------------------------------------------------------------------
# Spec/009 PR 2 — write mutations + lifecycle reads
# ---------------------------------------------------------------------------


@router.post(
    "/{project_id}/datasets",
    response_model=legacy_datasets.DatasetDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create dataset",
    description="BFF adapter for the legacy dataset create endpoint.",
)
async def create_dataset(
    project_id: UUID,
    request: DatasetCreate,
    http_request: Request,
    current_user: CurrentUser,
    service: legacy_datasets.DatasetServiceDep,
    db: DbSession,
) -> legacy_datasets.DatasetDetailResponse:
    """Delegate dataset creation to the legacy handler."""
    await gate_action(
        action=DATASET_CREATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    return await legacy_datasets.create_dataset(
        project_id=project_id,
        request=request,
        http_request=http_request,
        current_user=current_user,
        service=service,
        db=db,
    )


@router.patch(
    "/{project_id}/datasets/{dataset_id}",
    response_model=legacy_datasets.DatasetDetailResponse,
    summary="Update dataset",
    description="BFF adapter for the legacy dataset PATCH endpoint.",
)
async def update_dataset(
    project_id: UUID,
    dataset_id: UUID,
    request: DatasetUpdate,
    http_request: Request,
    current_user: CurrentUser,
    service: legacy_datasets.DatasetServiceDep,
    db: DbSession,
) -> legacy_datasets.DatasetDetailResponse:
    """Delegate dataset PATCH to the legacy handler."""
    await gate_action(
        action=DATASET_UPDATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    return await legacy_datasets.update_dataset(
        project_id=project_id,
        dataset_id=dataset_id,
        request=request,
        http_request=http_request,
        current_user=current_user,
        service=service,
        db=db,
    )


@router.delete(
    "/{project_id}/datasets/{dataset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete dataset",
    description="BFF adapter for the legacy dataset DELETE endpoint.",
)
async def delete_dataset(
    project_id: UUID,
    dataset_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: legacy_datasets.DatasetServiceDep,
    db: DbSession,
) -> None:
    """Delegate dataset DELETE to the legacy handler."""
    await gate_action(
        action=DATASET_DELETE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    await legacy_datasets.delete_dataset(
        project_id=project_id,
        dataset_id=dataset_id,
        request=request,
        current_user=current_user,
        service=service,
        db=db,
    )


@router.post(
    "/{project_id}/datasets/{dataset_id}/import",
    response_model=legacy_datasets.ImportStatusResponse,
    summary="Start dataset import",
    description="BFF adapter for the legacy dataset import start endpoint.",
)
async def start_import(
    project_id: UUID,
    dataset_id: UUID,
    request: ImportRequest,
    http_request: Request,
    current_user: CurrentUser,
    service: legacy_datasets.DatasetServiceDep,
    db: DbSession,
) -> legacy_datasets.ImportStatusResponse:
    """Delegate dataset import to the legacy handler."""
    await gate_action(
        action=DATASET_IMPORT_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    return await legacy_datasets.start_import(
        project_id=project_id,
        dataset_id=dataset_id,
        request=request,
        http_request=http_request,
        current_user=current_user,
        service=service,
        db=db,
    )


@router.get(
    "/{project_id}/datasets/{dataset_id}/import-status",
    response_model=legacy_datasets.ImportStatusResponse,
    summary="Get dataset import status",
    description="BFF adapter for the legacy dataset import-status read endpoint.",
)
async def get_import_status(
    project_id: UUID,
    dataset_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: legacy_datasets.DatasetServiceDep,
    db: DbSession,
) -> legacy_datasets.ImportStatusResponse:
    """Delegate dataset import-status reads to the legacy handler."""
    await gate_action(
        action=DATASET_IMPORT_STATUS_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_datasets.get_import_status(
        project_id=project_id,
        dataset_id=dataset_id,
        request=request,
        current_user=current_user,
        service=service,
        db=db,
    )


@router.post(
    "/{project_id}/datasets/{dataset_id}/datetime-config/auto-detect",
    response_model=legacy_datasets.DatetimeAutoDetectResponse,
    summary="Auto-detect datetime pattern",
    description="BFF adapter for the legacy dataset datetime auto-detect endpoint.",
)
async def auto_detect_datetime(
    project_id: UUID,
    dataset_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: legacy_datasets.DatasetServiceDep,
    db: DbSession,
) -> legacy_datasets.DatetimeAutoDetectResponse:
    """Delegate datetime auto-detect to the legacy handler."""
    await gate_action(
        action=DATASET_DATETIME_AUTODETECT_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_datasets.auto_detect_datetime(
        project_id=project_id,
        dataset_id=dataset_id,
        request=request,
        current_user=current_user,
        service=service,
        db=db,
    )


@router.post(
    "/{project_id}/datasets/{dataset_id}/datetime-config/test",
    response_model=list[legacy_datasets.DatetimeTestResult],
    summary="Test datetime pattern",
    description="BFF adapter for the legacy dataset datetime test endpoint.",
)
async def test_datetime_pattern(
    project_id: UUID,
    dataset_id: UUID,
    body: DatetimeTestRequest,
    request: Request,
    current_user: CurrentUser,
    service: legacy_datasets.DatasetServiceDep,
    db: DbSession,
) -> list[legacy_datasets.DatetimeTestResult]:
    """Delegate datetime pattern testing to the legacy handler."""
    await gate_action(
        action=DATASET_DATETIME_TEST_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_datasets.test_datetime_pattern(
        project_id=project_id,
        dataset_id=dataset_id,
        body=body,
        request=request,
        current_user=current_user,
        service=service,
        db=db,
    )


@router.post(
    "/{project_id}/datasets/{dataset_id}/datetime-config/apply",
    response_model=legacy_datasets.DatetimeApplyResponse,
    summary="Apply datetime pattern",
    description="BFF adapter for the legacy dataset datetime apply endpoint.",
)
async def apply_datetime_pattern(
    project_id: UUID,
    dataset_id: UUID,
    body: DatetimeApplyRequest,
    request: Request,
    current_user: CurrentUser,
    service: legacy_datasets.DatasetServiceDep,
    db: DbSession,
) -> legacy_datasets.DatetimeApplyResponse:
    """Delegate datetime pattern application to the legacy handler."""
    await gate_action(
        action=DATASET_DATETIME_APPLY_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_datasets.apply_datetime_pattern(
        project_id=project_id,
        dataset_id=dataset_id,
        body=body,
        request=request,
        current_user=current_user,
        service=service,
        db=db,
    )
