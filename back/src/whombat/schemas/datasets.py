"""Schemas for handling Datasets."""

from enum import Enum
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, DirectoryPath, Field, model_validator

from whombat.schemas.base import BaseSchema
from whombat.schemas.recordings import Recording
from whombat.models.dataset import VisibilityLevel

__all__ = [
    "VisibilityLevel",
    "Dataset",
    "DatasetRecording",
    "DatasetCreate",
    "DatasetUpdate",
    "DatasetRecordingCreate",
    "FileState",
    "DatasetCandidate",
    "DatasetCandidateInfo",
]


class DatasetCreate(BaseModel):
    """Schema for Dataset objects created by the user."""

    audio_dir: DirectoryPath
    """The path to the directory containing the audio files."""

    name: str = Field(..., min_length=1)
    """The name of the dataset."""

    description: str | None = Field(None)
    """The description of the dataset."""

    visibility: VisibilityLevel = VisibilityLevel.PRIVATE
    """Visibility level for the dataset."""

    owner_group_id: int | None = Field(default=None)
    """Owning group when visibility is restricted."""

    @model_validator(mode="after")
    def _validate_visibility(self):
        if (
            self.visibility == VisibilityLevel.RESTRICTED
            and self.owner_group_id is None
        ):
            raise ValueError(
                "Restricted visibility requires owner_group_id to be set."
            )
        if (
            self.visibility != VisibilityLevel.RESTRICTED
            and self.owner_group_id is not None
        ):
            raise ValueError(
                "owner_group_id can only be set when visibility is 'restricted'."
            )
        return self


class Dataset(BaseSchema):
    """Schema for Dataset objects returned to the user."""

    uuid: UUID
    """The uuid of the dataset."""

    id: int = Field(..., exclude=True)
    """The database id of the dataset."""

    audio_dir: Path
    """The path to the directory containing the audio files."""

    name: str
    """The name of the dataset."""

    description: str | None
    """The description of the dataset."""

    recording_count: int = 0
    """The number of recordings in the dataset."""

    visibility: VisibilityLevel
    """Visibility level for the dataset."""

    created_by_id: UUID
    """User who created the dataset."""

    owner_group_id: int | None = Field(default=None)
    """Owning group when visibility is restricted."""


class DatasetUpdate(BaseModel):
    """Schema for Dataset objects updated by the user."""

    audio_dir: DirectoryPath | None = None
    """The path to the directory containing the audio files."""

    name: str | None = Field(default=None, min_length=1)
    """The name of the dataset."""

    description: str | None = None
    """The description of the dataset."""

    visibility: VisibilityLevel | None = None
    """Updated visibility level."""

    owner_group_id: int | None = None
    """Target owner group."""

    @model_validator(mode="after")
    def _validate_visibility(self):
        if (
            self.visibility == VisibilityLevel.RESTRICTED
            and self.owner_group_id is None
        ):
            raise ValueError(
                "Changing visibility to 'restricted' requires owner_group_id."
            )
        if (
            self.visibility is not None
            and self.visibility != VisibilityLevel.RESTRICTED
            and self.owner_group_id is not None
        ):
            raise ValueError(
                "owner_group_id can only be set when visibility is 'restricted'."
            )
        return self


class FileState(Enum):
    """The state of a file in a dataset.

    Datasets can contain files that are not registered in the database. This
    can happen if the file was added to the dataset directory after the
    dataset was registered. Additionally, files can be registered in the
    database but missing from the dataset directory. This can happen if the
    file was removed from the dataset directory after the dataset was
    registered.

    The state of a file can be one of the following:

    - ``missing``: The file is not registered in the database and is missing.

    - ``registered``: The file is registered in the database and is present.

    - ``unregistered``: The file is not registered in the database but is
        present in the dataset directory.
    """

    MISSING = "missing"
    """If the recording is registered but the file is missing."""

    REGISTERED = "registered"
    """If the recording is registered and the file is present."""

    UNREGISTERED = "unregistered"
    """If the recording is not registered but the file is present."""


class DatasetFile(BaseModel):
    """Schema for DatasetFile objects returned to the user."""

    path: Path
    """The path to the file."""

    state: FileState
    """The state of the file."""


class DatasetRecordingCreate(BaseModel):
    """Schema for DatasetRecording objects created by the user."""

    path: Path
    """The path to the recording in the dataset directory."""


class DatasetRecording(BaseSchema):
    """Schema for DatasetRecording objects returned to the user."""

    recording: Recording
    """The uuid of the recording."""

    state: FileState = Field(default=FileState.REGISTERED)
    """The state of the file."""

    path: Path
    """The path to the recording in the dataset directory."""


class DatasetCandidate(BaseModel):
    """Schema for dataset directory candidates detected on disk."""

    name: str
    """Human-friendly label for the directory (folder name)."""

    relative_path: Path
    """Path relative to the configured audio directory."""

    absolute_path: Path
    """Absolute path to the directory on disk."""


class DatasetCandidateInfo(BaseModel):
    """Additional information about a dataset directory candidate."""

    relative_path: Path
    """Path relative to the configured audio directory."""

    absolute_path: Path
    """Absolute path to the directory on disk."""

    has_nested_directories: bool = False
    """True when the directory contains at least one subdirectory."""

    audio_file_count: int = 0
    """Number of audio files detected (wav/mp3/flac and similar)."""
