"""Celery worker tasks for upload session processing.

Tasks run outside FastAPI's async event loop, so async database calls
are executed via asyncio.run() in a sync Celery task context.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import io
import json
import logging
import os
import re
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
from os.path import splitext
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from celery.exceptions import Ignore

from echoroo.core import upload_staging
from echoroo.core.s3 import (
    delete_object,
    delete_objects_by_prefix,
    ensure_configured,
    get_object_stream,
    head_object,
    move_object,
    put_object,
    upload_file_to_object,
    verify_object_exists,
)
from echoroo.core.settings import get_settings
from echoroo.models.enums import (
    DatasetStatus,
    DatetimeParseStatus,
    UploadFileStatus,
    UploadSessionStatus,
)
from echoroo.models.recording import Recording
from echoroo.models.upload import UploadFile, UploadSession
from echoroo.repositories.dataset import DatasetRepository
from echoroo.repositories.recording import RecordingRepository
from echoroo.repositories.upload import UploadFileRepository, UploadSessionRepository
from echoroo.services.s3_upload_sanitizer import sanitize_put_object_kwargs
from echoroo.services.upload import strip_audio_gps_metadata
from echoroo.workers.celery_app import app
from echoroo.workers.db_utils import get_worker_engine_and_session_factory

logger = logging.getLogger(__name__)


class UploadSessionStateError(Exception):
    """Raised when a session's status does not match the expected precondition.

    These are terminal, non-transient failures (e.g. a redelivered acks_late
    task finding the session already past its expected state). Retrying can
    never succeed, so the task marks the session FAILED and terminates without
    re-queuing.
    """

    def __init__(self, message: str, *, mark_failed: bool = True) -> None:
        super().__init__(message)
        self.mark_failed = mark_failed


# ---------------------------------------------------------------------------
# Audio format magic byte signatures
# ---------------------------------------------------------------------------

_AUDIO_MAGIC: dict[str, list[bytes]] = {
    "wav": [b"RIFF"],
    "flac": [b"fLaC"],
    "mp3": [b"\xff\xfb", b"\xff\xf3", b"\xff\xf2", b"ID3"],
    "ogg": [b"OggS"],
}

_BATCH_SIZE = 100  # Number of recordings to insert per batch


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


_HEARTBEAT_INTERVAL_S = 60.0


async def _with_heartbeat(
    session_factory: Any, session_id: UUID, fn: Any, *args: Any, **kwargs: Any
) -> Any:
    """Run blocking ``fn`` in a thread and keep the session's heartbeat fresh meanwhile.

    A 1 GiB hash, sanitise or upload can outlast the 15-minute stale window on
    its own; the reaper (or the API's self-heal) would then fail live work. The
    heartbeat uses its own database session so it never touches the worker's
    open transaction.
    """
    work = asyncio.ensure_future(asyncio.to_thread(fn, *args, **kwargs))
    try:
        while True:
            done, _ = await asyncio.wait({work}, timeout=_HEARTBEAT_INTERVAL_S)
            if done:
                return work.result()
            try:
                async with session_factory() as beat_db:
                    await UploadSessionRepository(beat_db).touch(session_id)
                    await beat_db.commit()
            except Exception as exc:  # noqa: BLE001 - a missed beat is not fatal
                logger.warning("Heartbeat for session %s failed: %s", session_id, exc)
    finally:
        if not work.done():
            await asyncio.wait({work})


def _sanitize_to_clean(source: Path, clean_path: Path) -> tuple[int, str]:
    """Strip GPS from ``source`` and durably publish the result at ``clean_path``.

    Whole file in memory by design. Temp file in the same directory, fsync,
    atomic rename, directory fsync. Returns ``(size, sha256)`` of the clean
    bytes. Blocking: run it under :func:`_with_heartbeat`.
    """
    sanitized = strip_audio_gps_metadata(io.BytesIO(source.read_bytes())).read()
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=clean_path.parent, prefix=f".{clean_path.stem}.", delete=False
        ) as clean_file:
            temp_path = Path(clean_file.name)
            clean_file.write(sanitized)
            clean_file.flush()
            os.fsync(clean_file.fileno())
        os.replace(temp_path, clean_path)
        temp_path = None
        # The rename is atomic but not durable until the directory entry is flushed.
        dir_fd = os.open(clean_path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if temp_path is not None:
            with contextlib.suppress(OSError):
                temp_path.unlink()
    return len(sanitized), hashlib.sha256(sanitized).hexdigest()


def _staged_source(file: UploadFile) -> Path | None:
    """Return the staged file for a chunked upload, or None for a presigned one."""
    if file.received_bytes <= 0:
        return None
    return upload_staging.part_path(file.session_id, file.id)


def _clean_path(file: UploadFile) -> Path:
    """Where the GPS-sanitised copy of a staged file lives (same directory, atomic rename target)."""
    return upload_staging.session_dir(file.session_id) / f"{file.id}.clean"


def _sha256_of_path(path: Path) -> str:
    """Return the SHA-256 digest of a local file read in bounded chunks."""
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(65536)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _detect_audio_format(header: bytes) -> str | None:
    """Return format name if header matches a known audio magic signature, else None."""
    for fmt, signatures in _AUDIO_MAGIC.items():
        for sig in signatures:
            if header[: len(sig)] == sig:
                # Extra check for WAV: must contain "WAVE" in first 12 bytes
                if fmt == "wav" and b"WAVE" not in header[:12]:
                    continue
                return fmt
    return None


def _run_ffprobe(file_path: str) -> dict[str, Any] | None:
    """Run ffprobe on a local file path and return parsed JSON output, or None on failure."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                file_path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.warning("ffprobe returned non-zero exit code for %s: %s", file_path, result.stderr)
            return None
        parsed: dict[str, Any] = json.loads(result.stdout)
        return parsed
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as exc:
        logger.warning("ffprobe failed for %s: %s", file_path, exc)
        return None


def _extract_audio_metadata(probe_data: dict[str, Any]) -> dict[str, Any]:
    """Extract audio metadata fields from ffprobe output.

    Returns a dict with keys: duration, samplerate, channels, bit_depth.
    Missing values are set to None.
    """
    metadata: dict[str, Any] = {
        "duration": None,
        "samplerate": None,
        "channels": None,
        "bit_depth": None,
    }

    # Prefer format-level duration
    fmt = probe_data.get("format", {})
    if "duration" in fmt:
        with contextlib.suppress(ValueError, TypeError):
            metadata["duration"] = float(fmt["duration"])

    # Extract audio stream properties
    streams = probe_data.get("streams", [])
    for stream in streams:
        if stream.get("codec_type") != "audio":
            continue
        if metadata["duration"] is None and "duration" in stream:
            with contextlib.suppress(ValueError, TypeError):
                metadata["duration"] = float(stream["duration"])
        if "sample_rate" in stream:
            with contextlib.suppress(ValueError, TypeError):
                metadata["samplerate"] = int(stream["sample_rate"])
        if "channels" in stream:
            with contextlib.suppress(ValueError, TypeError):
                metadata["channels"] = int(stream["channels"])
        if "bits_per_sample" in stream:
            with contextlib.suppress(ValueError, TypeError):
                bps = int(stream["bits_per_sample"])
                metadata["bit_depth"] = bps if bps > 0 else None
        break  # Use the first audio stream

    return metadata


def _parse_datetime_from_filename(
    filename: str,
    pattern: str | None,
    format_str: str | None,
    timezone: str | None = None,
) -> tuple[datetime | None, str | None]:
    """Parse a datetime from a filename using regex pattern and strptime format.

    Args:
        filename: Original filename string.
        pattern: Regex pattern to extract the datetime portion.
        format_str: strptime format string.
        timezone: Optional IANA timezone string (e.g., 'Asia/Tokyo'). When provided,
            the parsed naive datetime is made timezone-aware by attaching this tzinfo.
            PostgreSQL will store it correctly as UTC internally.

    Returns:
        Tuple of (parsed datetime or None, error message or None).
    """
    if not pattern or not format_str:
        return None, None
    # Guard against excessively long patterns (ReDoS mitigation)
    if len(pattern) > 200:
        return None, "Regex pattern too long (max 200 characters)"
    try:
        compiled = re.compile(pattern)
        match = compiled.search(filename)
        if not match:
            return None, "Pattern did not match filename"
        datetime_str = match.group(0)
        parsed = datetime.strptime(datetime_str, format_str)
        if timezone:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(timezone)
            parsed = parsed.replace(tzinfo=tz)
        return parsed, None
    except re.error as exc:
        return None, f"Invalid regex pattern: {exc}"
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def _build_recording_s3_key(
    project_id: UUID,
    dataset_id: UUID,
    recording_id: UUID,
    extension: str,
) -> str:
    """Build the canonical S3 key for a recording file.

    Pattern: recordings/{project_id}/{dataset_id}/{recording_id}{ext}
    """
    return f"recordings/{project_id}/{dataset_id}/{recording_id}{extension}"


def _sanitize_uploaded_object_gps(
    object_key: str,
    local_path: str,
    s3_client: Any = None,
) -> tuple[bytes, str] | None:
    """Strip GPS metadata from an uploaded S3 object in-place.

    Reads the audio bytes from ``local_path`` (already downloaded for ffprobe),
    applies ``strip_audio_gps_metadata``, then re-uploads the sanitized payload
    to ``object_key`` with sanitized S3 user-metadata (FR-028a + FR-028e).

    Failure semantics are **fail-closed**: any S3 error (head_object,
    get_object, put_object) or sanitizer error raises an exception, which the
    caller turns into per-file ``INVALID`` status. The previous Round 1
    behaviour returned ``None`` on head_object failure, which let unsanitized
    objects pass through to ``VALID`` — Round 2 closes that gap.

    s3_client is a test seam; production callers omit it.

    Returns:
        Tuple of (new_payload_bytes, new_sha256_hex) when the object was
        rewritten, or ``None`` when no change was needed (payload unchanged
        AND S3 metadata clean of GPS keys). Raises on any hard S3 / sanitizer
        failure so the caller can mark the file ``INVALID``.
    """
    settings = get_settings()
    bucket = settings.S3_BUCKET

    # 1. Pull current S3 user-metadata so we can preserve non-GPS keys.
    # Fail-closed: any head_object failure aborts the sanitize so the file
    # cannot be marked VALID without a sanitization pass.
    try:
        head = head_object(object_key, client=s3_client, bucket=bucket)
    except Exception as exc:
        logger.error(
            "GPS sanitize: head_object failed for %s: %s; failing closed",
            object_key,
            exc,
        )
        raise
    current_metadata: dict[str, str] = dict(head.get("Metadata") or {})
    content_type: str | None = head.get("ContentType")

    # 2. Strip GPS from the audio payload.
    with open(local_path, "rb") as fp:
        original_bytes = fp.read()
    sanitized_stream = strip_audio_gps_metadata(io.BytesIO(original_bytes))
    sanitized_bytes = sanitized_stream.read()

    # 3. Determine whether anything actually needs to be re-uploaded.
    metadata_dirty = any(
        sanitize_put_object_kwargs({"Metadata": current_metadata})["Metadata"]
        != current_metadata
        for _ in (0,)  # single-shot eval
    )
    payload_dirty = sanitized_bytes != original_bytes
    if not metadata_dirty and not payload_dirty:
        return None

    # 4. Re-upload. put_object applies the S3 user-metadata sanitizer (FR-028e).
    try:
        put_object(
            object_key,
            sanitized_bytes,
            content_type=content_type,
            metadata=current_metadata,
            bucket=bucket,
            client=s3_client,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "GPS sanitize: put_object rewrite failed for %s: %s",
            object_key,
            exc,
        )
        raise

    new_sha = hashlib.sha256(sanitized_bytes).hexdigest()
    logger.info(
        "audio_gps_sanitize_persisted",
        extra={
            "event": "audio_gps_sanitize_persisted",
            "object_key": object_key,
            "original_size": len(original_bytes),
            "new_size": len(sanitized_bytes),
            "metadata_dirty": metadata_dirty,
            "payload_dirty": payload_dirty,
        },
    )
    return sanitized_bytes, new_sha


# ---------------------------------------------------------------------------
# Async implementations
# ---------------------------------------------------------------------------


async def _run_validate(session_id: str) -> dict[str, Any]:
    """Async implementation of upload session validation."""
    engine, session_factory = get_worker_engine_and_session_factory()
    ensure_configured()

    try:
        async with session_factory() as db:
            session_repo = UploadSessionRepository(db)
            file_repo = UploadFileRepository(db)

            # Load upload session
            upload_session: UploadSession | None = await session_repo.get_by_id(UUID(session_id))
            if upload_session is None:
                raise ValueError(f"Upload session not found: {session_id}")

            # Guard: only transition from UPLOADED state
            if upload_session.status != UploadSessionStatus.UPLOADED:
                # A dead earlier run (VALIDATING) is failed so the uploader
                # can start over (#250); any later stage means the work was
                # already done and this delivery is simply dropped.
                raise UploadSessionStateError(
                    f"Session {session_id} is in {upload_session.status.value}, expected UPLOADED",
                    mark_failed=upload_session.status == UploadSessionStatus.VALIDATING,
                )

            # CAS transition: UPLOADED -> VALIDATING
            transitioned = await session_repo.update_status(
                upload_session.id,
                UploadSessionStatus.VALIDATING,
                expected_status=UploadSessionStatus.UPLOADED,
            )
            if not transitioned:
                raise UploadSessionStateError(
                    f"Session {session_id} state changed concurrently, aborting validation"
                )
            await db.commit()

            valid_count = 0
            invalid_count = 0

            # Process each uploaded file
            files = upload_session.files
            for file in files:
                try:
                    if file.status != UploadFileStatus.UPLOADED:
                        continue

                    source = _staged_source(file)
                    if source is not None:
                        if not source.exists() or source.stat().st_size != file.declared_size:
                            await file_repo.update_status(
                                file.id,
                                UploadFileStatus.INVALID,
                                validation_error="Staged file missing or truncated",
                            )
                            await db.commit()
                            invalid_count += 1
                            continue

                        try:
                            with source.open("rb") as stream:
                                header = stream.read(65536)
                        except Exception as exc:  # noqa: BLE001
                            logger.warning("Failed to read staged header for %s: %s", source, exc)
                            await file_repo.update_status(
                                file.id,
                                UploadFileStatus.INVALID,
                                validation_error=f"Failed to read file from storage: {exc}",
                            )
                            await db.commit()
                            invalid_count += 1
                            continue

                        if _detect_audio_format(header) is None:
                            logger.info("Invalid audio magic bytes for file %s", file.original_filename)
                            await file_repo.update_status(
                                file.id,
                                UploadFileStatus.INVALID,
                                validation_error="Invalid audio file format",
                            )
                            await db.commit()
                            invalid_count += 1
                            continue

                        actual_hash = await _with_heartbeat(
                            session_factory, upload_session.id, _sha256_of_path, source
                        )
                        if (
                            file.checksum_sha256 is not None
                            and not hmac.compare_digest(actual_hash, file.checksum_sha256)
                        ):
                            logger.warning(
                                "Checksum mismatch for file %s: expected %s..., got %s...",
                                file.original_filename,
                                file.checksum_sha256[:16],
                                actual_hash[:16],
                            )
                            await file_repo.update_status(
                                file.id,
                                UploadFileStatus.INVALID,
                                validation_error=(
                                    f"Checksum mismatch: expected {file.checksum_sha256[:16]}..., "
                                    f"got {actual_hash[:16]}..."
                                ),
                            )
                            await db.commit()
                            invalid_count += 1
                            continue

                        staged_probe: dict[str, Any] | None = _run_ffprobe(str(source))
                        if staged_probe is None:
                            await file_repo.update_status(
                                file.id,
                                UploadFileStatus.INVALID,
                                validation_error="Could not extract audio metadata (ffprobe failed)",
                            )
                            await db.commit()
                            invalid_count += 1
                            continue

                        clean_path = _clean_path(file)
                        try:
                            clean_size, clean_sha = await _with_heartbeat(
                                session_factory,
                                upload_session.id,
                                _sanitize_to_clean,
                                source,
                                clean_path,
                            )
                        except Exception as exc:  # noqa: BLE001
                            logger.error(
                                "GPS sanitize failed for %s: %s",
                                file.original_filename,
                                exc,
                            )
                            await file_repo.update_status(
                                file.id,
                                UploadFileStatus.INVALID,
                                validation_error=f"GPS metadata strip failed: {exc}",
                            )
                            await db.commit()
                            invalid_count += 1
                            continue

                        metadata = _extract_audio_metadata(staged_probe)
                        if metadata["duration"] is None or metadata["samplerate"] is None:
                            await file_repo.update_status(
                                file.id,
                                UploadFileStatus.INVALID,
                                validation_error="Could not determine audio duration or sample rate",
                            )
                            await db.commit()
                            invalid_count += 1
                            continue

                        await file_repo.update_status(
                            file.id,
                            UploadFileStatus.VALID,
                            duration=metadata["duration"],
                            samplerate=metadata["samplerate"],
                            channels=metadata["channels"],
                            bit_depth=metadata["bit_depth"],
                            file_size=clean_size,
                            checksum_sha256=clean_sha,
                        )
                        await db.commit()
                        valid_count += 1
                        continue

                    file_ext = splitext(file.original_filename)[1].lower() or ".bin"

                    # --- Step 1: Check magic bytes ---
                    try:
                        stream = get_object_stream(file.object_key, byte_range="bytes=0-65535")
                        header = stream.read(65536)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Failed to read S3 header for %s: %s", file.object_key, exc)
                        await file_repo.update_status(
                            file.id,
                            UploadFileStatus.INVALID,
                            validation_error=f"Failed to read file from storage: {exc}",
                        )
                        await db.commit()
                        invalid_count += 1
                        continue

                    detected_format = _detect_audio_format(header)
                    if detected_format is None:
                        logger.info("Invalid audio magic bytes for file %s", file.original_filename)
                        await file_repo.update_status(
                            file.id,
                            UploadFileStatus.INVALID,
                            validation_error="Invalid audio file format",
                        )
                        await db.commit()
                        invalid_count += 1
                        continue

                    # --- Step 2: ffprobe metadata extraction ---
                    probe_data: dict[str, Any] | None = None
                    tmp_path: str | None = None
                    checksum_ok = True
                    # FR-028a: per-file sanitizer outputs (None when no rewrite).
                    sanitized_file_size: int | None = None
                    sanitized_checksum: str | None = None
                    try:
                        with tempfile.NamedTemporaryFile(suffix=file_ext, delete=False) as tmp:
                            tmp_path = tmp.name
                            # Download full file to temp location for ffprobe.
                            # Read in chunks to enforce a size limit (M4) and compute
                            # SHA-256 for integrity verification (M3 / H4 TOCTOU).
                            full_stream = get_object_stream(file.object_key)
                            max_bytes = file.file_size + 1024  # small margin for headers
                            bytes_written = 0
                            while True:
                                chunk = full_stream.read(65536)
                                if not chunk:
                                    break
                                bytes_written += len(chunk)
                                if bytes_written > max_bytes:
                                    raise ValueError(
                                        f"File exceeds expected size of {file.file_size} bytes"
                                    )
                                tmp.write(chunk)
                            tmp.flush()

                            # Verify SHA-256 checksum to detect corruption or TOCTOU replacement
                            # Skip verification if no checksum was provided (e.g. HTTP without crypto.subtle)
                            if file.checksum_sha256 is not None:
                                tmp.seek(0)
                                hasher = hashlib.sha256()
                                while True:
                                    read_chunk = tmp.read(65536)
                                    if not read_chunk:
                                        break
                                    hasher.update(read_chunk)
                                actual_hash = hasher.hexdigest()
                                if not hmac.compare_digest(actual_hash, file.checksum_sha256):
                                    checksum_ok = False
                                    logger.warning(
                                        "Checksum mismatch for file %s: expected %s..., got %s...",
                                        file.original_filename,
                                        file.checksum_sha256[:16],
                                        actual_hash[:16],
                                    )
                                    await file_repo.update_status(
                                        file.id,
                                        UploadFileStatus.INVALID,
                                        validation_error=(
                                            f"Checksum mismatch: expected {file.checksum_sha256[:16]}..., "
                                            f"got {actual_hash[:16]}..."
                                        ),
                                    )
                                    await db.commit()
                                    invalid_count += 1

                        if checksum_ok:
                            probe_data = _run_ffprobe(tmp_path)

                            # FR-028a + FR-028e: strip GPS from audio bytes and
                            # S3 user-metadata, then re-upload the sanitized
                            # payload so persistent storage never carries raw
                            # coordinates. Must run BEFORE the temp file is
                            # deleted in the finally block.
                            if probe_data is not None:
                                try:
                                    sanitize_result = _sanitize_uploaded_object_gps(
                                        file.object_key, tmp_path,
                                    )
                                except Exception as exc:  # noqa: BLE001
                                    logger.error(
                                        "GPS sanitize failed for %s: %s",
                                        file.original_filename,
                                        exc,
                                    )
                                    await file_repo.update_status(
                                        file.id,
                                        UploadFileStatus.INVALID,
                                        validation_error=(
                                            f"GPS metadata strip failed: {exc}"
                                        ),
                                    )
                                    await db.commit()
                                    invalid_count += 1
                                    checksum_ok = False
                                    probe_data = None
                                else:
                                    if sanitize_result is not None:
                                        new_bytes, new_sha = sanitize_result
                                        sanitized_file_size = len(new_bytes)
                                        sanitized_checksum = new_sha
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Error downloading/validating file %s: %s", file.original_filename, exc)
                        await file_repo.update_status(
                            file.id,
                            UploadFileStatus.INVALID,
                            validation_error=f"Validation error: {exc}",
                        )
                        await db.commit()
                        invalid_count += 1
                        checksum_ok = False  # Prevent further processing
                    finally:
                        if tmp_path is not None:
                            with contextlib.suppress(OSError):
                                os.unlink(tmp_path)

                    if not checksum_ok:
                        continue

                    if probe_data is None:
                        await file_repo.update_status(
                            file.id,
                            UploadFileStatus.INVALID,
                            validation_error="Could not extract audio metadata (ffprobe failed)",
                        )
                        await db.commit()
                        invalid_count += 1
                        continue

                    metadata = _extract_audio_metadata(probe_data)

                    # Require at minimum a duration and samplerate
                    if metadata["duration"] is None or metadata["samplerate"] is None:
                        await file_repo.update_status(
                            file.id,
                            UploadFileStatus.INVALID,
                            validation_error="Could not determine audio duration or sample rate",
                        )
                        await db.commit()
                        invalid_count += 1
                        continue

                    # Mark file as valid with extracted metadata. When the GPS
                    # sanitizer rewrote the object, propagate the new file size
                    # and checksum so downstream import-time TOCTOU checks
                    # operate on the sanitized payload.
                    update_kwargs: dict[str, Any] = {
                        "duration": metadata["duration"],
                        "samplerate": metadata["samplerate"],
                        "channels": metadata["channels"],
                        "bit_depth": metadata["bit_depth"],
                    }
                    if sanitized_file_size is not None:
                        update_kwargs["file_size"] = sanitized_file_size
                    if sanitized_checksum is not None:
                        update_kwargs["checksum_sha256"] = sanitized_checksum
                    await file_repo.update_status(
                        file.id,
                        UploadFileStatus.VALID,
                        **update_kwargs,
                    )
                    await db.commit()
                    valid_count += 1
                finally:
                    await session_repo.update_progress(
                        upload_session.id, validated_files=valid_count + invalid_count,
                    )
                    await db.commit()

            # Mark session as validated only if it is still being validated.
            transitioned = await session_repo.update_status(
                upload_session.id,
                UploadSessionStatus.VALIDATED,
                expected_status=UploadSessionStatus.VALIDATING,
            )
            if not transitioned:
                logger.warning(
                    "Session %s left VALIDATING during validation; not marking VALIDATED",
                    session_id,
                )
                raise UploadSessionStateError(
                    f"Session {session_id} left VALIDATING during validation",
                    mark_failed=False,
                )
            await db.commit()

            logger.info(
                "Validation complete for session %s: %d valid, %d invalid",
                session_id,
                valid_count,
                invalid_count,
            )
            return {
                "session_id": session_id,
                "valid_files": valid_count,
                "invalid_files": invalid_count,
            }
    finally:
        await engine.dispose()


async def _run_import(
    session_id: str,
    datetime_pattern: str | None,
    datetime_format: str | None,
    datetime_timezone: str | None = None,
) -> dict[str, Any]:
    """Async implementation of import from upload session."""
    engine, session_factory = get_worker_engine_and_session_factory()
    ensure_configured()

    try:
        async with session_factory() as db:
            session_repo = UploadSessionRepository(db)
            file_repo = UploadFileRepository(db)
            recording_repo = RecordingRepository(db)
            dataset_repo = DatasetRepository(db)

            # Load upload session
            upload_session: UploadSession | None = await session_repo.get_by_id(UUID(session_id))
            if upload_session is None:
                raise ValueError(f"Upload session not found: {session_id}")

            if upload_session.status != UploadSessionStatus.VALIDATED:
                # Same rule as validation: only a dead IMPORTING run is failed.
                raise UploadSessionStateError(
                    f"Session {session_id} is in status {upload_session.status.value}, "
                    "expected VALIDATED",
                    mark_failed=upload_session.status == UploadSessionStatus.IMPORTING,
                )

            # CAS transition: VALIDATED -> IMPORTING
            transitioned = await session_repo.update_status(
                upload_session.id,
                UploadSessionStatus.IMPORTING,
                expected_status=UploadSessionStatus.VALIDATED,
            )
            if not transitioned:
                raise UploadSessionStateError(
                    f"Session {session_id} state changed concurrently, aborting import"
                )
            await db.commit()

            dataset = upload_session.dataset
            project_id = dataset.project_id
            dataset_id = dataset.id

            # Resolve datetime pattern/format/timezone: prefer task arguments, fall back to dataset settings
            effective_pattern = datetime_pattern or dataset.datetime_pattern
            effective_format = datetime_format or dataset.datetime_format
            effective_timezone = datetime_timezone or dataset.datetime_timezone

            imported_count = 0
            failed_count = 0
            pending_recordings: list[Recording] = []
            pending_file_ids: list[UUID] = []

            async def _flush_batch() -> None:
                """Commit accumulated recording batch and update file statuses."""
                nonlocal imported_count
                if not pending_recordings:
                    return
                # Recording rows, their UploadFile links and the progress tick
                # commit together: a crash can never leave a Recording whose
                # upload row still says VALID.
                # Lock the session and confirm it is still ours: a force-fail
                # or reaper claim between publish and here must leave no
                # Recording behind (the reaper deletes unlinked objects).
                owner = await session_repo.get_for_update(upload_session.id)
                if owner is None or owner.status != UploadSessionStatus.IMPORTING:
                    await db.rollback()
                    # The objects of this batch were published after the
                    # session was taken from us; the reaper may already have
                    # run and will not come back, so this worker deletes them.
                    leftover = False
                    for rec in pending_recordings:
                        try:
                            leftover |= not delete_object(rec.path)
                        except Exception:  # noqa: BLE001
                            leftover = True
                    if leftover:
                        # Re-create the staging directory so the reaper's sweep
                        # revisits this session and retries the deletion.
                        with contextlib.suppress(OSError):
                            upload_staging.session_dir(upload_session.id).mkdir(
                                mode=0o700, parents=True, exist_ok=True
                            )
                    pending_recordings.clear()
                    pending_file_ids.clear()
                    raise UploadSessionStateError(
                        f"Session {session_id} left IMPORTING during import",
                        mark_failed=False,
                    )
                created = await recording_repo.create_many(pending_recordings)
                for rec, file_id in zip(created, pending_file_ids, strict=False):
                    await file_repo.update_status(
                        file_id,
                        UploadFileStatus.IMPORTED,
                        recording_id=rec.id,
                    )
                imported_count += len(created)
                await session_repo.update_progress(upload_session.id, imported_files=imported_count)
                await db.commit()
                pending_recordings.clear()
                pending_file_ids.clear()

            valid_files: list[UploadFile] = await file_repo.get_valid_files(upload_session.id)

            async def _process_file(file: UploadFile) -> None:
                """Publish one valid upload file and queue its Recording row."""
                nonlocal failed_count

                # Staged files get a deterministic destination (recording id =
                # upload file id): a re-run after a crash between publish and
                # commit overwrites the same key instead of leaving an orphan.
                recording_id = file.id if _staged_source(file) is not None else uuid4()
                file_ext = splitext(file.original_filename)[1].lower() or ""

                # Build destination S3 key
                dest_key = _build_recording_s3_key(project_id, dataset_id, recording_id, file_ext)

                source = _staged_source(file)
                if source is not None:
                    clean = _clean_path(file)
                    if not clean.exists() or clean.stat().st_size != file.file_size:
                        await file_repo.update_status(
                            file.id,
                            UploadFileStatus.INVALID,
                            validation_error="Clean staged file missing or truncated",
                        )
                        await db.commit()
                        failed_count += 1
                        return

                    actual_hash = await _with_heartbeat(
                        session_factory, upload_session.id, _sha256_of_path, clean
                    )
                    if (
                        file.checksum_sha256 is None
                        or not hmac.compare_digest(actual_hash, file.checksum_sha256)
                    ):
                        await file_repo.update_status(
                            file.id,
                            UploadFileStatus.INVALID,
                            validation_error="Checksum mismatch at import",
                        )
                        await db.commit()
                        failed_count += 1
                        return

                    await _with_heartbeat(
                        session_factory, upload_session.id, upload_file_to_object, clean, dest_key
                    )
                    try:
                        stored_size = head_object(dest_key)["ContentLength"]
                    except Exception:  # noqa: BLE001
                        stored_size = None
                    if stored_size != file.file_size:
                        # Never leave an unlinked object behind.
                        with contextlib.suppress(Exception):
                            delete_object(dest_key)
                        await file_repo.update_status(
                            file.id,
                            UploadFileStatus.INVALID,
                            validation_error="Stored object size mismatch",
                        )
                        await db.commit()
                        failed_count += 1
                        return
                else:
                    # Re-verify S3 object existence, size, AND SHA-256 before
                    # moving. A presigned PUT URL that is still inside its
                    # expiry window can be re-used by an attacker to swap the
                    # object's body for unsanitized / different content while
                    # keeping the same Content-Length — size checks alone do
                    # not detect this. Recomputing the SHA-256 against the
                    # value persisted by the validation pass (which reflects
                    # the post-sanitize bytes when GPS was stripped) closes
                    # this TOCTOU window (H4 / Round 2 hardening).
                    obj_info = verify_object_exists(
                        file.object_key,
                        expected_size=file.file_size,
                        expected_sha256=file.checksum_sha256,
                    )
                    if not obj_info["exists"] or not obj_info["size_match"]:
                        logger.error(
                            "File %s missing or size changed before import, skipping",
                            file.object_key,
                        )
                        await file_repo.update_status(
                            file.id,
                            UploadFileStatus.INVALID,
                            validation_error="Object missing or size changed before import",
                        )
                        await db.commit()
                        failed_count += 1
                        return
                    if (
                        file.checksum_sha256 is not None
                        and obj_info.get("sha256_match") is False
                    ):
                        actual_hex = obj_info.get("actual_sha256") or "unknown"
                        logger.error(
                            "audio_import_checksum_mismatch",
                            extra={
                                "event": "audio_import_checksum_mismatch",
                                "object_key": file.object_key,
                                "expected_sha256_prefix": file.checksum_sha256[:16],
                                "actual_sha256_prefix": actual_hex[:16],
                            },
                        )
                        await file_repo.update_status(
                            file.id,
                            UploadFileStatus.INVALID,
                            validation_error=(
                                "Checksum mismatch detected at import: "
                                f"expected {file.checksum_sha256[:16]}..., "
                                f"got {actual_hex[:16]}..."
                            ),
                        )
                        await db.commit()
                        failed_count += 1
                        return

                    # Move S3 object from uploads prefix to recordings prefix
                    moved = move_object(file.object_key, dest_key)
                    if not moved:
                        logger.error(
                            "Failed to move S3 object %s -> %s for file %s",
                            file.object_key,
                            dest_key,
                            file.id,
                        )
                        failed_count += 1
                        return

                # Parse datetime from original filename
                parsed_dt, parse_error = _parse_datetime_from_filename(
                    file.original_filename,
                    effective_pattern,
                    effective_format,
                    effective_timezone,
                )

                if parse_error is not None:
                    dt_status = DatetimeParseStatus.FAILED
                elif parsed_dt is not None:
                    dt_status = DatetimeParseStatus.SUCCESS
                else:
                    dt_status = DatetimeParseStatus.PENDING

                recording = Recording(
                    id=recording_id,
                    dataset_id=dataset_id,
                    filename=file.original_filename,
                    path=dest_key,
                    hash=file.checksum_sha256,
                    duration=file.duration or 0.0,
                    samplerate=file.samplerate or 0,
                    channels=file.channels or 1,
                    bit_depth=file.bit_depth,
                    datetime=parsed_dt,
                    datetime_parse_status=dt_status,
                    datetime_parse_error=parse_error,
                    time_expansion=1.0,
                )

                pending_recordings.append(recording)
                pending_file_ids.append(file.id)

                # Flush in batches to avoid large transactions
                if len(pending_recordings) >= _BATCH_SIZE:
                    await _flush_batch()

            for file in valid_files:
                try:
                    await _process_file(file)
                finally:
                    await session_repo.update_progress(
                        upload_session.id, imported_files=imported_count,
                    )
                    await db.commit()

            # Flush any remaining recordings
            await _flush_batch()

            # Mark the session as imported only if it is still being imported.
            transitioned = await session_repo.update_status(
                upload_session.id,
                UploadSessionStatus.IMPORTED,
                expected_status=UploadSessionStatus.IMPORTING,
            )
            if not transitioned:
                logger.warning(
                    "Session %s left IMPORTING during import; not marking IMPORTED",
                    session_id,
                )
                raise UploadSessionStateError(
                    f"Session {session_id} left IMPORTING during import",
                    mark_failed=False,
                )
            # The session's IMPORTED and the dataset's COMPLETED land in one
            # commit, so no other upload can start against a dataset whose
            # completion is still pending.
            await dataset_repo.update_import_status(
                dataset_id,
                DatasetStatus.COMPLETED,
                total_files=len(valid_files),
                processed_files=imported_count,
            )
            await db.commit()

            if await _delete_unlinked_publications(db, upload_session.id, project_id, dataset_id):
                try:
                    upload_staging.remove_session(upload_session.id)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Failed to remove staging directory for imported session %s: %s",
                        upload_session.id,
                        exc,
                    )

            logger.info(
                "Import complete for session %s: %d imported, %d failed",
                session_id,
                imported_count,
                failed_count,
            )

            # Note: automatic BirdNET detection after import has been removed.
            # Detection runs are now created explicitly via the API (DetectionRunService),
            # which ensures a DetectionRun record is committed to the database before
            # the Celery task is dispatched (avoiding a race condition).

            return {
                "session_id": session_id,
                "imported_files": imported_count,
                "failed_files": failed_count,
            }
    finally:
        await engine.dispose()


async def _delete_unlinked_publications(
    db: Any, session_id: UUID, project_id: UUID, dataset_id: UUID
) -> bool:
    """Delete staged files' deterministic destinations that never got a Recording.

    A crash between ``upload_file_to_object`` and the batch commit, or a HEAD
    size mismatch whose delete failed, leaves an object under
    ``recordings/…/{file_id}`` with the file unlinked. Returns True only when
    nothing is left; callers keep the staging directory otherwise so the next
    sweep retries.
    """
    all_gone = True
    for file in await UploadFileRepository(db).get_by_session(session_id):
        if file.received_bytes <= 0 or file.recording_id is not None:
            continue
        file_ext = splitext(file.original_filename)[1].lower() or ""
        key = _build_recording_s3_key(project_id, dataset_id, file.id, file_ext)
        try:
            if not delete_object(key):
                all_gone = False
        except Exception:  # noqa: BLE001
            all_gone = False
    return all_gone


_STALE_STATUSES_FOR_REAPER = (
    UploadSessionStatus.UPLOADED,
    UploadSessionStatus.VALIDATING,
    UploadSessionStatus.VALIDATED,
    UploadSessionStatus.IMPORTING,
)


async def _run_cleanup() -> dict[str, Any]:
    """Async implementation of orphan upload cleanup."""
    engine, session_factory = get_worker_engine_and_session_factory()
    ensure_configured()

    try:
        async with session_factory() as db:
            session_repo = UploadSessionRepository(db)

            expired_count = 0
            stale_count = 0
            orphaned_dirs = 0

            async def _claim_and_purge(
                candidate_id: UUID,
                project_id: UUID,
                dataset_id: UUID,
                *,
                reason: str,
                still_dead: Any,
            ) -> bool:
                """Fail a dead session and only then delete its bytes.

                The candidate list is a snapshot: between selection and here the
                session may have accepted a chunk (extended retention), started
                processing, or finished. Re-read under the row lock, re-check
                with ``still_dead``, claim it FAILED with a CAS, commit, and
                delete only after the claim is durable. Only scalars are used
                after the lock: a rollback expires every loaded ORM object.
                """
                locked = await session_repo.get_for_update(candidate_id)
                if locked is None or not still_dead(locked):
                    await db.rollback()
                    return False
                claimed = await session_repo.update_status(
                    candidate_id,
                    UploadSessionStatus.FAILED,
                    error=reason,
                    expected_status=locked.status,
                )
                if not claimed:
                    await db.rollback()
                    return False
                await db.commit()

                prefix = f"uploads/{project_id}/{dataset_id}/{candidate_id}/"
                try:
                    deleted = delete_objects_by_prefix(prefix)
                    logger.info(
                        "Deleted %d S3 objects for %s session %s",
                        deleted,
                        reason.lower(),
                        candidate_id,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("S3 cleanup failed for session %s: %s", candidate_id, exc)
                if await _delete_unlinked_publications(db, candidate_id, project_id, dataset_id):
                    try:
                        upload_staging.remove_session(candidate_id)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Staging cleanup failed for session %s: %s", candidate_id, exc)
                else:
                    logger.warning(
                        "Session %s: an unlinked object could not be deleted; staging kept for retry",
                        candidate_id,
                    )
                return True

            now = datetime.now(UTC)

            # --- Cleanup expired ISSUED sessions ---
            # Capture scalars first: candidates are ORM rows and a later
            # rollback would expire them.
            expired_candidates = [
                (s.id, s.dataset.project_id, s.dataset.id)
                for s in await session_repo.get_expired_sessions()
            ]
            for candidate_id, project_id, dataset_id in expired_candidates:
                if await _claim_and_purge(
                    candidate_id,
                    project_id,
                    dataset_id,
                    reason="Session expired",
                    still_dead=lambda s: s.status == UploadSessionStatus.ISSUED
                    and s.expires_at <= now,
                ):
                    expired_count += 1

            # --- Cleanup stale mid-processing sessions ---
            # Processing states (UPLOADED/VALIDATING/VALIDATED/IMPORTING) bump
            # updated_at on every progress tick, so the short stale timeout
            # (default 15 min) only reaps genuinely dead sessions — not slow
            # but alive imports.
            stale_timeout_seconds = get_settings().UPLOAD_STALE_TIMEOUT_SECONDS
            stale_cutoff = now - timedelta(seconds=stale_timeout_seconds)
            stale_candidates = [
                (s.id, s.dataset.project_id, s.dataset.id)
                for s in await session_repo.get_stale_sessions(max_age_seconds=stale_timeout_seconds)
            ]
            for candidate_id, project_id, dataset_id in stale_candidates:
                if await _claim_and_purge(
                    candidate_id,
                    project_id,
                    dataset_id,
                    reason="Session timed out",
                    still_dead=lambda s: s.status in _STALE_STATUSES_FOR_REAPER
                    and s.updated_at <= stale_cutoff,
                ):
                    stale_count += 1

            # --- Sweep staging directories that no longer belong to active sessions ---
            for staged_session_id in upload_staging.list_staged_sessions():
                staged_session = await session_repo.get_by_id(staged_session_id)
                if staged_session is None or staged_session.status in (
                    UploadSessionStatus.FAILED,
                    UploadSessionStatus.IMPORTED,
                ):
                    # A session failed elsewhere (cancel, force-fail, task
                    # failure) or imported with a rejected file may have
                    # published an object it never linked. Keep the directory
                    # until every such object is gone.
                    if staged_session is not None and not await _delete_unlinked_publications(
                        db,
                        staged_session_id,
                        staged_session.dataset.project_id,
                        staged_session.dataset.id,
                    ):
                        continue
                    try:
                        upload_staging.remove_session(staged_session_id)
                        orphaned_dirs += 1
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "Staging cleanup failed for orphaned session %s: %s",
                            staged_session_id,
                            exc,
                        )

            logger.info(
                "Cleanup complete: %d expired sessions, %d stale sessions removed, %d orphaned staging directories",
                expired_count,
                stale_count,
                orphaned_dirs,
            )
            return {
                "expired_sessions_cleaned": expired_count,
                "stale_sessions_cleaned": stale_count,
                "orphaned_dirs": orphaned_dirs,
            }
    finally:
        await engine.dispose()


async def _mark_session_failed(
    session_id: str, error: str, *, expected_status: UploadSessionStatus
) -> bool:
    """Mark an upload session FAILED only if it is still in ``expected_status``.

    ``expected_status`` is the processing state this task owns (VALIDATING for
    validation, IMPORTING for import). A session that meanwhile reached any
    other state — VALIDATED by the original run, IMPORTED, FAILED, cancelled —
    is left untouched, error text included. Returns whether the claim won.
    """
    engine, session_factory = get_worker_engine_and_session_factory()
    try:
        async with session_factory() as db:
            session_repo = UploadSessionRepository(db)
            claimed = await session_repo.update_status(
                UUID(session_id),
                UploadSessionStatus.FAILED,
                error=error,
                expected_status=expected_status,
            )
            if not claimed:
                logger.info(
                    "Not marking session %s failed: no longer in %s",
                    session_id,
                    expected_status.value,
                )
                await db.rollback()
                return False
            await db.commit()
            return True
    finally:
        await engine.dispose()


async def _mark_import_failed(session_id: str, error: str) -> None:
    """Fail an IMPORTING session and its dataset together; no-op otherwise."""
    engine, session_factory = get_worker_engine_and_session_factory()
    try:
        async with session_factory() as db:
            session_repo = UploadSessionRepository(db)
            session = await session_repo.get_by_id(UUID(session_id))
            if session is None:
                return
            claimed = await session_repo.update_status(
                UUID(session_id),
                UploadSessionStatus.FAILED,
                error=error,
                expected_status=UploadSessionStatus.IMPORTING,
            )
            if not claimed:
                logger.info("Not marking import of session %s failed: not IMPORTING", session_id)
                await db.rollback()
                return
            dataset_repo = DatasetRepository(db)
            await dataset_repo.update_import_status(
                session.dataset_id,
                DatasetStatus.FAILED,
                error=error,
            )
            await db.commit()
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Celery task definitions
# ---------------------------------------------------------------------------


@app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="echoroo.workers.upload_tasks.validate_upload_session",
    max_retries=1,
    # acks_late + reject_on_worker_lost: if the worker child is recycled
    # (worker_max_tasks_per_child), OOM-killed, or SIGKILLed mid-task, the
    # message is redelivered instead of silently lost. The CAS status guards
    # in _run_validate make a redelivery idempotent.
    acks_late=True,
    reject_on_worker_lost=True,
)
def validate_upload_session(self: Any, session_id: str) -> dict[str, Any]:
    """Validate audio files in an upload session using ffprobe.

    Downloads each uploaded file from S3, checks magic bytes, then runs
    ffprobe to extract audio metadata (duration, samplerate, channels,
    bit_depth). Updates per-file and session status in the database.

    Args:
        session_id: Upload session UUID string.

    Returns:
        Summary dict with valid_files and invalid_files counts.
    """
    logger.info("Starting validation for session %s", session_id)
    try:
        return asyncio.run(_run_validate(session_id))
    except UploadSessionStateError as exc:
        # Terminal precondition failure (e.g. a redelivered task whose session
        # already moved past UPLOADED). Retrying can never succeed, so mark the
        # session FAILED and stop without re-queuing.
        logger.warning("Validation aborted for session %s: %s", session_id, exc)
        if exc.mark_failed:
            with contextlib.suppress(Exception):
                asyncio.run(
                    _mark_session_failed(
                        session_id, str(exc), expected_status=UploadSessionStatus.VALIDATING
                    )
                )
        raise Ignore() from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Validation failed for session %s: %s", session_id, exc)
        with contextlib.suppress(Exception):
            asyncio.run(
                _mark_session_failed(
                    session_id, str(exc), expected_status=UploadSessionStatus.VALIDATING
                )
            )
        raise self.retry(exc=exc, countdown=30) from exc


@app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="echoroo.workers.upload_tasks.import_from_upload_session",
    max_retries=1,
    # acks_late + reject_on_worker_lost: survive worker child-recycle / OOM /
    # SIGKILL by redelivering the message. The VALIDATED->IMPORTING CAS guard in
    # _run_import prevents a redelivery from creating duplicate Recording rows.
    acks_late=True,
    reject_on_worker_lost=True,
)
def import_from_upload_session(
    self: Any,
    session_id: str,
    datetime_pattern: str | None = None,
    datetime_format: str | None = None,
    datetime_timezone: str | None = None,
) -> dict[str, Any]:
    """Create Recording records from a validated upload session.

    Moves each VALID file from the upload prefix to the recordings prefix
    in S3, parses datetime from the original filename if configured, and
    persists Recording objects to the database in batches.

    Args:
        session_id: Upload session UUID string.
        datetime_pattern: Override regex for datetime extraction (optional).
        datetime_format: Override strptime format string (optional).
        datetime_timezone: Override IANA timezone for datetime parsing (optional).

    Returns:
        Summary dict with imported_files and failed_files counts.
    """
    logger.info("Starting import for session %s", session_id)
    try:
        return asyncio.run(_run_import(session_id, datetime_pattern, datetime_format, datetime_timezone))
    except UploadSessionStateError as exc:
        # Terminal precondition failure (e.g. a redelivered task whose session
        # already moved past VALIDATED, so the CAS to IMPORTING failed). Retrying
        # can never succeed and could risk duplicate work, so mark FAILED and
        # stop without re-queuing.
        logger.warning("Import aborted for session %s: %s", session_id, exc)
        if exc.mark_failed:
            with contextlib.suppress(Exception):
                asyncio.run(_mark_import_failed(session_id, str(exc)))
        raise Ignore() from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Import failed for session %s: %s", session_id, exc)
        with contextlib.suppress(Exception):
            asyncio.run(_mark_import_failed(session_id, str(exc)))
        raise self.retry(exc=exc, countdown=30) from exc


async def _run_reparse_datetimes(
    dataset_id: str,
    pattern: str,
    format_str: str,
    timezone: str | None = None,
) -> dict[str, Any]:
    """Async implementation of datetime re-parsing for all recordings in a dataset."""
    engine, session_factory = get_worker_engine_and_session_factory()
    uuid_dataset_id = UUID(dataset_id)

    try:
        async with session_factory() as db:
            recording_repo = RecordingRepository(db)
            dataset_repo = DatasetRepository(db)

            total = await recording_repo.count_by_dataset(uuid_dataset_id)
            updated = 0
            failed = 0

            # Update dataset's datetime_timezone field when saving
            dataset = await dataset_repo.get_by_id(uuid_dataset_id)
            if dataset is not None:
                dataset.datetime_timezone = timezone
                await dataset_repo.update(dataset)
                await db.commit()

            # Process in batches of 100
            page = 1
            while True:
                recordings_page, _ = await recording_repo.list_by_dataset(
                    uuid_dataset_id,
                    page=page,
                    page_size=_BATCH_SIZE,
                    sort_by="id",
                    sort_order="asc",
                )
                if not recordings_page:
                    break

                for recording in recordings_page:
                    parsed_dt, parse_error = _parse_datetime_from_filename(
                        recording.filename, pattern, format_str, timezone
                    )

                    if parse_error is not None:
                        recording.datetime_parse_status = DatetimeParseStatus.FAILED
                        recording.datetime_parse_error = parse_error
                        recording.datetime = None
                        failed += 1
                    elif parsed_dt is not None:
                        recording.datetime_parse_status = DatetimeParseStatus.SUCCESS
                        recording.datetime_parse_error = None
                        recording.datetime = parsed_dt
                        updated += 1
                    else:
                        recording.datetime_parse_status = DatetimeParseStatus.PENDING
                        recording.datetime_parse_error = None
                        recording.datetime = None

                await db.commit()
                page += 1

            logger.info(
                "Re-parse complete for dataset %s: %d total, %d updated, %d failed",
                dataset_id,
                total,
                updated,
                failed,
            )
            return {
                "dataset_id": dataset_id,
                "total": total,
                "updated": updated,
                "failed": failed,
            }
    finally:
        await engine.dispose()


@app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="echoroo.workers.upload_tasks.reparse_recording_datetimes",
    max_retries=1,
)
def reparse_recording_datetimes(
    self: Any,
    dataset_id: str,
    pattern: str,
    format_str: str,
    timezone: str | None = None,
) -> dict[str, Any]:
    """Re-parse datetime from filenames for all recordings in a dataset.

    Processes recordings in batches of 100. For each recording, applies the
    given regex pattern and strptime format to extract a datetime from the
    filename, then updates the recording's datetime, datetime_parse_status,
    and datetime_parse_error fields.

    Args:
        dataset_id: Dataset UUID string.
        pattern: Regex pattern for datetime extraction.
        format_str: strptime format string.
        timezone: Optional IANA timezone string (e.g., 'Asia/Tokyo').

    Returns:
        Summary dict with total, updated, and failed counts.
    """
    logger.info("Starting datetime re-parse for dataset %s", dataset_id)
    try:
        return asyncio.run(_run_reparse_datetimes(dataset_id, pattern, format_str, timezone))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Datetime re-parse failed for dataset %s: %s", dataset_id, exc)
        raise self.retry(exc=exc, countdown=30) from exc


@app.task(name="echoroo.workers.upload_tasks.cleanup_orphan_uploads")  # type: ignore[untyped-decorator]
def cleanup_orphan_uploads() -> dict[str, Any]:
    """Remove orphaned upload sessions and their S3 objects.

    Handles two categories:
    - Expired ISSUED sessions: presigned URLs have passed their expiry without upload.
    - Stale sessions: stuck in a processing state (UPLOADED / VALIDATING /
      VALIDATED / IMPORTING) with no progress update within
      ``ECHOROO_UPLOAD_STALE_TIMEOUT_SECONDS`` (default 15 min).

    Deletes S3 objects for each orphaned session and marks the session as FAILED.

    Returns:
        Summary dict with expired_sessions_cleaned and stale_sessions_cleaned counts.
    """
    logger.info("Starting orphan upload cleanup")
    return asyncio.run(_run_cleanup())
