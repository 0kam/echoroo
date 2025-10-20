"""Dataset model.

A dataset is a collection of audio recordings that are grouped together
within a single directory. The purpose of a dataset is to organize and
group recordings that belong together, such as all recordings from a
single deployment or field study. Usually, recordings within a dataset
are made by the same group of people, using similar equipment, and
following a predefined protocol. However, this is not a strict
requirement.

Each dataset can be named and described, making it easier to identify
and manage multiple datasets within the app. Users can add new datasets
to the app and import recordings into them, or remove datasets and their
associated recordings from the app.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import sqlalchemy as sa
import sqlalchemy.orm as orm
from sqlalchemy import CheckConstraint, ForeignKey, UniqueConstraint, func, inspect, select

from whombat.models.base import Base
from whombat.models.recording import Recording

if TYPE_CHECKING:
    from whombat.models.group import Group
    from whombat.models.user import User

__all__ = [
    "VisibilityLevel",
    "Dataset",
    "DatasetRecording",
]


class VisibilityLevel(str, Enum):
    """Visibility level for datasets and annotation projects."""

    PRIVATE = "private"
    RESTRICTED = "restricted"
    PUBLIC = "public"


class Dataset(Base):
    """Dataset model for dataset table.

    Notes
    -----
    The `audio_dir` attribute is the path to the audio directory of the dataset.
    This is the directory that contains all the recordings of the dataset. Only
    the relative path to the base audio directory is stored in the database.
    Note that we should NEVER store absolute paths in the database.
    """

    __tablename__ = "dataset"
    __table_args__ = (
        CheckConstraint(
            "visibility != 'restricted' OR owner_group_id IS NOT NULL",
            name="chk_dataset_restricted_has_group",
        ),
    )

    id: orm.Mapped[int] = orm.mapped_column(primary_key=True, init=False)
    """The database id of the dataset."""

    uuid: orm.Mapped[UUID] = orm.mapped_column(
        default_factory=uuid4,
        unique=True,
        kw_only=True,
    )
    """The UUID of the dataset."""

    name: orm.Mapped[str] = orm.mapped_column(unique=True)
    """The name of the dataset."""

    audio_dir: orm.Mapped[Path] = orm.mapped_column()
    """The path to the audio directory of the dataset."""

    created_by_id: orm.Mapped[UUID] = orm.mapped_column(
        sa.ForeignKey("user.id"),
        nullable=False,
    )
    """The user who created the dataset."""

    description: orm.Mapped[str] = orm.mapped_column(nullable=True, default=None)
    """A textual description of the dataset."""

    visibility: orm.Mapped[VisibilityLevel] = orm.mapped_column(
        sa.Enum(VisibilityLevel, name="visibility_level"),
        nullable=False,
        default=VisibilityLevel.PRIVATE,
        server_default=VisibilityLevel.PRIVATE.value,
    )
    """Visibility level of the dataset."""

    owner_group_id: orm.Mapped[int | None] = orm.mapped_column(
        sa.ForeignKey("group.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    """The group that owns the dataset when visibility is restricted."""

    created_by: orm.Mapped["User"] = orm.relationship(
        "User",
        foreign_keys=[created_by_id],
        viewonly=True,
        repr=False,
        init=False,
    )
    """Relationship to the creating user."""

    owner_group: orm.Mapped["Group | None"] = orm.relationship(
        "Group",
        foreign_keys=[owner_group_id],
        viewonly=True,
        repr=False,
        init=False,
    )
    """Relationship to the owning group."""

    # Relations
    recordings: orm.Mapped[list[Recording]] = orm.relationship(
        "Recording",
        secondary="dataset_recording",
        viewonly=True,
        default_factory=list,
        repr=False,
        init=False,
    )

    # Secondary relations
    dataset_recordings: orm.Mapped[list["DatasetRecording"]] = (
        orm.relationship(
            "DatasetRecording",
            init=False,
            repr=False,
            back_populates="dataset",
            cascade="all, delete-orphan",
            default_factory=list,
        )
    )


class DatasetRecording(Base):
    """Dataset Recording Model.

    A dataset recording is a link between a dataset and a recording. It
    contains the path to the recording within the dataset.

    Notes
    -----
    The dataset recording model is a many-to-many relationship between the
    dataset and recording models. This means that a recording can be part of
    multiple datasets. This is useful when a recording is used in multiple
    studies or deployments. However, as we do not want to duplicate recordings
    in the database, we use a many-to-many relationship to link recordings to
    datasets.
    """

    __tablename__ = "dataset_recording"
    __table_args__ = (UniqueConstraint("dataset_id", "recording_id", "path"),)

    dataset_id: orm.Mapped[int] = orm.mapped_column(
        ForeignKey("dataset.id"),
        nullable=False,
        primary_key=True,
    )
    """The id of the dataset."""

    recording_id: orm.Mapped[int] = orm.mapped_column(
        ForeignKey("recording.id"),
        nullable=False,
        primary_key=True,
    )
    """The id of the recording."""

    path: orm.Mapped[Path]
    """The path to the recording within the dataset."""

    # Relations
    dataset: orm.Mapped[Dataset] = orm.relationship(
        init=False,
        repr=False,
        back_populates="dataset_recordings",
    )

    recording: orm.Mapped[Recording] = orm.relationship(
        Recording,
        init=False,
        repr=False,
        lazy="joined",
        back_populates="recording_datasets",
        cascade="all",
    )


# Add a property to the Dataset model that returns the number of recordings
# associated with the dataset.
inspect(Dataset).add_property(
    "recording_count",
    orm.column_property(
        select(func.count(DatasetRecording.recording_id))
        .where(DatasetRecording.dataset_id == Dataset.id)
        .correlate_except(DatasetRecording)
        .scalar_subquery(),
        deferred=False,
    ),
)
