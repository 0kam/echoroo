"""Species filter models for geographic and occurrence-based filtering."""

from __future__ import annotations

import datetime
import enum
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import sqlalchemy.orm as orm
from sqlalchemy import Enum, ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.dialects.postgresql import JSONB

from echoroo.models.base import Base

if TYPE_CHECKING:
    from echoroo.models.clip_prediction import ClipPrediction
    from echoroo.models.foundation_model import FoundationModelRun
    from echoroo.models.tag import Tag
    from echoroo.models.user import User

__all__ = [
    "SpeciesFilter",
    "SpeciesFilterApplication",
    "SpeciesFilterApplicationStatus",
    "SpeciesFilterMask",
    "SpeciesFilterType",
]


class SpeciesFilterType(str, enum.Enum):
    """Types of species filters."""

    GEOGRAPHIC = "geographic"
    OCCURRENCE = "occurrence"
    CUSTOM = "custom"


class SpeciesFilterApplicationStatus(str, enum.Enum):
    """Statuses for species filter applications."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# PostgreSQL ENUM definitions
species_filter_type_enum = PgEnum(
    "geographic",
    "occurrence",
    "custom",
    name="species_filter_type",
    create_type=False,
)

species_filter_application_status_enum = PgEnum(
    "pending",
    "running",
    "completed",
    "failed",
    "cancelled",
    name="species_filter_application_status",
    create_type=False,
)


class SpeciesFilter(Base):
    """Species filter definition.

    Represents a filter that can be applied to foundation model predictions
    to include or exclude species based on geographic location, occurrence
    data, or custom criteria.
    """

    __tablename__ = "species_filter"
    __table_args__ = (
        UniqueConstraint("slug"),
        UniqueConstraint("provider", "version"),
    )

    id: orm.Mapped[int] = orm.mapped_column(primary_key=True, init=False)
    """The database id of the species filter."""

    uuid: orm.Mapped[UUID] = orm.mapped_column(
        default_factory=uuid4,
        unique=True,
        kw_only=True,
    )
    """The UUID of the species filter."""

    slug: orm.Mapped[str] = orm.mapped_column()
    """Unique slug identifier (e.g., birdnet-geo-v2-4)."""

    display_name: orm.Mapped[str] = orm.mapped_column()
    """Human-friendly filter name."""

    provider: orm.Mapped[str] = orm.mapped_column()
    """Provider key (birdnet, ebird, gbif, ...)."""

    version: orm.Mapped[str] = orm.mapped_column()
    """Version string."""

    description: orm.Mapped[str | None] = orm.mapped_column(default=None)
    """Optional description of the filter."""

    filter_type: orm.Mapped[SpeciesFilterType] = orm.mapped_column(
        Enum(
            SpeciesFilterType,
            name=species_filter_type_enum.name,
            values_callable=lambda x: [e.value for e in x],
        ),
        default=SpeciesFilterType.GEOGRAPHIC,
    )
    """Type of filter (geographic, occurrence, custom)."""

    default_threshold: orm.Mapped[float] = orm.mapped_column(default=0.03)
    """Default probability threshold for species inclusion."""

    requires_location: orm.Mapped[bool] = orm.mapped_column(default=True)
    """Whether the filter requires location coordinates."""

    requires_date: orm.Mapped[bool] = orm.mapped_column(default=True)
    """Whether the filter requires date/time information."""

    is_active: orm.Mapped[bool] = orm.mapped_column(default=True)
    """Whether the filter is available for selection."""

    # Relationships
    applications: orm.Mapped[list["SpeciesFilterApplication"]] = orm.relationship(
        back_populates="species_filter",
        init=False,
        repr=False,
        default_factory=list,
    )
    """List of applications of this filter."""


class SpeciesFilterApplication(Base):
    """Application of a species filter to a foundation model run.

    Tracks the status and results of applying a species filter to
    the predictions from a foundation model run.
    """

    __tablename__ = "species_filter_application"
    __table_args__ = (
        UniqueConstraint("foundation_model_run_id", "species_filter_id"),
        Index("ix_species_filter_application_run_id", "foundation_model_run_id"),
        Index("ix_species_filter_application_status", "status"),
    )

    id: orm.Mapped[int] = orm.mapped_column(primary_key=True, init=False)
    """The database id of the filter application."""

    uuid: orm.Mapped[UUID] = orm.mapped_column(
        default_factory=uuid4,
        unique=True,
        kw_only=True,
    )
    """The UUID of the filter application."""

    foundation_model_run_id: orm.Mapped[int] = orm.mapped_column(
        ForeignKey("foundation_model_run.id", ondelete="CASCADE"),
    )
    """The foundation model run to which this filter was applied."""

    species_filter_id: orm.Mapped[int] = orm.mapped_column(
        ForeignKey("species_filter.id", ondelete="CASCADE"),
    )
    """The species filter that was applied."""

    threshold: orm.Mapped[float] = orm.mapped_column(default=0.03)
    """Probability threshold used for this application."""

    apply_to_all_detections: orm.Mapped[bool] = orm.mapped_column(default=True)
    """Whether the filter was applied to all detections."""

    status: orm.Mapped[SpeciesFilterApplicationStatus] = orm.mapped_column(
        Enum(
            SpeciesFilterApplicationStatus,
            name=species_filter_application_status_enum.name,
            values_callable=lambda x: [e.value for e in x],
        ),
        default=SpeciesFilterApplicationStatus.PENDING,
    )
    """Current status of the filter application."""

    progress: orm.Mapped[float] = orm.mapped_column(default=0.0)
    """Progress percentage (0.0 to 1.0)."""

    total_detections: orm.Mapped[int] = orm.mapped_column(default=0)
    """Total number of detections processed."""

    filtered_detections: orm.Mapped[int] = orm.mapped_column(default=0)
    """Number of detections that passed the filter (included)."""

    excluded_detections: orm.Mapped[int] = orm.mapped_column(default=0)
    """Number of detections excluded by the filter."""

    applied_by_id: orm.Mapped[UUID | None] = orm.mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"),
        default=None,
    )
    """The user who initiated the filter application."""

    started_on: orm.Mapped[datetime.datetime | None] = orm.mapped_column(
        default=None,
    )
    """Timestamp when the filter application started."""

    completed_on: orm.Mapped[datetime.datetime | None] = orm.mapped_column(
        default=None,
    )
    """Timestamp when the filter application completed."""

    error: orm.Mapped[dict[str, Any] | None] = orm.mapped_column(
        JSONB,
        default=None,
    )
    """Error details if the application failed."""

    # Relationships
    foundation_model_run: orm.Mapped["FoundationModelRun"] = orm.relationship(
        init=False,
        repr=False,
    )
    """The foundation model run."""

    species_filter: orm.Mapped["SpeciesFilter"] = orm.relationship(
        back_populates="applications",
        init=False,
        repr=False,
    )
    """The species filter definition."""

    applied_by: orm.Mapped["User | None"] = orm.relationship(
        init=False,
        repr=False,
    )
    """The user who applied the filter."""

    masks: orm.Mapped[list["SpeciesFilterMask"]] = orm.relationship(
        back_populates="species_filter_application",
        cascade="all, delete-orphan",
        init=False,
        repr=False,
        default_factory=list,
    )
    """List of mask entries for this application."""


class SpeciesFilterMask(Base):
    """Mask entry for a species filter application.

    Represents the inclusion/exclusion decision for a specific
    clip prediction and tag combination based on the filter criteria.
    """

    __tablename__ = "species_filter_mask"
    __table_args__ = (
        UniqueConstraint(
            "species_filter_application_id",
            "clip_prediction_id",
            "tag_id",
        ),
        Index(
            "ix_species_filter_mask_application_id",
            "species_filter_application_id",
        ),
        Index(
            "ix_species_filter_mask_application_included",
            "species_filter_application_id",
            "is_included",
        ),
    )

    id: orm.Mapped[int] = orm.mapped_column(primary_key=True, init=False)
    """The database id of the mask entry."""

    species_filter_application_id: orm.Mapped[int] = orm.mapped_column(
        ForeignKey("species_filter_application.id", ondelete="CASCADE"),
    )
    """The filter application this mask belongs to."""

    clip_prediction_id: orm.Mapped[int] = orm.mapped_column(
        ForeignKey("clip_prediction.id", ondelete="CASCADE"),
    )
    """The clip prediction being filtered."""

    tag_id: orm.Mapped[int] = orm.mapped_column(
        ForeignKey("tag.id", ondelete="CASCADE"),
    )
    """The tag (species) being evaluated."""

    is_included: orm.Mapped[bool] = orm.mapped_column(default=True)
    """Whether the prediction passed the filter (True = included)."""

    occurrence_probability: orm.Mapped[float | None] = orm.mapped_column(
        default=None,
    )
    """The occurrence probability from the filter data source."""

    exclusion_reason: orm.Mapped[str | None] = orm.mapped_column(
        default=None,
    )
    """Reason for exclusion if is_included is False."""

    # Relationships
    species_filter_application: orm.Mapped["SpeciesFilterApplication"] = (
        orm.relationship(
            back_populates="masks",
            init=False,
            repr=False,
        )
    )
    """The parent filter application."""

    clip_prediction: orm.Mapped["ClipPrediction"] = orm.relationship(
        init=False,
        repr=False,
    )
    """The clip prediction."""

    tag: orm.Mapped["Tag"] = orm.relationship(
        init=False,
        repr=False,
    )
    """The tag (species)."""
