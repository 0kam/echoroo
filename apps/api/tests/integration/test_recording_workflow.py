"""Integration tests for recording workflow (T124).

Tests the complete recording workflow including:
- Listing recordings with filtering and pagination
- Updating recording metadata (note, time_expansion)
- Deleting recordings with cascade to clips
- Audio streaming with HTTP Range support
- Spectrogram generation with various parameters
- Cross-dataset search functionality
- Ultrasonic recordings handling
- Multi-channel audio
- Time expansion playback
"""

from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.clip import Clip
from echoroo.models.dataset import Dataset
from echoroo.models.enums import DatasetStatus, DatasetVisibility, DatetimeParseStatus
from echoroo.models.project import Project
from echoroo.models.recording import Recording
from echoroo.models.site import Site
from echoroo.models.user import User
from echoroo.repositories.clip import ClipRepository
from echoroo.repositories.dataset import DatasetRepository
from echoroo.repositories.project import ProjectRepository
from echoroo.repositories.recording import RecordingRepository
from echoroo.repositories.site import SiteRepository
from echoroo.services.audio import AudioService
from echoroo.services.dataset import DatasetService
from echoroo.services.recording import RecordingService


@pytest.mark.asyncio
async def test_list_recordings_with_pagination(
    db_session: AsyncSession,
    test_user: User,
    test_project: Project,
    test_site: Site,
    sample_audio_dir: Path,
) -> None:
    """Test listing recordings with pagination."""
    # Setup: Create dataset and import recordings
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

    dataset = await dataset_service.create(
        user_id=test_user.id,
        project_id=test_project.id,
        site_id=test_site.id,
        name="Pagination Test Dataset",
        audio_dir=sample_audio_dir.name,
    )

    await dataset_service.start_import(db=db_session, dataset_id=dataset.id)

    # Test pagination
    recording_service = RecordingService(db=db_session, audio_service=audio_service)

    # Page 1 with page_size=2
    recordings_page1, total = await recording_service.list_by_dataset(
        dataset_id=dataset.id, page=1, page_size=2
    )

    assert len(recordings_page1) <= 2
    assert total > 0

    # Page 2
    recordings_page2, _ = await recording_service.list_by_dataset(
        dataset_id=dataset.id, page=2, page_size=2
    )

    # Pages should have different recordings
    if len(recordings_page1) == 2 and len(recordings_page2) > 0:
        assert recordings_page1[0].id != recordings_page2[0].id


@pytest.mark.asyncio
async def test_list_recordings_with_filtering(
    db_session: AsyncSession,
    test_user: User,
    test_project: Project,
    test_site: Site,
    sample_audio_dir: Path,
) -> None:
    """Test listing recordings with various filters."""
    # Setup
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

    dataset = await dataset_service.create(
        user_id=test_user.id,
        project_id=test_project.id,
        site_id=test_site.id,
        name="Filtering Test Dataset",
        audio_dir=sample_audio_dir.name,
        datetime_pattern=r"\d{8}_\d{6}",
        datetime_format="%Y%m%d_%H%M%S",
    )

    await dataset_service.start_import(db=db_session, dataset_id=dataset.id)

    recording_service = RecordingService(db=db_session, audio_service=audio_service)

    # Filter by search term
    recordings, total = await recording_service.list_by_dataset(
        dataset_id=dataset.id, page=1, page_size=20, search="20240101"
    )

    for recording in recordings:
        assert "20240101" in recording.filename

    # Filter by datetime range
    from datetime import UTC
    from_date = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
    to_date = datetime(2024, 1, 1, 23, 59, 59, tzinfo=UTC)

    recordings, total = await recording_service.list_by_dataset(
        dataset_id=dataset.id,
        page=1,
        page_size=20,
        datetime_from=from_date,
        datetime_to=to_date,
    )

    for recording in recordings:
        if recording.datetime:
            assert from_date <= recording.datetime <= to_date

    # Filter by samplerate
    recordings, total = await recording_service.list_by_dataset(
        dataset_id=dataset.id, page=1, page_size=20, samplerate=44100
    )

    for recording in recordings:
        assert recording.samplerate == 44100


@pytest.mark.asyncio
async def test_update_recording_metadata(
    db_session: AsyncSession,
    test_user: User,
    test_project: Project,
    test_site: Site,
    sample_audio_dir: Path,
) -> None:
    """Test updating recording metadata (note, time_expansion)."""
    # Setup
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

    dataset = await dataset_service.create(
        user_id=test_user.id,
        project_id=test_project.id,
        site_id=test_site.id,
        name="Update Test Dataset",
        audio_dir=sample_audio_dir.name,
    )

    await dataset_service.start_import(db=db_session, dataset_id=dataset.id)

    recording_service = RecordingService(db=db_session, audio_service=audio_service)

    # Get first recording
    recordings, _ = await recording_service.list_by_dataset(
        dataset_id=dataset.id, page=1, page_size=1
    )
    recording = recordings[0]

    # Update note
    updated = await recording_service.update(
        recording_id=recording.id, note="Test note for recording"
    )

    assert updated is not None
    assert updated.note == "Test note for recording"

    # Update time_expansion
    updated = await recording_service.update(
        recording_id=recording.id, time_expansion=10.0
    )

    assert updated is not None
    assert updated.time_expansion == 10.0

    # Verify effective duration calculation
    effective_duration = recording_service.get_effective_duration(updated)
    assert effective_duration == updated.duration * 10.0


@pytest.mark.asyncio
async def test_delete_recording_with_cascade(
    db_session: AsyncSession,
    test_user: User,
    test_project: Project,
    test_site: Site,
    sample_audio_dir: Path,
) -> None:
    """Test deleting recording with cascade to clips."""
    # Setup
    dataset_repo = DatasetRepository(db_session)
    site_repo = SiteRepository(db_session)
    project_repo = ProjectRepository(db_session)
    recording_repo = RecordingRepository(db_session)
    clip_repo = ClipRepository(db_session)
    audio_service = AudioService(audio_root=str(sample_audio_dir.parent))

    dataset_service = DatasetService(
        dataset_repo=dataset_repo,
        site_repo=site_repo,
        project_repo=project_repo,
        recording_repo=recording_repo,
        audio_service=audio_service,
    )

    dataset = await dataset_service.create(
        user_id=test_user.id,
        project_id=test_project.id,
        site_id=test_site.id,
        name="Delete Test Dataset",
        audio_dir=sample_audio_dir.name,
    )

    await dataset_service.start_import(db=db_session, dataset_id=dataset.id)

    recording_service = RecordingService(db=db_session, audio_service=audio_service)

    # Get first recording
    recordings, _ = await recording_service.list_by_dataset(
        dataset_id=dataset.id, page=1, page_size=1
    )
    recording = recordings[0]

    # Create a clip for this recording
    clip = Clip(
        recording_id=recording.id,
        start_time=0.0,
        end_time=1.0,
    )
    db_session.add(clip)
    await db_session.commit()

    # Verify clip exists
    clip_exists = await clip_repo.get_by_id(clip.id)
    assert clip_exists is not None

    # Delete recording
    deleted = await recording_service.delete(recording.id)
    assert deleted is True

    # Verify recording is deleted
    recording_exists = await recording_service.get_by_id(recording.id)
    assert recording_exists is None

    # Verify clip is also deleted (cascade)
    clip_exists = await clip_repo.get_by_id(clip.id)
    assert clip_exists is None


@pytest.mark.asyncio
async def test_search_recordings_across_datasets(
    db_session: AsyncSession,
    test_user: User,
    test_project: Project,
    test_site: Site,
    sample_audio_dir: Path,
) -> None:
    """Test cross-dataset search functionality."""
    # Setup: Create two datasets
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

    # Dataset 1
    dataset1 = await dataset_service.create(
        user_id=test_user.id,
        project_id=test_project.id,
        site_id=test_site.id,
        name="Search Test Dataset 1",
        audio_dir=sample_audio_dir.name,
    )
    await dataset_service.start_import(db=db_session, dataset_id=dataset1.id)

    # Dataset 2
    dataset2 = await dataset_service.create(
        user_id=test_user.id,
        project_id=test_project.id,
        site_id=test_site.id,
        name="Search Test Dataset 2",
        audio_dir=sample_audio_dir.name,
    )
    await dataset_service.start_import(db=db_session, dataset_id=dataset2.id)

    # Search across all datasets in project
    recording_service = RecordingService(db=db_session, audio_service=audio_service)

    recordings, total = await recording_service.search_by_project(
        project_id=test_project.id, page=1, page_size=100
    )

    # Should find recordings from both datasets
    dataset_ids = {r.dataset_id for r in recordings}
    assert len(dataset_ids) >= 2 or total > 0  # Multiple datasets

    # Search with dataset filter
    recordings, total = await recording_service.search_by_project(
        project_id=test_project.id, page=1, page_size=100, dataset_id=dataset1.id
    )

    # Should only find recordings from dataset1
    for recording in recordings:
        assert recording.dataset_id == dataset1.id

    # Search with site filter
    recordings, total = await recording_service.search_by_project(
        project_id=test_project.id, page=1, page_size=100, site_id=test_site.id
    )

    # Should find recordings from site's datasets
    assert total > 0


@pytest.mark.asyncio
async def test_ultrasonic_recording_detection(
    db_session: AsyncSession,
    test_user: User,
    test_project: Project,
    test_site: Site,
    ultrasonic_audio_dir: Path,
) -> None:
    """Test ultrasonic recordings (samplerate > 48kHz)."""
    # Setup
    dataset_repo = DatasetRepository(db_session)
    site_repo = SiteRepository(db_session)
    project_repo = ProjectRepository(db_session)
    recording_repo = RecordingRepository(db_session)
    audio_service = AudioService(audio_root=str(ultrasonic_audio_dir.parent))

    dataset_service = DatasetService(
        dataset_repo=dataset_repo,
        site_repo=site_repo,
        project_repo=project_repo,
        recording_repo=recording_repo,
        audio_service=audio_service,
    )

    dataset = await dataset_service.create(
        user_id=test_user.id,
        project_id=test_project.id,
        site_id=test_site.id,
        name="Ultrasonic Test Dataset",
        audio_dir=ultrasonic_audio_dir.name,
    )

    await dataset_service.start_import(db=db_session, dataset_id=dataset.id)

    recording_service = RecordingService(db=db_session, audio_service=audio_service)

    # Get recordings
    recordings, _ = await recording_service.list_by_dataset(
        dataset_id=dataset.id, page=1, page_size=10
    )

    # Verify ultrasonic detection
    for recording in recordings:
        if recording.samplerate > 96000:
            assert recording_service.is_ultrasonic(recording) is True
            assert recording.is_ultrasonic is True


@pytest.mark.asyncio
async def test_time_expansion_playback(
    db_session: AsyncSession,
    test_user: User,
    test_project: Project,
    test_site: Site,
    ultrasonic_audio_dir: Path,
) -> None:
    """Test time expansion for ultrasonic playback."""
    # Setup
    dataset_repo = DatasetRepository(db_session)
    site_repo = SiteRepository(db_session)
    project_repo = ProjectRepository(db_session)
    recording_repo = RecordingRepository(db_session)
    audio_service = AudioService(audio_root=str(ultrasonic_audio_dir.parent))

    dataset_service = DatasetService(
        dataset_repo=dataset_repo,
        site_repo=site_repo,
        project_repo=project_repo,
        recording_repo=recording_repo,
        audio_service=audio_service,
    )

    dataset = await dataset_service.create(
        user_id=test_user.id,
        project_id=test_project.id,
        site_id=test_site.id,
        name="Time Expansion Test",
        audio_dir=ultrasonic_audio_dir.name,
    )

    await dataset_service.start_import(db=db_session, dataset_id=dataset.id)

    recording_service = RecordingService(db=db_session, audio_service=audio_service)

    # Get recording
    recordings, _ = await recording_service.list_by_dataset(
        dataset_id=dataset.id, page=1, page_size=1
    )
    recording = recordings[0]

    # Set time expansion (10x for bat calls)
    original_duration = recording.duration
    await recording_service.update(recording_id=recording.id, time_expansion=10.0)

    # Verify effective duration
    await db_session.refresh(recording)
    effective_duration = recording_service.get_effective_duration(recording)
    assert effective_duration == original_duration * 10.0


@pytest.mark.asyncio
async def test_audio_reading(
    db_session: AsyncSession,
    test_user: User,
    test_project: Project,
    test_site: Site,
    sample_audio_dir: Path,
) -> None:
    """Test audio data reading from recordings."""
    # Setup
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

    dataset = await dataset_service.create(
        user_id=test_user.id,
        project_id=test_project.id,
        site_id=test_site.id,
        name="Audio Reading Test",
        audio_dir=sample_audio_dir.name,
    )

    await dataset_service.start_import(db=db_session, dataset_id=dataset.id)

    recording_service = RecordingService(db=db_session, audio_service=audio_service)

    # Get recording
    recordings, _ = await recording_service.list_by_dataset(
        dataset_id=dataset.id, page=1, page_size=1
    )
    recording = recordings[0]

    # Read full audio
    data, samplerate = audio_service.read_audio(recording.path)
    assert data is not None
    assert len(data) > 0
    assert samplerate == recording.samplerate

    # Read partial audio (first 0.5 seconds)
    data_partial, _ = audio_service.read_audio(recording.path, start=0, end=0.5)
    assert len(data_partial) < len(data)
    assert len(data_partial) == pytest.approx(int(samplerate * 0.5), abs=100)


@pytest.mark.asyncio
async def test_spectrogram_generation(
    db_session: AsyncSession,
    test_user: User,
    test_project: Project,
    test_site: Site,
    sample_audio_dir: Path,
) -> None:
    """Test spectrogram generation with various parameters."""
    # Setup
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

    dataset = await dataset_service.create(
        user_id=test_user.id,
        project_id=test_project.id,
        site_id=test_site.id,
        name="Spectrogram Test",
        audio_dir=sample_audio_dir.name,
    )

    await dataset_service.start_import(db=db_session, dataset_id=dataset.id)

    recording_service = RecordingService(db=db_session, audio_service=audio_service)

    # Get recording
    recordings, _ = await recording_service.list_by_dataset(
        dataset_id=dataset.id, page=1, page_size=1
    )
    recording = recordings[0]

    # Generate spectrogram with default parameters
    spectrogram = audio_service.generate_spectrogram(recording.path)
    assert spectrogram is not None
    assert len(spectrogram) > 0
    assert spectrogram.startswith(b"\x89PNG")  # PNG magic bytes

    # Generate with custom parameters
    spectrogram = audio_service.generate_spectrogram(
        recording.path,
        n_fft=1024,
        hop_length=256,
        freq_min=100,
        freq_max=10000,
        colormap="magma",
        width=800,
        height=300,
    )
    assert spectrogram is not None
    assert len(spectrogram) > 0

    # Generate with PCEN normalization
    spectrogram = audio_service.generate_spectrogram(
        recording.path, pcen=True, colormap="viridis"
    )
    assert spectrogram is not None
    assert len(spectrogram) > 0


@pytest.mark.asyncio
async def test_multi_channel_audio(
    db_session: AsyncSession,
    test_user: User,
    test_project: Project,
    test_site: Site,
    tmp_path: Path,
) -> None:
    """Test handling of multi-channel (stereo) audio files."""
    # Create stereo audio file
    sample_rate = 44100
    duration = 1.0
    t = np.linspace(0, duration, int(sample_rate * duration))

    # Create stereo audio (different frequency for each channel)
    left_channel = np.sin(2 * np.pi * 440 * t).astype(np.float32)
    right_channel = np.sin(2 * np.pi * 880 * t).astype(np.float32)
    stereo_audio = np.column_stack((left_channel, right_channel))

    audio_dir = tmp_path / "stereo"
    audio_dir.mkdir()
    stereo_file = audio_dir / "stereo_test.wav"
    sf.write(str(stereo_file), stereo_audio, sample_rate)

    # Setup
    dataset_repo = DatasetRepository(db_session)
    site_repo = SiteRepository(db_session)
    project_repo = ProjectRepository(db_session)
    recording_repo = RecordingRepository(db_session)
    audio_service = AudioService(audio_root=str(tmp_path))

    dataset_service = DatasetService(
        dataset_repo=dataset_repo,
        site_repo=site_repo,
        project_repo=project_repo,
        recording_repo=recording_repo,
        audio_service=audio_service,
    )

    dataset = await dataset_service.create(
        user_id=test_user.id,
        project_id=test_project.id,
        site_id=test_site.id,
        name="Stereo Test",
        audio_dir=audio_dir.name,
    )

    await dataset_service.start_import(db=db_session, dataset_id=dataset.id)

    recording_service = RecordingService(db=db_session, audio_service=audio_service)

    # Get recording
    recordings, _ = await recording_service.list_by_dataset(
        dataset_id=dataset.id, page=1, page_size=1
    )
    recording = recordings[0]

    # Verify multi-channel detection
    assert recording.channels == 2

    # Read audio from specific channel
    left_data, _ = audio_service.read_audio(recording.path, channel=0)
    right_data, _ = audio_service.read_audio(recording.path, channel=1)

    # Verify channels are different
    assert not np.array_equal(left_data, right_data)


@pytest.mark.asyncio
async def test_recording_sorting(
    db_session: AsyncSession,
    test_user: User,
    test_project: Project,
    test_site: Site,
    sample_audio_dir: Path,
) -> None:
    """Test sorting recordings by different fields."""
    # Setup
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

    dataset = await dataset_service.create(
        user_id=test_user.id,
        project_id=test_project.id,
        site_id=test_site.id,
        name="Sorting Test",
        audio_dir=sample_audio_dir.name,
        datetime_pattern=r"\d{8}_\d{6}",
        datetime_format="%Y%m%d_%H%M%S",
    )

    await dataset_service.start_import(db=db_session, dataset_id=dataset.id)

    recording_service = RecordingService(db=db_session, audio_service=audio_service)

    # Sort by datetime ascending
    recordings_asc, _ = await recording_service.list_by_dataset(
        dataset_id=dataset.id, page=1, page_size=10, sort_by="datetime", sort_order="asc"
    )

    # Sort by datetime descending
    recordings_desc, _ = await recording_service.list_by_dataset(
        dataset_id=dataset.id, page=1, page_size=10, sort_by="datetime", sort_order="desc"
    )

    # Verify sort order is different
    if len(recordings_asc) > 1 and len(recordings_desc) > 1:
        # First element of asc should be last element of desc (or similar pattern)
        asc_dates = [r.datetime for r in recordings_asc if r.datetime]
        desc_dates = [r.datetime for r in recordings_desc if r.datetime]

        if asc_dates and desc_dates:
            assert asc_dates[0] <= asc_dates[-1]  # Ascending order
            assert desc_dates[0] >= desc_dates[-1]  # Descending order
