"""Database model for cached ML models."""

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey, Integer, LargeBinary, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from echoroo.models.base import Base

if TYPE_CHECKING:
    from echoroo.models.search_session import SearchSession

__all__ = ["CachedModel"]


class CachedModel(Base):
    """Model for caching trained ML models during active learning.

    This table stores serialized machine learning models in PostgreSQL,
    replacing the previous Redis-based caching mechanism.

    Attributes
    ----------
    id
        Primary key UUID.
    session_uuid
        UUID of the associated search session.
    iteration
        Active learning iteration number.
    model_data
        Serialized model binary data (joblib-encoded).
    created_on
        Timestamp when the model was cached (inherited from Base).
    search_session
        Relationship to the SearchSession.
    """

    __tablename__ = "cached_model"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default="gen_random_uuid()",
        init=False,
        default=None,
    )

    session_uuid: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("search_session.uuid", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    iteration: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    model_data: Mapped[bytes] = mapped_column(
        LargeBinary,
        nullable=False,
    )

    # Relationships
    search_session: Mapped["SearchSession"] = relationship(
        "SearchSession",
        back_populates="cached_models",
        init=False,
        repr=False,
    )

    # Constraints
    __table_args__ = (
        UniqueConstraint(
            "session_uuid",
            "iteration",
            name="uq_cached_model_session_iteration",
        ),
    )

    def __repr__(self) -> str:
        """Return string representation of cached model."""
        return (
            f"<CachedModel(id={self.id}, session_uuid={self.session_uuid}, "
            f"iteration={self.iteration})>"
        )
