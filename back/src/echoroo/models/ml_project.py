"""ML Project model.

An ML Project is a machine learning workflow that enables users to find
and classify specific sounds in their audio datasets. The workflow
follows a structured pipeline:

1. Setup - Define target species/sounds and select reference audio
2. Searching - Use embeddings to find similar sounds in the dataset
3. Labeling - Review and label search results as positive/negative examples
4. Training - Train a custom classifier on the labeled data
5. Inference - Run the trained model on new/unlabeled audio
6. Review - Verify model predictions and refine the training set
7. Completed - Export annotations and trained model

Each ML Project is associated with a dataset and a parent project,
inheriting access control from the parent project. The project tracks
the embedding model used for similarity search and maintains
relationships to target species tags.

ML Projects support multiple datasets through MLProjectDatasetScope,
allowing similarity searches and inference across different datasets
with their respective foundation model runs.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import sqlalchemy as sa
import sqlalchemy.orm as orm
from sqlalchemy import ForeignKey, Index, UniqueConstraint

from echoroo.models.base import Base
from echoroo.models.tag import Tag

if TYPE_CHECKING:
    from echoroo.models.custom_model import CustomModel
    from echoroo.models.dataset import Dataset
    from echoroo.models.foundation_model import FoundationModel, FoundationModelRun
    from echoroo.models.inference_batch import InferenceBatch
    from echoroo.models.model_run import ModelRun
    from echoroo.models.project import Project
    from echoroo.models.reference_sound import ReferenceSound
    from echoroo.models.search_session import SearchSession
    from echoroo.models.user import User

__all__ = [
    "MLProject",
    "MLProjectDatasetScope",
    "MLProjectStatus",
    "MLProjectTag",
]


class MLProjectStatus(str, enum.Enum):
    """Status of the ML Project workflow."""

    SETUP = "setup"
    """Initial setup phase - defining targets and references."""

    SEARCHING = "searching"
    """Similarity search in progress."""

    LABELING = "labeling"
    """Reviewing and labeling search results."""

    TRAINING = "training"
    """Training a custom classifier."""

    INFERENCE = "inference"
    """Running inference on unlabeled data."""

    REVIEW = "review"
    """Reviewing model predictions."""

    COMPLETED = "completed"
    """Workflow completed, ready for export."""

    ARCHIVED = "archived"
    """Project archived and no longer active."""


class MLProject(Base):
    """ML Project model.

    An ML Project represents a complete machine learning workflow for
    finding and classifying specific sounds in audio datasets.
    """

    __tablename__ = "ml_project"

    # Fields without defaults (required fields) - must come first
    id: orm.Mapped[int] = orm.mapped_column(primary_key=True, init=False)
    """The database id of the ML project."""

    uuid: orm.Mapped[UUID] = orm.mapped_column(
        default_factory=uuid4,
        kw_only=True,
        unique=True,
    )
    """The UUID of the ML project."""

    name: orm.Mapped[str] = orm.mapped_column(nullable=False)
    """The name of the ML project."""

    project_id: orm.Mapped[str] = orm.mapped_column(
        ForeignKey("project.project_id", ondelete="RESTRICT"),
        nullable=False,
    )
    """The owning project identifier for access control."""

    created_by_id: orm.Mapped[UUID] = orm.mapped_column(
        ForeignKey("user.id"),
        nullable=False,
    )
    """The user who created this ML project."""

    # Fields with defaults (optional fields) - must come after required fields
    description: orm.Mapped[str | None] = orm.mapped_column(
        nullable=True,
        default=None,
    )
    """A textual description of the ML project."""

    foundation_model_id: orm.Mapped[int | None] = orm.mapped_column(
        ForeignKey("foundation_model.id", ondelete="RESTRICT"),
        nullable=True,
        default=None,
    )
    """The foundation model used for embeddings across all datasets.

    This defines which model (e.g., BirdNET, Perch) is used for
    generating embeddings for similarity search and classification.
    """

    status: orm.Mapped[MLProjectStatus] = orm.mapped_column(
        sa.Enum(
            MLProjectStatus,
            name="ml_project_status",
            values_callable=lambda x: [e.value for e in x],
            create_type=False,
        ),
        nullable=False,
        default=MLProjectStatus.SETUP,
        server_default=MLProjectStatus.SETUP.value,
    )
    """Current status of the ML project workflow."""

    default_similarity_threshold: orm.Mapped[float] = orm.mapped_column(
        nullable=False,
        default=0.7,
    )
    """Default similarity threshold for search sessions (0.0 to 1.0)."""

    updated_on: orm.Mapped[sa.DateTime | None] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        default=None,
        onupdate=sa.func.now(),
    )
    """Timestamp of the last update to this ML project."""

    # Relationships
    created_by: orm.Mapped["User"] = orm.relationship(
        "User",
        foreign_keys=[created_by_id],
        viewonly=True,
        repr=False,
        init=False,
    )
    """Relationship to the creator."""

    project: orm.Mapped["Project"] = orm.relationship(
        "Project",
        foreign_keys=[project_id],
        viewonly=True,
        repr=False,
        init=False,
    )
    """Owning project relationship."""

    foundation_model: orm.Mapped["FoundationModel | None"] = orm.relationship(
        "FoundationModel",
        foreign_keys=[foundation_model_id],
        viewonly=True,
        repr=False,
        init=False,
    )
    """The foundation model used for embeddings."""

    # Dataset scopes for multi-dataset support
    dataset_scopes: orm.Mapped[list["MLProjectDatasetScope"]] = orm.relationship(
        "MLProjectDatasetScope",
        back_populates="ml_project",
        default_factory=list,
        cascade="all, delete-orphan",
        repr=False,
        init=False,
    )
    """Dataset scopes for this ML project, linking datasets with their embeddings."""

    # Tag relationships via junction table
    tags: orm.Mapped[list[Tag]] = orm.relationship(
        "Tag",
        secondary="ml_project_tag",
        lazy="joined",
        viewonly=True,
        default_factory=list,
        repr=False,
    )
    """The target tags (species) associated with this ML project."""

    ml_project_tags: orm.Mapped[list["MLProjectTag"]] = orm.relationship(
        "MLProjectTag",
        back_populates="ml_project",
        default_factory=list,
        cascade="all, delete-orphan",
        repr=False,
        init=False,
    )
    """Secondary relationship to ML project tags."""

    # Child relationships
    reference_sounds: orm.Mapped[list["ReferenceSound"]] = orm.relationship(
        "ReferenceSound",
        back_populates="ml_project",
        default_factory=list,
        cascade="all, delete-orphan",
        repr=False,
        init=False,
    )
    """Reference sounds for similarity search."""

    search_sessions: orm.Mapped[list["SearchSession"]] = orm.relationship(
        "SearchSession",
        back_populates="ml_project",
        default_factory=list,
        cascade="all, delete-orphan",
        repr=False,
        init=False,
    )
    """Search sessions for this ML project."""

    custom_models: orm.Mapped[list["CustomModel"]] = orm.relationship(
        "CustomModel",
        back_populates="ml_project",
        default_factory=list,
        cascade="all, delete-orphan",
        repr=False,
        init=False,
    )
    """Custom models trained for this ML project."""

    inference_batches: orm.Mapped[list["InferenceBatch"]] = orm.relationship(
        "InferenceBatch",
        back_populates="ml_project",
        default_factory=list,
        cascade="all, delete-orphan",
        repr=False,
        init=False,
    )
    """Inference batches run for this ML project."""


class MLProjectTag(Base):
    """ML Project Tag junction model.

    Associates target species/sound tags with an ML project.
    """

    __tablename__ = "ml_project_tag"
    __table_args__ = (
        UniqueConstraint(
            "ml_project_id",
            "tag_id",
        ),
    )

    ml_project_id: orm.Mapped[int] = orm.mapped_column(
        ForeignKey("ml_project.id", ondelete="CASCADE"),
        nullable=False,
        primary_key=True,
    )
    """The database id of the ML project associated with the tag."""

    tag_id: orm.Mapped[int] = orm.mapped_column(
        ForeignKey("tag.id", ondelete="CASCADE"),
        nullable=False,
        primary_key=True,
    )
    """The database id of the tag."""

    # Relationships
    ml_project: orm.Mapped[MLProject] = orm.relationship(
        "MLProject",
        back_populates="ml_project_tags",
        init=False,
        repr=False,
    )
    """The ML project associated with the tag."""

    tag: orm.Mapped[Tag] = orm.relationship(
        "Tag",
        lazy="joined",
        init=False,
        repr=False,
    )
    """The tag associated with the ML project."""


class MLProjectDatasetScope(Base):
    """ML Project Dataset Scope model.

    Defines which datasets are included in an ML project and which
    foundation model run provides the embeddings for similarity search.
    This enables multi-dataset support where a single ML project can
    work across multiple datasets, each with its own embedding run.
    """

    __tablename__ = "ml_project_dataset_scope"
    __table_args__ = (
        UniqueConstraint(
            "ml_project_id",
            "dataset_id",
            name="uq_ml_project_dataset_scope_project_dataset",
        ),
        Index(
            "ix_ml_project_dataset_scope_ml_project_id",
            "ml_project_id",
        ),
    )

    # Primary key
    id: orm.Mapped[int] = orm.mapped_column(primary_key=True, init=False)
    """The database id of the dataset scope."""

    uuid: orm.Mapped[UUID] = orm.mapped_column(
        default_factory=uuid4,
        kw_only=True,
        unique=True,
    )
    """The UUID of the dataset scope."""

    # Required fields
    ml_project_id: orm.Mapped[int] = orm.mapped_column(
        ForeignKey("ml_project.id", ondelete="CASCADE"),
        nullable=False,
    )
    """The ML project this scope belongs to."""

    dataset_id: orm.Mapped[int] = orm.mapped_column(
        ForeignKey("dataset.id", ondelete="CASCADE"),
        nullable=False,
    )
    """The dataset included in this scope."""

    foundation_model_run_id: orm.Mapped[int] = orm.mapped_column(
        ForeignKey("foundation_model_run.id", ondelete="CASCADE"),
        nullable=False,
    )
    """The foundation model run that provides embeddings for this dataset."""

    # Relationships
    ml_project: orm.Mapped["MLProject"] = orm.relationship(
        "MLProject",
        back_populates="dataset_scopes",
        init=False,
        repr=False,
    )
    """The ML project this scope belongs to."""

    dataset: orm.Mapped["Dataset"] = orm.relationship(
        "Dataset",
        foreign_keys=[dataset_id],
        viewonly=True,
        init=False,
        repr=False,
        lazy="joined",
    )
    """The dataset included in this scope."""

    foundation_model_run: orm.Mapped["FoundationModelRun"] = orm.relationship(
        "FoundationModelRun",
        foreign_keys=[foundation_model_run_id],
        viewonly=True,
        init=False,
        repr=False,
        lazy="joined",
    )
    """The foundation model run providing embeddings."""
