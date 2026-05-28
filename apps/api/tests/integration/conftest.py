"""Fixtures for integration tests."""

from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.jwt import create_access_token
from echoroo.models.enums import (
    ProjectLicense,
    ProjectMemberRole,
    ProjectVisibility,
)
from echoroo.models.project import Project, ProjectMember
from echoroo.models.site import Site
from echoroo.models.user import User
from tests._kms_moto import provision_moto_kms
from tests.conftest import ensure_test_database_schema_sync


@pytest.fixture(scope="session", autouse=True)
def _ensure_test_database_schema_for_integration() -> None:
    """Session-scoped autouse fixture that ensures the test DB schema is current.

    Phase 17 §D-0 follow-up (2026-05-08): moved out of root ``tests/conftest.py``
    so ``tests/runbook/`` smoke tests (which have no Postgres available) no
    longer crash at session start with ``OSError: Connect call failed``.
    """
    ensure_test_database_schema_sync()


# ---------------------------------------------------------------------------
# PR-C5 (Phase 17 §C, 2026-05-07): autouse moto-backed KMS fixture.
#
# Prior to PR-C5 every integration test that hit ``compute_pii_hash`` (login,
# password reset, invitation enumeration, ``confirm_identity``) routed boto3
# straight at real AWS (or LocalStack via the dev-container endpoint env)
# producing ``UnrecognizedClientException`` / ``NoCredentialsError``.
# The autouse fixture below provisions a fresh moto KMS for every integration
# test, mirroring :func:`tests.unit.core.test_kms.kms_env`.
#
# The fixture is autouse + function-scoped so test isolation is preserved
# (each test gets fresh CMKs, no state leakage). Production code is
# untouched — only the test environment is patched.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True, scope="function")
def _integration_moto_kms(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[dict[str, str]]:
    """Provide a moto-backed KMS to every integration test.

    The moto context manager + env wiring lives in
    :func:`tests._kms_moto.provision_moto_kms`. See that module for the
    rationale and the alias-to-keyid mapping returned via ``yield``.
    """
    with provision_moto_kms(monkeypatch) as ids:
        yield ids

# Phase 16 Batch 6e (2026-04-29) downstream drift fix: Phase 7 / T320
# (FR-085) made ``license`` NOT NULL on ``projects``. Phase 11 added the
# ``ck_projects_restricted_config_shape`` CHECK that requires the eight
# canonical toggle keys when ``visibility = 'restricted'``. The shared
# integration ``test_project`` fixture must populate both so the legacy
# upload / annotation / review workflows continue to flow through the
# project-create step without 22NotNull on PG insert.
_DEFAULT_RESTRICTED_CONFIG: dict[str, object] = {
    "allow_media_playback": False,
    "allow_detection_view": False,
    "mask_species_in_detection": False,
    "allow_download": False,
    "allow_export": False,
    "allow_voting_and_comments": False,
    "public_location_precision_h3_res": 3,
    "allow_precise_location_to_viewer": False,
}


@pytest.fixture
def test_project_id(test_project: Project) -> str:
    """Get test project ID as string.

    Args:
        test_project: Test project

    Returns:
        Project UUID as string
    """
    return str(test_project.id)


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
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="Integration Test User",
        security_stamp="integration-stamp-test",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def member_user(db_session: AsyncSession) -> User:
    """Create a test member user for integration tests.

    Args:
        db_session: Database session

    Returns:
        Test member user instance
    """
    user = User(
        email="integrationmember@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="Integration Member User",
        security_stamp="integration-stamp-member",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def other_user(db_session: AsyncSession) -> User:
    """Create a test user with no project access for integration tests.

    Args:
        db_session: Database session

    Returns:
        Test user instance (no project access)
    """
    user = User(
        email="integrationother@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="Integration Other User",
        security_stamp="integration-stamp-other",
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
async def auth_headers_member(db_session: AsyncSession, member_user: User) -> dict[str, str]:
    """Create authentication headers for member user.

    Args:
        db_session: Database session
        member_user: Member test user

    Returns:
        Headers with Bearer token
    """
    access_token = create_access_token({"sub": str(member_user.id)})
    return {"Authorization": f"Bearer {access_token}"}


@pytest.fixture
async def auth_headers_other(db_session: AsyncSession, other_user: User) -> dict[str, str]:
    """Create authentication headers for other user (no project access).

    Args:
        db_session: Database session
        other_user: Other test user

    Returns:
        Headers with Bearer token
    """
    access_token = create_access_token({"sub": str(other_user.id)})
    return {"Authorization": f"Bearer {access_token}"}


@pytest.fixture
async def test_project(db_session: AsyncSession, test_user: User, member_user: User) -> Project:
    """Create a test project with test user as admin and member_user as member.

    Args:
        db_session: Database session
        test_user: Test user (admin)
        member_user: Member test user

    Returns:
        Test project instance
    """
    project = Project(
        name="Test Project",
        description="Test project for integration tests",
        owner_id=test_user.id,
        # Phase 16 Batch 6e drift fix: Phase 7 made license NOT NULL.
        license_id="cc-by",
        visibility=ProjectVisibility.RESTRICTED,
        restricted_config=dict(_DEFAULT_RESTRICTED_CONFIG),
    )
    db_session.add(project)
    await db_session.flush()

    # Add test user as admin
    admin_member = ProjectMember(
        project_id=project.id,
        user_id=test_user.id,
        role=ProjectMemberRole.ADMIN,
        invited_by_id=test_user.id,
    )
    db_session.add(admin_member)

    # Add member_user as member
    member = ProjectMember(
        project_id=project.id,
        user_id=member_user.id,
        role=ProjectMemberRole.MEMBER,
        invited_by_id=test_user.id,
    )
    db_session.add(member)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest.fixture
async def test_member(db_session: AsyncSession, test_project: Project, member_user: User) -> ProjectMember:
    """Get the project member relationship for member_user.

    Args:
        db_session: Database session
        test_project: Test project
        member_user: Member test user

    Returns:
        Project member instance
    """
    # Query explicitly to avoid lazy-loading issues in async context
    from sqlalchemy import select

    result = await db_session.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == test_project.id,
            ProjectMember.user_id == member_user.id,
        )
    )
    member = result.scalar_one_or_none()
    if member:
        return member
    # Fallback: create if not found (shouldn't happen)
    member = ProjectMember(
        project_id=test_project.id,
        user_id=member_user.id,
        role=ProjectMemberRole.MEMBER,
        invited_by_id=test_project.owner_id,
    )
    db_session.add(member)
    await db_session.commit()
    await db_session.refresh(member)
    return member


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
        h3_index_member="851fb46ffffffff",  # Valid H3 index
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
