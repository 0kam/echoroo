"""Contract tests for upload session API endpoints.

Tests verify that endpoints conform to the upload feature specification.

Note: S3/MinIO is mocked in all tests. Rate limiting depends on Redis,
which may not be available in tests; rate limiters are configured to be
disabled during test execution by the test client setup in conftest.py.
"""

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.dataset import Dataset
from echoroo.models.enums import DatasetStatus
from echoroo.models.site import Site
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

    @patch("echoroo.api.v1.uploads.s3.ensure_bucket_exists")
    @patch("echoroo.core.s3.generate_presigned_upload_url")
    @patch("echoroo.core.s3.get_s3_client")
    async def test_create_upload_session_success(
        self,
        mock_get_s3_client: MagicMock,
        mock_presigned_url: MagicMock,
        mock_ensure_bucket: MagicMock,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_dataset: Dataset,
    ) -> None:
        """Test POST /web-api/v1/projects/{project_id}/datasets/{dataset_id}/upload-sessions - Create upload session."""
        # Mock S3 client and presigned URL generation
        mock_get_s3_client.return_value = MagicMock()
        mock_presigned_url.return_value = "https://minio:9000/echoroo/fake-presigned-url"
        mock_ensure_bucket.return_value = None

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
            assert "upload_url" in file_info
            assert file_info["upload_url"] == "https://minio:9000/echoroo/fake-presigned-url"

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

    @patch("echoroo.api.v1.uploads.s3.ensure_bucket_exists")
    @patch("echoroo.core.s3.generate_presigned_upload_url")
    @patch("echoroo.core.s3.get_s3_client")
    async def test_create_upload_session_forbidden_non_admin(
        self,
        mock_get_s3_client: MagicMock,
        mock_presigned_url: MagicMock,
        mock_ensure_bucket: MagicMock,
        client: AsyncClient,
        csrf_headers_other: dict[str, str],
        test_project_id: str,
        test_dataset: Dataset,
    ) -> None:
        """Test POST upload-sessions denies Authenticated non-members.

        Phase 16 Batch 6e (2026-04-29) downstream drift fix: Phase 9 /
        T280 spec gave MEMBER role ``Permission.UPLOAD`` (see
        ``apps/api/echoroo/core/permissions.py::_MEMBER_PERMS``) so the
        legacy "member -> 403" expectation no longer holds. The
        canonical 403 path is now Authenticated non-member
        (``csrf_headers_other``); that identity has zero project
        permissions. The "viewer cannot upload" path is covered by
        the dedicated viewer-permission-boundary suite.
        """
        mock_get_s3_client.return_value = MagicMock()
        mock_presigned_url.return_value = "https://minio:9000/fake-url"
        mock_ensure_bucket.return_value = None

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

    @patch("echoroo.api.v1.uploads.s3.ensure_bucket_exists")
    @patch("echoroo.core.s3.generate_presigned_upload_url")
    @patch("echoroo.core.s3.get_s3_client")
    async def test_create_upload_session_dataset_not_found(
        self,
        mock_get_s3_client: MagicMock,
        mock_presigned_url: MagicMock,
        mock_ensure_bucket: MagicMock,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test POST upload-sessions with invalid dataset_id returns 404."""
        mock_get_s3_client.return_value = MagicMock()
        mock_presigned_url.return_value = "https://minio:9000/fake-url"
        mock_ensure_bucket.return_value = None

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

    @patch("echoroo.api.v1.uploads.s3.ensure_bucket_exists")
    @patch("echoroo.core.s3.generate_presigned_upload_url")
    @patch("echoroo.core.s3.get_s3_client")
    async def test_create_upload_session_invalid_extension(
        self,
        mock_get_s3_client: MagicMock,
        mock_presigned_url: MagicMock,
        mock_ensure_bucket: MagicMock,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_dataset: Dataset,
    ) -> None:
        """Test POST upload-sessions rejects unsupported file extension."""
        mock_get_s3_client.return_value = MagicMock()
        mock_presigned_url.return_value = "https://minio:9000/fake-url"
        mock_ensure_bucket.return_value = None

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

    @patch("echoroo.api.v1.uploads.s3.ensure_bucket_exists")
    @patch("echoroo.core.s3.generate_presigned_upload_url")
    @patch("echoroo.core.s3.get_s3_client")
    async def test_create_upload_session_file_too_large(
        self,
        mock_get_s3_client: MagicMock,
        mock_presigned_url: MagicMock,
        mock_ensure_bucket: MagicMock,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_dataset: Dataset,
    ) -> None:
        """Test POST upload-sessions rejects file exceeding 1GB limit."""
        mock_get_s3_client.return_value = MagicMock()
        mock_presigned_url.return_value = "https://minio:9000/fake-url"
        mock_ensure_bucket.return_value = None

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

    @patch("echoroo.api.v1.uploads.s3.ensure_bucket_exists")
    @patch("echoroo.core.s3.generate_presigned_upload_url")
    @patch("echoroo.core.s3.get_s3_client")
    async def test_create_upload_session_too_many_files(
        self,
        mock_get_s3_client: MagicMock,
        mock_presigned_url: MagicMock,
        mock_ensure_bucket: MagicMock,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_dataset: Dataset,
    ) -> None:
        """Test POST upload-sessions rejects >500 files."""
        mock_get_s3_client.return_value = MagicMock()
        mock_presigned_url.return_value = "https://minio:9000/fake-url"
        mock_ensure_bucket.return_value = None

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

    @patch("echoroo.api.v1.uploads.s3.ensure_bucket_exists")
    @patch("echoroo.core.s3.generate_presigned_upload_url")
    @patch("echoroo.core.s3.get_s3_client")
    async def test_create_upload_session_invalid_filename_traversal(
        self,
        mock_get_s3_client: MagicMock,
        mock_presigned_url: MagicMock,
        mock_ensure_bucket: MagicMock,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_dataset: Dataset,
    ) -> None:
        """Test POST upload-sessions rejects path traversal in filename."""
        mock_get_s3_client.return_value = MagicMock()
        mock_presigned_url.return_value = "https://minio:9000/fake-url"
        mock_ensure_bucket.return_value = None

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

    @patch("echoroo.api.v1.uploads.s3.ensure_bucket_exists")
    @patch("echoroo.core.s3.generate_presigned_upload_url")
    @patch("echoroo.core.s3.get_s3_client")
    async def test_create_upload_session_invalid_checksum(
        self,
        mock_get_s3_client: MagicMock,
        mock_presigned_url: MagicMock,
        mock_ensure_bucket: MagicMock,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_dataset: Dataset,
    ) -> None:
        """Test POST upload-sessions rejects invalid checksum format."""
        mock_get_s3_client.return_value = MagicMock()
        mock_presigned_url.return_value = "https://minio:9000/fake-url"
        mock_ensure_bucket.return_value = None

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

    @patch("echoroo.api.v1.uploads.s3.ensure_bucket_exists")
    @patch("echoroo.core.s3.generate_presigned_upload_url")
    @patch("echoroo.core.s3.get_s3_client")
    async def test_create_upload_session_conflict_existing_session(
        self,
        mock_get_s3_client: MagicMock,
        mock_presigned_url: MagicMock,
        mock_ensure_bucket: MagicMock,
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
        mock_get_s3_client.return_value = MagicMock()
        mock_presigned_url.return_value = "https://minio:9000/fake-url"
        mock_ensure_bucket.return_value = None

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

    @patch("echoroo.core.s3.verify_object_exists")
    @patch("echoroo.core.s3.get_s3_client")
    @patch("echoroo.api.v1.uploads.s3.ensure_bucket_exists")
    @patch("echoroo.core.s3.generate_presigned_upload_url")
    async def test_complete_upload_session_success(
        self,
        mock_presigned_url: MagicMock,
        mock_ensure_bucket: MagicMock,
        mock_get_s3_client_for_verify: MagicMock,
        mock_verify_object: MagicMock,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_dataset: Dataset,
    ) -> None:
        """Test POST upload-sessions/{session_id}/complete - Complete upload."""
        # Mock S3 operations for session creation
        mock_get_s3_client_for_verify.return_value = MagicMock()
        mock_presigned_url.return_value = "https://minio:9000/fake-url"
        mock_ensure_bucket.return_value = None

        # Mock verify_object_exists to return successful verification
        mock_verify_object.return_value = {
            "exists": True,
            "size_match": True,
            "actual_size": 1024000,
        }

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

        # Create session first
        create_response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/datasets/{test_dataset.id}/upload-sessions",
            headers=csrf_headers,
            json=request_data,
        )
        assert create_response.status_code == 201
        session_id = create_response.json()["session_id"]

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
        assert "mismatched_files" in data
        assert data["mismatched_files"] == 0

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

    @patch("echoroo.api.v1.uploads.s3.ensure_bucket_exists")
    @patch("echoroo.core.s3.generate_presigned_upload_url")
    @patch("echoroo.core.s3.get_s3_client")
    async def test_complete_upload_session_not_found(
        self,
        mock_get_s3_client: MagicMock,
        mock_presigned_url: MagicMock,
        mock_ensure_bucket: MagicMock,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_dataset: Dataset,
    ) -> None:
        """Test POST upload-sessions/{session_id}/complete with non-existent session."""
        mock_get_s3_client.return_value = MagicMock()
        mock_presigned_url.return_value = "https://minio:9000/fake-url"
        mock_ensure_bucket.return_value = None

        fake_session_id = "00000000-0000-0000-0000-000000000000"

        response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/datasets/{test_dataset.id}/upload-sessions/{fake_session_id}/complete",
            headers=csrf_headers,
        )

        assert response.status_code == 404

    @patch("echoroo.core.s3.verify_object_exists")
    @patch("echoroo.core.s3.get_s3_client")
    @patch("echoroo.api.v1.uploads.s3.ensure_bucket_exists")
    @patch("echoroo.core.s3.generate_presigned_upload_url")
    async def test_complete_upload_session_wrong_state(
        self,
        mock_presigned_url: MagicMock,
        mock_ensure_bucket: MagicMock,
        mock_get_s3_client_for_verify: MagicMock,
        mock_verify_object: MagicMock,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_dataset: Dataset,
    ) -> None:
        """Test POST upload-sessions/{session_id}/complete fails if session not in ISSUED state."""
        # Mock S3 operations
        mock_get_s3_client_for_verify.return_value = MagicMock()
        mock_presigned_url.return_value = "https://minio:9000/fake-url"
        mock_ensure_bucket.return_value = None
        mock_verify_object.return_value = {
            "exists": True,
            "size_match": True,
            "actual_size": 1024000,
        }

        request_data = {
            "files": [
                {
                    "filename": "recording.wav",
                    "size": 1024000,
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

    @patch("echoroo.api.v1.uploads.s3.ensure_bucket_exists")
    @patch("echoroo.core.s3.generate_presigned_upload_url")
    @patch("echoroo.core.s3.get_s3_client")
    async def test_get_session_status_success(
        self,
        mock_get_s3_client: MagicMock,
        mock_presigned_url: MagicMock,
        mock_ensure_bucket: MagicMock,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_dataset: Dataset,
    ) -> None:
        """Test GET upload-sessions/{session_id} - Get session status."""
        mock_get_s3_client.return_value = MagicMock()
        mock_presigned_url.return_value = "https://minio:9000/fake-url"
        mock_ensure_bucket.return_value = None

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

    @patch("echoroo.api.v1.uploads.s3.ensure_bucket_exists")
    @patch("echoroo.core.s3.generate_presigned_upload_url")
    @patch("echoroo.core.s3.get_s3_client")
    async def test_get_session_status_not_found(
        self,
        mock_get_s3_client: MagicMock,
        mock_presigned_url: MagicMock,
        mock_ensure_bucket: MagicMock,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_dataset: Dataset,
    ) -> None:
        """Test GET upload-sessions/{session_id} with non-existent session."""
        mock_get_s3_client.return_value = MagicMock()
        mock_presigned_url.return_value = "https://minio:9000/fake-url"
        mock_ensure_bucket.return_value = None

        fake_session_id = "00000000-0000-0000-0000-000000000000"

        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/datasets/{test_dataset.id}/upload-sessions/{fake_session_id}",
            headers=csrf_headers,
        )

        assert response.status_code == 404

    @patch("echoroo.api.v1.uploads.s3.ensure_bucket_exists")
    @patch("echoroo.core.s3.generate_presigned_upload_url")
    @patch("echoroo.core.s3.get_s3_client")
    async def test_get_session_status_member_access(
        self,
        mock_get_s3_client: MagicMock,
        mock_presigned_url: MagicMock,
        mock_ensure_bucket: MagicMock,
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
        mock_get_s3_client.return_value = MagicMock()
        mock_presigned_url.return_value = "https://minio:9000/fake-url"
        mock_ensure_bucket.return_value = None

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
