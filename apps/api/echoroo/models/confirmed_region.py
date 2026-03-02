"""ConfirmedRegion model for verified time segments in recordings."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Float, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from echoroo.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from echoroo.models.recording import Recording
    from echoroo.models.user import User


class ConfirmedRegion(UUIDMixin, TimestampMixin, Base):
    """A time region in a recording that has been confirmed by a reviewer.

    Confirmed regions represent segments of a recording where a species or
    sound has been positively identified. They are created when an annotation
    is confirmed during the review workflow.

    Attributes:
        id: Unique identifier (UUID)
        recording_id: Foreign key to the source recording
        start_time: Start time in seconds within the recording
        end_time: End time in seconds within the recording
        reviewed_by_id: Foreign key to the user who confirmed this region
    """

    __tablename__ = "confirmed_regions"

    recording_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("recordings.id", ondelete="CASCADE"),
        nullable=False,
        doc="Source recording ID",
    )
    start_time: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        doc="Start time in seconds within the recording",
    )
    end_time: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        doc="End time in seconds within the recording",
    )
    reviewed_by_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        doc="User who confirmed this region",
    )

    # Relationships
    recording: Mapped[Recording] = relationship(
        "Recording",
        lazy="joined",
    )
    reviewed_by: Mapped[User] = relationship(
        "User",
        lazy="joined",
    )

    __table_args__ = (
        Index("ix_confirmed_regions_recording_id", "recording_id"),
        Index("ix_confirmed_regions_reviewed_by_id", "reviewed_by_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<ConfirmedRegion(id={self.id}, recording_id={self.recording_id}, "
            f"start={self.start_time}, end={self.end_time})>"
        )
