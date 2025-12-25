"""Foundation model metadata and run tracking."""

from __future__ import annotations

import datetime
import enum
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import sqlalchemy.orm as orm
from sqlalchemy import JSON, Enum, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import ENUM as PgEnum

from echoroo.models.base import Base

if TYPE_CHECKING:  # pragma: no cover - circular imports
    from echoroo.models.dataset import Dataset
    from echoroo.models.model_run import ModelRun
    from echoroo.models.species_detection_job import SpeciesDetectionJob
    from echoroo.models.tag import Tag
    from echoroo.models.user import User

__all__ = [
    "FoundationModel",
    "FoundationModelRun",
    "FoundationModelRunSpecies",
    "FoundationModelRunStatus",
]


class FoundationModelRunStatus(str, enum.Enum):
    """Statuses for foundation model runs."""

    QUEUED = "queued"
    RUNNING = "running"
    POST_PROCESSING = "post_processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


foundation_model_run_status_enum = PgEnum(
    "queued",
    "running",
    "post_processing",
    "completed",
    "failed",
    "cancelled",
    name="foundation_model_run_status",
    create_type=False,
)


class FoundationModel(Base):
    """Registered foundation model (BirdNET, Perch, etc.)."""

    __tablename__ = "foundation_model"
    __table_args__ = (UniqueConstraint("slug"), UniqueConstraint("provider", "version"))

    id: orm.Mapped[int] = orm.mapped_column(primary_key=True, init=False)

    uuid: orm.Mapped[UUID] = orm.mapped_column(
        default_factory=uuid4,
        unique=True,
        kw_only=True,
    )

    slug: orm.Mapped[str]
    """Unique slug identifier (e.g., birdnet-v2-4)."""

    display_name: orm.Mapped[str]
    """Human-friendly model name."""

    provider: orm.Mapped[str]
    """Provider key (`birdnet`, `perch`, ...)."""

    version: orm.Mapped[str]
    """Version string."""

    description: orm.Mapped[str | None] = orm.mapped_column(default=None)
    """Optional description."""

    default_confidence_threshold: orm.Mapped[float] = orm.mapped_column(default=0.1)
    """Default confidence threshold."""

    is_active: orm.Mapped[bool] = orm.mapped_column(default=True)
    """Whether the model is visible for selection."""

    runs: orm.Mapped[list["FoundationModelRun"]] = orm.relationship(
        back_populates="foundation_model",
        init=False,
        repr=False,
        default_factory=list,
    )


class FoundationModelRun(Base):
    """A single execution of a foundation model on a dataset."""

    __tablename__ = "foundation_model_run"
    __table_args__ = (
        UniqueConstraint("uuid"),
    )

    id: orm.Mapped[int] = orm.mapped_column(primary_key=True, init=False)

    uuid: orm.Mapped[UUID] = orm.mapped_column(
        default_factory=uuid4,
        unique=True,
        kw_only=True,
    )

    foundation_model_id: orm.Mapped[int] = orm.mapped_column(
        ForeignKey("foundation_model.id", ondelete="CASCADE"),
    )

    dataset_id: orm.Mapped[int] = orm.mapped_column(
        ForeignKey("dataset.id", ondelete="CASCADE"),
    )

    requested_by_id: orm.Mapped[UUID | None] = orm.mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"),
        default=None,
    )

    species_detection_job_id: orm.Mapped[int | None] = orm.mapped_column(
        ForeignKey("species_detection_job.id", ondelete="SET NULL"),
        default=None,
    )

    model_run_id: orm.Mapped[int | None] = orm.mapped_column(
        ForeignKey("model_run.id", ondelete="SET NULL"),
        default=None,
    )

    status: orm.Mapped[FoundationModelRunStatus] = orm.mapped_column(
        Enum(
            FoundationModelRunStatus,
            name=foundation_model_run_status_enum.name,
            values_callable=lambda x: [e.value for e in x],
        ),
        default=FoundationModelRunStatus.QUEUED,
    )

    confidence_threshold: orm.Mapped[float] = orm.mapped_column(default=0.1)

    scope: orm.Mapped[dict[str, Any] | None] = orm.mapped_column(JSON, default=None)

    progress: orm.Mapped[float] = orm.mapped_column(default=0.0)

    total_recordings: orm.Mapped[int] = orm.mapped_column(default=0)
    processed_recordings: orm.Mapped[int] = orm.mapped_column(default=0)
    total_clips: orm.Mapped[int] = orm.mapped_column(default=0)
    total_detections: orm.Mapped[int] = orm.mapped_column(default=0)

    classification_csv_path: orm.Mapped[str | None] = orm.mapped_column(default=None)
    embedding_store_key: orm.Mapped[str | None] = orm.mapped_column(default=None)

    summary: orm.Mapped[dict[str, Any] | None] = orm.mapped_column(JSON, default=None)
    error: orm.Mapped[dict[str, Any] | None] = orm.mapped_column(JSON, default=None)

    started_on: orm.Mapped[datetime.datetime | None] = orm.mapped_column(
        default=None,
    )
    completed_on: orm.Mapped[datetime.datetime | None] = orm.mapped_column(
        default=None,
    )

    foundation_model: orm.Mapped["FoundationModel"] = orm.relationship(
        back_populates="runs",
        init=False,
        repr=False,
    )

    dataset: orm.Mapped["Dataset"] = orm.relationship(
        init=False,
        repr=False,
    )

    requested_by: orm.Mapped["User | None"] = orm.relationship(
        init=False,
        repr=False,
    )

    job: orm.Mapped["SpeciesDetectionJob | None"] = orm.relationship(
        init=False,
        repr=False,
    )

    model_run: orm.Mapped["ModelRun | None"] = orm.relationship(
        init=False,
        repr=False,
    )

    species: orm.Mapped[list["FoundationModelRunSpecies"]] = orm.relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        init=False,
        repr=False,
        default_factory=list,
    )


class FoundationModelRunSpecies(Base):
    """Aggregated per-species summary for a foundation model run."""

    __tablename__ = "foundation_model_run_species"
    __table_args__ = (
        UniqueConstraint(
            "foundation_model_run_id",
            "gbif_taxon_id",
        ),
    )

    id: orm.Mapped[int] = orm.mapped_column(primary_key=True, init=False)

    foundation_model_run_id: orm.Mapped[int] = orm.mapped_column(
        ForeignKey("foundation_model_run.id", ondelete="CASCADE"),
    )

    scientific_name: orm.Mapped[str]

    gbif_taxon_id: orm.Mapped[str | None] = orm.mapped_column(default=None)

    annotation_tag_id: orm.Mapped[int | None] = orm.mapped_column(
        ForeignKey("tag.id", ondelete="SET NULL"),
        default=None,
    )

    common_name_ja: orm.Mapped[str | None] = orm.mapped_column(default=None)

    detection_count: orm.Mapped[int] = orm.mapped_column(default=0)
    avg_confidence: orm.Mapped[float] = orm.mapped_column(default=0.0)

    run: orm.Mapped["FoundationModelRun"] = orm.relationship(
        back_populates="species",
        init=False,
        repr=False,
    )

    tag: orm.Mapped["Tag | None"] = orm.relationship(
        init=False,
        repr=False,
    )
