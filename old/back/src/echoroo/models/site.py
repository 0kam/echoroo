"""Site models.

Defines monitoring locations and associated media assets.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
import sqlalchemy.orm as orm

from echoroo.models.base import Base

if TYPE_CHECKING:
    from echoroo.models.dataset import Dataset
    from echoroo.models.project import Project

__all__ = ["Site", "SiteImage"]


class Site(Base):
    """Monitoring location lookup table."""

    __tablename__ = "site"

    site_id: orm.Mapped[str] = orm.mapped_column(
        sa.String(length=255),
        primary_key=True,
    )
    """Natural identifier for the site (e.g. tateyama01)."""

    site_name: orm.Mapped[str] = orm.mapped_column(
        sa.String(length=255),
        nullable=False,
    )
    """Human-readable display name."""

    h3_index: orm.Mapped[str] = orm.mapped_column(
        sa.String(length=32),
        nullable=False,
        index=True,
    )
    """Uber H3 cell id representing the site location."""

    project_id: orm.Mapped[str] = orm.mapped_column(
        sa.ForeignKey("project.project_id", ondelete="RESTRICT"),
        nullable=False,
    )
    """Owning project identifier."""

    # Relationships -----------------------------------------------------------------
    images: orm.Mapped[list["SiteImage"]] = orm.relationship(
        "SiteImage",
        cascade="all, delete-orphan",
        back_populates="site",
        default_factory=list,
        repr=False,
        init=False,
    )
    """Associated site imagery assets."""

    datasets: orm.Mapped[list["Dataset"]] = orm.relationship(
        "Dataset",
        back_populates="primary_site",
        default_factory=list,
        repr=False,
        init=False,
    )
    """Datasets referencing this site as primary location."""

    project: orm.Mapped["Project"] = orm.relationship(
        "Project",
        back_populates="sites",
        repr=False,
        init=False,
    )
    """Project that owns this site."""


class SiteImage(Base):
    """Image assets associated with a site."""

    __tablename__ = "site_image"

    site_image_id: orm.Mapped[str] = orm.mapped_column(
        sa.String(length=255),
        primary_key=True,
    )
    """Identifier for the image entry."""

    site_id: orm.Mapped[str] = orm.mapped_column(
        sa.ForeignKey("site.site_id", ondelete="CASCADE"),
        nullable=False,
    )
    """Foreign key to the parent site."""

    site_image_path: orm.Mapped[str] = orm.mapped_column(
        sa.String(length=512),
        nullable=False,
    )
    """Filesystem path relative to the metadata storage root."""

    site: orm.Mapped[Site] = orm.relationship(
        "Site",
        back_populates="images",
        repr=False,
        init=False,
    )
    """Parent site relationship."""
