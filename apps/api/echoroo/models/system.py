"""System configuration models.

Phase 13 P1 (T803a): rewritten to match the canonical spec / DB shape from
``data-model.md`` §3.19 and the baseline DDL in
``alembic/versions/0001_baseline_permissions_redesign.py``.

Drift items reconciled by this rewrite (see ``/tmp/phase13-inventory.md`` §(e)):

* ``value`` is now ``JSONB`` (was ``Text`` in the legacy ORM).
* ``value_type`` column dropped — JSONB is self-describing.
* ``description`` column dropped — not part of the canonical schema.
* The phantom ``setting_type`` enum is no longer declared anywhere.
* ``updated_by_id`` FK target changed from ``users`` to ``superusers``
  (only superusers may mutate system-wide settings; FR-094 / NFR-006).
* ``updated_by_id`` is ``NOT NULL`` (Phase 13 P1 R2 致命 #1) — every row
  must record the superuser who last persisted it. Boot-time defaults are
  no longer seeded by the baseline migration; the bootstrap superuser
  creation flow seeds them with a non-null FK.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from echoroo.models.base import Base


class SystemSetting(Base):
    """System-wide configuration settings.

    Stores key-value pairs for system configuration. Values are stored as
    native JSONB so the database is the single source of truth for both the
    raw value and its shape (string / number / boolean / object).

    Attributes:
        key: Unique setting identifier (primary key).
        value: Setting value as JSONB; reads return native Python objects.
        updated_at: Last update timestamp.
        updated_by_id: Superuser who last updated the setting.
    """

    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(
        String(100),
        primary_key=True,
        doc="Setting identifier (e.g., 'dormant_threshold_seconds')",
    )
    value: Mapped[Any] = mapped_column(
        JSONB,
        nullable=False,
        doc="Setting value as native JSONB",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
        doc="Last update timestamp",
    )
    updated_by_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("superusers.id"),
        nullable=False,
        doc="Superuser who last updated (FK → superusers.id, NOT NULL)",
    )

    def __repr__(self) -> str:
        """String representation of SystemSetting."""
        return f"<SystemSetting(key={self.key}, value={self.value!r})>"
