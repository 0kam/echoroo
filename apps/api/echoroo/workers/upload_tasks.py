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
from datetime import datetime
from os.path import splitext
from typing import Any
from uuid import UUID, uuid4

from echoroo.core.s3 import (
    delete_objects_by_prefix,
    get_object_stream,
    get_s3_client,
    move_object,
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
    s3_client: Any,
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
        head = s3_client.head_object(Bucket=bucket, Key=object_key)
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

    # 4. Build sanitized PutObject kwargs and re-upload.
    put_kwargs: dict[str, Any] = {
        "Bucket": bucket,
        "Key": object_key,
        "Body": sanitized_bytes,
        "Metadata": current_metadata,
    }
    if content_type:
        put_kwargs["ContentType"] = content_type
    put_kwargs = sanitize_put_object_kwargs(put_kwargs)

    try:
        s3_client.put_object(**put_kwargs)
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
    s3 = get_s3_client()

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
                # FR-028a: per-file sanitizer outputs (None when no rewrite).
                sanitized_file_size: int | None = None
                sanitized_checksum: str | None = None
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
                                    file.object_key, tmp_path, s3,
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
    s3 = get_s3_client()

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
                    client=s3,
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
                    continue
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

            # Flush any remaining recordings
            await _flush_batch()

            # Update both session and dataset status in a single commit
            await session_repo.update_status(upload_session.id, UploadSessionStatus.IMPORTED)
            await dataset_repo.update_import_status(
                dataset_id,
                DatasetStatus.COMPLETED,
                total_files=len(valid_files),
                processed_files=imported_count,
            )
            await db.commit()

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


async def _run_cleanup() -> dict[str, Any]:
    """Async implementation of orphan upload cleanup."""
    engine, session_factory = get_worker_engine_and_session_factory()
    s3 = get_s3_client()

    try:
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
    finally:
        await engine.dispose()


async def _mark_session_failed(session_id: str, error: str) -> None:
    """Mark an upload session as FAILED with an error message."""
    engine, session_factory = get_worker_engine_and_session_factory()
    try:
        async with session_factory() as db:
            session_repo = UploadSessionRepository(db)
            await session_repo.update_status(
                UUID(session_id),
                UploadSessionStatus.FAILED,
                error=error,
            )
            await db.commit()
    finally:
        await engine.dispose()


async def _mark_import_failed(session_id: str, error: str) -> None:
    """Mark an upload session and its dataset as FAILED after an import error."""
    engine, session_factory = get_worker_engine_and_session_factory()
    try:
        async with session_factory() as db:
            session_repo = UploadSessionRepository(db)
            session = await session_repo.get_by_id(UUID(session_id))
            await session_repo.update_status(
                UUID(session_id),
                UploadSessionStatus.FAILED,
                error=error,
            )
            if session is not None:
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
    - Stale sessions: stuck in UPLOADED or VALIDATING state for more than 24 hours.

    Deletes S3 objects for each orphaned session and marks the session as FAILED.

    Returns:
        Summary dict with expired_sessions_cleaned and stale_sessions_cleaned counts.
    """
    logger.info("Starting orphan upload cleanup")
    return asyncio.run(_run_cleanup())
