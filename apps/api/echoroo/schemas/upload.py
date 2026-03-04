"""Upload session request and response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

# Characters forbidden in filenames (path separators, null byte, control chars)
_FORBIDDEN_FILENAME_CHARS = set('/\\:\x00')


class UploadFileRequest(BaseModel):
    """Single file in an upload request."""

    filename: str = Field(..., min_length=1, max_length=255, description="Original filename")

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, v: str) -> str:
        """Reject filenames with path traversal, null bytes, or control characters."""
        if ".." in v:
            raise ValueError("Filename must not contain '..'")
        if any(c in _FORBIDDEN_FILENAME_CHARS for c in v):
            raise ValueError("Filename contains forbidden characters (/, \\, :, or null byte)")
        if any(ord(c) < 32 for c in v):
            raise ValueError("Filename must not contain control characters")
        return v
    size: int = Field(..., gt=0, le=1073741824, description="File size in bytes (max 1GB)")
    checksum_sha256: str = Field(
        ...,
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
        description="Lowercase hex SHA-256 checksum",
    )


class CreateUploadSessionRequest(BaseModel):
    """Request to create an upload session and get presigned URLs."""

    files: list[UploadFileRequest] = Field(
        ...,
        min_length=1,
        max_length=500,
        description="List of files to upload (1-500 files per session)",
    )


class CompleteUploadRequest(BaseModel):
    """Optional request body for complete endpoint."""

    # Reserved for future partial completion flags
    pass


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class UploadFilePresignedResponse(BaseModel):
    """Presigned URL info for a single file."""

    file_id: str = Field(..., description="Upload file UUID")
    original_filename: str = Field(..., description="Original filename")
    upload_url: str = Field(..., description="Presigned S3 PUT URL")


class CreateUploadSessionResponse(BaseModel):
    """Response with session info and presigned URLs."""

    session_id: str = Field(..., description="Upload session UUID")
    status: str = Field(..., description="Session status")
    expires_at: datetime = Field(..., description="Presigned URL expiry time")
    total_files: int = Field(..., description="Total number of files in session")
    total_bytes: int = Field(..., description="Total expected bytes")
    files: list[UploadFilePresignedResponse] = Field(..., description="Per-file presigned URL info")


class UploadFileStatusResponse(BaseModel):
    """Status of a single file in a session."""

    file_id: str = Field(..., description="Upload file UUID")
    original_filename: str = Field(..., description="Original filename")
    status: str = Field(..., description="File status")
    file_size: int = Field(..., description="File size in bytes")
    duration: float | None = Field(None, description="Audio duration in seconds")
    samplerate: int | None = Field(None, description="Sample rate in Hz")
    channels: int | None = Field(None, description="Number of audio channels")
    validation_error: str | None = Field(None, description="Validation failure message")
    recording_id: str | None = Field(None, description="Created recording UUID (after import)")


class UploadSessionStatusResponse(BaseModel):
    """Full session status for polling."""

    session_id: str = Field(..., description="Upload session UUID")
    status: str = Field(..., description="Session lifecycle status")
    total_files: int = Field(..., description="Total number of files in session")
    total_bytes: int = Field(..., description="Total expected bytes")
    validated_files: int = Field(..., description="Number of files that passed validation")
    imported_files: int = Field(..., description="Number of files imported as recordings")
    progress_percent: float = Field(..., description="Import progress percentage (0-100)")
    error: str | None = Field(None, description="Session-level error message")
    files: list[UploadFileStatusResponse] = Field(..., description="Per-file status list")
    created_at: datetime = Field(..., description="Session creation time")
    updated_at: datetime = Field(..., description="Last update time")


class CompleteUploadResponse(BaseModel):
    """Response after completing upload verification."""

    session_id: str = Field(..., description="Upload session UUID")
    status: str = Field(..., description="Updated session status")
    verified_files: int = Field(..., description="Number of files confirmed present in S3")
    missing_files: int = Field(..., description="Number of files not yet found in S3")
    mismatched_files: int = Field(..., description="Number of files with size or checksum mismatch")
