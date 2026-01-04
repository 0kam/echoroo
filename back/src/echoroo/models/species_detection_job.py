"""Species Detection Job model.

This model tracks species detection jobs using BirdNET/Perch analysis
for automatic species identification. Jobs can process entire datasets
with optional filters, and results are stored as ClipPredictions linked
via ModelRun.
"""

import datetime
import enum
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID, uuid4

import sqlalchemy.orm as orm
from sqlalchemy import JSON, Enum, ForeignKey
from sqlalchemy.dialects.postgresql import ENUM as PgEnum

from echoroo.models.base import Base

if TYPE_CHECKING:
    from echoroo.models.dataset import Dataset
    from echoroo.models.model_run import ModelRun
    from echoroo.models.user import User

__all__ = [
    "SpeciesDetectionJob",
    "SpeciesDetectionJobStatus",
]


class SpeciesDetectionJobStatus(str, enum.Enum):
    """Enumeration of possible species detection job statuses."""

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


# PostgreSQL ENUM type for status
# Use values_callable to ensure lowercase values are sent to the database
species_detection_job_status_enum = PgEnum(
    "pending", "running", "completed", "failed", "cancelled",
    name="species_detection_job_status",
    create_type=False,  # Don't create type, already exists from migration
)


class SpeciesDetectionJob(Base):
    """Species Detection Job model.

    Tracks BirdNET/Perch analysis jobs for automatic species detection.
    Results are stored as ClipPredictions linked via ModelRun.
    """

    __tablename__ = "species_detection_job"

    id: orm.Mapped[int] = orm.mapped_column(primary_key=True, init=False)
    """The database id of the species detection job."""

    uuid: orm.Mapped[UUID] = orm.mapped_column(
        default_factory=uuid4,
        kw_only=True,
        unique=True,
    )
    """The UUID of the species detection job."""

    name: orm.Mapped[str]
    """The name of the species detection job."""

    dataset_id: orm.Mapped[int] = orm.mapped_column(
        ForeignKey("dataset.id", ondelete="CASCADE"),
    )
    """The database id of the dataset being processed."""

    # Model configuration
    model_name: orm.Mapped[str]
    """The name of the detection model (e.g., 'birdnet' or 'perch')."""

    created_by_id: orm.Mapped[Optional[UUID]] = orm.mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    """The database id of the user who created this job."""

    model_version: orm.Mapped[str] = orm.mapped_column(default="latest")
    """The version of the detection model."""

    confidence_threshold: orm.Mapped[float] = orm.mapped_column(default=0.5)
    """Minimum confidence score for detections to be included."""

    overlap: orm.Mapped[float] = orm.mapped_column(default=0.0)
    """Overlap fraction between consecutive analysis windows."""

    locale: orm.Mapped[str] = orm.mapped_column(default="en_us")
    """Locale for species common names (e.g., 'en_us', 'ja')."""

    use_metadata_filter: orm.Mapped[bool] = orm.mapped_column(default=False)
    """Whether to apply species filters explicitly after the run."""

    custom_species_list: orm.Mapped[Optional[list[str]]] = orm.mapped_column(
        JSON,
        nullable=True,
        default=None,
    )
    """Custom list of species to detect (if not using metadata filter)."""

    # Recording filters
    recording_filters: orm.Mapped[Optional[dict[str, Any]]] = orm.mapped_column(
        JSON,
        nullable=True,
        default=None,
    )
    """Recording filters (date_from, date_to, h3_indices, tag_ids, recording_uuids)."""

    # Status tracking
    status: orm.Mapped[str] = orm.mapped_column(
        species_detection_job_status_enum,
        nullable=False,
        default="pending",
    )
    """Current status of the job (pending, running, completed, failed, cancelled)."""

    progress: orm.Mapped[float] = orm.mapped_column(
        nullable=False,
        default=0.0,
    )
    """Progress of the job as a fraction (0.0 to 1.0)."""

    total_recordings: orm.Mapped[int] = orm.mapped_column(
        nullable=False,
        default=0,
    )
    """Total number of recordings to process."""

    processed_recordings: orm.Mapped[int] = orm.mapped_column(
        nullable=False,
        default=0,
    )
    """Number of recordings that have been processed."""

    total_clips: orm.Mapped[int] = orm.mapped_column(
        nullable=False,
        default=0,
    )
    """Total number of audio clips analyzed."""

    total_detections: orm.Mapped[int] = orm.mapped_column(
        nullable=False,
        default=0,
    )
    """Total number of species detections found."""

    # Error handling
    error_message: orm.Mapped[Optional[str]] = orm.mapped_column(
        nullable=True,
        default=None,
    )
    """Error message if the job failed."""

    # Timestamps
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

    # Result link
    model_run_id: orm.Mapped[Optional[int]] = orm.mapped_column(
        ForeignKey("model_run.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    """The database id of the model run that contains the predictions."""

    # Relationships
    dataset: orm.Mapped["Dataset"] = orm.relationship(
        init=False,
        repr=False,
        lazy="joined",
    )
    """The dataset being processed by this job."""

    created_by: orm.Mapped[Optional["User"]] = orm.relationship(
        init=False,
        repr=False,
        lazy="joined",
    )
    """The user who created this job."""

    model_run: orm.Mapped[Optional["ModelRun"]] = orm.relationship(
        init=False,
        repr=False,
        lazy="joined",
    )
    """The model run that contains the prediction results."""
