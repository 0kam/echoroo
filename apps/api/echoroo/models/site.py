"""Site model for geographic locations."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from echoroo.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from echoroo.models.dataset import Dataset
    from echoroo.models.project import Project


class Site(UUIDMixin, TimestampMixin, Base):
    """Geographic location for field recordings using H3 hexagonal cells.

    Attributes:
        id: Unique identifier (UUID)
        project_id: Foreign key to parent project
        name: Human-readable site name (max 200 chars)
        h3_index: Uber H3 cell identifier (resolution 5-15)
        created_at: Creation timestamp
        updated_at: Last update timestamp
        project: Relationship to Project
        datasets: Relationship to Dataset[]
    """

    __tablename__ = "sites"

    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        doc="Parent project ID",
    )
    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        doc="Human-readable site name",
    )
    h3_index: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        doc="Uber H3 cell identifier",
    )

    # Relationships
    project: Mapped[Project] = relationship(
        "Project",
        lazy="joined",
    )
    datasets: Mapped[list[Dataset]] = relationship(
        "Dataset",
        back_populates="site",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_site_project_name"),
        UniqueConstraint("project_id", "h3_index", name="uq_site_project_h3"),
        Index("ix_sites_project_id", "project_id"),
        Index("ix_sites_h3_index", "h3_index"),
    )

    def __repr__(self) -> str:
        return f"<Site(id={self.id}, name={self.name})>"
