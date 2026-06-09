"""Note model for comments on annotations."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from echoroo.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from echoroo.models.user import User


class Note(UUIDMixin, TimestampMixin, Base):
    """Comment or review note attached to an annotation-set object.

    Attributes:
        id: Unique identifier (UUID)
        created_by_id: Foreign key to user who wrote this note
        content: Note text content
        is_review: Whether this note is a formal review comment
    """

    __tablename__ = "notes"

    created_by_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        doc="User who wrote this note",
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Note text content",
    )
    is_review: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        doc="Whether this note is a formal review comment",
    )
    is_issue: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
        doc=(
            "Quality-concern flag for ground-truth annotation notes (see "
            "spec 003-annotation). Surfaced as an issue badge in the UI."
        ),
    )

    # Relationships
    created_by: Mapped[User] = relationship(
        "User",
        lazy="joined",
    )

    def __repr__(self) -> str:
        return f"<Note(id={self.id}, is_review={self.is_review})>"
