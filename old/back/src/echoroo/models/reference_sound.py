"""Reference Sound model.

Reference sounds are example audio clips used to define what the ML
project is searching for. They serve as positive examples that anchor
the similarity search, helping to find similar sounds in the dataset.

Reference sounds can come from three sources:
1. Xeno-canto - External bird sound database with verified recordings
2. Custom upload - User-uploaded audio files
3. Dataset clip - Existing clips from the dataset being searched

Each reference sound is associated with a specific species tag and
can have multiple embedding vectors generated using a sliding window
approach. The embeddings are generated using the same model as the
dataset clips to ensure compatible similarity comparisons.
"""

from __future__ import annotations

import datetime
import enum
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import sqlalchemy as sa
import sqlalchemy.orm as orm
from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey

from echoroo.models.base import Base
from echoroo.models.tag import Tag

if TYPE_CHECKING:
    from echoroo.models.clip import Clip
    from echoroo.models.ml_project import MLProject
    from echoroo.models.user import User

__all__ = [
    "ReferenceSound",
    "ReferenceSoundEmbedding",
    "ReferenceSoundSource",
]


class ReferenceSoundSource(str, enum.Enum):
    """Source type for reference sounds."""

    XENO_CANTO = "xeno_canto"
    """Reference from the Xeno-canto bird sound database."""

    CUSTOM_UPLOAD = "custom_upload"
    """User-uploaded audio file."""

    DATASET_CLIP = "dataset_clip"
    """Existing clip from the dataset."""


class ReferenceSound(Base):
    """Reference Sound model.

    Represents an example audio clip used for similarity search in
    an ML project.
    """

    __tablename__ = "reference_sound"

    # Fields without defaults (required fields) - must come first
    id: orm.Mapped[int] = orm.mapped_column(primary_key=True, init=False)
    """The database id of the reference sound."""

    uuid: orm.Mapped[UUID] = orm.mapped_column(
        default_factory=uuid4,
        kw_only=True,
        unique=True,
    )
    """The UUID of the reference sound."""

    name: orm.Mapped[str] = orm.mapped_column(nullable=False)
    """A descriptive name for this reference sound."""

    ml_project_id: orm.Mapped[int] = orm.mapped_column(
        ForeignKey("ml_project.id", ondelete="CASCADE"),
        nullable=False,
    )
    """The ML project this reference sound belongs to."""

    source: orm.Mapped[ReferenceSoundSource] = orm.mapped_column(
        sa.Enum(
            ReferenceSoundSource,
            name="reference_sound_source",
            values_callable=lambda x: [e.value for e in x],
            create_type=False,
        ),
        nullable=False,
    )
    """The source type of this reference sound."""

    tag_id: orm.Mapped[int] = orm.mapped_column(
        ForeignKey("tag.id", ondelete="RESTRICT"),
        nullable=False,
    )
    """The species/sound tag this reference represents."""

    end_time: orm.Mapped[float] = orm.mapped_column(
        nullable=False,
    )
    """End time of the relevant segment in seconds."""

    created_by_id: orm.Mapped[UUID] = orm.mapped_column(
        ForeignKey("user.id"),
        nullable=False,
    )
    """The user who added this reference sound."""

    # Fields with defaults (optional fields) - must come after required fields
    description: orm.Mapped[str | None] = orm.mapped_column(
        nullable=True,
        default=None,
    )
    """Optional description providing context about this reference."""

    # Xeno-canto specific fields
    xeno_canto_id: orm.Mapped[str | None] = orm.mapped_column(
        nullable=True,
        default=None,
    )
    """The Xeno-canto recording ID (e.g., 'XC123456')."""

    xeno_canto_url: orm.Mapped[str | None] = orm.mapped_column(
        nullable=True,
        default=None,
    )
    """The URL to the Xeno-canto recording page."""

    # Custom upload specific fields
    audio_path: orm.Mapped[str | None] = orm.mapped_column(
        nullable=True,
        default=None,
    )
    """Path to the uploaded audio file (relative to storage root)."""

    # Dataset clip specific fields
    clip_id: orm.Mapped[int | None] = orm.mapped_column(
        ForeignKey("clip.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    """The clip ID if this reference is from the dataset."""

    # Time segment within the audio
    start_time: orm.Mapped[float] = orm.mapped_column(
        nullable=False,
        default=0.0,
    )
    """Start time of the relevant segment in seconds."""

    is_active: orm.Mapped[bool] = orm.mapped_column(
        nullable=False,
        default=True,
    )
    """Whether this reference sound is active in searches."""

    # Audit fields
    created_on: orm.Mapped[datetime.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
        init=False,
    )
    """Timestamp when this reference sound was created."""

    # Relationships
    ml_project: orm.Mapped["MLProject"] = orm.relationship(
        "MLProject",
        back_populates="reference_sounds",
        init=False,
        repr=False,
    )
    """The ML project this reference belongs to."""

    tag: orm.Mapped[Tag] = orm.relationship(
        "Tag",
        lazy="joined",
        init=False,
        repr=False,
    )
    """The species/sound tag for this reference."""

    clip: orm.Mapped["Clip | None"] = orm.relationship(
        "Clip",
        lazy="joined",
        init=False,
        repr=False,
    )
    """The source clip if this reference is from the dataset."""

    created_by: orm.Mapped["User"] = orm.relationship(
        "User",
        foreign_keys=[created_by_id],
        viewonly=True,
        init=False,
        repr=False,
    )
    """The user who created this reference sound."""

    embeddings: orm.Mapped[list["ReferenceSoundEmbedding"]] = orm.relationship(
        "ReferenceSoundEmbedding",
        back_populates="reference_sound",
        cascade="all, delete-orphan",
        init=False,
        repr=False,
    )
    """The embedding vectors generated using sliding windows."""


class ReferenceSoundEmbedding(Base):
    """Reference Sound Embedding model.

    Stores individual embedding vectors generated from a reference sound
    using a sliding window approach. Each reference sound can have multiple
    embeddings, allowing for better matching against the selected audio segment.
    """

    __tablename__ = "reference_sound_embeddings"

    id: orm.Mapped[int] = orm.mapped_column(primary_key=True, init=False)
    """The database id of the embedding."""

    reference_sound_id: orm.Mapped[int] = orm.mapped_column(
        ForeignKey("reference_sound.id", ondelete="CASCADE"),
        nullable=False,
    )
    """The reference sound this embedding belongs to."""

    embedding: orm.Mapped[list[float]] = orm.mapped_column(
        Vector(),
        nullable=False,
    )
    """The embedding vector (1024-dim for BirdNET, 1536-dim for Perch)."""

    window_start_time: orm.Mapped[float] = orm.mapped_column(
        nullable=False,
    )
    """Start time of the window used to generate this embedding (relative to original audio)."""

    window_end_time: orm.Mapped[float] = orm.mapped_column(
        nullable=False,
    )
    """End time of the window used to generate this embedding (relative to original audio)."""

    created_on: orm.Mapped[datetime.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
        init=False,
    )
    """Timestamp when this embedding was created."""

    # Relationships
    reference_sound: orm.Mapped["ReferenceSound"] = orm.relationship(
        "ReferenceSound",
        back_populates="embeddings",
        init=False,
        repr=False,
    )
    """The reference sound this embedding belongs to."""
