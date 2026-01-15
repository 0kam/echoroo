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
from sqlalchemy import ForeignKey, UniqueConstraint, func, inspect, select

from echoroo.models.base import Base
from echoroo.models.recording import Recording

if TYPE_CHECKING:
    from echoroo.models.annotation_project import AnnotationProject
    from echoroo.models.license import License
    from echoroo.models.project import Project
    from echoroo.models.recorder import Recorder
    from echoroo.models.site import Site
    from echoroo.models.user import User
    from echoroo.models.datetime_pattern import DatasetDatetimePattern

__all__ = [
    "VisibilityLevel",
    "DatasetStatus",
    "Dataset",
    "DatasetRecording",
]


class VisibilityLevel(str, Enum):
    """Visibility level for datasets and annotation projects."""

    RESTRICTED = "restricted"
    PUBLIC = "public"


class DatasetStatus(str, Enum):
    """Processing status for dataset creation."""

    PENDING = "pending"
    SCANNING = "scanning"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


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
    id: orm.Mapped[int] = orm.mapped_column(primary_key=True, init=False)
    """The database id of the dataset."""

    name: orm.Mapped[str] = orm.mapped_column(unique=True)
    """The name of the dataset."""

    audio_dir: orm.Mapped[Path] = orm.mapped_column()
    """The path to the audio directory of the dataset."""

    created_by_id: orm.Mapped[UUID] = orm.mapped_column(
        sa.ForeignKey("user.id"),
        nullable=False,
    )
    """The user who created the dataset."""

    project_id: orm.Mapped[str] = orm.mapped_column(
        sa.ForeignKey("project.project_id", ondelete="RESTRICT"),
        nullable=False,
    )
    """The project that owns the dataset."""

    uuid: orm.Mapped[UUID] = orm.mapped_column(
        default_factory=uuid4,
        unique=True,
        kw_only=True,
    )
    """The UUID of the dataset."""

    description: orm.Mapped[str | None] = orm.mapped_column(
        nullable=True,
        default=None,
    )
    """A textual description of the dataset."""

    primary_site_id: orm.Mapped[str | None] = orm.mapped_column(
        sa.ForeignKey("site.site_id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    """Primary site for the dataset."""

    primary_recorder_id: orm.Mapped[str | None] = orm.mapped_column(
        sa.ForeignKey("recorder.recorder_id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    """Primary recorder associated with the dataset."""

    license_id: orm.Mapped[str | None] = orm.mapped_column(
        sa.ForeignKey("license.license_id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    """License applied to the dataset."""

    doi: orm.Mapped[str | None] = orm.mapped_column(
        sa.String(length=255),
        nullable=True,
        default=None,
    )
    """Optional DOI reference."""

    note: orm.Mapped[str | None] = orm.mapped_column(
        sa.Text(),
        nullable=True,
        default=None,
    )
    """Optional notes for internal use."""

    gain: orm.Mapped[float | None] = orm.mapped_column(
        nullable=True,
        default=None,
    )
    """Recorder gain in dB."""

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
    """Visibility level of the dataset."""

    status: orm.Mapped[DatasetStatus] = orm.mapped_column(
        sa.Enum(
            DatasetStatus,
            name="dataset_status",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=DatasetStatus.COMPLETED,
        server_default=DatasetStatus.COMPLETED.value,
    )
    """Processing status of the dataset."""

    processing_progress: orm.Mapped[int] = orm.mapped_column(
        nullable=False,
        default=100,
        server_default="100",
    )
    """Processing progress (0-100)."""

    processing_error: orm.Mapped[str | None] = orm.mapped_column(
        sa.Text(),
        nullable=True,
        default=None,
    )
    """Error message if processing failed."""

    total_files: orm.Mapped[int] = orm.mapped_column(
        nullable=False,
        default=0,
        server_default="0",
    )
    """Total number of audio files discovered."""

    processed_files: orm.Mapped[int] = orm.mapped_column(
        nullable=False,
        default=0,
        server_default="0",
    )
    """Number of files successfully processed."""

    created_by: orm.Mapped["User"] = orm.relationship(
        "User",
        foreign_keys=[created_by_id],
        viewonly=True,
        repr=False,
        init=False,
    )
    """Relationship to the creating user."""

    project: orm.Mapped["Project | None"] = orm.relationship(
        "Project",
        foreign_keys="[Dataset.project_id]",
        back_populates="datasets",
        lazy="joined",
        repr=False,
        init=False,
    )
    """Project metadata for this dataset."""

    primary_site: orm.Mapped["Site | None"] = orm.relationship(
        "Site",
        back_populates="datasets",
        lazy="joined",
        repr=False,
        init=False,
    )
    """Primary site metadata."""

    primary_recorder: orm.Mapped["Recorder | None"] = orm.relationship(
        "Recorder",
        back_populates="datasets",
        lazy="joined",
        repr=False,
        init=False,
    )
    """Primary recorder metadata."""

    license: orm.Mapped["License | None"] = orm.relationship(
        "License",
        back_populates="datasets",
        lazy="joined",
        repr=False,
        init=False,
    )
    """License metadata."""

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

    datetime_pattern: orm.Mapped["DatasetDatetimePattern | None"] = (
        orm.relationship(
            "DatasetDatetimePattern",
            back_populates="dataset",
            cascade="all, delete-orphan",
            uselist=False,
            init=False,
        )
    )

    annotation_projects: orm.Mapped[list["AnnotationProject"]] = (
        orm.relationship(
            "AnnotationProject",
            back_populates="dataset",
            default_factory=list,
            init=False,
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


# Add a property that returns the earliest recording datetime
inspect(Dataset).add_property(
    "recording_start_date",
    orm.column_property(
        select(func.min(Recording.datetime))
        .select_from(DatasetRecording)
        .join(Recording, DatasetRecording.recording_id == Recording.id)
        .where(DatasetRecording.dataset_id == Dataset.id)
        .where(Recording.datetime.isnot(None))
        .correlate_except(DatasetRecording, Recording)
        .scalar_subquery(),
        deferred=False,
    ),
)


# Add a property that returns the latest recording datetime
inspect(Dataset).add_property(
    "recording_end_date",
    orm.column_property(
        select(func.max(Recording.datetime))
        .select_from(DatasetRecording)
        .join(Recording, DatasetRecording.recording_id == Recording.id)
        .where(DatasetRecording.dataset_id == Dataset.id)
        .where(Recording.datetime.isnot(None))
        .correlate_except(DatasetRecording, Recording)
        .scalar_subquery(),
        deferred=False,
    ),
)
