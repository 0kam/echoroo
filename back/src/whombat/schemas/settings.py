"""Schemas for application-level settings."""

from pathlib import Path

from pydantic import BaseModel, DirectoryPath, Field

__all__ = [
    "AudioDirectory",
    "AudioDirectoryUpdate",
]


class AudioDirectory(BaseModel):
    """Payload describing the configured audio directory."""

    audio_dir: Path = Field(
        ...,
        description="Absolute path to the directory containing audio data.",
    )


class AudioDirectoryUpdate(BaseModel):
    """Request payload used to update the audio directory."""

    audio_dir: DirectoryPath = Field(
        ...,
        description="Absolute path to an existing directory that should store audio data.",
    )
