"""Recorder model for audio recording devices."""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from echoroo.models.base import Base, TimestampMixin


class Recorder(TimestampMixin, Base):
    """Recorder entity for audio recording devices.

    This model represents an audio recording device used for field recordings.
    Recorders have unique identifiers (e.g., 'am120') and metadata about the
    manufacturer and device specifications.

    Attributes:
        id: Unique recorder identifier (e.g., 'am120'), primary key
        manufacturer: Manufacturer name
        recorder_name: Model or name of the recorder
        version: Optional version or revision number
        created_at: Record creation timestamp (from TimestampMixin)
        updated_at: Last update timestamp (from TimestampMixin)
    """

    __tablename__ = "recorders"

    id: Mapped[str] = mapped_column(
        String(50),
        primary_key=True,
        doc="Unique recorder identifier (e.g., 'am120')",
    )
    manufacturer: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        doc="Manufacturer name",
    )
    recorder_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        doc="Model or name of the recorder",
    )
    version: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        doc="Optional version or revision number",
    )

    def __repr__(self) -> str:
        """String representation of Recorder."""
        return f"<Recorder(id={self.id}, manufacturer={self.manufacturer}, recorder_name={self.recorder_name})>"
