"""AnnotationComment model for detection review discussion."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Enum, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from echoroo.models.base import Base, TimestampMixin, UUIDMixin
from echoroo.models.enums import AnnotationVoteSource

if TYPE_CHECKING:
    from echoroo.models.annotation import Annotation
    from echoroo.models.project import Project
    from echoroo.models.user import User


class AnnotationComment(UUIDMixin, TimestampMixin, Base):
    """Comment posted by a user on a detection annotation."""

    __tablename__ = "annotation_comments"

    annotation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("annotations.id", ondelete="CASCADE"),
        nullable=False,
    )
    commenter_user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[AnnotationVoteSource] = mapped_column(
        Enum(
            AnnotationVoteSource,
            name="annotationvotesource",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
    )

    annotation: Mapped[Annotation] = relationship("Annotation", lazy="raise")
    commenter: Mapped[User] = relationship(
        "User",
        foreign_keys=[commenter_user_id],
        lazy="raise",
    )
    project: Mapped[Project] = relationship("Project", lazy="raise")

    __table_args__ = (
        Index("ix_annotation_comments_annotation", "annotation_id"),
    )
