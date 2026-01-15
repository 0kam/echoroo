"""Inference Job model.

This model tracks ML inference jobs, providing visibility into the status
and progress of background inference tasks. Jobs can process entire datasets,
individual recordings, or be associated with specific model runs.
"""

import datetime
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID, uuid4

import sqlalchemy.orm as orm
from sqlalchemy import ForeignKey, JSON

from echoroo.models.base import Base

if TYPE_CHECKING:
    from echoroo.models.dataset import Dataset
    from echoroo.models.model_run import ModelRun
    from echoroo.models.recording import Recording
    from echoroo.models.user import User

__all__ = [
    "InferenceJob",
    "InferenceJobStatus",
]


class InferenceJobStatus:
    """Enumeration of possible inference job statuses."""

    PENDING = "pending"
    """Job is queued and waiting to start."""

    RUNNING = "running"
    """Job is currently being processed."""

    COMPLETED = "completed"
    """Job finished successfully."""

    FAILED = "failed"
    """Job encountered an error and stopped."""

    CANCELLED = "cancelled"
    """Job was manually cancelled."""


class InferenceJob(Base):
    """Inference Job model.

    Tracks ML inference jobs including their status, progress, and results.
    Jobs can be scoped to a dataset, individual recording, or both.
    """

    __tablename__ = "inference_job"

    id: orm.Mapped[int] = orm.mapped_column(primary_key=True, init=False)
    """The database id of the inference job."""

    uuid: orm.Mapped[UUID] = orm.mapped_column(
        default_factory=uuid4,
        kw_only=True,
        unique=True,
    )
    """The UUID of the inference job."""

    model_run_id: orm.Mapped[Optional[int]] = orm.mapped_column(
        ForeignKey("model_run.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    """The database id of the model run associated with this job."""

    dataset_id: orm.Mapped[Optional[int]] = orm.mapped_column(
        ForeignKey("dataset.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    """The database id of the dataset being processed."""

    recording_id: orm.Mapped[Optional[int]] = orm.mapped_column(
        ForeignKey("recording.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    """The database id of the recording being processed."""

    created_by_id: orm.Mapped[Optional[int]] = orm.mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    """The database id of the user who created this job."""

    status: orm.Mapped[str] = orm.mapped_column(
        nullable=False,
        default=InferenceJobStatus.PENDING,
    )
    """Current status of the job (pending, running, completed, failed, cancelled)."""

    progress: orm.Mapped[float] = orm.mapped_column(
        nullable=False,
        default=0.0,
    )
    """Progress of the job as a fraction (0.0 to 1.0)."""

    total_items: orm.Mapped[int] = orm.mapped_column(
        nullable=False,
        default=0,
    )
    """Total number of items to process."""

    processed_items: orm.Mapped[int] = orm.mapped_column(
        nullable=False,
        default=0,
    )
    """Number of items that have been processed."""

    error_message: orm.Mapped[Optional[str]] = orm.mapped_column(
        nullable=True,
        default=None,
    )
    """Error message if the job failed."""

    config: orm.Mapped[Optional[dict[str, Any]]] = orm.mapped_column(
        JSON,
        nullable=True,
        default=None,
    )
    """Model-specific configuration for the inference job."""

    started_on: orm.Mapped[Optional[datetime.datetime]] = orm.mapped_column(
        nullable=True,
        default=None,
    )
    """Timestamp when the job started processing."""

    completed_on: orm.Mapped[Optional[datetime.datetime]] = orm.mapped_column(
        nullable=True,
        default=None,
    )
    """Timestamp when the job finished (successfully or with error)."""

    # Relations
    model_run: orm.Mapped[Optional["ModelRun"]] = orm.relationship(
        init=False,
        repr=False,
        lazy="joined",
    )
    """The model run associated with this job."""

    dataset: orm.Mapped[Optional["Dataset"]] = orm.relationship(
        init=False,
        repr=False,
        lazy="joined",
    )
    """The dataset being processed by this job."""

    recording: orm.Mapped[Optional["Recording"]] = orm.relationship(
        init=False,
        repr=False,
        lazy="joined",
    )
    """The recording being processed by this job."""

    created_by: orm.Mapped[Optional["User"]] = orm.relationship(
        init=False,
        repr=False,
        lazy="joined",
    )
    """The user who created this job."""
