"""Fixtures for integration tests."""

import tempfile
from pathlib import Path
from uuid import UUID

import numpy as np
import pytest
import soundfile as sf
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.jwt import create_access_token
from echoroo.models.enums import ProjectRole
from echoroo.models.project import Project, ProjectMember
from echoroo.models.site import Site
from echoroo.models.user import User


@pytest.fixture
async def test_user(db_session: AsyncSession) -> User:
    """Create a test user for integration tests.

    Args:
        db_session: Database session

    Returns:
        Test user instance
    """
    user = User(
        email="integrationtest@example.com",
        hashed_password="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="Integration Test User",
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def auth_headers(db_session: AsyncSession, test_user: User) -> dict[str, str]:
    """Create authentication headers for test user.

    Args:
        db_session: Database session
        test_user: Test user

    Returns:
        Headers with Bearer token
    """
    access_token = create_access_token({"sub": str(test_user.id)})
    return {"Authorization": f"Bearer {access_token}"}


@pytest.fixture
async def test_project(db_session: AsyncSession, test_user: User) -> Project:
    """Create a test project with test user as admin.

    Args:
        db_session: Database session
        test_user: Test user

    Returns:
        Test project instance
    """
    project = Project(
        name="Test Project",
        description="Test project for integration tests",
        owner_id=test_user.id,
    )
    db_session.add(project)
    await db_session.flush()

    # Add test user as admin
    member = ProjectMember(
        project_id=project.id,
        user_id=test_user.id,
        role=ProjectRole.ADMIN,
    )
    db_session.add(member)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest.fixture
async def test_site(db_session: AsyncSession, test_project: Project) -> Site:
    """Create a test site for the test project.

    Args:
        db_session: Database session
        test_project: Test project

    Returns:
        Test site instance
    """
    site = Site(
        project_id=test_project.id,
        name="Test Site",
        h3_index="851fb46ffffffff",  # Valid H3 index
    )
    db_session.add(site)
    await db_session.commit()
    await db_session.refresh(site)
    return site


@pytest.fixture
def sample_audio_dir(tmp_path: Path) -> Path:
    """Create a directory with sample audio files.

    Args:
        tmp_path: Pytest temporary directory

    Returns:
        Path to the directory containing sample audio files
    """
    # Create sample audio files with different characteristics
    sample_rate = 44100
    duration = 1.0  # 1 second
    t = np.linspace(0, duration, int(sample_rate * duration))

    # Create valid audio files with datetime in filename
    audio_files = [
        ("test_20240101_120000.wav", 440),  # A4 note
        ("test_20240101_130000.wav", 880),  # A5 note
        ("test_20240102_090000.wav", 220),  # A3 note
    ]

    for filename, frequency in audio_files:
        audio = np.sin(2 * np.pi * frequency * t).astype(np.float32)
        file_path = tmp_path / filename
        sf.write(str(file_path), audio, sample_rate)

    # Create an invalid/corrupted file (text file with .wav extension)
    invalid_file = tmp_path / "invalid.wav"
    invalid_file.write_text("This is not a valid audio file")

    # Create a subdirectory with more files
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    audio = np.sin(2 * np.pi * 440 * t).astype(np.float32)
    sf.write(str(subdir / "test_20240103_140000.wav"), audio, sample_rate)

    return tmp_path


@pytest.fixture
def empty_audio_dir(tmp_path: Path) -> Path:
    """Create an empty directory for testing empty import.

    Args:
        tmp_path: Pytest temporary directory

    Returns:
        Path to empty directory
    """
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    return empty_dir


@pytest.fixture
def ultrasonic_audio_dir(tmp_path: Path) -> Path:
    """Create directory with ultrasonic audio files (high samplerate).

    Args:
        tmp_path: Pytest temporary directory

    Returns:
        Path to directory with ultrasonic audio files
    """
    # Create ultrasonic recording (250 kHz samplerate for bat detection)
    sample_rate = 250000
    duration = 0.5  # 0.5 seconds
    t = np.linspace(0, duration, int(sample_rate * duration))

    # Create ultrasonic frequency sweep (20-100 kHz)
    frequencies = np.linspace(20000, 100000, len(t))
    audio = np.sin(2 * np.pi * frequencies * t).astype(np.float32)

    file_path = tmp_path / "ultrasonic_20240101_200000.wav"
    sf.write(str(file_path), audio, sample_rate)

    return tmp_path
