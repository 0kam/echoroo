"""Detection Review model.

This model tracks review status for ClipPrediction detections from
species detection jobs. It allows users to confirm, reject, or mark
detections as uncertain, and tracks conversion to annotations.
"""

import datetime
import enum
from typing import TYPE_CHECKING, Optional
from uuid import UUID, uuid4

import sqlalchemy.orm as orm
from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import ENUM as PgEnum

from echoroo.models.base import Base

if TYPE_CHECKING:
    from echoroo.models.clip_annotation import ClipAnnotation
    from echoroo.models.clip_prediction import ClipPrediction
    from echoroo.models.species_detection_job import SpeciesDetectionJob
    from echoroo.models.user import User

__all__ = [
    "DetectionReview",
    "DetectionReviewStatus",
]


class DetectionReviewStatus(str, enum.Enum):
    """Enumeration of detection review statuses."""

    UNREVIEWED = "unreviewed"
    """Detection has not been reviewed yet."""

    CONFIRMED = "confirmed"
    """Detection has been confirmed as correct."""

    REJECTED = "rejected"
    """Detection has been rejected as incorrect."""

    UNCERTAIN = "uncertain"
    """Reviewer is uncertain about the detection."""


# PostgreSQL ENUM type for review status
# Use explicit values to ensure lowercase values are sent to the database
detection_review_status_enum = PgEnum(
    "unreviewed", "confirmed", "rejected", "uncertain",
    name="detection_review_status",
    create_type=False,  # Don't create type, already exists from migration
)


class DetectionReview(Base):
    """Detection Review model.

    Tracks review status for ClipPrediction detections from species detection jobs.
    """

    __tablename__ = "detection_review"
    __table_args__ = (
        UniqueConstraint("clip_prediction_id", "species_detection_job_id"),
    )

    id: orm.Mapped[int] = orm.mapped_column(primary_key=True, init=False)
    """The database id of the detection review."""

    uuid: orm.Mapped[UUID] = orm.mapped_column(
        default_factory=uuid4,
        kw_only=True,
        unique=True,
    )
    """The UUID of the detection review."""

    # Links
    clip_prediction_id: orm.Mapped[int] = orm.mapped_column(
        ForeignKey("clip_prediction.id", ondelete="CASCADE"),
    )
    """The database id of the clip prediction being reviewed."""

    species_detection_job_id: orm.Mapped[int] = orm.mapped_column(
        ForeignKey("species_detection_job.id", ondelete="CASCADE"),
    )
    """The database id of the species detection job that created this detection."""

    # Review info
    status: orm.Mapped[str] = orm.mapped_column(
        detection_review_status_enum,
        nullable=False,
        default="unreviewed",
    )
    """Review status (unreviewed, confirmed, rejected, uncertain)."""

    reviewed_by_id: orm.Mapped[Optional[UUID]] = orm.mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    """The database id of the user who reviewed this detection."""

    reviewed_on: orm.Mapped[Optional[datetime.datetime]] = orm.mapped_column(
        nullable=True,
        default=None,
    )
    """Timestamp when the detection was reviewed."""

    notes: orm.Mapped[Optional[str]] = orm.mapped_column(
        nullable=True,
        default=None,
    )
    """Notes about the review."""

    # Conversion tracking
    converted_to_annotation: orm.Mapped[bool] = orm.mapped_column(
        nullable=False,
        default=False,
    )
    """Whether this detection has been converted to an annotation."""

    clip_annotation_id: orm.Mapped[Optional[int]] = orm.mapped_column(
        ForeignKey("clip_annotation.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    """The database id of the clip annotation created from this detection."""

    # Relationships
    clip_prediction: orm.Mapped["ClipPrediction"] = orm.relationship(
        init=False,
        repr=False,
        lazy="joined",
    )
    """The clip prediction being reviewed."""

    species_detection_job: orm.Mapped["SpeciesDetectionJob"] = orm.relationship(
        init=False,
        repr=False,
        lazy="joined",
    )
    """The species detection job that created this detection."""

    reviewed_by: orm.Mapped[Optional["User"]] = orm.relationship(
        init=False,
        repr=False,
        lazy="joined",
    )
    """The user who reviewed this detection."""

    clip_annotation: orm.Mapped[Optional["ClipAnnotation"]] = orm.relationship(
        init=False,
        repr=False,
        lazy="joined",
    )
    """The clip annotation created from this detection (if converted)."""
