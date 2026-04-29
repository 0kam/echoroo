"""Site model for geographic locations."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from echoroo.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from echoroo.models.dataset import Dataset
    from echoroo.models.project import Project


class Site(UUIDMixin, TimestampMixin, Base):
    """Geographic location for field recordings using H3 hexagonal cells.

    Phase 13 P4 / T807 (2026-04-28): the ORM column is named
    ``h3_index_member`` to match the spec data-model §3.10 canonical
    name and the baseline migration ``0001_baseline_permissions_redesign``
    column. The legacy ``h3_index`` attribute name has been removed —
    every caller (schemas, services, repositories, frontend types,
    tests) must use ``h3_index_member`` going forward (full rename, no
    facade alias).

    Attributes:
        id: Unique identifier (UUID)
        project_id: Foreign key to parent project
        name: Human-readable site name (max 200 chars)
        h3_index_member: Uber H3 cell identifier at member precision
            (FR-028 / NFR-003; resolution 9 or 15 only). VARCHAR(32).
        h3_index_member_resolution: H3 resolution of ``h3_index_member``;
            CHECK constraint forces ``IN (9, 15)``. Default 15.
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
    h3_index_member: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        doc="Uber H3 cell identifier at member precision (FR-028)",
    )
    h3_index_member_resolution: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=15,
        server_default="15",
        doc="H3 resolution of h3_index_member; member precision: 9 or 15 (NFR-003)",
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
        UniqueConstraint("project_id", "name", name="ux_sites_project_name"),
        UniqueConstraint("project_id", "h3_index_member", name="ux_sites_project_h3"),
        CheckConstraint(
            "h3_index_member_resolution IN (9, 15)",
            name="ck_sites_h3_member_resolution",
        ),
        Index("ix_sites_project_id", "project_id"),
        Index("ix_sites_h3_index_member", "h3_index_member"),
    )

    def __repr__(self) -> str:
        return f"<Site(id={self.id}, name={self.name})>"
