"""Clip model for time segments within recordings."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import CheckConstraint, Float, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from echoroo.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from echoroo.models.recording import Recording


class Clip(UUIDMixin, TimestampMixin, Base):
    """Time segment within a recording.

    Attributes:
        id: Unique identifier (UUID)
        recording_id: Foreign key to parent recording
        start_time: Start time in seconds
        end_time: End time in seconds
        note: User notes
    """

    __tablename__ = "clips"

    recording_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("recordings.id", ondelete="CASCADE"),
        nullable=False,
        doc="Parent recording ID",
    )
    start_time: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        doc="Start time in seconds",
    )
    end_time: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        doc="End time in seconds",
    )
    note: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="User notes",
    )

    # Relationships
    recording: Mapped[Recording] = relationship(
        "Recording",
        back_populates="clips",
        lazy="joined",
    )

    __table_args__ = (
        UniqueConstraint("recording_id", "start_time", "end_time", name="uq_clip_recording_time"),
        CheckConstraint("end_time > start_time", name="ck_clip_valid_time_range"),
        Index("ix_clips_recording_id", "recording_id"),
    )

    def __repr__(self) -> str:
        return f"<Clip(id={self.id}, start={self.start_time}, end={self.end_time})>"

    @property
    def duration(self) -> float:
        """Clip duration in seconds."""
        return self.end_time - self.start_time
