"""API functions to interact with inference jobs."""

import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from echoroo import models, schemas
from echoroo.api.common import BaseAPI
from echoroo.api.common.utils import update_object


class InferenceJobAPI(
    BaseAPI[
        UUID,
        models.InferenceJob,
        schemas.InferenceJob,
        schemas.InferenceJobCreate,
        schemas.InferenceJobUpdate,
    ]
):
    """API for managing inference jobs."""

    _model = models.InferenceJob
    _schema = schemas.InferenceJob

    async def update(
        self,
        session: AsyncSession,
        obj: schemas.InferenceJob,
        data: schemas.InferenceJobUpdate,
        **kwargs: Any,
    ) -> schemas.InferenceJob:
        """Update an inference job.

        Parameters
        ----------
        session
            SQLAlchemy AsyncSession.
        obj
            Inference job to update.
        data
            Update data.
        **kwargs
            Additional fields to update directly (e.g., model_run_id, started_on).

        Returns
        -------
        schemas.InferenceJob
            Updated inference job.
        """
        db_obj = await update_object(
            session,
            models.InferenceJob,
            models.InferenceJob.uuid == obj.uuid,
            data,
            **kwargs,
        )
        updated = schemas.InferenceJob.model_validate(db_obj)
        self._update_cache(updated)
        return updated

    async def create(
        self,
        session: AsyncSession,
        config: dict[str, Any],
        dataset_id: int | None = None,
        recording_id: int | None = None,
        created_by_id: int | None = None,
        total_items: int = 0,
        **kwargs,
    ) -> schemas.InferenceJob:
        """Create a new inference job."""
        return await self.create_from_data(
            session,
            schemas.InferenceJobCreate(
                config=schemas.InferenceConfig(**config),
                dataset_uuid=None,
                recording_uuid=None,
            ),
            dataset_id=dataset_id,
            recording_id=recording_id,
            created_by_id=created_by_id,
            total_items=total_items,
            config=config,
            **kwargs,
        )

    async def start(
        self,
        session: AsyncSession,
        obj: schemas.InferenceJob,
        model_run_id: int | None = None,
    ) -> schemas.InferenceJob:
        """Mark job as running."""
        return await self.update(
            session,
            obj,
            schemas.InferenceJobUpdate(status="running"),
            model_run_id=model_run_id,
            started_on=datetime.datetime.now(datetime.timezone.utc),
        )

    async def complete(
        self,
        session: AsyncSession,
        obj: schemas.InferenceJob,
    ) -> schemas.InferenceJob:
        """Mark job as completed."""
        return await self.update(
            session,
            obj,
            schemas.InferenceJobUpdate(
                status="completed",
                progress=1.0,
                processed_items=obj.total_items,
            ),
            completed_on=datetime.datetime.now(datetime.timezone.utc),
        )

    async def fail(
        self,
        session: AsyncSession,
        obj: schemas.InferenceJob,
        error_message: str,
    ) -> schemas.InferenceJob:
        """Mark job as failed with error message."""
        return await self.update(
            session,
            obj,
            schemas.InferenceJobUpdate(
                status="failed",
                error_message=error_message,
            ),
            completed_on=datetime.datetime.now(datetime.timezone.utc),
        )

    async def cancel(
        self,
        session: AsyncSession,
        obj: schemas.InferenceJob,
    ) -> schemas.InferenceJob:
        """Cancel a pending or running job."""
        return await self.update(
            session,
            obj,
            schemas.InferenceJobUpdate(status="cancelled"),
            completed_on=datetime.datetime.now(datetime.timezone.utc),
        )

    async def update_progress(
        self,
        session: AsyncSession,
        obj: schemas.InferenceJob,
        processed_items: int,
    ) -> schemas.InferenceJob:
        """Update job progress."""
        progress = (
            processed_items / obj.total_items
            if obj.total_items > 0
            else 0.0
        )
        return await self.update(
            session,
            obj,
            schemas.InferenceJobUpdate(
                progress=progress,
                processed_items=processed_items,
            ),
        )

    async def set_total_items(
        self,
        session: AsyncSession,
        obj: schemas.InferenceJob,
        total_items: int,
    ) -> schemas.InferenceJob:
        """Set the total number of items to process.

        Parameters
        ----------
        session
            SQLAlchemy AsyncSession.
        obj
            Inference job to update.
        total_items
            Total number of items to process.

        Returns
        -------
        schemas.InferenceJob
            Updated inference job.
        """
        db_obj = await update_object(
            session,
            models.InferenceJob,
            models.InferenceJob.uuid == obj.uuid,
            total_items=total_items,
        )
        updated = schemas.InferenceJob.model_validate(db_obj)
        self._update_cache(updated)
        return updated


inference_jobs = InferenceJobAPI()
