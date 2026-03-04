"""Celery worker tasks for upload session processing.

Tasks run outside FastAPI's async event loop, so async database calls
are executed via asyncio.run() in a sync Celery task context.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import json
import logging
import os
import re
import subprocess
import tempfile
from datetime import datetime
from os.path import splitext
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from echoroo.core.s3 import (
    delete_objects_by_prefix,
    get_object_stream,
    get_s3_client,
    move_object,
    verify_object_exists,
)
from echoroo.core.settings import get_settings
from echoroo.models.enums import DatetimeParseStatus, UploadFileStatus, UploadSessionStatus
from echoroo.models.recording import Recording
from echoroo.models.upload import UploadFile, UploadSession
from echoroo.repositories.recording import RecordingRepository
from echoroo.repositories.upload import UploadFileRepository, UploadSessionRepository
from echoroo.workers.celery_app import app

logger = logging.getLogger(__name__)

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
# Async session factory for worker use
# ---------------------------------------------------------------------------


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Create a fresh async session factory for each task invocation.

    Each Celery task calls ``asyncio.run()`` which creates a new event loop.
    Reusing a cached engine across loops causes "Future attached to a different
    loop" errors, so we create a fresh engine every time.

    TODO: expose the engine so callers can dispose it in a finally block after
    the task completes (same pattern as ml_tasks._get_engine_and_session_factory).
    Currently the engine is leaked to GC, which is acceptable for short-lived
    tasks but should be cleaned up for consistency.
    """
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, echo=False, pool_pre_ping=True)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


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
) -> tuple[datetime | None, str | None]:
    """Parse a datetime from a filename using regex pattern and strptime format.

    Args:
        filename: Original filename string.
        pattern: Regex pattern to extract the datetime portion.
        format_str: strptime format string.

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


# ---------------------------------------------------------------------------
# Async implementations
# ---------------------------------------------------------------------------


async def _run_validate(session_id: str) -> dict[str, Any]:
    """Async implementation of upload session validation."""
    session_factory = _get_session_factory()
    s3 = get_s3_client()

    async with session_factory() as db:
        session_repo = UploadSessionRepository(db)
        file_repo = UploadFileRepository(db)

        # Load upload session
        upload_session: UploadSession | None = await session_repo.get_by_id(UUID(session_id))
        if upload_session is None:
            raise ValueError(f"Upload session not found: {session_id}")

        # Guard: only transition from UPLOADED state
        if upload_session.status != UploadSessionStatus.UPLOADED:
            raise ValueError(
                f"Session {session_id} is in {upload_session.status.value}, expected UPLOADED"
            )

        # CAS transition: UPLOADED -> VALIDATING
        transitioned = await session_repo.update_status(
            upload_session.id,
            UploadSessionStatus.VALIDATING,
            expected_status=UploadSessionStatus.UPLOADED,
        )
        if not transitioned:
            raise ValueError(f"Session {session_id} state changed concurrently, aborting validation")
        await db.commit()

        valid_count = 0
        invalid_count = 0

        # Process each uploaded file
        files = upload_session.files
        for file in files:
            if file.status != UploadFileStatus.UPLOADED:
                continue

            file_ext = splitext(file.original_filename)[1].lower() or ".bin"

            # --- Step 1: Check magic bytes ---
            try:
                stream = get_object_stream(file.object_key, byte_range="bytes=0-65535", client=s3)
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
            try:
                with tempfile.NamedTemporaryFile(suffix=file_ext, delete=False) as tmp:
                    tmp_path = tmp.name
                    # Download full file to temp location for ffprobe.
                    # Read in chunks to enforce a size limit (M4) and compute
                    # SHA-256 for integrity verification (M3 / H4 TOCTOU).
                    full_stream = get_object_stream(file.object_key, client=s3)
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

            # Mark file as valid with extracted metadata
            await file_repo.update_status(
                file.id,
                UploadFileStatus.VALID,
                duration=metadata["duration"],
                samplerate=metadata["samplerate"],
                channels=metadata["channels"],
                bit_depth=metadata["bit_depth"],
            )
            await db.commit()
            valid_count += 1

            # Update validated_files counter (valid+invalid = processed for progress)
            await session_repo.update_progress(
                upload_session.id, validated_files=valid_count + invalid_count,
            )
            await db.commit()

        # Mark session as validated regardless of per-file errors
        await session_repo.update_status(upload_session.id, UploadSessionStatus.VALIDATED)
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


async def _run_import(
    session_id: str,
    datetime_pattern: str | None,
    datetime_format: str | None,
) -> dict[str, Any]:
    """Async implementation of import from upload session."""
    session_factory = _get_session_factory()
    s3 = get_s3_client()

    async with session_factory() as db:
        session_repo = UploadSessionRepository(db)
        file_repo = UploadFileRepository(db)
        recording_repo = RecordingRepository(db)

        # Load upload session
        upload_session: UploadSession | None = await session_repo.get_by_id(UUID(session_id))
        if upload_session is None:
            raise ValueError(f"Upload session not found: {session_id}")

        if upload_session.status != UploadSessionStatus.VALIDATED:
            raise ValueError(
                f"Session {session_id} is in status {upload_session.status.value}, "
                "expected VALIDATED"
            )

        # CAS transition: VALIDATED -> IMPORTING
        transitioned = await session_repo.update_status(
            upload_session.id,
            UploadSessionStatus.IMPORTING,
            expected_status=UploadSessionStatus.VALIDATED,
        )
        if not transitioned:
            raise ValueError(f"Session {session_id} state changed concurrently, aborting import")
        await db.commit()

        dataset = upload_session.dataset
        project_id = dataset.project_id
        dataset_id = dataset.id

        # Resolve datetime pattern/format: prefer task arguments, fall back to dataset settings
        effective_pattern = datetime_pattern or dataset.datetime_pattern
        effective_format = datetime_format or dataset.datetime_format

        imported_count = 0
        failed_count = 0
        pending_recordings: list[Recording] = []
        pending_file_ids: list[UUID] = []

        async def _flush_batch() -> None:
            """Commit accumulated recording batch and update file statuses."""
            nonlocal imported_count
            if not pending_recordings:
                return
            created = await recording_repo.create_many(pending_recordings)
            await db.commit()
            for rec, file_id in zip(created, pending_file_ids, strict=False):
                await file_repo.update_status(
                    file_id,
                    UploadFileStatus.IMPORTED,
                    recording_id=rec.id,
                )
            await db.commit()
            imported_count += len(created)
            await session_repo.update_progress(upload_session.id, imported_files=imported_count)
            await db.commit()
            pending_recordings.clear()
            pending_file_ids.clear()

        valid_files: list[UploadFile] = await file_repo.get_valid_files(upload_session.id)

        for file in valid_files:
            recording_id = uuid4()
            file_ext = splitext(file.original_filename)[1].lower() or ""

            # Build destination S3 key
            dest_key = _build_recording_s3_key(project_id, dataset_id, recording_id, file_ext)

            # Re-verify S3 object existence and size before moving to guard
            # against TOCTOU: another process may have removed or replaced the
            # object between validation and import (H4).
            obj_info = verify_object_exists(file.object_key, expected_size=file.file_size, client=s3)
            if not obj_info["exists"] or not obj_info["size_match"]:
                logger.error(
                    "File %s missing or size changed before import, skipping",
                    file.object_key,
                )
                failed_count += 1
                continue

            # Move S3 object from uploads prefix to recordings prefix
            moved = move_object(file.object_key, dest_key, client=s3)
            if not moved:
                logger.error(
                    "Failed to move S3 object %s -> %s for file %s",
                    file.object_key,
                    dest_key,
                    file.id,
                )
                failed_count += 1
                continue

            # Parse datetime from original filename
            parsed_dt, parse_error = _parse_datetime_from_filename(
                file.original_filename,
                effective_pattern,
                effective_format,
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

        # Flush any remaining recordings
        await _flush_batch()

        # Mark session as fully imported
        await session_repo.update_status(upload_session.id, UploadSessionStatus.IMPORTED)
        await db.commit()

        logger.info(
            "Import complete for session %s: %d imported, %d failed",
            session_id,
            imported_count,
            failed_count,
        )

        # Trigger BirdNET detection after successful import
        try:
            from echoroo.workers.ml_tasks import run_birdnet_detection

            run_birdnet_detection.delay(str(dataset_id), str(project_id))
            logger.info("Triggered BirdNET detection for dataset %s", dataset_id)
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to trigger BirdNET detection: %s", e)
            # Import itself should still succeed even if ML trigger fails

        return {
            "session_id": session_id,
            "imported_files": imported_count,
            "failed_files": failed_count,
        }


async def _run_cleanup() -> dict[str, Any]:
    """Async implementation of orphan upload cleanup."""
    session_factory = _get_session_factory()
    s3 = get_s3_client()

    async with session_factory() as db:
        session_repo = UploadSessionRepository(db)

        expired_count = 0
        stale_count = 0

        # --- Cleanup expired ISSUED sessions ---
        expired_sessions: list[UploadSession] = await session_repo.get_expired_sessions()
        for upload_session in expired_sessions:
            dataset = upload_session.dataset
            prefix = f"uploads/{dataset.project_id}/{dataset.id}/{upload_session.id}/"
            try:
                deleted = delete_objects_by_prefix(prefix, client=s3)
                logger.info(
                    "Deleted %d S3 objects for expired session %s",
                    deleted,
                    upload_session.id,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("S3 cleanup failed for expired session %s: %s", upload_session.id, exc)

            await session_repo.update_status(
                upload_session.id,
                UploadSessionStatus.FAILED,
                error="Session expired",
            )
            await db.commit()
            expired_count += 1

        # --- Cleanup stale mid-processing sessions ---
        stale_sessions: list[UploadSession] = await session_repo.get_stale_sessions(max_age_hours=24)
        for upload_session in stale_sessions:
            dataset = upload_session.dataset
            prefix = f"uploads/{dataset.project_id}/{dataset.id}/{upload_session.id}/"
            try:
                deleted = delete_objects_by_prefix(prefix, client=s3)
                logger.info(
                    "Deleted %d S3 objects for stale session %s",
                    deleted,
                    upload_session.id,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("S3 cleanup failed for stale session %s: %s", upload_session.id, exc)

            await session_repo.update_status(
                upload_session.id,
                UploadSessionStatus.FAILED,
                error="Session timed out",
            )
            await db.commit()
            stale_count += 1

        logger.info(
            "Cleanup complete: %d expired sessions, %d stale sessions removed",
            expired_count,
            stale_count,
        )
        return {
            "expired_sessions_cleaned": expired_count,
            "stale_sessions_cleaned": stale_count,
        }


async def _mark_session_failed(session_id: str, error: str) -> None:
    """Mark an upload session as FAILED with an error message."""
    session_factory = _get_session_factory()
    async with session_factory() as db:
        session_repo = UploadSessionRepository(db)
        await session_repo.update_status(
            UUID(session_id),
            UploadSessionStatus.FAILED,
            error=error,
        )
        await db.commit()


# ---------------------------------------------------------------------------
# Celery task definitions
# ---------------------------------------------------------------------------


@app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="echoroo.workers.upload_tasks.validate_upload_session",
    max_retries=1,
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
    except Exception as exc:  # noqa: BLE001
        logger.exception("Validation failed for session %s: %s", session_id, exc)
        with contextlib.suppress(Exception):
            asyncio.run(_mark_session_failed(session_id, str(exc)))
        raise self.retry(exc=exc, countdown=30) from exc


@app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="echoroo.workers.upload_tasks.import_from_upload_session",
    max_retries=1,
)
def import_from_upload_session(
    self: Any,
    session_id: str,
    datetime_pattern: str | None = None,
    datetime_format: str | None = None,
) -> dict[str, Any]:
    """Create Recording records from a validated upload session.

    Moves each VALID file from the upload prefix to the recordings prefix
    in S3, parses datetime from the original filename if configured, and
    persists Recording objects to the database in batches.

    Args:
        session_id: Upload session UUID string.
        datetime_pattern: Override regex for datetime extraction (optional).
        datetime_format: Override strptime format string (optional).

    Returns:
        Summary dict with imported_files and failed_files counts.
    """
    logger.info("Starting import for session %s", session_id)
    try:
        return asyncio.run(_run_import(session_id, datetime_pattern, datetime_format))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Import failed for session %s: %s", session_id, exc)
        with contextlib.suppress(Exception):
            asyncio.run(_mark_session_failed(session_id, str(exc)))
        raise self.retry(exc=exc, countdown=30) from exc


@app.task(name="echoroo.workers.upload_tasks.cleanup_orphan_uploads")  # type: ignore[untyped-decorator]
def cleanup_orphan_uploads() -> dict[str, Any]:
    """Remove orphaned upload sessions and their S3 objects.

    Handles two categories:
    - Expired ISSUED sessions: presigned URLs have passed their expiry without upload.
    - Stale sessions: stuck in UPLOADED or VALIDATING state for more than 24 hours.

    Deletes S3 objects for each orphaned session and marks the session as FAILED.

    Returns:
        Summary dict with expired_sessions_cleaned and stale_sessions_cleaned counts.
    """
    logger.info("Starting orphan upload cleanup")
    return asyncio.run(_run_cleanup())
