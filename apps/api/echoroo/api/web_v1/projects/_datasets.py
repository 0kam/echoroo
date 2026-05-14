"""Project dataset read BFF adapters needed by browser export smoke."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, Request

from echoroo.api.v1 import datasets as legacy_datasets
from echoroo.core.database import DbSession
from echoroo.middleware.auth import CurrentUser
from echoroo.models.enums import DatasetStatus, DatasetVisibility

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
    return await legacy_datasets.get_datetime_config(
        project_id=project_id,
        dataset_id=dataset_id,
        request=request,
        current_user=current_user,
        service=service,
        db=db,
    )
