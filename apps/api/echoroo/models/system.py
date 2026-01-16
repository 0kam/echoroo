"""System configuration models."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column

from echoroo.models.base import Base


class SystemSetting(Base):
    """System-wide configuration settings.

    Stores key-value pairs for system configuration with type information.
    Used for runtime settings that can be changed without code deployment.

    Attributes:
        key: Unique setting identifier (primary key)
        value: Setting value stored as text (JSON-encoded for complex types)
        value_type: Type of the value (string, number, boolean, json)
        description: Human-readable description of the setting
        updated_at: Last update timestamp
        updated_by_id: User who last updated the setting
    """

    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(
        String(100),
        primary_key=True,
        doc="Setting identifier (e.g., 'registration_mode')",
    )
    value: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Setting value (JSON-encoded for complex types)",
    )
    value_type: Mapped[str] = mapped_column(
        ENUM("string", "number", "boolean", "json", name="setting_type", create_type=False),
        nullable=False,
        doc="Value type for parsing",
    )
    description: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        doc="Human-readable description",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
        doc="Last update timestamp",
    )
    updated_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
        doc="User who last updated (None for system defaults)",
    )

    def __repr__(self) -> str:
        """String representation of SystemSetting."""
        return f"<SystemSetting(key={self.key}, value={self.value}, type={self.value_type})>"
