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
    checksum_sha256: str | None = Field(
        None,
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
        description="Lowercase hex SHA-256 checksum (optional, skipped if unavailable e.g. HTTP without crypto.subtle)",
    )


class CreateUploadSessionRequest(BaseModel):
    """Request to create an upload session."""

    files: list[UploadFileRequest] = Field(
        ...,
        min_length=1,
        max_length=500,
        description="List of files to upload (1-500 files per session)",
    )


class CompleteUploadRequest(BaseModel):
    """Options for completing a session."""

    skip_missing: bool = Field(
        False,
        description=(
            "Mark files that were never fully transferred as skipped and proceed with the rest, "
            "instead of leaving the session open."
        ),
    )


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class UploadFileIssuedResponse(BaseModel):
    """One file of a freshly created session."""

    file_id: str = Field(..., description="Upload file UUID; used in the chunk URL")
    original_filename: str
    declared_size: int


class CreateUploadSessionResponse(BaseModel):
    """Response with session info and issued file identifiers."""

    session_id: str = Field(..., description="Upload session UUID")
    status: str = Field(..., description="Session status")
    expires_at: datetime = Field(..., description="Inactivity deadline; extended by every accepted chunk")
    total_files: int = Field(..., description="Total number of files in session")
    total_bytes: int = Field(..., description="Total expected bytes")
    files: list[UploadFileIssuedResponse] = Field(..., description="Per-file issued upload info")


class UploadFileStatusResponse(BaseModel):
    """Status of a single file in a session."""

    file_id: str = Field(..., description="Upload file UUID")
    original_filename: str = Field(..., description="Original filename")
    status: str = Field(..., description="File status")
    file_size: int = Field(..., description="File size in bytes")
    declared_size: int = Field(..., description="Size announced at session creation")
    received_bytes: int = Field(0, description="Bytes staged so far")
    chunk_digests: list[str] = Field(
        default_factory=list,
        description="SHA-256 of every staged chunk, in order",
    )
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
    """Response after completing upload staging."""

    session_id: str = Field(..., description="Upload session UUID")
    status: str = Field(..., description="Updated session status")
    verified_files: int = Field(..., description="Number of files fully staged on the server")
    missing_files: int = Field(..., description="Number of files not fully staged on the server")
    skipped_files: int = Field(0, description="Files marked skipped")


class ChunkAcceptedResponse(BaseModel):
    """Result of one accepted chunk."""

    file_id: str
    received_bytes: int = Field(..., description="Bytes staged after this chunk")
    complete: bool = Field(..., description="True once received_bytes == declared_size")


class ChunkOffsetDetail(BaseModel):
    """Payload of the 409 returned when a chunk cannot be appended."""

    detail: str
    received_bytes: int = Field(..., description="Offset the next chunk must start at")


class ChunkOffsetConflict(BaseModel):
    """Wire envelope of that 409 (FastAPI wraps HTTPException detail)."""

    detail: ChunkOffsetDetail


class ActiveUploadSessionResponse(BaseModel):
    """The caller's unfinished session, or ``session`` = None."""

    session: UploadSessionStatusResponse | None
