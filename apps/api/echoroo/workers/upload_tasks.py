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
from pathlib import Path
from typing import Any
from uuid import UUID

from celery.exceptions import Ignore
from sqlalchemy import select

from echoroo.core import upload_staging
from echoroo.core.s3 import (
    delete_object,
    ensure_configured,
    head_object,
    upload_file_to_object,
)
from echoroo.core.settings import get_settings
from echoroo.models.dataset import Dataset
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
    """Return the staged file for a chunked upload, or None when absent."""
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
            # Plain UUID for everything below: a rollback expires the ORM row.
            session_uuid = UUID(session_id)

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
                session_uuid,
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
                            session_factory, session_uuid, _sha256_of_path, source
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
                                session_uuid,
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

                    await file_repo.update_status(
                        file.id,
                        UploadFileStatus.INVALID,
                        validation_error="No staged bytes for this file",
                    )
                    await db.commit()
                    invalid_count += 1
                    continue

                finally:
                    await session_repo.update_progress(
                        session_uuid, validated_files=valid_count + invalid_count,
                    )
                    await db.commit()

            # Mark session as validated only if it is still being validated.
            transitioned = await session_repo.update_status(
                session_uuid,
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
            # Plain UUID for everything below: a rollback expires the ORM row.
            session_uuid = UUID(session_id)

            if upload_session.status != UploadSessionStatus.VALIDATED:
                # Same rule as validation: only a dead IMPORTING run is failed.
                raise UploadSessionStateError(
                    f"Session {session_id} is in status {upload_session.status.value}, "
                    "expected VALIDATED",
                    mark_failed=upload_session.status == UploadSessionStatus.IMPORTING,
                )

            # CAS transition: VALIDATED -> IMPORTING
            transitioned = await session_repo.update_status(
                session_uuid,
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
                # Dataset before session (the same order as session creation):
                # inserting Recording rows takes a KEY SHARE lock on the dataset
                # through the foreign key, so take it explicitly first or a
                # concurrent create (dataset FOR UPDATE, then session) deadlocks.
                await db.execute(
                    select(Dataset.id).where(Dataset.id == dataset_id).with_for_update(read=True, key_share=True)
                )
                owner = await session_repo.get_for_update(session_uuid)
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
                            # UUID(session_id), not session_uuid: the
                            # rollback above expired the ORM object.
                            upload_staging.session_dir(UUID(session_id)).mkdir(
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
                await session_repo.update_progress(session_uuid, imported_files=imported_count)
                await db.commit()
                pending_recordings.clear()
                pending_file_ids.clear()

            valid_files: list[UploadFile] = await file_repo.get_valid_files(session_uuid)

            async def _process_file(file: UploadFile) -> None:
                """Publish one valid upload file and queue its Recording row."""
                nonlocal failed_count

                recording_id = file.id
                dest_key = file.object_key

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
                        session_factory, session_uuid, _sha256_of_path, clean
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
                        session_factory, session_uuid, upload_file_to_object, clean, dest_key
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
                ownership_lost = False
                try:
                    await _process_file(file)
                except UploadSessionStateError:
                    ownership_lost = True  # the row is no longer ours: no progress tick
                    raise
                finally:
                    if not ownership_lost:
                        await session_repo.update_progress(
                            session_uuid, imported_files=imported_count,
                        )
                        await db.commit()

            # Flush any remaining recordings
            await _flush_batch()

            # Dataset first, then the session CAS: session creation locks the
            # dataset row before the session row, so this transaction must take
            # them in the same order or a concurrent create can deadlock it.
            await dataset_repo.update_import_status(
                dataset_id,
                DatasetStatus.COMPLETED,
                total_files=len(valid_files),
                processed_files=imported_count,
            )
            # Mark the session as imported only if it is still being imported;
            # the dataset update above rolls back with it otherwise.
            transitioned = await session_repo.update_status(
                session_uuid,
                UploadSessionStatus.IMPORTED,
                expected_status=UploadSessionStatus.IMPORTING,
            )
            if not transitioned:
                await db.rollback()
                logger.warning(
                    "Session %s left IMPORTING during import; not marking IMPORTED",
                    session_id,
                )
                raise UploadSessionStateError(
                    f"Session {session_id} left IMPORTING during import",
                    mark_failed=False,
                )
            await db.commit()

            if await _delete_unlinked_publications(db, session_uuid, project_id, dataset_id):
                try:
                    upload_staging.remove_session(session_uuid)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Failed to remove staging directory for imported session %s: %s",
                        session_uuid,
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
        key = file.object_key
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
                """Fail a dead session and only then delete its staged bytes.

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
            # Dataset row before the session row (same order as session
            # creation, which locks dataset → session) to avoid a deadlock.
            dataset_repo = DatasetRepository(db)
            await dataset_repo.update_import_status(
                session.dataset_id,
                DatasetStatus.FAILED,
                error=error,
            )
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
    """Remove orphaned upload sessions and their staged bytes.

    Handles two categories:
    - Expired ISSUED sessions: their inactivity deadline has passed without completion.
    - Stale sessions: stuck in a processing state (UPLOADED / VALIDATING /
      VALIDATED / IMPORTING) with no progress update within
      ``ECHOROO_UPLOAD_STALE_TIMEOUT_SECONDS`` (default 15 min).

    Deletes staged bytes for each orphaned session and marks the session as FAILED.

    Returns:
        Summary dict with expired_sessions_cleaned and stale_sessions_cleaned counts.
    """
    logger.info("Starting orphan upload cleanup")
    return asyncio.run(_run_cleanup())
