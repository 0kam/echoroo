"""Integration coverage for staged upload validation, import, and cleanup."""

from __future__ import annotations

import asyncio
import hashlib
import io
import struct
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
from botocore.exceptions import ClientError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from echoroo.core import upload_staging
from echoroo.core.settings import get_settings
from echoroo.models.dataset import Dataset
from echoroo.models.enums import DatasetStatus, UploadFileStatus, UploadSessionStatus
from echoroo.models.recording import Recording
from echoroo.models.site import Site
from echoroo.models.upload import UploadFile, UploadSession
from echoroo.repositories.upload import UploadSessionRepository
from echoroo.workers import upload_tasks
from tests.conftest import TEST_DATABASE_URL

if TYPE_CHECKING:
    from echoroo.models.project import Project


class _FakeS3:
    """In-memory S3 client implementing the methods used by upload helpers."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.upload_calls: list[dict[str, str]] = []

    def upload_file(self, Filename: str, Bucket: str, Key: str) -> None:  # noqa: N803
        del Bucket
        self.upload_calls.append({"Filename": Filename, "Key": Key})
        self.objects[Key] = Path(Filename).read_bytes()

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        del Bucket
        if Key not in self.objects:
            raise ClientError(
                {"Error": {"Code": "404", "Message": "Not Found"}},
                "HeadObject",
            )
        return {"ContentLength": len(self.objects[Key])}

    def get_object(self, *, Bucket: str, Key: str, **_: Any) -> dict[str, Any]:  # noqa: N803
        del Bucket
        return {"Body": io.BytesIO(self.objects[Key])}

    def copy_object(
        self,
        *,
        Bucket: str,
        CopySource: dict[str, str],
        Key: str,
    ) -> None:  # noqa: N803
        del Bucket
        self.objects[Key] = self.objects[CopySource["Key"]]

    def delete_object(self, *, Bucket: str, Key: str) -> None:  # noqa: N803
        del Bucket
        self.objects.pop(Key, None)

    def get_paginator(self, name: str) -> _FakeS3:
        assert name == "list_objects_v2"
        return self

    def paginate(self, *, Bucket: str, Prefix: str) -> list[dict[str, list[dict[str, str]]]]:
        del Bucket
        contents = [{"Key": key} for key in self.objects if key.startswith(Prefix)]
        return [{"Contents": contents}]

    def delete_objects(
        self,
        *,
        Bucket: str,
        Delete: dict[str, list[dict[str, str]]],
    ) -> dict[str, list[dict[str, str]]]:  # noqa: N803
        del Bucket
        deleted: list[dict[str, str]] = []
        for item in Delete["Objects"]:
            key = item["Key"]
            self.objects.pop(key, None)
            deleted.append({"Key": key})
        return {"Deleted": deleted}


def _worker_engine_and_session_factory() -> tuple[
    AsyncEngine, async_sessionmaker[AsyncSession]
]:
    """Build a fresh worker-style engine bound to the test database."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


def _normal_probe() -> dict[str, Any]:
    return {
        "format": {"duration": "0.1"},
        "streams": [
            {
                "codec_type": "audio",
                "sample_rate": "44100",
                "channels": 1,
                "bits_per_sample": 16,
            }
        ],
    }


def _build_wav_with_fake_gps_chunk() -> bytes:
    """Build a minimal RIFF WAV byte stream containing a fake GPS chunk."""
    chunk_id = b"GPS "
    chunk_payload = b"\x00\x00\x00\x00LAT=35.6;LON=139.7"
    gps_chunk = chunk_id + struct.pack("<I", len(chunk_payload)) + chunk_payload

    fmt_chunk = b"fmt " + struct.pack("<I", 16) + b"\x01\x00" + b"\x01\x00"
    fmt_chunk += struct.pack("<I", 44100) + struct.pack("<I", 88200)
    fmt_chunk += b"\x02\x00" + b"\x10\x00"
    data_chunk = b"data" + struct.pack("<I", 0)

    body = b"WAVE" + fmt_chunk + gps_chunk + data_chunk
    return b"RIFF" + struct.pack("<I", len(body)) + body


@pytest.fixture
async def staged_dataset(
    db_session: AsyncSession,
    test_project: Project,
) -> Dataset:
    """Create a dataset for staged upload task tests."""
    site = Site(
        project_id=test_project.id,
        name="Staged Upload Site",
        h3_index_member="8928308280fffff",
    )
    db_session.add(site)
    await db_session.flush()
    dataset = Dataset(
        project_id=test_project.id,
        site_id=site.id,
        created_by_id=test_project.owner_id,
        name="Staged Upload Dataset",
        audio_dir="/data/audio/staged",
        status=DatasetStatus.COMPLETED,
    )
    db_session.add(dataset)
    await db_session.commit()
    await db_session.refresh(dataset)
    return dataset


@pytest.fixture
def staged_worker_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> _FakeS3:
    """Use a temporary staging root and an in-memory S3 client."""
    monkeypatch.setattr(get_settings(), "UPLOAD_STAGING_DIR", str(tmp_path))
    fake_s3 = _FakeS3()
    monkeypatch.setattr("echoroo.core.s3.get_s3_client", lambda: fake_s3)
    monkeypatch.setattr(
        upload_tasks,
        "get_worker_engine_and_session_factory",
        _worker_engine_and_session_factory,
    )
    monkeypatch.setattr(upload_tasks, "_run_ffprobe", lambda _path: _normal_probe())
    return fake_s3


async def _create_staged_upload(
    db_session: AsyncSession,
    dataset: Dataset,
    owner_id: UUID,
    payload: bytes,
) -> tuple[UUID, UUID]:
    """Create an UPLOADED session and append one complete staged file."""
    session = UploadSession(
        dataset_id=dataset.id,
        created_by_id=owner_id,
        status=UploadSessionStatus.UPLOADED,
        total_files=1,
        total_bytes=len(payload),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)

    file_id = uuid4()
    upload_file = UploadFile(
        id=file_id,
        session_id=session.id,
        original_filename="recording.wav",
        object_key=f"recordings/{dataset.project_id}/{dataset.id}/{file_id}.wav",
        file_size=len(payload),
        declared_size=len(payload),
        received_bytes=0,
        chunk_digests=[],
        checksum_sha256=hashlib.sha256(payload).hexdigest(),
        status=UploadFileStatus.UPLOADED,
    )
    db_session.add(upload_file)
    await db_session.commit()

    received = upload_staging.append_chunk(
        session.id,
        file_id,
        offset=0,
        data=payload,
        declared_size=len(payload),
    )
    upload_file.received_bytes = received
    upload_file.chunk_digests = [hashlib.sha256(payload).hexdigest()]
    await db_session.commit()
    return session.id, file_id


async def _run_task_in_thread(task: Any, session_id: UUID) -> Any:
    """Run an eager Celery task without nesting asyncio.run in the test loop."""
    return await asyncio.to_thread(task.apply, args=[str(session_id)])


async def _get_file_row(db_session: AsyncSession, file_id: UUID) -> tuple[Any, ...]:
    result = await db_session.execute(
        select(
            UploadFile.status,
            UploadFile.validation_error,
            UploadFile.checksum_sha256,
            UploadFile.file_size,
            UploadFile.duration,
            UploadFile.samplerate,
            UploadFile.recording_id,
        ).where(UploadFile.id == file_id)
    )
    return tuple(result.one())


async def test_validate_staged_wav_strips_gps_and_records_clean_metadata(
    db_session: AsyncSession,
    test_project: Project,
    staged_dataset: Dataset,
    staged_worker_env: _FakeS3,
) -> None:
    """Validation writes clean staged bytes and persists their metadata."""
    del staged_worker_env
    raw = _build_wav_with_fake_gps_chunk()
    session_id, file_id = await _create_staged_upload(
        db_session, staged_dataset, test_project.owner_id, raw
    )

    await _run_task_in_thread(upload_tasks.validate_upload_session, session_id)

    clean_path = upload_staging.session_dir(session_id) / f"{file_id}.clean"
    clean = clean_path.read_bytes()
    row = await _get_file_row(db_session, file_id)
    session_row = await db_session.execute(
        select(UploadSession.status, UploadSession.validated_files).where(
            UploadSession.id == session_id
        )
    )
    session_status, validated_files = session_row.one()

    assert row[0] == UploadFileStatus.VALID
    assert row[1] is None
    assert row[2] == hashlib.sha256(clean).hexdigest()
    assert b"GPS " not in clean
    assert row[3] == len(clean)
    assert row[4] == 0.1
    assert row[5] == 44100
    assert session_status == UploadSessionStatus.VALIDATED
    assert validated_files == 1


async def test_validate_staged_missing_file_is_invalid_and_session_still_validated(
    db_session: AsyncSession,
    test_project: Project,
    staged_dataset: Dataset,
    staged_worker_env: _FakeS3,
) -> None:
    """A missing staged part is counted by the validation heartbeat."""
    del staged_worker_env
    raw = _build_wav_with_fake_gps_chunk()
    session_id, file_id = await _create_staged_upload(
        db_session, staged_dataset, test_project.owner_id, raw
    )
    upload_staging.part_path(session_id, file_id).unlink()

    await _run_task_in_thread(upload_tasks.validate_upload_session, session_id)

    row = await _get_file_row(db_session, file_id)
    session_row = await db_session.execute(
        select(UploadSession.status, UploadSession.validated_files).where(
            UploadSession.id == session_id
        )
    )
    session_status, validated_files = session_row.one()
    assert row[0] == UploadFileStatus.INVALID
    assert row[1] == "Staged file missing or truncated"
    assert session_status == UploadSessionStatus.VALIDATED
    assert validated_files == 1


@pytest.mark.asyncio
async def test_validate_rejects_legacy_object_key_without_hashing_or_sanitising(
    db_session: AsyncSession,
    test_project: Project,
    staged_dataset: Dataset,
    staged_worker_env: _FakeS3,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Validation rejects staged bytes stored under the legacy object key."""
    del staged_worker_env
    raw = _build_wav_with_fake_gps_chunk()
    session_id, file_id = await _create_staged_upload(
        db_session, staged_dataset, test_project.owner_id, raw
    )
    await db_session.execute(
        update(UploadFile)
        .where(UploadFile.id == file_id)
        .values(
            object_key=f"uploads/{file_id}.wav",
            status=UploadFileStatus.UPLOADED,
        )
    )
    await db_session.commit()

    monkeypatch.setattr(
        upload_tasks,
        "_sha256_of_path",
        lambda *_args: pytest.fail("legacy object key must not be hashed"),
    )
    monkeypatch.setattr(
        upload_tasks,
        "_sanitize_to_clean",
        lambda *_args: pytest.fail("legacy object key must not be sanitised"),
    )

    await _run_task_in_thread(upload_tasks.validate_upload_session, session_id)

    row = await _get_file_row(db_session, file_id)
    assert row[0] == UploadFileStatus.INVALID
    assert row[1] == "Legacy upload key; upload the file again"
    assert not (upload_staging.session_dir(session_id) / f"{file_id}.clean").exists()


@pytest.mark.asyncio
async def test_import_rejects_legacy_file_without_staged_bytes_or_s3_access(
    db_session: AsyncSession,
    test_project: Project,
    staged_dataset: Dataset,
    staged_worker_env: _FakeS3,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Import invalidates a pre-slice-2e file instead of creating a recording."""
    raw = _build_wav_with_fake_gps_chunk()
    session_id, file_id = await _create_staged_upload(
        db_session, staged_dataset, test_project.owner_id, raw
    )
    await db_session.execute(
        update(UploadSession)
        .where(UploadSession.id == session_id)
        .values(status=UploadSessionStatus.VALIDATED)
    )
    await db_session.execute(
        update(UploadFile)
        .where(UploadFile.id == file_id)
        .values(
            object_key=f"uploads/{file_id}.wav",
            received_bytes=0,
            status=UploadFileStatus.VALID,
        )
    )
    await db_session.commit()
    upload_staging.part_path(session_id, file_id).unlink()

    monkeypatch.setattr(
        upload_tasks,
        "upload_file_to_object",
        lambda *_args, **_kwargs: pytest.fail("legacy file must not be uploaded"),
    )
    monkeypatch.setattr(
        upload_tasks,
        "head_object",
        lambda *_args, **_kwargs: pytest.fail("legacy file must not be checked in S3"),
    )

    result = await _run_task_in_thread(upload_tasks.import_from_upload_session, session_id)

    assert result.get()["failed_files"] == 1
    row = await _get_file_row(db_session, file_id)
    recording_count = await db_session.scalar(
        select(Recording.id).where(Recording.dataset_id == staged_dataset.id)
    )
    assert row[0] == UploadFileStatus.INVALID
    assert row[1] == "No staged bytes; upload the file again"
    assert recording_count is None
    assert staged_worker_env.upload_calls == []


async def test_import_staged_file_publishes_once_and_removes_staging(
    db_session: AsyncSession,
    test_project: Project,
    staged_dataset: Dataset,
    staged_worker_env: _FakeS3,
) -> None:
    """Import uploads the clean staged file once and removes its directory."""
    raw = _build_wav_with_fake_gps_chunk()
    session_id, file_id = await _create_staged_upload(
        db_session, staged_dataset, test_project.owner_id, raw
    )
    await _run_task_in_thread(upload_tasks.validate_upload_session, session_id)
    clean_path = upload_staging.session_dir(session_id) / f"{file_id}.clean"
    clean_size = clean_path.stat().st_size

    await _run_task_in_thread(upload_tasks.import_from_upload_session, session_id)

    assert len(staged_worker_env.upload_calls) == 1
    upload_call = staged_worker_env.upload_calls[0]
    object_key_result = await db_session.execute(
        select(UploadFile.object_key).where(UploadFile.id == file_id)
    )
    file_object_key = object_key_result.scalar_one()
    assert upload_call["Key"].startswith(
        f"recordings/{staged_dataset.project_id}/{staged_dataset.id}/"
    )
    assert upload_call["Key"].endswith(".wav")
    assert len(staged_worker_env.objects[upload_call["Key"]]) == clean_size

    file_row = await _get_file_row(db_session, file_id)
    recording_result = await db_session.execute(
        select(Recording.path).where(Recording.dataset_id == staged_dataset.id)
    )
    paths = list(recording_result.scalars())
    session_result = await db_session.execute(
        select(UploadSession.status).where(UploadSession.id == session_id)
    )
    assert len(paths) == 1
    assert paths[0] == upload_call["Key"]
    assert file_row[0] == UploadFileStatus.IMPORTED
    assert file_row[6] is not None
    assert session_result.scalar_one() == UploadSessionStatus.IMPORTED
    assert not upload_staging.session_dir(session_id).exists()
    # Deterministic destination: the recording id is the upload file id, so a
    # republish after a crash would overwrite the same key.
    assert upload_call["Key"] == file_object_key

    # Duplicate deliveries after completion are harmless: the terminal state,
    # the dataset and the published object are left alone.
    await _run_task_in_thread(upload_tasks.import_from_upload_session, session_id)
    await _run_task_in_thread(upload_tasks.validate_upload_session, session_id)
    session_result = await db_session.execute(
        select(UploadSession.status, UploadSession.error).where(UploadSession.id == session_id)
    )
    status_after, error_after = session_result.one()
    assert status_after == UploadSessionStatus.IMPORTED
    assert error_after is None
    assert len(staged_worker_env.upload_calls) == 1


async def test_import_refuses_tampered_clean_file(
    db_session: AsyncSession,
    test_project: Project,
    staged_dataset: Dataset,
    staged_worker_env: _FakeS3,
) -> None:
    """Import rejects a clean staged file whose same-length bytes were changed."""
    raw = _build_wav_with_fake_gps_chunk()
    session_id, file_id = await _create_staged_upload(
        db_session, staged_dataset, test_project.owner_id, raw
    )
    await _run_task_in_thread(upload_tasks.validate_upload_session, session_id)
    clean_path = upload_staging.session_dir(session_id) / f"{file_id}.clean"
    clean_path.write_bytes(b"x" * clean_path.stat().st_size)

    await _run_task_in_thread(upload_tasks.import_from_upload_session, session_id)

    file_row = await _get_file_row(db_session, file_id)
    recording_count = await db_session.scalar(
        select(Recording.id).where(Recording.dataset_id == staged_dataset.id)
    )
    assert file_row[0] == UploadFileStatus.INVALID
    assert file_row[1] == "Checksum mismatch at import"
    assert staged_worker_env.upload_calls == []
    assert recording_count is None


async def test_validate_does_not_resurrect_force_failed_session(
    db_session: AsyncSession,
    test_project: Project,
    staged_dataset: Dataset,
    staged_worker_env: _FakeS3,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A force-fail during validation wins over the worker's final CAS."""
    del staged_worker_env
    raw = _build_wav_with_fake_gps_chunk()
    session_id, _file_id = await _create_staged_upload(
        db_session, staged_dataset, test_project.owner_id, raw
    )
    first_probe = True

    def force_fail_then_probe(_path: str) -> dict[str, Any]:
        nonlocal first_probe
        if first_probe:
            first_probe = False

            async def mark_failed() -> None:
                engine, factory = _worker_engine_and_session_factory()
                try:
                    async with factory() as worker_db:
                        await worker_db.execute(
                            update(UploadSession)
                            .where(UploadSession.id == session_id)
                            .values(status=UploadSessionStatus.FAILED)
                        )
                        await worker_db.commit()
                finally:
                    await engine.dispose()

            thread = threading.Thread(target=lambda: asyncio.run(mark_failed()))
            thread.start()
            thread.join()
        return _normal_probe()

    monkeypatch.setattr(upload_tasks, "_run_ffprobe", force_fail_then_probe)
    result = await _run_task_in_thread(upload_tasks.validate_upload_session, session_id)

    status_result = await db_session.execute(
        select(UploadSession.status).where(UploadSession.id == session_id)
    )
    assert result.state == "IGNORED"
    assert status_result.scalar_one() == UploadSessionStatus.FAILED


async def test_cleanup_removes_staging_of_terminal_and_unknown_sessions(
    db_session: AsyncSession,
    test_project: Project,
    staged_dataset: Dataset,
    staged_worker_env: _FakeS3,
) -> None:
    """The staging janitor removes terminal/unknown directories only."""
    del staged_worker_env
    session_ids: dict[UploadSessionStatus, UUID] = {}
    for status in (UploadSessionStatus.IMPORTED, UploadSessionStatus.FAILED, UploadSessionStatus.ISSUED):
        session = UploadSession(
            dataset_id=staged_dataset.id,
            created_by_id=test_project.owner_id,
            status=status,
            total_files=0,
            total_bytes=0,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        db_session.add(session)
        await db_session.flush()
        session_ids[status] = session.id
    await db_session.commit()

    for session_id in session_ids.values():
        upload_staging.session_dir(session_id).mkdir(parents=True)
    unknown_id = uuid4()
    upload_staging.session_dir(unknown_id).mkdir(parents=True)

    result = await asyncio.to_thread(upload_tasks.cleanup_orphan_uploads.apply)
    summary = result.get()

    assert summary["orphaned_dirs"] == 3
    assert not upload_staging.session_dir(session_ids[UploadSessionStatus.IMPORTED]).exists()
    assert not upload_staging.session_dir(session_ids[UploadSessionStatus.FAILED]).exists()
    assert not upload_staging.session_dir(unknown_id).exists()
    assert upload_staging.session_dir(session_ids[UploadSessionStatus.ISSUED]).exists()


@pytest.mark.asyncio
async def test_cleanup_does_not_reap_a_session_that_came_back_to_life(
    db_session: AsyncSession,
    test_project: Project,
    staged_dataset: Dataset,
    staged_worker_env: _FakeS3,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale candidate whose heartbeat moved after selection is left alone."""
    raw = _build_wav_with_fake_gps_chunk()
    session_id, _file_id = await _create_staged_upload(
        db_session, staged_dataset, test_project.owner_id, raw
    )
    stale_at = datetime.now(UTC) - timedelta(hours=2)
    await db_session.execute(
        update(UploadSession)
        .where(UploadSession.id == session_id)
        .values(status=UploadSessionStatus.VALIDATING, updated_at=stale_at)
    )
    await db_session.commit()

    real_get_stale = UploadSessionRepository.get_stale_sessions

    async def revived_between_select_and_claim(self: Any, *args: Any, **kwargs: Any) -> Any:
        candidates = await real_get_stale(self, *args, **kwargs)
        # Simulate the worker heartbeating right after the reaper picked it.
        await db_session.execute(
            update(UploadSession)
            .where(UploadSession.id == session_id)
            .values(updated_at=datetime.now(UTC))
        )
        await db_session.commit()
        return candidates

    monkeypatch.setattr(UploadSessionRepository, "get_stale_sessions", revived_between_select_and_claim)

    await asyncio.to_thread(upload_tasks.cleanup_orphan_uploads.apply)

    result = await db_session.execute(
        select(UploadSession.status).where(UploadSession.id == session_id)
    )
    assert result.scalar_one() == UploadSessionStatus.VALIDATING
    assert upload_staging.session_dir(session_id).exists()


@pytest.mark.asyncio
async def test_duplicate_validate_after_validated_is_harmless(
    db_session: AsyncSession,
    test_project: Project,
    staged_dataset: Dataset,
    staged_worker_env: _FakeS3,
) -> None:
    raw = _build_wav_with_fake_gps_chunk()
    session_id, _file_id = await _create_staged_upload(
        db_session, staged_dataset, test_project.owner_id, raw
    )
    await _run_task_in_thread(upload_tasks.validate_upload_session, session_id)
    await _run_task_in_thread(upload_tasks.validate_upload_session, session_id)

    result = await db_session.execute(
        select(UploadSession.status, UploadSession.error).where(UploadSession.id == session_id)
    )
    status_after, error_after = result.one()
    assert status_after == UploadSessionStatus.VALIDATED
    assert error_after is None


@pytest.mark.asyncio
async def test_import_deletes_object_when_stored_size_mismatches(
    db_session: AsyncSession,
    test_project: Project,
    staged_dataset: Dataset,
    staged_worker_env: _FakeS3,
) -> None:
    raw = _build_wav_with_fake_gps_chunk()
    session_id, file_id = await _create_staged_upload(
        db_session, staged_dataset, test_project.owner_id, raw
    )
    await _run_task_in_thread(upload_tasks.validate_upload_session, session_id)

    real_head = staged_worker_env.head_object

    def short_head(**kwargs: Any) -> dict[str, Any]:
        response = real_head(**kwargs)
        return {**response, "ContentLength": response["ContentLength"] - 1}

    staged_worker_env.head_object = short_head  # type: ignore[method-assign]
    await _run_task_in_thread(upload_tasks.import_from_upload_session, session_id)

    file_row = await _get_file_row(db_session, file_id)
    assert file_row[0] == UploadFileStatus.INVALID
    assert not any(key.startswith("recordings/") for key in staged_worker_env.objects)
