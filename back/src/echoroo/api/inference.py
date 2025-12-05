"""API functions for managing inference jobs."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from echoroo import models, schemas
from echoroo.api.common import BaseAPI

__all__ = [
    "InferenceJobAPI",
    "inference_jobs",
]


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

    async def create(
        self,
        session: AsyncSession,
        data: schemas.InferenceJobCreate,
        *,
        dataset_id: int | None = None,
        recording_id: int | None = None,
        model_run_id: int | None = None,
        created_by_id: int | None = None,
        **kwargs,
    ) -> schemas.InferenceJob:
        """Create a new inference job.

        Parameters
        ----------
        session
            The database session to use.
        data
            The inference job creation data.
        dataset_id
            The database id of the dataset to process.
        recording_id
            The database id of the recording to process.
        model_run_id
            The database id of the model run to associate.
        created_by_id
            The database id of the user creating the job.
        **kwargs
            Additional keyword arguments.

        Returns
        -------
        schemas.InferenceJob
            The created inference job.
        """
        return await self.create_from_data(
            session,
            dataset_id=dataset_id,
            recording_id=recording_id,
            model_run_id=model_run_id,
            created_by_id=created_by_id,
            config=data.config.model_dump(),
            **kwargs,
        )

    async def update_status(
        self,
        session: AsyncSession,
        obj: schemas.InferenceJob,
        status: str,
        *,
        error_message: str | None = None,
    ) -> schemas.InferenceJob:
        """Update the status of an inference job.

        Parameters
        ----------
        session
            The database session to use.
        obj
            The inference job to update.
        status
            The new status.
        error_message
            Optional error message if status is 'failed'.

        Returns
        -------
        schemas.InferenceJob
            The updated inference job.
        """
        update_data = schemas.InferenceJobUpdate(
            status=status,  # type: ignore
            error_message=error_message,
        )
        return await self.update(session, obj, update_data)

    async def update_progress(
        self,
        session: AsyncSession,
        obj: schemas.InferenceJob,
        processed_items: int,
    ) -> schemas.InferenceJob:
        """Update the progress of an inference job.

        Parameters
        ----------
        session
            The database session to use.
        obj
            The inference job to update.
        processed_items
            The number of items processed.

        Returns
        -------
        schemas.InferenceJob
            The updated inference job.
        """
        progress = (
            processed_items / obj.total_items
            if obj.total_items > 0
            else 0.0
        )
        update_data = schemas.InferenceJobUpdate(
            processed_items=processed_items,
            progress=progress,
        )
        return await self.update(session, obj, update_data)

    async def cancel(
        self,
        session: AsyncSession,
        obj: schemas.InferenceJob,
    ) -> schemas.InferenceJob:
        """Cancel an inference job.

        Only jobs with status 'pending' or 'running' can be cancelled.

        Parameters
        ----------
        session
            The database session to use.
        obj
            The inference job to cancel.

        Returns
        -------
        schemas.InferenceJob
            The cancelled inference job.

        Raises
        ------
        ValueError
            If the job cannot be cancelled.
        """
        if obj.status not in ("pending", "running"):
            raise ValueError(
                f"Cannot cancel job with status '{obj.status}'. "
                "Only 'pending' or 'running' jobs can be cancelled."
            )
        return await self.update_status(session, obj, "cancelled")


inference_jobs = InferenceJobAPI()
