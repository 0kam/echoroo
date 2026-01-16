"""License model for audio content licensing."""

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from echoroo.models.base import Base, TimestampMixin


class License(TimestampMixin, Base):
    """License entity for audio content licensing.

    This model represents a license type that can be applied to audio recordings,
    following Creative Commons and similar licensing standards. The ID is a string
    code (e.g., 'BY-NC-SA') for easy reference and compatibility with standard
    license identifiers.

    Attributes:
        id: License identifier code (e.g., 'BY-NC-SA'), primary key
        name: Full license name (required, max 200 chars)
        short_name: Short license name (required, max 50 chars)
        url: Optional URL to license text/details
        description: Optional detailed description of license terms
        created_at: License creation timestamp (from TimestampMixin)
        updated_at: Last update timestamp (from TimestampMixin)
    """

    __tablename__ = "licenses"

    id: Mapped[str] = mapped_column(
        String(50),
        primary_key=True,
        doc="License identifier code (e.g., 'BY-NC-SA')",
    )
    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        doc="Full license name",
    )
    short_name: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        doc="Short license name",
    )
    url: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        doc="URL to license text/details",
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Detailed description of license terms",
    )

    def __repr__(self) -> str:
        """String representation of License."""
        return f"<License(id={self.id}, name={self.name})>"
