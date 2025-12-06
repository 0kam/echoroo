"""Annotation Project model.

An annotation project is a focused effort to label specific sound events
or audio features in a set of recordings. These projects have clear
goals, such as identifying all sound events of a certain species or
tagging all 3-second audio clips with the correct labels. Each project
has a unique name and includes detailed instructions on how to perform
the annotations. The project is divided into individual tasks, each
consisting of a single clip from the registered recordings. Annotators
are assigned to each task to complete the annotations according to the
project criteria, ensuring that all relevant sound events or audio
features are accurately identified and labeled.

When building an annotation project, users can specify the set of tags
they wish to use within the project, and add any number of clips from
the registered recordings. The annotation process then proceeds by
distributing tasks to annotators. Once the user is satisfied that the
annotation criteria have been met, they should indicate that the task
has been completed. Other users can review the completed tasks and add
notes or raise issues with the existing annotations.

It's worth noting that some annotation projects are created with the
purpose of automatically generating machine learning models from the
annotations. Therefore, maintaining a high level of quality control is
essential, including outlier detection.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import sqlalchemy as sa
import sqlalchemy.orm as orm
from sqlalchemy import ForeignKey, UniqueConstraint

from echoroo.models.annotation_task import AnnotationTask
from echoroo.models.base import Base
from echoroo.models.dataset import VisibilityLevel
from echoroo.models.tag import Tag

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from echoroo.models.dataset import Dataset
    from echoroo.models.project import Project
    from echoroo.models.user import User

__all__ = [
    "AnnotationProject",
    "AnnotationProjectTag",
]


class AnnotationProject(Base):
    """Annotation Project model."""

    __tablename__ = "annotation_project"
    id: orm.Mapped[int] = orm.mapped_column(primary_key=True, init=False)
    """The database id of the annotation project."""

    uuid: orm.Mapped[UUID] = orm.mapped_column(
        default_factory=uuid4,
        kw_only=True,
        unique=True,
    )
    """The UUID of the annotation project."""

    name: orm.Mapped[str] = orm.mapped_column(unique=True)
    """The name of the annotation project."""

    description: orm.Mapped[str]
    """The description of the annotation project."""

    created_by_id: orm.Mapped[UUID] = orm.mapped_column(
        sa.ForeignKey("user.id"),
        nullable=False,
    )
    """The user who created the project."""

    dataset_id: orm.Mapped[int] = orm.mapped_column(
        sa.ForeignKey("dataset.id", ondelete="RESTRICT"),
        nullable=False,
    )
    """Dataset from which this annotation project derives recordings."""

    project_id: orm.Mapped[str] = orm.mapped_column(
        sa.ForeignKey("project.project_id", ondelete="RESTRICT"),
        nullable=False,
    )
    """Owning project identifier."""

    annotation_instructions: orm.Mapped[str | None] = orm.mapped_column(
        default=None
    )
    """The instructions for annotators."""

    visibility: orm.Mapped[VisibilityLevel] = orm.mapped_column(
        sa.Enum(
            VisibilityLevel,
            name="visibility_level",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=VisibilityLevel.RESTRICTED,
        server_default=VisibilityLevel.RESTRICTED.value,
    )
    """Visibility level for the project."""

    created_by: orm.Mapped["User"] = orm.relationship(
        "User",
        foreign_keys=[created_by_id],
        viewonly=True,
        repr=False,
        init=False,
    )
    """Relationship to the creator."""

    dataset: orm.Mapped["Dataset"] = orm.relationship(
        "Dataset",
        back_populates="annotation_projects",
        repr=False,
        init=False,
    )
    """Parent dataset relationship."""

    project: orm.Mapped["Project"] = orm.relationship(
        "Project",
        back_populates="annotation_projects",
        repr=False,
        init=False,
    )
    """Owning project relationship."""

    # Relationships
    tags: orm.Mapped[list[Tag]] = orm.relationship(
        "Tag",
        secondary="annotation_project_tag",
        lazy="joined",
        viewonly=True,
        default_factory=list,
        repr=False,
    )
    """The tags associated with the annotation project."""

    annotation_tasks: orm.Mapped[list["AnnotationTask"]] = orm.relationship(
        back_populates="annotation_project",
        default_factory=list,
        cascade="all, delete-orphan",
    )

    # Secondary relationships
    annotation_project_tags: orm.Mapped[list["AnnotationProjectTag"]] = (
        orm.relationship(
            "AnnotationProjectTag",
            default_factory=list,
            cascade="all, delete-orphan",
        )
    )


class AnnotationProjectTag(Base):
    """Annotation Project Tag model."""

    __tablename__ = "annotation_project_tag"
    __table_args__ = (
        UniqueConstraint(
            "annotation_project_id",
            "tag_id",
        ),
    )

    annotation_project_id: orm.Mapped[int] = orm.mapped_column(
        ForeignKey("annotation_project.id"),
        nullable=False,
        primary_key=True,
    )
    """The database id of the annotation project associated with the tag."""

    tag_id: orm.Mapped[int] = orm.mapped_column(
        ForeignKey("tag.id"),
        nullable=False,
        primary_key=True,
    )
    """The database id of the tag."""

    # Relationships
    annotation_project: orm.Mapped[AnnotationProject] = orm.relationship(
        "AnnotationProject",
        back_populates="annotation_project_tags",
        init=False,
        repr=False,
    )
    """The annotation project associated with the tag."""

    tag: orm.Mapped[Tag] = orm.relationship(
        "Tag",
        back_populates="annotation_project_tags",
        lazy="joined",
        init=False,
        repr=False,
    )
    """The tag associated with the annotation project."""
