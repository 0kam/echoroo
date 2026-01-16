"""Recording model for audio files."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from echoroo.models.base import Base, TimestampMixin, UUIDMixin
from echoroo.models.enums import DatetimeParseStatus

if TYPE_CHECKING:
    from echoroo.models.clip import Clip
    from echoroo.models.dataset import Dataset


class Recording(UUIDMixin, TimestampMixin, Base):
    """Single audio file with extracted metadata.

    Attributes:
        id: Unique identifier (UUID)
        dataset_id: Foreign key to parent dataset
        filename: Original filename
        path: Relative path within audio_dir
        hash: MD5 hash for deduplication
        duration: Duration in seconds
        samplerate: Sample rate in Hz
        channels: Number of audio channels
        bit_depth: Bits per sample
        datetime: Recording date/time (parsed)
        datetime_parse_status: Parse status
        datetime_parse_error: Parse error details
        time_expansion: Time expansion factor
        note: User notes
    """

    __tablename__ = "recordings"

    dataset_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("datasets.id", ondelete="CASCADE"),
        nullable=False,
        doc="Parent dataset ID",
    )
    filename: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Original filename",
    )
    path: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        doc="Relative path within audio_dir",
    )
    hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        doc="MD5 hash for deduplication",
    )
    duration: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        doc="Duration in seconds",
    )
    samplerate: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        doc="Sample rate in Hz",
    )
    channels: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        doc="Number of audio channels",
    )
    bit_depth: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        doc="Bits per sample",
    )
    datetime: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Recording date/time (parsed)",
    )
    datetime_parse_status: Mapped[DatetimeParseStatus] = mapped_column(
        Enum(
            DatetimeParseStatus,
            name="datetimeparsestatus",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        default=DatetimeParseStatus.PENDING,
        nullable=False,
        doc="Datetime parse status",
    )
    datetime_parse_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Parse error details",
    )
    time_expansion: Mapped[float] = mapped_column(
        Float,
        default=1.0,
        nullable=False,
        doc="Time expansion factor",
    )
    note: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="User notes",
    )

    # Relationships
    dataset: Mapped[Dataset] = relationship(
        "Dataset",
        back_populates="recordings",
        lazy="joined",
    )
    clips: Mapped[list[Clip]] = relationship(
        "Clip",
        back_populates="recording",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("dataset_id", "path", name="uq_recording_dataset_path"),
        Index("ix_recordings_dataset_id", "dataset_id"),
        Index("ix_recordings_hash", "hash"),
        Index("ix_recordings_datetime", "datetime"),
        Index("ix_recordings_dataset_id_datetime", "dataset_id", "datetime"),
    )

    def __repr__(self) -> str:
        return f"<Recording(id={self.id}, filename={self.filename})>"

    @property
    def effective_duration(self) -> float:
        """Duration with time expansion applied."""
        return self.duration * self.time_expansion

    @property
    def is_ultrasonic(self) -> bool:
        """True if samplerate > 48000 Hz."""
        return self.samplerate > 48000
