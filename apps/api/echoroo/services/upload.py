"""Upload service for managing file upload sessions."""

from __future__ import annotations

import io
import logging
import os
import struct
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status

from echoroo.core import s3
from echoroo.core.settings import get_settings
from echoroo.models.enums import UploadFileStatus, UploadSessionStatus
from echoroo.models.upload import UploadFile, UploadSession
from echoroo.repositories.dataset import DatasetRepository
from echoroo.repositories.project import ProjectRepository
from echoroo.repositories.upload import UploadFileRepository, UploadSessionRepository
from echoroo.schemas.upload import UploadFilePresignedResponse, UploadFileRequest

__all__ = [
    "AudioGpsStripError",
    "UploadService",
    "strip_audio_gps_metadata",
]

logger = logging.getLogger(__name__)


class AudioGpsStripError(RuntimeError):
    """Raised when GPS sanitisation of a *supported* audio format fails.

    Round 2 hardening (B-2): when the magic-byte detector identifies a
    container we know how to sanitise (FLAC / OGG / MP3 via mutagen, or
    RIFF/WAVE via in-house chunk filter), any subsequent failure
    (mutagen load/strip/save error, bytestream corruption) is treated as
    fail-closed. The worker catches this and marks the file ``INVALID``
    rather than persisting a payload that may still carry GPS data.

    Unknown / unsupported formats continue to fall through cleanly: the
    upload pipeline rejects them at the magic-byte stage instead.
    """


# ---------------------------------------------------------------------------
# FR-028a: stream-level GPS metadata stripper
# ---------------------------------------------------------------------------
#
# This helper removes GPS / coordinate / location metadata from audio file
# byte streams *before* they are persisted to long-term object storage. It
# is the upload-side complement to ``s3_upload_sanitizer.sanitize_put_object_kwargs``
# (FR-028e), which strips raw lat/lng entries from S3 user-defined metadata.
#
# Supported formats are detected from header magic bytes:
#
# * RIFF / WAVE  -> drop GPS-bearing chunks (e.g. ``GPS ``, case-insensitive
#   match on the 4-byte chunk id), then rewrite the RIFF chunk size header.
# * FLAC         -> mutagen Vorbis comments: drop GPS-/LOCATION-/GEO-/COORD-
#   prefixed keys plus LATITUDE/LONGITUDE.
# * Ogg Vorbis / Ogg Opus -> same Vorbis comment policy as FLAC.
# * MP3 (ID3v2)  -> drop ``GEOB`` frames whose description hints at GPS,
#   ``TXXX:*`` frames whose description matches GPS keys, and any frame
#   whose key starts with ``GPS:``.
#
# Unknown / unsupported formats are returned unchanged. The upload pipeline
# already rejects such files at the ``_detect_audio_format`` stage; the
# defensive passthrough here avoids raising during best-effort cleanup.

# Lowercased Vorbis-comment keys that must be removed outright.
_VORBIS_GPS_EXACT_KEYS: frozenset[str] = frozenset(
    {
        "lat",
        "latitude",
        "lng",
        "lon",
        "longitude",
        "gps",
        "geo",
        "coord",
        "coords",
        "location",
    }
)

# Lowercased Vorbis-comment key prefixes that must be removed.
_VORBIS_GPS_PREFIXES: tuple[str, ...] = (
    "gps_",
    "gps-",
    "geo_",
    "geo-",
    "coord_",
    "coord-",
    "location_",
    "location-",
)


def _is_vorbis_gps_key(key: str) -> bool:
    """Return True if a Vorbis-comment key references GPS-derived metadata."""
    lowered = key.strip().lower()
    if lowered in _VORBIS_GPS_EXACT_KEYS:
        return True
    return any(lowered.startswith(prefix) for prefix in _VORBIS_GPS_PREFIXES)


def _is_riff_gps_chunk_id(chunk_id: bytes) -> bool:
    """Return True if a 4-byte RIFF chunk id is GPS-bearing.

    The RIFF/WAVE specification reserves a ``GPS `` chunk for navigation
    metadata; some recorders extend this with ``Gps `` / ``gps ``. We accept
    case-insensitive matches of the 3-letter prefix as defense in depth.
    """
    if len(chunk_id) != 4:
        return False
    try:
        decoded = chunk_id.decode("ascii", errors="strict")
    except UnicodeDecodeError:
        return False
    return decoded.strip().lower() in {"gps", "geo", "loca", "coor"}


def _strip_wav_gps_chunks(payload: bytes) -> bytes:
    """Remove GPS-bearing chunks from a RIFF/WAVE byte stream."""
    if len(payload) < 12 or payload[:4] != b"RIFF" or payload[8:12] != b"WAVE":
        return payload

    body_chunks: list[bytes] = []
    cursor = 12
    stripped = False
    while cursor + 8 <= len(payload):
        chunk_id = payload[cursor : cursor + 4]
        (chunk_size,) = struct.unpack("<I", payload[cursor + 4 : cursor + 8])
        # RIFF pads odd-length chunks to even byte boundary.
        padded_size = chunk_size + (chunk_size % 2)
        chunk_end = cursor + 8 + padded_size
        if chunk_end > len(payload):
            # Truncated stream: keep remaining bytes verbatim and break.
            body_chunks.append(payload[cursor:])
            cursor = len(payload)
            break

        if _is_riff_gps_chunk_id(chunk_id):
            stripped = True
            logger.info(
                "audio_gps_chunk_stripped",
                extra={
                    "event": "audio_gps_chunk_stripped",
                    "format": "wav",
                    "chunk_id": chunk_id.decode("ascii", errors="replace"),
                },
            )
        else:
            body_chunks.append(payload[cursor:chunk_end])
        cursor = chunk_end

    if not stripped:
        return payload

    body = b"WAVE" + b"".join(body_chunks)
    new_riff_size = len(body)
    return b"RIFF" + struct.pack("<I", new_riff_size) + body


def _strip_vorbis_comment_gps_keys(audio: Any) -> bool:
    """Delete GPS-bearing Vorbis comments in-place. Return True if changed."""
    if audio is None or not getattr(audio, "tags", None):
        return False
    keys_to_delete = [k for k in list(audio.tags.keys()) if _is_vorbis_gps_key(k)]
    if not keys_to_delete:
        return False
    for key in keys_to_delete:
        try:
            del audio.tags[key]
        except KeyError:
            continue
    logger.info(
        "audio_gps_chunk_stripped",
        extra={
            "event": "audio_gps_chunk_stripped",
            "format": getattr(audio, "__class__", type(audio)).__name__.lower(),
            "keys": keys_to_delete,
        },
    )
    return True


def _strip_id3_gps_frames(audio: Any) -> bool:
    """Delete GPS-bearing ID3v2 frames in-place. Return True if changed."""
    if audio is None or not getattr(audio, "tags", None):
        return False
    frame_keys = list(audio.tags.keys())
    keys_to_delete: list[str] = []
    for key in frame_keys:
        # ID3 frame keys look like ``TXXX:GPS Latitude`` or ``GEOB:gps``.
        # We treat anything whose suffix (post-colon) matches our policy or
        # whose prefix is a custom GPS-named frame as GPS-bearing.
        lowered = key.lower()
        if lowered.startswith("gps:") or lowered.startswith("geob:gps") \
                or lowered.startswith("txxx:gps") or lowered.startswith("txxx:lat") \
                or lowered.startswith("txxx:lng") or lowered.startswith("txxx:lon") \
                or lowered.startswith("txxx:longitude") or lowered.startswith("txxx:latitude") \
                or lowered.startswith("txxx:location") or lowered.startswith("txxx:geo") \
                or lowered.startswith("txxx:coord"):
            keys_to_delete.append(key)
    if not keys_to_delete:
        return False
    for key in keys_to_delete:
        try:
            del audio.tags[key]
        except KeyError:
            continue
    logger.info(
        "audio_gps_chunk_stripped",
        extra={
            "event": "audio_gps_chunk_stripped",
            "format": "mp3",
            "keys": keys_to_delete,
        },
    )
    return True


def strip_audio_gps_metadata(stream: io.BytesIO) -> io.BytesIO:
    """Strip GPS metadata from an in-memory audio byte stream.

    The function detects the container format from header magic bytes and
    removes any chunks/frames/tags that may carry coordinate data. The
    stream's read position is reset before inspection; the returned stream
    is positioned at offset zero.

    Args:
        stream: ``io.BytesIO`` containing the raw audio payload.

    Returns:
        A new ``io.BytesIO`` whose contents are the sanitized payload. When
        the input format is unsupported or contains no GPS metadata, the
        returned stream's bytes equal the input bytes.

    Raises:
        AudioGpsStripError: When the magic-byte detector identifies a
            *supported* format (RIFF/WAVE, FLAC, OGG, MP3) but the
            sanitiser fails to load, strip, or save the payload. This is
            **fail-closed** behaviour — the caller (worker validation) is
            expected to mark the file ``INVALID`` rather than persist a
            payload that may still leak GPS data.

    Notes:
        * For *unsupported* formats (no magic match) the function returns
          the input unchanged. The upload pipeline rejects such files at
          the ``_detect_audio_format`` stage; this defensive passthrough
          only triggers when a non-audio payload reaches the sanitiser.
        * Format detection is best-effort and based on magic bytes only;
          callers should pre-validate format upstream.
        * **Scope (RIFF/WAVE)**: only the top-level chunk list is filtered
          for GPS-bearing chunk ids (``GPS ``, ``GEO ``, ``LOCA``,
          ``COOR``, plus their case variants). RIFF ``LIST/INFO`` sub-
          chunks (``IART``, ``IGNR``, ``ICMT`` …) are not currently
          inspected because they are not standard locations for GPS
          coordinates; if that assumption changes, ``_strip_wav_gps_chunks``
          must be extended to recurse into ``LIST`` containers.
        * **Out of scope**: image-format EXIF (JPEG / WebP / TIFF). The
          B-2 release blocker covers audio uploads only; image uploads
          will be addressed by a follow-up backlog item.
    """
    import contextlib as _ctx

    with _ctx.suppress(Exception):
        stream.seek(0)
    try:
        payload = stream.read()
    except Exception as exc:  # noqa: BLE001
        logger.warning("strip_audio_gps_metadata: stream read failed: %s", exc)
        return stream

    sanitized = _strip_audio_gps_metadata_bytes(payload)
    return io.BytesIO(sanitized)


def _strip_audio_gps_metadata_bytes(payload: bytes) -> bytes:
    """Internal worker: strip GPS metadata from a raw audio byte payload."""
    if len(payload) < 4:
        return payload

    header4 = payload[:4]
    header2 = payload[:2]

    # WAV / RIFF
    if header4 == b"RIFF":
        return _strip_wav_gps_chunks(payload)

    # FLAC
    if header4 == b"fLaC":
        return _strip_flac_gps(payload)

    # Ogg (Vorbis or Opus)
    if header4 == b"OggS":
        return _strip_ogg_gps(payload)

    # MP3: either ID3v2 header or MPEG sync
    if header4[:3] == b"ID3" or header2 in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return _strip_mp3_gps(payload)

    return payload


def _roundtrip_with_mutagen(
    payload: bytes,
    suffix: str,
    loader: Any,
    stripper: Any,
) -> bytes:
    """Save mutagen-edited audio back to a byte payload via a temp file.

    Round 2 hardening (B-2): every mutagen failure path raises
    :class:`AudioGpsStripError` instead of returning the original payload.
    The caller dispatches here only after a positive magic-byte match, so
    a load/strip/save error means we cannot prove the persisted payload is
    free of GPS metadata — fail-closed and reject the file.
    """
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(payload)
        tmp.flush()
        tmp_path = tmp.name
    try:
        try:
            audio = loader(tmp_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "strip_audio_gps_metadata: mutagen load failed (%s): %s",
                suffix,
                exc,
            )
            raise AudioGpsStripError(
                f"mutagen load failed for {suffix} payload: {exc}",
            ) from exc
        try:
            changed = stripper(audio)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "strip_audio_gps_metadata: mutagen strip failed (%s): %s",
                suffix,
                exc,
            )
            raise AudioGpsStripError(
                f"mutagen strip failed for {suffix} payload: {exc}",
            ) from exc
        if not changed:
            return payload
        try:
            audio.save()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "strip_audio_gps_metadata: mutagen save failed (%s): %s",
                suffix,
                exc,
            )
            raise AudioGpsStripError(
                f"mutagen save failed for {suffix} payload: {exc}",
            ) from exc
        with open(tmp_path, "rb") as fp:
            return fp.read()
    finally:
        import contextlib as _ctx

        with _ctx.suppress(OSError):
            os.unlink(tmp_path)


def _strip_flac_gps(payload: bytes) -> bytes:
    from mutagen.flac import FLAC

    return _roundtrip_with_mutagen(
        payload, ".flac", FLAC, _strip_vorbis_comment_gps_keys,
    )


def _strip_ogg_gps(payload: bytes) -> bytes:
    # Try Opus first (more specific magic bytes inside Ogg pages); fall back
    # to Vorbis on failure.
    from mutagen.oggopus import OggOpus
    from mutagen.oggvorbis import OggVorbis

    # Heuristic: Ogg Opus pages contain "OpusHead" near the start.
    if b"OpusHead" in payload[:512]:
        return _roundtrip_with_mutagen(
            payload, ".opus", OggOpus, _strip_vorbis_comment_gps_keys,
        )
    return _roundtrip_with_mutagen(
        payload, ".ogg", OggVorbis, _strip_vorbis_comment_gps_keys,
    )


def _strip_mp3_gps(payload: bytes) -> bytes:
    from mutagen.mp3 import MP3

    return _roundtrip_with_mutagen(
        payload, ".mp3", MP3, _strip_id3_gps_frames,
    )


class UploadService:
    """Service for managing file upload sessions."""

    def __init__(
        self,
        session_repo: UploadSessionRepository,
        file_repo: UploadFileRepository,
        dataset_repo: DatasetRepository,
        project_repo: ProjectRepository,
    ) -> None:
        """Initialize service with repositories.

        Args:
            session_repo: Upload session repository instance
            file_repo: Upload file repository instance
            dataset_repo: Dataset repository instance
            project_repo: Project repository instance
        """
        self.session_repo = session_repo
        self.file_repo = file_repo
        self.dataset_repo = dataset_repo
        self.project_repo = project_repo

    async def create_session(
        self,
        user_id: UUID,
        project_id: UUID,
        dataset_id: UUID,
        files: list[UploadFileRequest],
    ) -> tuple[UploadSession, list[UploadFilePresignedResponse]]:
        """Create upload session with presigned URLs.

        Validates permissions, file constraints, and generates presigned S3 PUT
        URLs for each file in the session.

        Args:
            user_id: ID of the requesting user
            project_id: Project UUID (for access control)
            dataset_id: Dataset UUID where files will be ingested
            files: List of file metadata entries to upload

        Returns:
            Tuple of (UploadSession instance, list of per-file presigned URL responses)

        Raises:
            HTTPException 404: Dataset not found or does not belong to the project
            HTTPException 409: An active upload session already exists for this dataset
            HTTPException 422: Validation failure (bad extension, file too large, quota exceeded,
                               too many files)

        Note:
            Permission enforcement is performed by the API layer via the
            Stage-1 ``is_allowed`` gate (``UPLOAD_CREATE_ACTION`` /
            ``Permission.UPLOAD``). The legacy admin-only check has been
            removed here so that any caller satisfying the matrix-defined
            ``UPLOAD`` permission (Member or higher) can create a session
            without a redundant admin gate that contradicted the spec.
        """
        settings = get_settings()

        # 1. Verify dataset exists and belongs to this project
        dataset = await self.dataset_repo.get_by_id(dataset_id)
        if dataset is None or dataset.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dataset not found",
            )

        # 2. Check for existing active session
        active_session = await self.session_repo.get_active_by_dataset(dataset_id)
        if active_session is not None:
            # Auto-cancel stale ISSUED/UPLOADED sessions (user retried after a failure)
            if active_session.status in (
                UploadSessionStatus.ISSUED,
                UploadSessionStatus.UPLOADED,
            ):
                await self.session_repo.update_status(
                    active_session.id,
                    UploadSessionStatus.FAILED,
                    error="Superseded by new upload session",
                )
            else:
                # Session is actively processing (VALIDATING/VALIDATED/IMPORTING)
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="An active upload session is currently being processed for this dataset",
                )

        # 3. Validate file count
        if len(files) > settings.UPLOAD_MAX_SESSION_FILES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Too many files: maximum {settings.UPLOAD_MAX_SESSION_FILES} per session",
            )

        # 4. Validate each file's extension and size
        allowed_extensions = set(settings.UPLOAD_ALLOWED_EXTENSIONS)
        for file_req in files:
            ext = os.path.splitext(file_req.filename)[1].lower()
            if ext not in allowed_extensions:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"File '{file_req.filename}' has unsupported extension '{ext}'. "
                        f"Allowed: {', '.join(sorted(allowed_extensions))}"
                    ),
                )
            if file_req.size > settings.UPLOAD_MAX_FILE_SIZE:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"File '{file_req.filename}' exceeds maximum size of "
                        f"{settings.UPLOAD_MAX_FILE_SIZE} bytes"
                    ),
                )

        # 5. Validate total size against project quota (cumulative check)
        total_bytes = sum(f.size for f in files)
        current_usage = await self.session_repo.get_total_storage_by_project(project_id)
        if current_usage + total_bytes > settings.DEFAULT_STORAGE_QUOTA:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Upload would exceed project storage quota. "
                    f"Current usage: {current_usage} bytes, "
                    f"requested: {total_bytes} bytes, "
                    f"quota: {settings.DEFAULT_STORAGE_QUOTA} bytes"
                ),
            )

        # Create session record (no files yet, need session ID for object keys)
        expires_at = datetime.now(UTC) + timedelta(seconds=settings.UPLOAD_SESSION_TTL)
        session = UploadSession(
            dataset_id=dataset_id,
            created_by_id=user_id,
            status=UploadSessionStatus.ISSUED,
            total_files=len(files),
            total_bytes=total_bytes,
            expires_at=expires_at,
        )
        session = await self.session_repo.create(session)

        # Build UploadFile records and presigned URLs.
        # Use the public client so presigned URLs point to the browser-accessible endpoint.
        s3_client = s3.get_public_s3_client()
        upload_file_records: list[UploadFile] = []
        presigned_responses: list[UploadFilePresignedResponse] = []

        for file_req in files:
            ext = os.path.splitext(file_req.filename)[1].lower()
            file_uuid = uuid.uuid4()
            object_key = (
                f"uploads/{project_id}/{dataset_id}/{session.id}/{file_uuid}{ext}"
            )

            # Generate presigned PUT URL
            upload_url = s3.generate_presigned_upload_url(
                object_key=object_key,
                expiry_seconds=settings.S3_PRESIGNED_URL_EXPIRY,
                client=s3_client,
            )

            upload_file = UploadFile(
                id=file_uuid,
                session_id=session.id,
                original_filename=file_req.filename,
                object_key=object_key,
                file_size=file_req.size,
                checksum_sha256=file_req.checksum_sha256,
                status=UploadFileStatus.PENDING,
            )
            upload_file_records.append(upload_file)
            presigned_responses.append(
                UploadFilePresignedResponse(
                    file_id=str(file_uuid),
                    original_filename=file_req.filename,
                    upload_url=upload_url,
                )
            )

        # Persist file records
        await self.file_repo.create_many(upload_file_records)

        return session, presigned_responses

    async def complete_upload(
        self,
        user_id: UUID,
        project_id: UUID,
        dataset_id: UUID,
        session_id: UUID,
    ) -> dict[str, Any]:
        """Verify uploaded files and transition session to UPLOADED state.

        Checks S3 for each file's presence, updates per-file status accordingly,
        and advances the session status to UPLOADED when all files are confirmed.

        Args:
            user_id: ID of the requesting user
            project_id: Project UUID (for access control)
            dataset_id: Dataset UUID (for ownership verification)
            session_id: Upload session UUID to complete

        Returns:
            Dict with keys: session_id, status, verified_files, missing_files, mismatched_files

        Raises:
            HTTPException 403: Caller does not own this upload session
            HTTPException 404: Session not found or does not belong to this dataset/project
            HTTPException 409: Session is not in ISSUED state

        Note:
            Permission enforcement is performed by the API layer via the
            Stage-1 ``is_allowed`` gate (``UPLOAD_CREATE_ACTION`` /
            ``Permission.UPLOAD``). The legacy admin-only check has been
            removed; ownership of the session is still asserted below so
            callers cannot complete a session they did not create.
        """
        # 1. Load and validate the session
        session = await self.session_repo.get_by_id(session_id)
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Upload session not found",
            )

        # Verify dataset belongs to project
        dataset = await self.dataset_repo.get_by_id(dataset_id)
        if dataset is None or dataset.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dataset not found",
            )

        # Verify session belongs to the specified dataset and user
        if session.dataset_id != dataset_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Upload session not found",
            )
        if session.created_by_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not own this upload session",
            )

        # 2. Require ISSUED state
        if session.status != UploadSessionStatus.ISSUED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Upload session is in '{session.status.value}' state; expected 'issued'",
            )

        # 3. Verify each file in S3
        s3_client = s3.get_s3_client()
        files = await self.file_repo.get_by_session(session_id)

        verified_files = 0
        missing_files = 0
        mismatched_files = 0

        for upload_file in files:
            result = s3.verify_object_exists(
                object_key=upload_file.object_key,
                expected_size=upload_file.file_size,
                client=s3_client,
            )

            if not result["exists"]:
                missing_files += 1
                # Leave file status as PENDING (not uploaded yet)
            elif not result["size_match"]:
                mismatched_files += 1
                # Mark as uploaded but size mismatch will be caught during validation
                await self.file_repo.update_status(upload_file.id, UploadFileStatus.UPLOADED)
                verified_files += 1
            else:
                verified_files += 1
                await self.file_repo.update_status(upload_file.id, UploadFileStatus.UPLOADED)

        # 4. If all files are verified, transition session to UPLOADED (CAS guard)
        if missing_files == 0:
            await self.session_repo.update_status(
                session_id,
                UploadSessionStatus.UPLOADED,
                expected_status=UploadSessionStatus.ISSUED,
            )
            new_status = UploadSessionStatus.UPLOADED
        else:
            # Some files still missing; session stays ISSUED for retry
            new_status = UploadSessionStatus.ISSUED

        return {
            "session_id": str(session_id),
            "status": new_status.value,
            "verified_files": verified_files,
            "missing_files": missing_files,
            "mismatched_files": mismatched_files,
        }

    async def get_session_status(
        self,
        user_id: UUID,
        project_id: UUID,
        dataset_id: UUID,
        session_id: UUID,
    ) -> UploadSession:
        """Get session with access check.

        Verifies user has project access, dataset belongs to the project, and
        the session belongs to the dataset.

        Args:
            user_id: ID of the requesting user
            project_id: Project UUID (for access control)
            dataset_id: Dataset UUID (for ownership verification)
            session_id: Upload session UUID to retrieve

        Returns:
            UploadSession instance with files eagerly loaded

        Raises:
            HTTPException 403: User does not have project access
            HTTPException 404: Dataset or session not found / ownership mismatch
        """
        # Verify user has any project access (members can view status)
        has_access = await self.project_repo.has_project_access(project_id, user_id)
        if not has_access:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to this project",
            )

        # Verify dataset belongs to the project
        dataset = await self.dataset_repo.get_by_id(dataset_id)
        if dataset is None or dataset.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dataset not found",
            )

        # Load session
        session = await self.session_repo.get_by_id(session_id)
        if session is None or session.dataset_id != dataset_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Upload session not found",
            )

        return session
