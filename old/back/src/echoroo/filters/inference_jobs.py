"""Filters for Inference Jobs."""

from uuid import UUID

from sqlalchemy import Select

from echoroo import models
from echoroo.filters import base

__all__ = [
    "InferenceJobFilter",
    "StatusFilter",
    "CreatedOnFilter",
    "DatasetFilter",
    "RecordingFilter",
]


StatusFilter = base.string_filter(models.InferenceJob.status)
"""Filter inference jobs by status (pending, running, completed, failed, cancelled)."""

CreatedOnFilter = base.date_filter(models.InferenceJob.created_on)
"""Filter inference jobs by creation date."""


class DatasetFilter(base.Filter):
    """Filter inference jobs by dataset UUID."""

    eq: UUID | None = None

    def filter(self, query: Select) -> Select:
        """Apply the filter."""
        if self.eq is None:
            return query

        return query.join(
            models.Dataset,
            models.Dataset.id == models.InferenceJob.dataset_id,
        ).where(models.Dataset.uuid == self.eq)


class RecordingFilter(base.Filter):
    """Filter inference jobs by recording UUID."""

    eq: UUID | None = None

    def filter(self, query: Select) -> Select:
        """Apply the filter."""
        if self.eq is None:
            return query

        return query.join(
            models.Recording,
            models.Recording.id == models.InferenceJob.recording_id,
        ).where(models.Recording.uuid == self.eq)


InferenceJobFilter = base.combine(
    status=StatusFilter,
    created_on=CreatedOnFilter,
    dataset=DatasetFilter,
    recording=RecordingFilter,
)
