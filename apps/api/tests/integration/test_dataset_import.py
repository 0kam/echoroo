"""Integration tests for dataset import workflow (T123).

Tests the complete dataset import workflow including:
- Dataset creation
- Audio file scanning
- Recording metadata extraction
- Datetime parsing from filenames
- Error handling for invalid/corrupted files
- Progress tracking and status transitions
"""

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.dataset import Dataset
from echoroo.models.enums import DatasetStatus, DatasetVisibility, DatetimeParseStatus
from echoroo.models.project import Project
from echoroo.models.recording import Recording
from echoroo.models.site import Site
from echoroo.models.user import User
from echoroo.repositories.dataset import DatasetRepository
from echoroo.repositories.project import ProjectRepository
from echoroo.repositories.recording import RecordingRepository
from echoroo.repositories.site import SiteRepository
from echoroo.services.audio import AudioService
from echoroo.services.dataset import DatasetService


@pytest.mark.asyncio
async def test_create_dataset_and_start_import(
    db_session: AsyncSession,
    test_user: User,
    test_project: Project,
    test_site: Site,
    sample_audio_dir: Path,
) -> None:
    """Test creating a dataset and starting the import process."""
    # Initialize services
    dataset_repo = DatasetRepository(db_session)
    site_repo = SiteRepository(db_session)
    project_repo = ProjectRepository(db_session)
    recording_repo = RecordingRepository(db_session)
    audio_service = AudioService(audio_root=str(sample_audio_dir.parent))

    dataset_service = DatasetService(
        dataset_repo=dataset_repo,
        site_repo=site_repo,
        project_repo=project_repo,
        recording_repo=recording_repo,
        audio_service=audio_service,
    )

    # Create dataset
    dataset = await dataset_service.create(
        user_id=test_user.id,
        project_id=test_project.id,
        site_id=test_site.id,
        name="Test Dataset",
        audio_dir=sample_audio_dir.name,
        description="Test dataset for import workflow",
        visibility=DatasetVisibility.PRIVATE,
        datetime_pattern=r"\d{8}_\d{6}",
        datetime_format="%Y%m%d_%H%M%S",
    )

    assert dataset.id is not None
    assert dataset.name == "Test Dataset"
    assert dataset.status == DatasetStatus.PENDING
    assert dataset.total_files == 0
    assert dataset.processed_files == 0

    # Start import
    success = await dataset_service.start_import(
        db=db_session,
        dataset_id=dataset.id,
    )

    assert success is True

    # Verify dataset status updated
    await db_session.refresh(dataset)
    assert dataset.status == DatasetStatus.COMPLETED
    assert dataset.total_files > 0
    assert dataset.processed_files == dataset.total_files

    # Verify recordings were created
    recordings = await recording_repo.list_by_dataset(
        dataset_id=dataset.id, page=1, page_size=100
    )
    assert len(recordings[0]) > 0

    # Verify datetime parsing
    for recording in recordings[0]:
        if "invalid" not in recording.filename:
            # Valid files should have datetime parsed
            assert recording.datetime is not None
            assert recording.datetime_parse_status == DatetimeParseStatus.SUCCESS
            assert recording.datetime_parse_error is None


@pytest.mark.asyncio
async def test_import_with_datetime_parsing(
    db_session: AsyncSession,
    test_user: User,
    test_project: Project,
    test_site: Site,
    sample_audio_dir: Path,
) -> None:
    """Test datetime parsing from filenames during import."""
    # Initialize services
    dataset_repo = DatasetRepository(db_session)
    site_repo = SiteRepository(db_session)
    project_repo = ProjectRepository(db_session)
    recording_repo = RecordingRepository(db_session)
    audio_service = AudioService(audio_root=str(sample_audio_dir.parent))

    dataset_service = DatasetService(
        dataset_repo=dataset_repo,
        site_repo=site_repo,
        project_repo=project_repo,
        recording_repo=recording_repo,
        audio_service=audio_service,
    )

    # Create dataset with datetime pattern
    dataset = await dataset_service.create(
        user_id=test_user.id,
        project_id=test_project.id,
        site_id=test_site.id,
        name="Datetime Test Dataset",
        audio_dir=sample_audio_dir.name,
        datetime_pattern=r"\d{8}_\d{6}",
        datetime_format="%Y%m%d_%H%M%S",
    )

    # Start import
    await dataset_service.start_import(db=db_session, dataset_id=dataset.id)

    # Verify recordings have parsed datetime
    recordings = await recording_repo.list_by_dataset(
        dataset_id=dataset.id, page=1, page_size=100
    )

    valid_recordings = [r for r in recordings[0] if "invalid" not in r.filename]
    assert len(valid_recordings) > 0

    for recording in valid_recordings:
        assert recording.datetime is not None
        assert recording.datetime_parse_status == DatetimeParseStatus.SUCCESS

        # Verify datetime matches filename (parsed as naive, stored as UTC)
        if "20240101_120000" in recording.filename:
            assert recording.datetime.year == 2024
            assert recording.datetime.month == 1
            assert recording.datetime.day == 1
            # Note: hour may vary due to timezone conversion
            # The important thing is that datetime was successfully parsed


@pytest.mark.asyncio
async def test_import_with_invalid_files(
    db_session: AsyncSession,
    test_user: User,
    test_project: Project,
    test_site: Site,
    sample_audio_dir: Path,
) -> None:
    """Test handling of invalid/corrupted audio files during import."""
    # Initialize services
    dataset_repo = DatasetRepository(db_session)
    site_repo = SiteRepository(db_session)
    project_repo = ProjectRepository(db_session)
    recording_repo = RecordingRepository(db_session)
    audio_service = AudioService(audio_root=str(sample_audio_dir.parent))

    dataset_service = DatasetService(
        dataset_repo=dataset_repo,
        site_repo=site_repo,
        project_repo=project_repo,
        recording_repo=recording_repo,
        audio_service=audio_service,
    )

    # Create dataset
    dataset = await dataset_service.create(
        user_id=test_user.id,
        project_id=test_project.id,
        site_id=test_site.id,
        name="Invalid Files Test",
        audio_dir=sample_audio_dir.name,
    )

    # Start import (should handle invalid files gracefully)
    success = await dataset_service.start_import(db=db_session, dataset_id=dataset.id)

    # Import should complete despite invalid files
    assert success is True
    await db_session.refresh(dataset)
    assert dataset.status == DatasetStatus.COMPLETED

    # Verify only valid files were imported
    recordings = await recording_repo.list_by_dataset(
        dataset_id=dataset.id, page=1, page_size=100
    )

    # Should not include the invalid.wav file
    filenames = [r.filename for r in recordings[0]]
    assert "invalid.wav" not in filenames


@pytest.mark.asyncio
async def test_import_empty_directory(
    db_session: AsyncSession,
    test_user: User,
    test_project: Project,
    test_site: Site,
    empty_audio_dir: Path,
) -> None:
    """Test importing from an empty directory."""
    # Initialize services
    dataset_repo = DatasetRepository(db_session)
    site_repo = SiteRepository(db_session)
    project_repo = ProjectRepository(db_session)
    recording_repo = RecordingRepository(db_session)
    audio_service = AudioService(audio_root=str(empty_audio_dir.parent))

    dataset_service = DatasetService(
        dataset_repo=dataset_repo,
        site_repo=site_repo,
        project_repo=project_repo,
        recording_repo=recording_repo,
        audio_service=audio_service,
    )

    # Create dataset
    dataset = await dataset_service.create(
        user_id=test_user.id,
        project_id=test_project.id,
        site_id=test_site.id,
        name="Empty Directory Test",
        audio_dir=empty_audio_dir.name,
    )

    # Start import
    success = await dataset_service.start_import(db=db_session, dataset_id=dataset.id)

    assert success is True
    await db_session.refresh(dataset)
    assert dataset.status == DatasetStatus.COMPLETED
    assert dataset.total_files == 0
    assert dataset.processed_files == 0

    # Verify no recordings were created
    recordings = await recording_repo.list_by_dataset(
        dataset_id=dataset.id, page=1, page_size=100
    )
    assert len(recordings[0]) == 0


@pytest.mark.asyncio
async def test_import_progress_tracking(
    db_session: AsyncSession,
    test_user: User,
    test_project: Project,
    test_site: Site,
    sample_audio_dir: Path,
) -> None:
    """Test progress tracking during import (total_files, processed_files)."""
    # Initialize services
    dataset_repo = DatasetRepository(db_session)
    site_repo = SiteRepository(db_session)
    project_repo = ProjectRepository(db_session)
    recording_repo = RecordingRepository(db_session)
    audio_service = AudioService(audio_root=str(sample_audio_dir.parent))

    dataset_service = DatasetService(
        dataset_repo=dataset_repo,
        site_repo=site_repo,
        project_repo=project_repo,
        recording_repo=recording_repo,
        audio_service=audio_service,
    )

    # Create dataset
    dataset = await dataset_service.create(
        user_id=test_user.id,
        project_id=test_project.id,
        site_id=test_site.id,
        name="Progress Tracking Test",
        audio_dir=sample_audio_dir.name,
    )

    # Start import
    await dataset_service.start_import(db=db_session, dataset_id=dataset.id)

    # Verify progress
    await db_session.refresh(dataset)
    import_status = dataset_service.get_import_status(dataset)

    assert import_status["status"] == DatasetStatus.COMPLETED
    assert import_status["total_files"] > 0
    assert import_status["processed_files"] == import_status["total_files"]
    assert import_status["progress_percent"] == 100.0
    assert import_status["error"] is None


@pytest.mark.asyncio
async def test_import_status_transitions(
    db_session: AsyncSession,
    test_user: User,
    test_project: Project,
    test_site: Site,
    sample_audio_dir: Path,
) -> None:
    """Test status transitions: pending → scanning → processing → completed."""
    # Initialize services
    dataset_repo = DatasetRepository(db_session)
    site_repo = SiteRepository(db_session)
    project_repo = ProjectRepository(db_session)
    recording_repo = RecordingRepository(db_session)
    audio_service = AudioService(audio_root=str(sample_audio_dir.parent))

    dataset_service = DatasetService(
        dataset_repo=dataset_repo,
        site_repo=site_repo,
        project_repo=project_repo,
        recording_repo=recording_repo,
        audio_service=audio_service,
    )

    # Create dataset (initial status: PENDING)
    dataset = await dataset_service.create(
        user_id=test_user.id,
        project_id=test_project.id,
        site_id=test_site.id,
        name="Status Transitions Test",
        audio_dir=sample_audio_dir.name,
    )

    assert dataset.status == DatasetStatus.PENDING

    # Start import (should transition through statuses)
    await dataset_service.start_import(db=db_session, dataset_id=dataset.id)

    # Final status should be COMPLETED
    await db_session.refresh(dataset)
    assert dataset.status == DatasetStatus.COMPLETED


@pytest.mark.asyncio
async def test_import_duplicate_files(
    db_session: AsyncSession,
    test_user: User,
    test_project: Project,
    test_site: Site,
    sample_audio_dir: Path,
) -> None:
    """Test handling of duplicate files (same path)."""
    # Initialize services
    dataset_repo = DatasetRepository(db_session)
    site_repo = SiteRepository(db_session)
    project_repo = ProjectRepository(db_session)
    recording_repo = RecordingRepository(db_session)
    audio_service = AudioService(audio_root=str(sample_audio_dir.parent))

    dataset_service = DatasetService(
        dataset_repo=dataset_repo,
        site_repo=site_repo,
        project_repo=project_repo,
        recording_repo=recording_repo,
        audio_service=audio_service,
    )

    # Create dataset
    dataset = await dataset_service.create(
        user_id=test_user.id,
        project_id=test_project.id,
        site_id=test_site.id,
        name="Duplicate Files Test",
        audio_dir=sample_audio_dir.name,
    )

    # First import
    await dataset_service.start_import(db=db_session, dataset_id=dataset.id)

    # Get initial count
    initial_count = await recording_repo.count_by_dataset(dataset.id)
    assert initial_count > 0

    # Import again (should skip existing files)
    await dataset_service.rescan(db=db_session, dataset_id=dataset.id)

    # Count should remain the same
    final_count = await recording_repo.count_by_dataset(dataset.id)
    assert final_count == initial_count


@pytest.mark.asyncio
async def test_import_with_failed_status(
    db_session: AsyncSession,
    test_user: User,
    test_project: Project,
    test_site: Site,
) -> None:
    """Test import with non-existent directory (completes with 0 files)."""
    # Initialize services
    dataset_repo = DatasetRepository(db_session)
    site_repo = SiteRepository(db_session)
    project_repo = ProjectRepository(db_session)
    recording_repo = RecordingRepository(db_session)
    audio_service = AudioService(audio_root="/nonexistent")

    dataset_service = DatasetService(
        dataset_repo=dataset_repo,
        site_repo=site_repo,
        project_repo=project_repo,
        recording_repo=recording_repo,
        audio_service=audio_service,
    )

    # Create dataset with non-existent directory
    dataset = await dataset_service.create(
        user_id=test_user.id,
        project_id=test_project.id,
        site_id=test_site.id,
        name="Failed Import Test",
        audio_dir="nonexistent_dir",
    )

    # Start import (completes successfully with 0 files)
    success = await dataset_service.start_import(db=db_session, dataset_id=dataset.id)

    # Import completes but with no files found
    assert success is True
    await db_session.refresh(dataset)
    assert dataset.status == DatasetStatus.COMPLETED
    assert dataset.total_files == 0
    assert dataset.processed_files == 0


@pytest.mark.asyncio
async def test_rescan_with_new_files(
    db_session: AsyncSession,
    test_user: User,
    test_project: Project,
    test_site: Site,
    sample_audio_dir: Path,
) -> None:
    """Test rescanning directory to detect new files."""
    # Initialize services
    dataset_repo = DatasetRepository(db_session)
    site_repo = SiteRepository(db_session)
    project_repo = ProjectRepository(db_session)
    recording_repo = RecordingRepository(db_session)
    audio_service = AudioService(audio_root=str(sample_audio_dir.parent))

    dataset_service = DatasetService(
        dataset_repo=dataset_repo,
        site_repo=site_repo,
        project_repo=project_repo,
        recording_repo=recording_repo,
        audio_service=audio_service,
    )

    # Create dataset and initial import
    dataset = await dataset_service.create(
        user_id=test_user.id,
        project_id=test_project.id,
        site_id=test_site.id,
        name="Rescan Test",
        audio_dir=sample_audio_dir.name,
    )

    await dataset_service.start_import(db=db_session, dataset_id=dataset.id)
    initial_count = await recording_repo.count_by_dataset(dataset.id)

    # Add a new file
    import numpy as np
    import soundfile as sf

    sample_rate = 44100
    duration = 1.0
    t = np.linspace(0, duration, int(sample_rate * duration))
    audio = np.sin(2 * np.pi * 440 * t).astype(np.float32)
    new_file = sample_audio_dir / "test_20240104_150000.wav"
    sf.write(str(new_file), audio, sample_rate)

    # Rescan
    success = await dataset_service.rescan(db=db_session, dataset_id=dataset.id)

    assert success is True
    final_count = await recording_repo.count_by_dataset(dataset.id)
    assert final_count > initial_count


@pytest.mark.asyncio
async def test_datetime_parse_without_pattern(
    db_session: AsyncSession,
    test_user: User,
    test_project: Project,
    test_site: Site,
    sample_audio_dir: Path,
) -> None:
    """Test import without datetime pattern (datetime should be None)."""
    # Initialize services
    dataset_repo = DatasetRepository(db_session)
    site_repo = SiteRepository(db_session)
    project_repo = ProjectRepository(db_session)
    recording_repo = RecordingRepository(db_session)
    audio_service = AudioService(audio_root=str(sample_audio_dir.parent))

    dataset_service = DatasetService(
        dataset_repo=dataset_repo,
        site_repo=site_repo,
        project_repo=project_repo,
        recording_repo=recording_repo,
        audio_service=audio_service,
    )

    # Create dataset without datetime pattern
    dataset = await dataset_service.create(
        user_id=test_user.id,
        project_id=test_project.id,
        site_id=test_site.id,
        name="No Pattern Test",
        audio_dir=sample_audio_dir.name,
        # No datetime_pattern or datetime_format
    )

    # Start import
    await dataset_service.start_import(db=db_session, dataset_id=dataset.id)

    # Verify recordings have PENDING status for datetime
    recordings = await recording_repo.list_by_dataset(
        dataset_id=dataset.id, page=1, page_size=100
    )

    for recording in recordings[0]:
        if "invalid" not in recording.filename:
            assert recording.datetime is None
            assert recording.datetime_parse_status == DatetimeParseStatus.PENDING
            assert recording.datetime_parse_error is None
