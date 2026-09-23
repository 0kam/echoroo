"""Contract coverage for resumable upload chunks and session controls."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core import s3, upload_staging
from echoroo.core.settings import get_settings
from echoroo.models.dataset import Dataset
from echoroo.models.enums import DatasetStatus, UploadFileStatus, UploadSessionStatus
from echoroo.models.site import Site
from echoroo.models.upload import UploadFile, UploadSession
from echoroo.schemas.upload import ChunkAcceptedResponse
from echoroo.services.upload import UploadService
from tests.contract.conftest import bff_session_headers

if TYPE_CHECKING:
    from echoroo.models.project import Project
    from echoroo.models.user import User


@pytest.fixture
async def test_site(
    db_session: AsyncSession,
    test_project: Project,
) -> Site:
    """Create a site for the upload dataset."""
    site = Site(
        project_id=test_project.id,
        name="Chunk Upload Test Site",
        h3_index_member="8928308280fffff",
    )
    db_session.add(site)
    await db_session.commit()
    await db_session.refresh(site)
    return site


@pytest.fixture
async def test_dataset(
    db_session: AsyncSession,
    test_project: Project,
    test_site: Site,
) -> Dataset:
    """Create a completed dataset for upload-session tests."""
    dataset = Dataset(
        project_id=test_project.id,
        site_id=test_site.id,
        created_by_id=test_project.owner_id,
        name="Chunk Upload Test Dataset",
        audio_dir="/data/audio/chunk-test",
        status=DatasetStatus.COMPLETED,
    )
    db_session.add(dataset)
    await db_session.commit()
    await db_session.refresh(dataset)
    return dataset


def _upload_url(project_id: str, dataset_id: UUID, session_id: str, file_id: str) -> str:
    return (
        f"/web-api/v1/projects/{project_id}/datasets/{dataset_id}/"
        f"upload-sessions/{session_id}/files/{file_id}/chunks"
    )


def _session_url(project_id: str, dataset_id: UUID) -> str:
    return (
        f"/web-api/v1/projects/{project_id}/datasets/{dataset_id}/upload-sessions"
    )


async def _create_session(
    client: AsyncClient,
    headers: dict[str, str],
    project_id: str,
    dataset_id: UUID,
    files: list[dict[str, object]],
) -> tuple[str, list[dict[str, str]]]:
    response = await client.post(
        _session_url(project_id, dataset_id),
        headers=headers,
        json={"files": files},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return body["session_id"], body["files"]


def _mock_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep contract tests independent of S3."""
    monkeypatch.setattr(s3, "ensure_bucket_exists", lambda: None)


def _stub_validation_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep completion tests independent of a Celery broker."""
    from echoroo.workers import upload_tasks

    monkeypatch.setattr(
        upload_tasks.validate_upload_session,
        "delay",
        lambda *_args, **_kwargs: None,
    )


@pytest.mark.asyncio
async def test_chunk_append_retry_checksum_and_staging_reconcile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    client: AsyncClient,
    csrf_headers: dict[str, str],
    test_project_id: str,
    test_dataset: Dataset,
    db_session: AsyncSession,
) -> None:
    """Chunks append at the DB offset, preserve digests, and reconcile excess bytes."""
    _mock_storage(monkeypatch)
    settings = get_settings()
    monkeypatch.setattr(settings, "UPLOAD_STAGING_DIR", str(tmp_path))

    session_id, files = await _create_session(
        client,
        csrf_headers,
        test_project_id,
        test_dataset.id,
        [{"filename": "recording.wav", "size": 20}],
    )
    file_id = files[0]["file_id"]
    url = _upload_url(test_project_id, test_dataset.id, session_id, file_id)

    first = await client.put(f"{url}?offset=0", headers=csrf_headers, content=b"12345678")
    assert first.status_code == 200
    assert first.json() == {
        "file_id": file_id,
        "received_bytes": 8,
        "complete": False,
    }
    path = upload_staging.part_path(UUID(session_id), UUID(file_id))
    assert path.read_bytes() == b"12345678"

    second_data = b"abcdefghijkl"
    second = await client.put(
        f"{url}?offset=8",
        headers={
            **csrf_headers,
            "X-Chunk-SHA256": hashlib.sha256(second_data).hexdigest(),
        },
        content=second_data,
    )
    assert second.status_code == 200
    assert second.json()["complete"] is True
    assert path.read_bytes() == b"12345678abcdefghijkl"

    retry = await client.put(f"{url}?offset=8", headers=csrf_headers, content=second_data)
    assert retry.status_code == 409
    assert retry.json()["detail"]["detail"] == "File already complete"
    assert retry.json()["detail"]["received_bytes"] == 20

    result = await db_session.execute(select(UploadFile).where(UploadFile.id == UUID(file_id)))
    upload_file = result.scalar_one()
    assert upload_file.status == UploadFileStatus.UPLOADED
    assert len(upload_file.chunk_digests) == 2

    # A crash after writing but before committing leaves excess staged bytes.
    fresh_session_id, fresh_files = await _create_session(
        client,
        csrf_headers,
        test_project_id,
        test_dataset.id,
        [{"filename": "reconcile.wav", "size": 10}],
    )
    fresh_file_id = fresh_files[0]["file_id"]
    fresh_url = _upload_url(
        test_project_id, test_dataset.id, fresh_session_id, fresh_file_id
    )
    first_fresh = await client.put(
        f"{fresh_url}?offset=0", headers=csrf_headers, content=b"abc"
    )
    assert first_fresh.status_code == 200
    fresh_path = upload_staging.part_path(UUID(fresh_session_id), UUID(fresh_file_id))
    with fresh_path.open("ab") as staged_file:
        staged_file.write(b"crash-excess")
    resumed = await client.put(
        f"{fresh_url}?offset=3", headers=csrf_headers, content=b"de"
    )
    assert resumed.status_code == 200
    assert fresh_path.read_bytes() == b"abcde"


@pytest.mark.asyncio
async def test_chunk_conflicts_limits_and_authentication(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
    other_user: User,
    auth_headers: dict[str, str],
    test_project_id: str,
    test_dataset: Dataset,
) -> None:
    """Wrong offsets, checksums, size limits, and BFF auth failures are explicit.

    Sessions are built inline: the client has one cookie jar, so two users'
    sessions cannot coexist as fixtures (the second would 419 the first).
    """
    csrf_headers = await bff_session_headers(client, db_session, test_user)
    _mock_storage(monkeypatch)
    settings = get_settings()
    monkeypatch.setattr(settings, "UPLOAD_STAGING_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "UPLOAD_CHUNK_SIZE", 8)
    session_id, files = await _create_session(
        client,
        csrf_headers,
        test_project_id,
        test_dataset.id,
        [{"filename": "small.wav", "size": 20}],
    )
    url = _upload_url(test_project_id, test_dataset.id, session_id, files[0]["file_id"])

    wrong_offset = await client.put(f"{url}?offset=3", headers=csrf_headers, content=b"abc")
    assert wrong_offset.status_code == 409
    assert wrong_offset.json()["detail"]["received_bytes"] == 0

    mismatch = await client.put(
        f"{url}?offset=0",
        headers={**csrf_headers, "X-Chunk-SHA256": "0" * 64},
        content=b"abc",
    )
    assert mismatch.status_code == 422
    assert mismatch.json()["detail"] == "Chunk checksum mismatch"

    correct = await client.put(
        f"{url}?offset=0",
        headers={
            **csrf_headers,
            "X-Chunk-SHA256": hashlib.sha256(b"abc").hexdigest(),
        },
        content=b"abc",
    )
    assert correct.status_code == 200

    too_large = await client.put(
        f"{url}?offset=3", headers=csrf_headers, content=b"123456789"
    )
    assert too_large.status_code == 413

    other_session_id, other_files = await _create_session(
        client,
        csrf_headers,
        test_project_id,
        test_dataset.id,
        [{"filename": "declared.wav", "size": 4}],
    )
    other_url = _upload_url(
        test_project_id, test_dataset.id, other_session_id, other_files[0]["file_id"]
    )
    declared_overflow = await client.put(
        f"{other_url}?offset=0", headers=csrf_headers, content=b"12345"
    )
    assert declared_overflow.status_code == 413

    csrf_headers_other = await bff_session_headers(client, db_session, other_user)
    forbidden = await client.put(
        f"{url}?offset=3", headers=csrf_headers_other, content=b"abc"
    )
    assert forbidden.status_code == 403
    client.cookies.clear()
    assert (await client.put(f"{url}?offset=3", content=b"abc")).status_code == 401
    csrf_headers = await bff_session_headers(client, db_session, test_user)
    csrf_missing = {key: value for key, value in csrf_headers.items() if key != "X-CSRF-Token"}
    assert (await client.put(f"{url}?offset=3", headers=csrf_missing, content=b"abc")).status_code == 403
    assert auth_headers


@pytest.mark.asyncio
async def test_active_session_cancel_and_status_progress(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    client: AsyncClient,
    csrf_headers: dict[str, str],
    test_project_id: str,
    test_dataset: Dataset,
    db_session: AsyncSession,
) -> None:
    """Active resume returns staged byte counts and cancel removes staging."""
    _mock_storage(monkeypatch)
    settings = get_settings()
    monkeypatch.setattr(settings, "UPLOAD_STAGING_DIR", str(tmp_path))
    session_id, files = await _create_session(
        client,
        csrf_headers,
        test_project_id,
        test_dataset.id,
        [{"filename": "resume.wav", "size": 10}],
    )
    file_id = files[0]["file_id"]
    chunk_url = _upload_url(test_project_id, test_dataset.id, session_id, file_id)
    assert (
        await client.put(f"{chunk_url}?offset=0", headers=csrf_headers, content=b"1234")
    ).status_code == 200

    active_url = f"{_session_url(test_project_id, test_dataset.id)}/active"
    active = await client.get(active_url, headers=csrf_headers)
    assert active.status_code == 200
    assert active.json()["session"]["files"][0]["received_bytes"] == 4

    cancel_url = f"{_session_url(test_project_id, test_dataset.id)}/{session_id}/cancel"
    cancelled = await client.post(cancel_url, headers=csrf_headers)
    assert cancelled.status_code == 204
    assert not upload_staging.session_dir(UUID(session_id)).exists()

    result = await db_session.execute(
        select(UploadSession).where(UploadSession.id == UUID(session_id))
    )
    assert result.scalar_one().status == UploadSessionStatus.FAILED
    active_after = await client.get(active_url, headers=csrf_headers)
    assert active_after.status_code == 200
    assert active_after.json()["session"] is None


@pytest.mark.asyncio
async def test_active_exposes_chunk_digests(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    client: AsyncClient,
    csrf_headers: dict[str, str],
    test_project_id: str,
    test_dataset: Dataset,
) -> None:
    """Active-session status exposes the digest of every staged chunk."""
    _mock_storage(monkeypatch)
    settings = get_settings()
    monkeypatch.setattr(settings, "UPLOAD_STAGING_DIR", str(tmp_path))
    session_id, files = await _create_session(
        client,
        csrf_headers,
        test_project_id,
        test_dataset.id,
        [{"filename": "digests.wav", "size": 8}],
    )
    url = _upload_url(test_project_id, test_dataset.id, session_id, files[0]["file_id"])
    chunks = [b"1234", b"5678"]
    for offset, chunk in ((0, chunks[0]), (4, chunks[1])):
        response = await client.put(
            f"{url}?offset={offset}", headers=csrf_headers, content=chunk
        )
        assert response.status_code == 200

    active = await client.get(
        f"{_session_url(test_project_id, test_dataset.id)}/active",
        headers=csrf_headers,
    )
    assert active.status_code == 200
    assert active.json()["session"]["files"][0]["chunk_digests"] == [
        hashlib.sha256(chunk).hexdigest() for chunk in chunks
    ]


@pytest.mark.asyncio
async def test_restart_resets_a_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    client: AsyncClient,
    csrf_headers: dict[str, str],
    test_project_id: str,
    test_dataset: Dataset,
) -> None:
    """A digest mismatch can restart one file from offset zero."""
    _mock_storage(monkeypatch)
    settings = get_settings()
    monkeypatch.setattr(settings, "UPLOAD_STAGING_DIR", str(tmp_path))
    session_id, files = await _create_session(
        client,
        csrf_headers,
        test_project_id,
        test_dataset.id,
        [{"filename": "restart.wav", "size": 8}],
    )
    file_id = files[0]["file_id"]
    url = _upload_url(test_project_id, test_dataset.id, session_id, file_id)
    first = b"old!"
    new = b"new!"
    assert (
        await client.put(f"{url}?offset=0", headers=csrf_headers, content=first)
    ).status_code == 200

    restarted = await client.put(
        f"{url}?offset=0&restart=true", headers=csrf_headers, content=new
    )
    assert restarted.status_code == 200
    assert restarted.json()["received_bytes"] == len(new)
    assert upload_staging.part_path(UUID(session_id), UUID(file_id)).read_bytes() == new

    active = await client.get(
        f"{_session_url(test_project_id, test_dataset.id)}/active",
        headers=csrf_headers,
    )
    assert active.status_code == 200
    file_status = active.json()["session"]["files"][0]
    assert len(file_status["chunk_digests"]) == 1

    invalid_restart = await client.put(
        f"{url}?offset=4&restart=true", headers=csrf_headers, content=b"tail"
    )
    assert invalid_restart.status_code == 422
    assert invalid_restart.json()["detail"] == "restart requires offset=0"


@pytest.mark.asyncio
async def test_active_session_is_owner_scoped(
    monkeypatch: pytest.MonkeyPatch,
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
    other_user: User,
    member_user: User,
    test_member: object,
    test_project_id: str,
    test_dataset: Dataset,
) -> None:
    """The active-session lookup never exposes another caller's session."""
    _mock_storage(monkeypatch)
    csrf_headers = await bff_session_headers(client, db_session, test_user)
    session_id, _ = await _create_session(
        client,
        csrf_headers,
        test_project_id,
        test_dataset.id,
        [{"filename": "owner.wav", "size": 4}],
    )
    csrf_headers_other = await bff_session_headers(client, db_session, other_user)
    response = await client.get(
        f"{_session_url(test_project_id, test_dataset.id)}/active",
        headers=csrf_headers_other,
    )
    assert response.status_code == 403
    member_headers = await bff_session_headers(client, db_session, member_user)
    member_response = await client.get(
        f"{_session_url(test_project_id, test_dataset.id)}/active",
        headers=member_headers,
    )
    # Decision 5: members cannot upload at all, so the resume lookup is 403 for them.
    assert member_response.status_code == 403
    assert test_member
    assert session_id


@pytest.mark.asyncio
async def test_create_conflicts_with_another_users_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
    admin_user: User,
    test_admin_member: object,
    test_project_id: str,
    test_dataset: Dataset,
) -> None:
    """Only the session owner may supersede an unfinished upload."""
    _mock_storage(monkeypatch)
    settings = get_settings()
    monkeypatch.setattr(settings, "UPLOAD_STAGING_DIR", str(tmp_path))
    owner_headers = await bff_session_headers(client, db_session, test_user)
    session_id, files = await _create_session(
        client,
        owner_headers,
        test_project_id,
        test_dataset.id,
        [{"filename": "conflict.wav", "size": 8}],
    )
    chunk_url = _upload_url(test_project_id, test_dataset.id, session_id, files[0]["file_id"])
    uploaded = await client.put(
        f"{chunk_url}?offset=0", headers=owner_headers, content=b"1234"
    )
    assert uploaded.status_code == 200

    admin_headers = await bff_session_headers(client, db_session, admin_user)
    conflict = await client.post(
        _session_url(test_project_id, test_dataset.id),
        headers=admin_headers,
        json={"files": [{"filename": "admin.wav", "size": 4}]},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "Another user has an unfinished upload for this dataset"

    owner_headers = await bff_session_headers(client, db_session, test_user)
    replacement = await client.post(
        _session_url(test_project_id, test_dataset.id),
        headers=owner_headers,
        json={"files": [{"filename": "replacement.wav", "size": 4}]},
    )
    assert replacement.status_code == 201

    result = await db_session.execute(
        select(UploadSession).where(UploadSession.id == UUID(session_id))
    )
    assert result.scalar_one().status == UploadSessionStatus.FAILED
    assert not upload_staging.session_dir(UUID(session_id)).exists()
    assert test_admin_member


@pytest.mark.asyncio
async def test_complete_skip_missing_and_preserves_missing_retry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    client: AsyncClient,
    csrf_headers: dict[str, str],
    test_project_id: str,
    test_dataset: Dataset,
    db_session: AsyncSession,
) -> None:
    """Partial completion skips untouched files, while the default stays resumable."""
    _mock_storage(monkeypatch)
    _stub_validation_dispatch(monkeypatch)
    settings = get_settings()
    monkeypatch.setattr(settings, "UPLOAD_STAGING_DIR", str(tmp_path))

    session_id, files = await _create_session(
        client,
        csrf_headers,
        test_project_id,
        test_dataset.id,
        [
            {"filename": "complete.wav", "size": 4},
            {"filename": "skip.wav", "size": 5},
        ],
    )
    complete_url = f"{_session_url(test_project_id, test_dataset.id)}/{session_id}/complete"
    chunk_url = _upload_url(
        test_project_id, test_dataset.id, session_id, files[0]["file_id"]
    )
    assert (
        await client.put(f"{chunk_url}?offset=0", headers=csrf_headers, content=b"done")
    ).status_code == 200
    completed = await client.post(
        complete_url,
        headers=csrf_headers,
        json={"skip_missing": True},
    )
    assert completed.status_code == 202
    assert completed.json()["skipped_files"] == 1
    assert completed.json()["status"] == "uploaded"

    result = await db_session.execute(
        select(UploadFile).where(UploadFile.session_id == UUID(session_id))
    )
    assert {file.status for file in result.scalars().all()} == {
        UploadFileStatus.UPLOADED,
        UploadFileStatus.SKIPPED,
    }

    missing_session_id, missing_files = await _create_session(
        client,
        csrf_headers,
        test_project_id,
        test_dataset.id,
        [
            {"filename": "present-on-retry.wav", "size": 4},
            {"filename": "missing.wav", "size": 4},
        ],
    )
    missing_chunk_url = _upload_url(
        test_project_id, test_dataset.id, missing_session_id, missing_files[0]["file_id"]
    )
    assert (
        await client.put(
            f"{missing_chunk_url}?offset=0",
            headers=csrf_headers,
            content=b"done",
        )
    ).status_code == 200
    missing_complete = await client.post(
        f"{_session_url(test_project_id, test_dataset.id)}/{missing_session_id}/complete",
        headers=csrf_headers,
    )
    assert missing_complete.status_code == 202
    assert missing_complete.json()["missing_files"] == 1
    assert missing_complete.json()["status"] == "issued"

    all_skipped_id, _ = await _create_session(
        client,
        csrf_headers,
        test_project_id,
        test_dataset.id,
        [{"filename": "all-missing.wav", "size": 4}],
    )
    all_skipped = await client.post(
        f"{_session_url(test_project_id, test_dataset.id)}/{all_skipped_id}/complete",
        headers=csrf_headers,
        json={"skip_missing": True},
    )
    assert all_skipped.status_code == 409
    assert all_skipped.json()["detail"] == "No files were uploaded"


@pytest.mark.asyncio
async def test_chunk_admission_limit_returns_retry_after(
    monkeypatch: pytest.MonkeyPatch,
    client: AsyncClient,
    csrf_headers: dict[str, str],
    test_project_id: str,
    test_dataset: Dataset,
) -> None:
    """At most the configured number of per-user chunk calls are admitted."""
    _mock_storage(monkeypatch)
    settings = get_settings()
    monkeypatch.setattr(settings, "UPLOAD_MAX_CONCURRENT_CHUNKS_PER_USER", 1)
    session_id, files = await _create_session(
        client,
        csrf_headers,
        test_project_id,
        test_dataset.id,
        [{"filename": "concurrent.wav", "size": 10}],
    )
    url = _upload_url(test_project_id, test_dataset.id, session_id, files[0]["file_id"])

    async def slow_append(self: UploadService, *args: object, **kwargs: object) -> dict[str, object]:
        await asyncio.sleep(0.05)
        return {"file_id": str(files[0]["file_id"]), "received_bytes": 1, "complete": False}

    monkeypatch.setattr(UploadService, "append_chunk", slow_append)
    responses = await asyncio.gather(
        client.put(f"{url}?offset=0", headers=csrf_headers, content=b"a"),
        client.put(f"{url}?offset=0", headers=csrf_headers, content=b"b"),
    )
    statuses = sorted(response.status_code for response in responses)
    assert statuses == [200, 429]
    limited = next(response for response in responses if response.status_code == 429)
    assert limited.headers["Retry-After"] == "1"


@pytest.mark.asyncio
async def test_upload_file_status_exposes_declared_and_received_bytes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    client: AsyncClient,
    csrf_headers: dict[str, str],
    test_project_id: str,
    test_dataset: Dataset,
) -> None:
    """Status polling includes the resumable transfer counters."""
    _mock_storage(monkeypatch)
    settings = get_settings()
    monkeypatch.setattr(settings, "UPLOAD_STAGING_DIR", str(tmp_path))
    session_id, files = await _create_session(
        client,
        csrf_headers,
        test_project_id,
        test_dataset.id,
        [{"filename": "status.wav", "size": 20}],
    )
    url = _upload_url(test_project_id, test_dataset.id, session_id, files[0]["file_id"])
    await client.put(f"{url}?offset=0", headers=csrf_headers, content=b"1234")
    response = await client.get(
        f"{_session_url(test_project_id, test_dataset.id)}/{session_id}",
        headers=csrf_headers,
    )
    assert response.status_code == 200
    file_status = response.json()["files"][0]
    assert file_status["declared_size"] == 20
    assert file_status["received_bytes"] == 4


def test_chunk_response_schema_has_stable_shape() -> None:
    """Keep the accepted-chunk contract explicit for clients."""
    response = ChunkAcceptedResponse(file_id="file", received_bytes=1, complete=False)
    assert response.model_dump() == {
        "file_id": "file",
        "received_bytes": 1,
        "complete": False,
    }


@pytest.mark.asyncio
async def test_concurrent_same_offset_chunks_never_truncate_committed_bytes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    client: AsyncClient,
    csrf_headers: dict[str, str],
    test_project_id: str,
    test_dataset: Dataset,
) -> None:
    """Two requests for offset 0: the loser must see the winner's commit under the lock.

    Regression for the stale identity-map read: the loser used to re-read
    received_bytes == 0 and truncate the bytes the winner had committed.
    """
    _mock_storage(monkeypatch)
    settings = get_settings()
    monkeypatch.setattr(settings, "UPLOAD_STAGING_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "UPLOAD_MAX_CONCURRENT_CHUNKS_PER_USER", 4)
    session_id, files = await _create_session(
        client, csrf_headers, test_project_id, test_dataset.id,
        [{"filename": "race.wav", "size": 8}],
    )
    url = _upload_url(test_project_id, test_dataset.id, session_id, files[0]["file_id"])
    first, second = await asyncio.gather(
        client.put(f"{url}?offset=0", headers=csrf_headers, content=b"abcd"),
        client.put(f"{url}?offset=0", headers=csrf_headers, content=b"abcd"),
    )
    codes = sorted([first.status_code, second.status_code])
    assert codes == [200, 409], (first.text, second.text)
    loser = first if first.status_code == 409 else second
    assert loser.json()["detail"]["received_bytes"] == 4
    part = upload_staging.part_path(UUID(session_id), UUID(files[0]["file_id"]))
    assert part.read_bytes() == b"abcd"
    tail = await client.put(f"{url}?offset=4", headers=csrf_headers, content=b"efgh")
    assert tail.status_code == 200 and tail.json()["complete"] is True


@pytest.mark.asyncio
async def test_chunk_body_caps_announced_and_streamed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    client: AsyncClient,
    csrf_headers: dict[str, str],
    test_project_id: str,
    test_dataset: Dataset,
) -> None:
    """413 from the Content-Length pre-check, and from the streaming cap when no length is announced."""
    _mock_storage(monkeypatch)
    settings = get_settings()
    monkeypatch.setattr(settings, "UPLOAD_STAGING_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "UPLOAD_CHUNK_SIZE", 4)
    session_id, files = await _create_session(
        client, csrf_headers, test_project_id, test_dataset.id,
        [{"filename": "cap.wav", "size": 40}],
    )
    url = _upload_url(test_project_id, test_dataset.id, session_id, files[0]["file_id"])

    announced = await client.put(f"{url}?offset=0", headers=csrf_headers, content=b"12345")
    assert announced.status_code == 413

    async def _stream() -> Any:
        yield b"123"
        yield b"45"

    streamed = await client.put(f"{url}?offset=0", headers=csrf_headers, content=_stream())
    assert streamed.status_code == 413

    ok = await client.put(f"{url}?offset=0", headers=csrf_headers, content=b"1234")
    assert ok.status_code == 200 and ok.json()["received_bytes"] == 4


@pytest.mark.asyncio
async def test_chunk_admission_limit_is_deterministic(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    client: AsyncClient,
    csrf_headers: dict[str, str],
    test_user: User,
    test_project_id: str,
    test_dataset: Dataset,
) -> None:
    """With the caller's in-flight count already at the limit, the next chunk is 429."""
    from echoroo.api.web_v1.projects import _uploads

    _mock_storage(monkeypatch)
    settings = get_settings()
    monkeypatch.setattr(settings, "UPLOAD_STAGING_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "UPLOAD_MAX_CONCURRENT_CHUNKS_PER_USER", 1)
    session_id, files = await _create_session(
        client, csrf_headers, test_project_id, test_dataset.id,
        [{"filename": "busy.wav", "size": 4}],
    )
    url = _upload_url(test_project_id, test_dataset.id, session_id, files[0]["file_id"])
    monkeypatch.setitem(_uploads._chunk_in_flight, test_user.id, 1)

    busy = await client.put(f"{url}?offset=0", headers=csrf_headers, content=b"ab")
    assert busy.status_code == 429
    assert busy.headers.get("Retry-After") == "1"
    # The rejected request must not have touched the counter.
    assert _uploads._chunk_in_flight[test_user.id] == 1
