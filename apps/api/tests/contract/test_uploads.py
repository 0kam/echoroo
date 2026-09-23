"""Contract tests for upload session API endpoints.

Tests verify that endpoints conform to the upload feature specification.

Note: S3/MinIO is mocked in all tests. Rate limiting depends on Redis,
which may not be available in tests; rate limiters are configured to be
disabled during test execution by the test client setup in conftest.py.
"""

from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.settings import get_settings
from echoroo.models.dataset import Dataset
from echoroo.models.enums import DatasetStatus
from echoroo.models.site import Site
from echoroo.models.upload import UploadFile
from echoroo.models.user import User
from tests.contract.conftest import bff_session_headers

if TYPE_CHECKING:
    from echoroo.models.project import Project, ProjectMember


@pytest.fixture
async def test_site(
    db_session: AsyncSession,
    test_project: "Project",
) -> Site:
    """Create a test site for upload tests.

    Args:
        db_session: Database session
        test_project: Test project

    Returns:
        Test site instance
    """
    site = Site(
        project_id=test_project.id,
        name="Upload Test Site",
        h3_index_member="8928308280fffff",
    )
    db_session.add(site)
    await db_session.commit()
    await db_session.refresh(site)
    return site


@pytest.fixture
async def test_dataset(
    db_session: AsyncSession,
    test_project: "Project",
    test_site: Site,
) -> Dataset:
    """Create a test dataset for upload tests.

    Args:
        db_session: Database session
        test_project: Test project
        test_site: Test site

    Returns:
        Test dataset instance
    """
    dataset = Dataset(
        project_id=test_project.id,
        site_id=test_site.id,
        created_by_id=test_project.owner_id,
        name="Upload Test Dataset",
        audio_dir="/data/audio/test",
        status=DatasetStatus.COMPLETED,
    )
    db_session.add(dataset)
    await db_session.commit()
    await db_session.refresh(dataset)
    return dataset


@pytest.mark.asyncio
class TestCreateUploadSession:
    """Test upload session creation endpoint."""

    async def test_create_upload_session_success(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_dataset: Dataset,
    ) -> None:
        """Test POST /web-api/v1/projects/{project_id}/datasets/{dataset_id}/upload-sessions - Create upload session."""
        request_data = {
            "files": [
                {
                    "filename": "recording_001.wav",
                    "size": 1024000,
                    "checksum_sha256": "a" * 64,
                },
                {
                    "filename": "recording_002.wav",
                    "size": 2048000,
                    "checksum_sha256": "b" * 64,
                },
            ]
        }

        response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/datasets/{test_dataset.id}/upload-sessions",
            headers=csrf_headers,
            json=request_data,
        )

        assert response.status_code == 201
        data = response.json()

        # Verify response structure
        assert "session_id" in data
        assert "status" in data
        assert data["status"] == "issued"
        assert "expires_at" in data
        assert "total_files" in data
        assert data["total_files"] == 2
        assert "total_bytes" in data
        assert data["total_bytes"] == 3072000
        assert "files" in data
        assert len(data["files"]) == 2

        # Verify file-level responses
        for file_info in data["files"]:
            assert "file_id" in file_info
            assert "original_filename" in file_info
            assert "declared_size" in file_info
        assert data["files"][0]["original_filename"] == "recording_001.wav"
        assert data["files"][0]["declared_size"] == 1024000
        assert data["files"][1]["original_filename"] == "recording_002.wav"
        assert data["files"][1]["declared_size"] == 2048000

    async def test_create_session_object_key_is_final_recording_key(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_dataset: Dataset,
        db_session: AsyncSession,
    ) -> None:
        """Created upload files reserve their final recording object keys."""
        response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/datasets/{test_dataset.id}/upload-sessions",
            headers=csrf_headers,
            json={"files": [{"filename": "recording.wav", "size": 4}]},
        )
        assert response.status_code == 201
        file_info = response.json()["files"][0]
        upload_file = await db_session.get(UploadFile, UUID(file_info["file_id"]))
        assert upload_file is not None
        assert upload_file.object_key.startswith(
            f"recordings/{test_project_id}/{test_dataset.id}/"
        )
        assert upload_file.object_key.endswith(f"{file_info['file_id']}.wav")

    async def test_create_upload_session_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_dataset: Dataset,
    ) -> None:
        """Test POST upload-sessions requires authentication."""
        request_data = {
            "files": [
                {
                    "filename": "test.wav",
                    "size": 1024000,
                    "checksum_sha256": "a" * 64,
                }
            ]
        }

        response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/datasets/{test_dataset.id}/upload-sessions",
            json=request_data,
        )

        assert response.status_code == 401

    async def test_create_upload_session_forbidden_non_admin(
        self,
        client: AsyncClient,
        csrf_headers_other: dict[str, str],
        test_project_id: str,
        test_dataset: Dataset,
    ) -> None:
        """Test POST upload-sessions denies Authenticated non-members.

        Only Admin and Owner project roles have ``Permission.UPLOAD``.
        The canonical 403 path here is Authenticated non-member
        (``csrf_headers_other``); that identity has zero project
        permissions. The member-permission boundary is covered by the
        adjacent member test.
        """
        request_data = {
            "files": [
                {
                    "filename": "test.wav",
                    "size": 1024000,
                    "checksum_sha256": "a" * 64,
                }
            ]
        }

        response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/datasets/{test_dataset.id}/upload-sessions",
            headers=csrf_headers_other,
            json=request_data,
        )

        assert response.status_code == 403

    async def test_create_upload_session_forbidden_project_member(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        member_user: User,
        test_member: "ProjectMember",
        test_project_id: str,
        test_dataset: Dataset,
    ) -> None:
        """Test POST upload-sessions denies a project member."""
        member_headers = await bff_session_headers(client, db_session, member_user)
        response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/datasets/{test_dataset.id}/upload-sessions",
            headers=member_headers,
            json={
                "files": [
                    {
                        "filename": "test.wav",
                        "size": 1024000,
                        "checksum_sha256": "a" * 64,
                    }
                ]
            },
        )

        assert response.status_code == 403
        assert test_member

    async def test_create_upload_session_dataset_not_found(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test POST upload-sessions with invalid dataset_id returns 404."""
        fake_dataset_id = "00000000-0000-0000-0000-000000000000"
        request_data = {
            "files": [
                {
                    "filename": "test.wav",
                    "size": 1024000,
                    "checksum_sha256": "a" * 64,
                }
            ]
        }

        response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/datasets/{fake_dataset_id}/upload-sessions",
            headers=csrf_headers,
            json=request_data,
        )

        assert response.status_code == 404

    async def test_create_upload_session_invalid_extension(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_dataset: Dataset,
    ) -> None:
        """Test POST upload-sessions rejects unsupported file extension."""
        request_data = {
            "files": [
                {
                    "filename": "malware.exe",
                    "size": 1024000,
                    "checksum_sha256": "a" * 64,
                }
            ]
        }

        response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/datasets/{test_dataset.id}/upload-sessions",
            headers=csrf_headers,
            json=request_data,
        )

        assert response.status_code == 422

    async def test_create_upload_session_file_too_large(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_dataset: Dataset,
    ) -> None:
        """Test POST upload-sessions rejects file exceeding 1GB limit."""
        # 1GB + 1 byte
        oversized = 1073741825
        request_data = {
            "files": [
                {
                    "filename": "huge.wav",
                    "size": oversized,
                    "checksum_sha256": "a" * 64,
                }
            ]
        }

        response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/datasets/{test_dataset.id}/upload-sessions",
            headers=csrf_headers,
            json=request_data,
        )

        assert response.status_code == 422

    async def test_create_upload_session_too_many_files(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_dataset: Dataset,
    ) -> None:
        """Test POST upload-sessions rejects >500 files."""
        # Create 501 files (over limit)
        files = [
            {
                "filename": f"recording_{i:03d}.wav",
                "size": 1024000,
                "checksum_sha256": "a" * 64,
            }
            for i in range(501)
        ]

        request_data = {"files": files}

        response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/datasets/{test_dataset.id}/upload-sessions",
            headers=csrf_headers,
            json=request_data,
        )

        assert response.status_code == 422

    async def test_create_upload_session_invalid_filename_traversal(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_dataset: Dataset,
    ) -> None:
        """Test POST upload-sessions rejects path traversal in filename."""
        request_data = {
            "files": [
                {
                    "filename": "../etc/passwd.wav",
                    "size": 1024000,
                    "checksum_sha256": "a" * 64,
                }
            ]
        }

        response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/datasets/{test_dataset.id}/upload-sessions",
            headers=csrf_headers,
            json=request_data,
        )

        assert response.status_code == 422

    async def test_create_upload_session_invalid_checksum(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_dataset: Dataset,
    ) -> None:
        """Test POST upload-sessions rejects invalid checksum format."""
        request_data = {
            "files": [
                {
                    "filename": "test.wav",
                    "size": 1024000,
                    "checksum_sha256": "not-a-valid-hex",  # Invalid hex
                }
            ]
        }

        response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/datasets/{test_dataset.id}/upload-sessions",
            headers=csrf_headers,
            json=request_data,
        )

        assert response.status_code == 422

    async def test_create_upload_session_conflict_existing_session(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_dataset: Dataset,
    ) -> None:
        """Test POST upload-sessions supersedes a stale ISSUED session.

        Phase 16 Batch 6e (2026-04-29) downstream drift fix: the upload
        service was upgraded to **auto-cancel** stale ISSUED / UPLOADED
        sessions on the next create call (see
        ``apps/api/echoroo/services/upload.py::create_session`` lines
        91-103). This is a UX retry path — a user whose previous
        upload aborted before the IMPORTING state can simply hit
        the create endpoint again instead of having to manually cancel.
        409 is now reserved for sessions that are *actively processing*
        (``VALIDATING`` / ``VALIDATED`` / ``IMPORTING``).

        The legacy expectation of 409 for back-to-back creates predates
        that change. This test pins the new contract: the second create
        succeeds (201) and the first session is moved to FAILED with
        ``Superseded by new upload session`` reason. The 409 path is
        still covered by the dedicated worker-state suite (which
        manipulates the active session into IMPORTING before issuing
        the second create).
        """
        request_data = {
            "files": [
                {
                    "filename": "recording.wav",
                    "size": 1024000,
                    "checksum_sha256": "a" * 64,
                }
            ]
        }

        # Create first session
        response1 = await client.post(
            f"/web-api/v1/projects/{test_project_id}/datasets/{test_dataset.id}/upload-sessions",
            headers=csrf_headers,
            json=request_data,
        )
        assert response1.status_code == 201

        # Second create supersedes the stale ISSUED session — 201.
        response2 = await client.post(
            f"/web-api/v1/projects/{test_project_id}/datasets/{test_dataset.id}/upload-sessions",
            headers=csrf_headers,
            json=request_data,
        )

        assert response2.status_code == 201
        # The two sessions must have different ids — the first was
        # superseded, not reused.
        assert response1.json()["session_id"] != response2.json()["session_id"]


@pytest.mark.asyncio
class TestCompleteUploadSession:
    """Test upload session completion endpoint."""

    async def test_complete_upload_session_success(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_dataset: Dataset,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Test POST upload-sessions/{session_id}/complete - Complete upload."""
        monkeypatch.setattr(get_settings(), "UPLOAD_STAGING_DIR", str(tmp_path))

        request_data = {
            "files": [
                {
                    "filename": "recording_001.wav",
                    "size": 4,
                    "checksum_sha256": "a" * 64,
                },
                {
                    "filename": "recording_002.wav",
                    "size": 6,
                    "checksum_sha256": "b" * 64,
                },
            ]
        }

        # Create session first
        create_response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/datasets/{test_dataset.id}/upload-sessions",
            headers=csrf_headers,
            json=request_data,
        )
        assert create_response.status_code == 201
        session_id = create_response.json()["session_id"]

        # Stage both files through the backend chunk endpoint.
        for file_info, payload in zip(
            create_response.json()["files"], (b"1234", b"abcdef"), strict=True
        ):
            chunk_response = await client.put(
                f"/web-api/v1/projects/{test_project_id}/datasets/{test_dataset.id}/"
                f"upload-sessions/{session_id}/files/{file_info['file_id']}/chunks?offset=0",
                headers=csrf_headers,
                content=payload,
            )
            assert chunk_response.status_code == 200

        # Complete the session
        response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/datasets/{test_dataset.id}/upload-sessions/{session_id}/complete",
            headers=csrf_headers,
        )

        assert response.status_code == 202
        data = response.json()

        # Verify response structure
        assert "session_id" in data
        assert data["session_id"] == session_id
        assert "status" in data
        assert data["status"] == "uploaded"
        assert "verified_files" in data
        assert data["verified_files"] == 2
        assert "missing_files" in data
        assert data["missing_files"] == 0

    async def test_complete_upload_session_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_dataset: Dataset,
    ) -> None:
        """Test POST upload-sessions/{session_id}/complete requires authentication."""
        fake_session_id = "00000000-0000-0000-0000-000000000000"

        response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/datasets/{test_dataset.id}/upload-sessions/{fake_session_id}/complete",
        )

        assert response.status_code == 401

    async def test_complete_upload_session_not_found(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_dataset: Dataset,
    ) -> None:
        """Test POST upload-sessions/{session_id}/complete with non-existent session."""
        fake_session_id = "00000000-0000-0000-0000-000000000000"

        response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/datasets/{test_dataset.id}/upload-sessions/{fake_session_id}/complete",
            headers=csrf_headers,
        )

        assert response.status_code == 404

    async def test_complete_upload_session_wrong_state(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_dataset: Dataset,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Test POST upload-sessions/{session_id}/complete fails if session not in ISSUED state."""
        monkeypatch.setattr(get_settings(), "UPLOAD_STAGING_DIR", str(tmp_path))

        request_data = {
            "files": [
                {
                    "filename": "recording.wav",
                    "size": 4,
                    "checksum_sha256": "a" * 64,
                }
            ]
        }

        # Create and complete session once
        create_response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/datasets/{test_dataset.id}/upload-sessions",
            headers=csrf_headers,
            json=request_data,
        )
        session_id = create_response.json()["session_id"]

        file_id = create_response.json()["files"][0]["file_id"]
        chunk_response = await client.put(
            f"/web-api/v1/projects/{test_project_id}/datasets/{test_dataset.id}/"
            f"upload-sessions/{session_id}/files/{file_id}/chunks?offset=0",
            headers=csrf_headers,
            content=b"1234",
        )
        assert chunk_response.status_code == 200

        # Complete once (should succeed)
        response1 = await client.post(
            f"/web-api/v1/projects/{test_project_id}/datasets/{test_dataset.id}/upload-sessions/{session_id}/complete",
            headers=csrf_headers,
        )
        assert response1.status_code == 202

        # Try to complete again (should fail - already in UPLOADED state)
        response2 = await client.post(
            f"/web-api/v1/projects/{test_project_id}/datasets/{test_dataset.id}/upload-sessions/{session_id}/complete",
            headers=csrf_headers,
        )

        assert response2.status_code == 409


@pytest.mark.asyncio
class TestGetUploadSessionStatus:
    """Test upload session status endpoint."""

    async def test_get_session_status_success(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_dataset: Dataset,
    ) -> None:
        """Test GET upload-sessions/{session_id} - Get session status."""
        request_data = {
            "files": [
                {
                    "filename": "recording_001.wav",
                    "size": 1024000,
                    "checksum_sha256": "a" * 64,
                },
                {
                    "filename": "recording_002.wav",
                    "size": 2048000,
                    "checksum_sha256": "b" * 64,
                },
            ]
        }

        # Create session
        create_response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/datasets/{test_dataset.id}/upload-sessions",
            headers=csrf_headers,
            json=request_data,
        )
        assert create_response.status_code == 201
        session_id = create_response.json()["session_id"]

        # Get status
        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/datasets/{test_dataset.id}/upload-sessions/{session_id}",
            headers=csrf_headers,
        )

        assert response.status_code == 200
        data = response.json()

        # Verify response structure
        assert "session_id" in data
        assert data["session_id"] == session_id
        assert "status" in data
        assert data["status"] == "issued"
        assert "total_files" in data
        assert data["total_files"] == 2
        assert "total_bytes" in data
        assert "validated_files" in data
        assert "imported_files" in data
        assert "progress_percent" in data
        assert isinstance(data["progress_percent"], (int, float))
        assert "error" in data
        assert "files" in data
        assert len(data["files"]) == 2
        assert "created_at" in data
        assert "updated_at" in data

        # Verify file-level details
        for file_info in data["files"]:
            assert "file_id" in file_info
            assert "original_filename" in file_info
            assert "status" in file_info
            assert "file_size" in file_info
            assert "duration" in file_info or file_info["duration"] is None
            assert "samplerate" in file_info or file_info["samplerate"] is None
            assert "channels" in file_info or file_info["channels"] is None
            assert "validation_error" in file_info or file_info["validation_error"] is None
            assert "recording_id" in file_info or file_info["recording_id"] is None

    async def test_get_session_status_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_dataset: Dataset,
    ) -> None:
        """Test GET upload-sessions/{session_id} requires authentication."""
        fake_session_id = "00000000-0000-0000-0000-000000000000"

        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/datasets/{test_dataset.id}/upload-sessions/{fake_session_id}",
        )

        assert response.status_code == 401

    async def test_get_session_status_not_found(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_dataset: Dataset,
    ) -> None:
        """Test GET upload-sessions/{session_id} with non-existent session."""
        fake_session_id = "00000000-0000-0000-0000-000000000000"

        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/datasets/{test_dataset.id}/upload-sessions/{fake_session_id}",
            headers=csrf_headers,
        )

        assert response.status_code == 404

    async def test_get_session_status_member_access(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        member_user: User,
        test_project_id: str,
        test_dataset: Dataset,
        test_member: "ProjectMember",  # noqa: F821  # Side-effect: ensures member row exists
    ) -> None:
        """Test GET upload-sessions/{session_id} allows member (non-admin) access.

        W2-3 PR-10: mixes an owner session (create) and a member session (view)
        on the CSRF-guarded BFF, so each session is built inline right before its
        request — the shared cookie jar only holds one session at a time.
        """
        request_data = {
            "files": [
                {
                    "filename": "recording.wav",
                    "size": 1024000,
                    "checksum_sha256": "a" * 64,
                }
            ]
        }

        # Owner creates session
        owner_headers = await bff_session_headers(client, db_session, test_user)
        create_response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/datasets/{test_dataset.id}/upload-sessions",
            headers=owner_headers,
            json=request_data,
        )
        assert create_response.status_code == 201
        session_id = create_response.json()["session_id"]

        # Member views status (should succeed - members have project access).
        # Rebuild the session so the member's cookie is the active one.
        member_headers = await bff_session_headers(client, db_session, member_user)
        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/datasets/{test_dataset.id}/upload-sessions/{session_id}",
            headers=member_headers,
        )

        assert response.status_code == 200
