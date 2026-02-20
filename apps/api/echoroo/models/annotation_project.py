"""AnnotationProject model for managing annotation workflows."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Column, Enum, ForeignKey, Index, String, Table, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from echoroo.models.base import Base, TimestampMixin, UUIDMixin
from echoroo.models.enums import AnnotationProjectVisibility

if TYPE_CHECKING:
    from echoroo.models.annotation_task import AnnotationTask
    from echoroo.models.dataset import Dataset
    from echoroo.models.project import Project
    from echoroo.models.tag import Tag
    from echoroo.models.user import User


# Association table for annotation projects and datasets (many-to-many)
annotation_project_datasets = Table(
    "annotation_project_datasets",
    Base.metadata,
    Column(
        "annotation_project_id",
        PG_UUID(as_uuid=True),
        ForeignKey("annotation_projects.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "dataset_id",
        PG_UUID(as_uuid=True),
        ForeignKey("datasets.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)

# Association table for annotation projects and tags (many-to-many)
annotation_project_tags = Table(
    "annotation_project_tags",
    Base.metadata,
    Column(
        "annotation_project_id",
        PG_UUID(as_uuid=True),
        ForeignKey("annotation_projects.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "tag_id",
        PG_UUID(as_uuid=True),
        ForeignKey("tags.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class AnnotationProject(UUIDMixin, TimestampMixin, Base):
    """Annotation project organizing tasks for labeling audio clips.

    Attributes:
        id: Unique identifier (UUID)
        project_id: Foreign key to parent project
        created_by_id: Foreign key to user who created this annotation project
        name: Annotation project name (max 200 chars)
        description: Optional description
        instructions: Optional annotator instructions
        visibility: Project visibility (private/public)
    """

    __tablename__ = "annotation_projects"

    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        doc="Parent project ID",
    )
    created_by_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        doc="User who created this annotation project",
    )
    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        doc="Annotation project name",
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Annotation project description",
    )
    instructions: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Instructions for annotators",
    )
    visibility: Mapped[AnnotationProjectVisibility] = mapped_column(
        Enum(
            AnnotationProjectVisibility,
            name="annotationprojectvisibility",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        default=AnnotationProjectVisibility.PRIVATE,
        nullable=False,
        doc="Annotation project visibility level",
    )

    # Relationships
    project: Mapped[Project] = relationship(
        "Project",
        lazy="joined",
    )
    created_by: Mapped[User] = relationship(
        "User",
        lazy="joined",
    )
    datasets: Mapped[list[Dataset]] = relationship(
        "Dataset",
        secondary=annotation_project_datasets,
        back_populates="annotation_projects",
        lazy="select",
    )
    tags: Mapped[list[Tag]] = relationship(
        "Tag",
        secondary=annotation_project_tags,
        back_populates="annotation_projects",
        lazy="select",
    )
    tasks: Mapped[list[AnnotationTask]] = relationship(
        "AnnotationTask",
        back_populates="annotation_project",
        cascade="all, delete-orphan",
        lazy="select",
    )

    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_annotation_project_project_name"),
        Index("ix_annotation_projects_project_id", "project_id"),
        Index("ix_annotation_projects_created_by_id", "created_by_id"),
    )

    def __repr__(self) -> str:
        return f"<AnnotationProject(id={self.id}, name={self.name})>"
