"""Integration tests for upload workflow.

Tests verify the complete upload lifecycle from session creation through status monitoring.
"""

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.dataset import Dataset
from echoroo.models.enums import DatasetStatus
from echoroo.models.site import Site

if TYPE_CHECKING:
    from echoroo.models.project import Project, ProjectMember


@pytest.fixture
async def test_site(
    db_session: AsyncSession,
    test_project: "Project",
) -> Site:
    """Create a test site for integration tests.

    Args:
        db_session: Database session
        test_project: Test project

    Returns:
        Test site instance
    """
    site = Site(
        project_id=test_project.id,
        name="Integration Test Site",
        h3_index="8928308280fffff",
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
    """Create a test dataset for integration tests.

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
        name="Integration Test Dataset",
        audio_dir="/data/audio/integration",
        status=DatasetStatus.COMPLETED,
    )
    db_session.add(dataset)
    await db_session.commit()
    await db_session.refresh(dataset)
    return dataset


@pytest.mark.asyncio
class TestUploadWorkflow:
    """Test complete upload workflow from creation to status monitoring."""

    @patch("echoroo.core.s3.verify_object_exists")
    @patch("echoroo.core.s3.get_s3_client")
    @patch("echoroo.api.v1.uploads.s3.ensure_bucket_exists")
    @patch("echoroo.core.s3.generate_presigned_upload_url")
    async def test_full_upload_workflow(
        self,
        mock_presigned_url: MagicMock,
        mock_ensure_bucket: MagicMock,
        mock_get_s3_client_for_verify: MagicMock,
        mock_verify_object: MagicMock,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_dataset: Dataset,
    ) -> None:
        """Test complete workflow: Create session → Upload → Complete → Check status."""
        mock_get_s3_client_for_verify.return_value = MagicMock()
        mock_presigned_url.return_value = "https://minio:9000/bucket/fake-presigned-url"
        mock_ensure_bucket.return_value = None
        mock_verify_object.return_value = {
            "exists": True,
            "size_match": True,
            "actual_size": 1024000,
        }

        # Step 1: Create upload session
        files_to_upload: list[dict[str, Any]] = [
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
            {
                "filename": "recording_003.wav",
                "size": 512000,
                "checksum_sha256": "c" * 64,
            },
        ]

        create_response = await client.post(
            f"/api/v1/projects/{test_project_id}/datasets/{test_dataset.id}/upload-sessions",
            headers=auth_headers,
            json={"files": files_to_upload},
        )

        assert create_response.status_code == 201
        session_data = create_response.json()
        session_id = session_data["session_id"]

        # Validate session creation response
        assert session_data["status"] == "issued"
        assert session_data["total_files"] == 3
        assert session_data["total_bytes"] == sum(f["size"] for f in files_to_upload)
        assert len(session_data["files"]) == 3

        # Verify each file has presigned URL
        for file_info in session_data["files"]:
            assert "file_id" in file_info
            assert "upload_url" in file_info
            assert file_info["upload_url"] == "https://minio:9000/bucket/fake-presigned-url"

        # Step 2: Simulate file uploads (in real scenario, client uploads via presigned URLs)
        # We'll skip actual S3 upload and just verify completion works

        # Step 3: Complete upload session (verify files in S3)
        complete_response = await client.post(
            f"/api/v1/projects/{test_project_id}/datasets/{test_dataset.id}/upload-sessions/{session_id}/complete",
            headers=auth_headers,
        )

        assert complete_response.status_code == 202
        complete_data = complete_response.json()
        assert complete_data["session_id"] == session_id
        assert complete_data["status"] == "uploaded"
        assert complete_data["verified_files"] == 3
        assert complete_data["missing_files"] == 0
        assert complete_data["mismatched_files"] == 0

        # Step 4: Check session status
        status_response = await client.get(
            f"/api/v1/projects/{test_project_id}/datasets/{test_dataset.id}/upload-sessions/{session_id}",
            headers=auth_headers,
        )

        assert status_response.status_code == 200
        status_data = status_response.json()

        # Verify status endpoint reflects completion
        assert status_data["session_id"] == session_id
        assert status_data["status"] == "uploaded"
        assert status_data["total_files"] == 3
        assert status_data["total_bytes"] == sum(f["size"] for f in files_to_upload)
        assert len(status_data["files"]) == 3

        # All files should be in UPLOADED state
        for file_info in status_data["files"]:
            assert file_info["status"] == "uploaded"
            assert file_info["file_size"] in [1024000, 2048000, 512000]

    @patch("echoroo.api.v1.uploads.s3.ensure_bucket_exists")
    @patch("echoroo.core.s3.generate_presigned_upload_url")
    @patch("echoroo.core.s3.get_s3_client")
    async def test_upload_session_conflict_resolution(
        self,
        mock_get_s3_client: MagicMock,
        mock_presigned_url: MagicMock,
        mock_ensure_bucket: MagicMock,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_dataset: Dataset,
    ) -> None:
        """Test that creating second session while first is active returns 409."""
        mock_get_s3_client.return_value = MagicMock()
        mock_presigned_url.return_value = "https://minio:9000/fake-url"
        mock_ensure_bucket.return_value = None

        files = [
            {
                "filename": "recording.wav",
                "size": 1024000,
                "checksum_sha256": "a" * 64,
            }
        ]

        # Create first session (succeeds)
        response1 = await client.post(
            f"/api/v1/projects/{test_project_id}/datasets/{test_dataset.id}/upload-sessions",
            headers=auth_headers,
            json={"files": files},
        )
        assert response1.status_code == 201
        session1_id = response1.json()["session_id"]

        # Try to create second session (should fail with conflict)
        response2 = await client.post(
            f"/api/v1/projects/{test_project_id}/datasets/{test_dataset.id}/upload-sessions",
            headers=auth_headers,
            json={"files": files},
        )
        assert response2.status_code == 409

        # Verify first session is still active
        status_response = await client.get(
            f"/api/v1/projects/{test_project_id}/datasets/{test_dataset.id}/upload-sessions/{session1_id}",
            headers=auth_headers,
        )
        assert status_response.status_code == 200
        assert status_response.json()["status"] == "issued"

    @patch("echoroo.api.v1.uploads.s3.ensure_bucket_exists")
    @patch("echoroo.core.s3.generate_presigned_upload_url")
    @patch("echoroo.core.s3.get_s3_client")
    async def test_upload_session_access_control(
        self,
        mock_get_s3_client: MagicMock,
        mock_presigned_url: MagicMock,
        mock_ensure_bucket: MagicMock,
        client: AsyncClient,
        auth_headers: dict[str, str],
        auth_headers_member: dict[str, str],
        auth_headers_other: dict[str, str],
        test_project_id: str,
        test_dataset: Dataset,
        _test_member: "ProjectMember",  # noqa: F821  # Side-effect: ensures member row exists
    ) -> None:
        """Test access control: Owner manages, member views, outsider denied."""
        mock_get_s3_client.return_value = MagicMock()
        mock_presigned_url.return_value = "https://minio:9000/fake-url"
        mock_ensure_bucket.return_value = None

        files = [
            {
                "filename": "recording.wav",
                "size": 1024000,
                "checksum_sha256": "a" * 64,
            }
        ]

        # Owner creates session (succeeds)
        create_response = await client.post(
            f"/api/v1/projects/{test_project_id}/datasets/{test_dataset.id}/upload-sessions",
            headers=auth_headers,
            json={"files": files},
        )
        assert create_response.status_code == 201
        session_id = create_response.json()["session_id"]

        # Member views status (succeeds - has project access)
        member_status = await client.get(
            f"/api/v1/projects/{test_project_id}/datasets/{test_dataset.id}/upload-sessions/{session_id}",
            headers=auth_headers_member,
        )
        assert member_status.status_code == 200

        # Member tries to complete (fails - only admins can complete)
        member_complete = await client.post(
            f"/api/v1/projects/{test_project_id}/datasets/{test_dataset.id}/upload-sessions/{session_id}/complete",
            headers=auth_headers_member,
        )
        assert member_complete.status_code == 403

        # Outsider tries to view status (fails - no project access)
        outsider_status = await client.get(
            f"/api/v1/projects/{test_project_id}/datasets/{test_dataset.id}/upload-sessions/{session_id}",
            headers=auth_headers_other,
        )
        assert outsider_status.status_code == 403

        # Outsider tries to create session (fails - no admin role)
        outsider_create = await client.post(
            f"/api/v1/projects/{test_project_id}/datasets/{test_dataset.id}/upload-sessions",
            headers=auth_headers_other,
            json={"files": files},
        )
        assert outsider_create.status_code == 403

    @patch("echoroo.core.s3.verify_object_exists")
    @patch("echoroo.core.s3.get_s3_client")
    @patch("echoroo.api.v1.uploads.s3.ensure_bucket_exists")
    @patch("echoroo.core.s3.generate_presigned_upload_url")
    async def test_upload_partial_file_verification(
        self,
        mock_presigned_url: MagicMock,
        mock_ensure_bucket: MagicMock,
        mock_get_s3_client_for_verify: MagicMock,
        mock_verify_object: MagicMock,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_dataset: Dataset,
    ) -> None:
        """Test completion with some missing/mismatched files."""
        mock_get_s3_client_for_verify.return_value = MagicMock()
        mock_presigned_url.return_value = "https://minio:9000/fake-url"
        mock_ensure_bucket.return_value = None

        # Create session with 3 files
        files = [
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
            {
                "filename": "recording_003.wav",
                "size": 512000,
                "checksum_sha256": "c" * 64,
            },
        ]

        create_response = await client.post(
            f"/api/v1/projects/{test_project_id}/datasets/{test_dataset.id}/upload-sessions",
            headers=auth_headers,
            json={"files": files},
        )
        assert create_response.status_code == 201
        session_id = create_response.json()["session_id"]

        # Mock verification results: first file OK, second missing, third mismatched
        verification_results = [
            {"exists": True, "size_match": True, "actual_size": 1024000},  # OK
            {"exists": False, "size_match": False, "actual_size": 0},  # Missing
            {"exists": True, "size_match": False, "actual_size": 513000},  # Mismatched size
        ]

        call_count = [0]

        def verify_side_effect(*args: Any, **kwargs: Any) -> dict[str, Any]:
            result = verification_results[call_count[0]]
            call_count[0] += 1
            return result

        mock_verify_object.side_effect = verify_side_effect

        # Complete session
        complete_response = await client.post(
            f"/api/v1/projects/{test_project_id}/datasets/{test_dataset.id}/upload-sessions/{session_id}/complete",
            headers=auth_headers,
        )

        assert complete_response.status_code == 202
        complete_data = complete_response.json()

        # Verify counts
        assert complete_data["verified_files"] == 2  # 1 OK + 1 mismatched
        assert complete_data["missing_files"] == 1
        assert complete_data["mismatched_files"] == 1
        # Session should stay in ISSUED state because files are missing
        assert complete_data["status"] == "issued"

    @patch("echoroo.api.v1.uploads.s3.ensure_bucket_exists")
    @patch("echoroo.core.s3.generate_presigned_upload_url")
    @patch("echoroo.core.s3.get_s3_client")
    async def test_upload_session_multiple_files_details(
        self,
        mock_get_s3_client: MagicMock,
        mock_presigned_url: MagicMock,
        mock_ensure_bucket: MagicMock,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_dataset: Dataset,
    ) -> None:
        """Test session with multiple files has correct per-file details."""
        mock_get_s3_client.return_value = MagicMock()
        mock_presigned_url.return_value = "https://minio:9000/fake-url"
        mock_ensure_bucket.return_value = None

        files: list[dict[str, Any]] = [
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
            {
                "filename": "recording_003.wav",
                "size": 512000,
                "checksum_sha256": "c" * 64,
            },
            {
                "filename": "recording_004.wav",
                "size": 768000,
                "checksum_sha256": "d" * 64,
            },
            {
                "filename": "recording_005.wav",
                "size": 1536000,
                "checksum_sha256": "e" * 64,
            },
        ]

        create_response = await client.post(
            f"/api/v1/projects/{test_project_id}/datasets/{test_dataset.id}/upload-sessions",
            headers=auth_headers,
            json={"files": files},
        )

        assert create_response.status_code == 201
        session_data = create_response.json()

        # Verify total counts
        assert session_data["total_files"] == 5
        assert session_data["total_bytes"] == sum(f["size"] for f in files)

        # Verify file-level details
        file_responses: list[dict[str, Any]] = session_data["files"]
        assert len(file_responses) == 5

        # Each file should have unique ID but same presigned URL structure
        file_ids = [f["file_id"] for f in file_responses]
        assert len(file_ids) == len(set(file_ids))  # All unique

        filenames: list[str] = [f["original_filename"] for f in file_responses]
        expected_filenames: list[str] = [f["filename"] for f in files]
        assert sorted(filenames) == sorted(expected_filenames)

        # Get status and verify files appear there too
        status_response = await client.get(
            f"/api/v1/projects/{test_project_id}/datasets/{test_dataset.id}/upload-sessions/{session_data['session_id']}",
            headers=auth_headers,
        )

        assert status_response.status_code == 200
        status_data = status_response.json()

        assert len(status_data["files"]) == 5
        for file_info in status_data["files"]:
            assert file_info["status"] == "pending"  # Initial state
            assert file_info["file_size"] in [1024000, 2048000, 512000, 768000, 1536000]

    @patch("echoroo.api.v1.uploads.s3.ensure_bucket_exists")
    @patch("echoroo.core.s3.generate_presigned_upload_url")
    @patch("echoroo.core.s3.get_s3_client")
    async def test_upload_single_large_file(
        self,
        mock_get_s3_client: MagicMock,
        mock_presigned_url: MagicMock,
        mock_ensure_bucket: MagicMock,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_dataset: Dataset,
    ) -> None:
        """Test session with single large file (approaching 1GB limit)."""
        mock_get_s3_client.return_value = MagicMock()
        mock_presigned_url.return_value = "https://minio:9000/fake-url"
        mock_ensure_bucket.return_value = None

        # 900 MB file
        large_size = 900 * 1024 * 1024

        files = [
            {
                "filename": "large_recording.wav",
                "size": large_size,
                "checksum_sha256": "a" * 64,
            }
        ]

        create_response = await client.post(
            f"/api/v1/projects/{test_project_id}/datasets/{test_dataset.id}/upload-sessions",
            headers=auth_headers,
            json={"files": files},
        )

        assert create_response.status_code == 201
        session_data = create_response.json()

        assert session_data["total_files"] == 1
        assert session_data["total_bytes"] == large_size
        assert len(session_data["files"]) == 1
        assert session_data["files"][0]["original_filename"] == "large_recording.wav"

    @patch("echoroo.api.v1.uploads.s3.ensure_bucket_exists")
    @patch("echoroo.core.s3.generate_presigned_upload_url")
    @patch("echoroo.core.s3.get_s3_client")
    async def test_upload_various_audio_formats(
        self,
        mock_get_s3_client: MagicMock,
        mock_presigned_url: MagicMock,
        mock_ensure_bucket: MagicMock,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_dataset: Dataset,
    ) -> None:
        """Test session with various audio file formats."""
        mock_get_s3_client.return_value = MagicMock()
        mock_presigned_url.return_value = "https://minio:9000/fake-url"
        mock_ensure_bucket.return_value = None

        files: list[dict[str, Any]] = [
            {
                "filename": "recording_01.wav",
                "size": 1024000,
                "checksum_sha256": "a" * 64,
            },
            {
                "filename": "recording_02.mp3",
                "size": 512000,
                "checksum_sha256": "b" * 64,
            },
            {
                "filename": "recording_03.flac",
                "size": 768000,
                "checksum_sha256": "c" * 64,
            },
            {
                "filename": "recording_04.ogg",
                "size": 640000,
                "checksum_sha256": "d" * 64,
            },
        ]

        create_response = await client.post(
            f"/api/v1/projects/{test_project_id}/datasets/{test_dataset.id}/upload-sessions",
            headers=auth_headers,
            json={"files": files},
        )

        assert create_response.status_code == 201
        session_data = create_response.json()

        assert session_data["total_files"] == 4
        assert session_data["total_bytes"] == sum(f["size"] for f in files)

        # Verify all formats are accepted
        filenames = {f["original_filename"] for f in session_data["files"]}
        expected = {"recording_01.wav", "recording_02.mp3", "recording_03.flac", "recording_04.ogg"}
        assert filenames == expected
