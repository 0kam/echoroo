"""REST API routes for datasets."""

import datetime
import logging
import re
from io import StringIO
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import DirectoryPath
from sqlalchemy.exc import IntegrityError

from echoroo import api, exceptions, models, schemas
from echoroo.filters.datasets import DatasetFilter
from echoroo.routes.dependencies import (
    Session,
    EchorooSettings,
    get_current_user_dependency,
    get_optional_current_user_dependency,
)
from echoroo.routes.types import Limit, Offset

__all__ = ["get_dataset_router"]

logger = logging.getLogger(__name__)

_FILENAME_SANITIZER = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_filename(name: str) -> str:
    """Convert a dataset name into a filesystem-friendly slug."""
    sanitized = _FILENAME_SANITIZER.sub("_", name).strip("._")
    return sanitized or "dataset"


def get_dataset_router(settings: EchorooSettings) -> APIRouter:
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
        settings: EchorooSettings,
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
        settings: EchorooSettings,
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
            project_id=dataset.project_id,
            primary_site_id=dataset.primary_site_id,
            primary_recorder_id=dataset.primary_recorder_id,
            license_id=dataset.license_id,
            doi=dataset.doi,
            note=dataset.note,
            gain=dataset.gain,
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

    @router.post(
        "/import/",
        response_model=schemas.Dataset,
    )
    async def import_dataset(
        settings: EchorooSettings,
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

    @router.post(
        "/detail/datetime_pattern/",
        response_model=schemas.DatasetDatetimePattern,
    )
    async def set_datetime_pattern(
        session: Session,
        dataset_uuid: UUID,
        pattern_data: schemas.DatasetDatetimePatternUpdate,
        user: models.User = Depends(current_user_dep),
    ):
        """Configure datetime parsing pattern for a dataset."""
        dataset_obj = await api.datasets.get(session, dataset_uuid, user=user)
        pattern = await api.datasets.set_datetime_pattern(
            session,
            dataset_obj,
            pattern_data,
            user=user,
        )
        await session.commit()
        return pattern

    @router.post(
        "/detail/parse_datetime/",
    )
    async def parse_datetime(
        session: Session,
        dataset_uuid: UUID,
        user: models.User = Depends(current_user_dep),
    ):
        """Parse datetime for all recordings in the dataset."""
        dataset_obj = await api.datasets.get(session, dataset_uuid, user=user)
        result = await api.datasets.parse_datetime_for_recordings(
            session,
            dataset_obj,
            user=user,
        )
        await session.commit()
        return result

    @router.get(
        "/detail/datetime_parse_status/",
    )
    async def get_datetime_parse_status(
        session: Session,
        dataset_uuid: UUID,
        user: models.User | None = Depends(optional_user_dep),
    ):
        """Get datetime parsing status for a dataset."""
        dataset_obj = await api.datasets.get(session, dataset_uuid, user=user)
        return await api.datasets.get_datetime_parse_status(
            session,
            dataset_obj,
            user=user,
        )

    @router.get(
        "/detail/filename_samples/",
        response_model=list[str],
    )
    async def get_filename_samples(
        session: Session,
        dataset_uuid: UUID,
        limit: int = 20,
        user: models.User | None = Depends(optional_user_dep),
    ):
        """Get sample recording filenames from a dataset."""
        dataset_obj = await api.datasets.get(session, dataset_uuid, user=user)
        return await api.datasets.get_filename_samples(
            session,
            dataset_obj,
            limit=limit,
            user=user,
        )

    @router.get(
        "/detail/export/camtrapdp/deployments/",
        response_class=Response,
    )
    async def export_camtrapdp_deployments(
        session: Session,
        dataset_uuid: UUID,
        user: models.User | None = Depends(optional_user_dep),
    ):
        """Export dataset as CamtrapDP deployments.csv."""
        dataset_obj = await api.datasets.get(session, dataset_uuid, user=user)
        df = await api.datasets.export_camtrapdp_deployments(
            session,
            dataset_obj,
            user=user,
        )

        # Convert to CSV
        csv_buffer = StringIO()
        df.to_csv(csv_buffer, index=False)
        csv_content = csv_buffer.getvalue()

        # Return as downloadable CSV
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=deployments_{dataset_obj.name}.csv"
            },
        )

    @router.get(
        "/detail/export/camtrapdp/media/",
        response_class=Response,
    )
    async def export_camtrapdp_media(
        session: Session,
        dataset_uuid: UUID,
        user: models.User | None = Depends(optional_user_dep),
    ):
        """Export dataset recordings as CamtrapDP media.csv."""
        dataset_obj = await api.datasets.get(session, dataset_uuid, user=user)
        df = await api.datasets.export_camtrapdp_media(
            session,
            dataset_obj,
            user=user,
        )

        # Convert to CSV
        csv_buffer = StringIO()
        df.to_csv(csv_buffer, index=False)
        csv_content = csv_buffer.getvalue()

        # Return as downloadable CSV
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=media_{dataset_obj.name}.csv"
            },
        )

    @router.get(
        "/detail/stats/",
        response_model=schemas.DatasetOverviewStats,
    )
    async def get_dataset_overview_stats(
        session: Session,
        dataset_uuid: UUID,
        user: models.User | None = Depends(optional_user_dep),
    ):
        """Return aggregated statistics for the dataset overview."""
        dataset_obj = await api.datasets.get(session, dataset_uuid, user=user)
        return await api.datasets.get_overview_stats(
            session,
            dataset_obj,
            user=user,
        )

    # Simple cache for export files: {cache_key: (temp_path, file_size, filename, created_at)}
    _export_cache: dict[str, tuple[str, int, str, float]] = {}
    _CACHE_TTL = 300  # 5 minutes

    @router.get(
        "/detail/export/bioacoustics/",
        response_class=StreamingResponse,
    )
    async def export_bioacoustics_package(
        session: Session,
        settings: EchorooSettings,
        dataset_uuid: UUID,
        include_audio: bool = False,
        user: models.User | None = Depends(optional_user_dep),
    ):
        """Stream a CamtrapDP-compliant export with optional audio assets."""
        import os
        import time

        # Clean up expired cache entries
        current_time = time.time()
        expired_keys = [
            k for k, v in _export_cache.items()
            if current_time - v[3] > _CACHE_TTL
        ]
        for key in expired_keys:
            try:
                os.unlink(_export_cache[key][0])
            except Exception:
                pass
            del _export_cache[key]

        # Check cache
        cache_key = f"{dataset_uuid}:{include_audio}"
        if cache_key in _export_cache:
            cached = _export_cache[cache_key]
            temp_path, file_size, filename, _ = cached
            if os.path.exists(temp_path):
                # Return cached file without cleanup (will be cleaned up after TTL)
                def cached_file_iterator():
                    with open(temp_path, 'rb') as f:
                        chunk_size = 64 * 1024 * 1024
                        while True:
                            chunk = f.read(chunk_size)
                            if not chunk:
                                break
                            yield chunk

                return StreamingResponse(
                    cached_file_iterator(),
                    media_type="application/zip",
                    headers={
                        "Content-Disposition": f'attachment; filename="{filename}"',
                        "Content-Length": str(file_size),
                    },
                )

        # Build new export
        dataset_obj = await api.datasets.get(session, dataset_uuid, user=user)
        temp_path, file_size = await api.datasets.build_bioacoustics_export(
            session,
            dataset_obj,
            include_audio=include_audio,
            user=user,
            audio_dir=settings.audio_dir,
        )
        suffix = "metadata_audio" if include_audio else "metadata"
        timestamp = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        safe_name = _safe_filename(dataset_obj.name)
        filename = f"{safe_name}_{suffix}_{timestamp}.zip"

        # Store in cache
        _export_cache[cache_key] = (temp_path, file_size, filename, time.time())

        # Create a file iterator (no cleanup - cache handles it)
        def file_iterator():
            with open(temp_path, 'rb') as f:
                chunk_size = 64 * 1024 * 1024  # 64MB chunks
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    yield chunk

        return StreamingResponse(
            file_iterator(),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Length": str(file_size),
            },
        )

    return router
