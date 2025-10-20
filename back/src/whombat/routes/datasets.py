"""REST API routes for datasets."""

import datetime
import logging
from io import StringIO
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import DirectoryPath
from soundevent.io.aoef import DatasetObject
from sqlalchemy.exc import IntegrityError

from whombat import api, exceptions, models, schemas
from whombat.filters.datasets import DatasetFilter
from whombat.routes.dependencies import (
    Session,
    WhombatSettings,
    get_current_user_dependency,
    get_optional_current_user_dependency,
)
from whombat.routes.types import Limit, Offset

__all__ = ["get_dataset_router"]

logger = logging.getLogger(__name__)


def get_dataset_router(settings: WhombatSettings) -> APIRouter:
    """Create a router with dataset endpoints wired with authentication."""
    current_user_dep = get_current_user_dependency(settings)
    optional_user_dep = get_optional_current_user_dependency(settings)

    router = APIRouter()

    @router.get(
        "/detail/",
        response_model=schemas.Dataset,
    )
    async def get_dataset(
        session: Session,
        dataset_uuid: UUID,
        user: models.User | None = Depends(optional_user_dep),
    ):
        """Get a dataset by UUID."""
        return await api.datasets.get(session, dataset_uuid, user=user)

    @router.get(
        "/",
        response_model=schemas.Page[schemas.Dataset],
    )
    async def get_datasets(
        session: Session,
        filter: Annotated[
            DatasetFilter,  # type: ignore
            Depends(DatasetFilter),
        ],
        limit: Limit = 10,
        offset: Offset = 0,
        user: models.User | None = Depends(optional_user_dep),
    ):
        """Get a page of datasets respecting visibility rules."""
        datasets, total = await api.datasets.get_many(
            session,
            limit=limit,
            offset=offset,
            filters=[filter],
            user=user,
        )

        return schemas.Page(
            items=datasets,
            total=total,
            offset=offset,
            limit=limit,
        )

    @router.get(
        "/candidates/",
        response_model=list[schemas.DatasetCandidate],
    )
    async def list_dataset_candidates(
        session: Session,
        settings: WhombatSettings,
        user: models.User = Depends(current_user_dep),
    ):
        """List directories that can be registered as new datasets."""
        return await api.datasets.list_candidates(
            session,
            audio_dir=settings.audio_dir,
        )

    @router.get(
        "/candidates/info/",
        response_model=schemas.DatasetCandidateInfo,
    )
    async def get_dataset_candidate_info(
        session: Session,
        settings: WhombatSettings,
        relative_path: str,
        user: models.User = Depends(current_user_dep),
    ):
        """Inspect a dataset directory candidate before creation."""
        return await api.datasets.inspect_candidate(
            directory=Path(relative_path),
            audio_dir=settings.audio_dir,
        )

    @router.post(
        "/",
        response_model=schemas.Dataset,
    )
    async def create_dataset(
        session: Session,
        dataset: schemas.DatasetCreate,
        user: models.User = Depends(current_user_dep),
    ):
        """Create a new dataset."""
        created = await api.datasets.create(
            session,
            name=dataset.name,
            description=dataset.description,
            dataset_dir=dataset.audio_dir,
            user=user,
            visibility=dataset.visibility,
            owner_group_id=dataset.owner_group_id,
        )
        await session.commit()
        return created

    @router.patch(
        "/detail/",
        response_model=schemas.Dataset,
    )
    async def update_dataset(
        session: Session,
        dataset_uuid: UUID,
        data: schemas.DatasetUpdate,
        user: models.User = Depends(current_user_dep),
    ):
        """Update a dataset."""
        dataset_obj = await api.datasets.get(session, dataset_uuid, user=user)
        updated = await api.datasets.update(
            session,
            dataset_obj,
            data,
            user=user,
        )
        await session.commit()
        return updated

    @router.get(
        "/detail/state/",
        response_model=list[schemas.DatasetFile],
    )
    async def get_file_state(
        session: Session,
        dataset_uuid: UUID,
        user: models.User | None = Depends(optional_user_dep),
    ):
        """Get the status of the files in a dataset."""
        dataset_obj = await api.datasets.get(session, dataset_uuid, user=user)
        return await api.datasets.get_state(session, dataset_obj)

    @router.delete(
        "/detail/",
        response_model=schemas.Dataset,
    )
    async def delete_dataset(
        session: Session,
        dataset_uuid: UUID,
        user: models.User = Depends(current_user_dep),
    ):
        """Delete a dataset."""
        dataset_obj = await api.datasets.get(session, dataset_uuid, user=user)

        try:
            deleted = await api.datasets.delete(session, dataset_obj, user=user)
        except IntegrityError as error:  # pragma: no cover - DB constraint
            raise exceptions.DataIntegrityError(
                "Cannot delete this dataset because it is currently in use. "
                "This dataset may be associated with active annotation projects "
                "or other processes. Please ensure that the dataset is not being "
                "used in any active tasks before attempting to delete it."
            ) from error

        await session.commit()
        return deleted

    @router.get(
        "/detail/download/json/",
        response_model=DatasetObject,
    )
    async def download_dataset_json(
        session: Session,
        dataset_uuid: UUID,
        settings: WhombatSettings,
        user: models.User | None = Depends(optional_user_dep),
    ):
        """Export a dataset as JSON."""
        whombat_dataset = await api.datasets.get(session, dataset_uuid, user=user)
        obj = await api.datasets.export_dataset(
            session,
            whombat_dataset,
            audio_dir=settings.audio_dir,
        )
        filename = f"{whombat_dataset.name}_{obj.created_on.isoformat()}.json"
        return Response(
            obj.model_dump_json(),
            media_type="application/json",
            status_code=200,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    @router.get(
        "/detail/download/csv/",
    )
    async def download_dataset_csv(
        session: Session,
        dataset_uuid: UUID,
        user: models.User | None = Depends(optional_user_dep),
    ):
        """Export the dataset recordings in csv format."""
        dataset_obj = await api.datasets.get(session, dataset_uuid, user=user)
        df = await api.datasets.to_dataframe(session, dataset_obj)
        buffer = StringIO()
        df.to_csv(buffer, index=False)
        buffer.seek(0)
        filename = f"{dataset_obj.name}_{datetime.datetime.now()}.csv"
        return StreamingResponse(
            buffer,
            media_type="text/csv",
            status_code=200,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    @router.post(
        "/import/",
        response_model=schemas.Dataset,
    )
    async def import_dataset(
        settings: WhombatSettings,
        session: Session,
        dataset: UploadFile,
        audio_dir: Annotated[DirectoryPath, Body()],
    ):
        """Import a dataset."""
        if not audio_dir.exists():
            raise FileNotFoundError(f"Audio directory {audio_dir} does not exist.")

        return await api.datasets.import_dataset(
            session,
            dataset.file,
            dataset_audio_dir=audio_dir,
            audio_dir=settings.audio_dir,
        )

    return router
