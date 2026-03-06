"""Tag model for annotation taxonomy."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Enum, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from echoroo.models.base import Base, TimestampMixin, UUIDMixin
from echoroo.models.enums import TagCategory

if TYPE_CHECKING:
    from echoroo.models.annotation_project import AnnotationProject
    from echoroo.models.project import Project
    from echoroo.models.taxon import Taxon


class Tag(UUIDMixin, TimestampMixin, Base):
    """Taxonomy tag for annotating species, sound types, and quality.

    Attributes:
        id: Unique identifier (UUID)
        project_id: Foreign key to parent project
        parent_id: Optional foreign key to parent tag (self-referential hierarchy)
        name: Tag name (max 200 chars)
        category: Tag classification category
        gbif_taxon_key: Optional GBIF taxonomic key for species tags
        scientific_name: Optional scientific name (max 300 chars)
        common_name: Optional common name (max 300 chars)
    """

    __tablename__ = "tags"

    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        doc="Parent project ID",
    )
    parent_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tags.id", ondelete="SET NULL"),
        nullable=True,
        doc="Parent tag ID for hierarchical taxonomy",
    )
    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        doc="Tag name",
    )
    category: Mapped[TagCategory] = mapped_column(
        Enum(
            TagCategory,
            name="tagcategory",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        doc="Tag classification category",
    )
    gbif_taxon_key: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        doc="GBIF taxonomic key for species identification",
    )
    scientific_name: Mapped[str | None] = mapped_column(
        String(300),
        nullable=True,
        doc="Scientific name (for species tags)",
    )
    common_name: Mapped[str | None] = mapped_column(
        String(300),
        nullable=True,
        doc="Common name (for species tags)",
    )
    taxon_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("taxa.id", ondelete="SET NULL"),
        nullable=True,
        doc="Link to global taxon record",
    )

    # Relationships
    project: Mapped[Project] = relationship(
        "Project",
        lazy="joined",
    )
    parent: Mapped[Tag | None] = relationship(
        "Tag",
        remote_side="Tag.id",
        back_populates="children",
        lazy="joined",
    )
    children: Mapped[list[Tag]] = relationship(
        "Tag",
        back_populates="parent",
        lazy="select",
    )
    annotation_projects: Mapped[list[AnnotationProject]] = relationship(
        "AnnotationProject",
        secondary="annotation_project_tags",
        back_populates="tags",
        lazy="select",
    )
    taxon: Mapped[Taxon | None] = relationship(
        "Taxon",
        lazy="joined",
    )

    __table_args__ = (
        UniqueConstraint("project_id", "name", "category", name="uq_tag_project_name_category"),
        Index("ix_tags_project_id", "project_id"),
        Index("ix_tags_category", "category"),
        Index("ix_tags_gbif_taxon_key", "gbif_taxon_key"),
        Index("ix_tags_taxon_id", "taxon_id"),
    )

    def __repr__(self) -> str:
        return f"<Tag(id={self.id}, name={self.name}, category={self.category})>"
