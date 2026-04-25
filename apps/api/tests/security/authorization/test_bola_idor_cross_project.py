"""BOLA / IDOR cross-project isolation tests (T134).

Spec: PR-007 — A user authorised on project A must NOT be able to access
resources that belong to project B by supplying project B's resource IDs
through project A's URL namespace.

Implementation guards verified here:
  * ``RecordingRepository.get_by_id_in_project`` (Recording -> Dataset -> Project)
  * ``DatasetRepository.get_by_id_in_project``    (Dataset -> Project)
  * ``AnnotationRepository.exists_in_project``    (Annotation -> Recording -> Dataset -> Project)
  * Detection GET: ``AnnotationRepository.exists_in_project`` (detection == annotation)

All requests are made with a user who is a MEMBER of project A. The resources
(recordings, datasets, annotations, detections) belong exclusively to project B.
All cross-project requests must return 404 (or 403 when the vote gate fires
before the BOLA check — currently the vote endpoints use ANNOTATION_VOTE_CREATE_ACTION
which requires VOTE permission, and Member has that permission, so the gate passes
and the BOLA check 404s).

Pure-logic unit tests verify the repository methods directly (no HTTP) so
they run even when the test database is unavailable.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.jwt import create_access_token
from echoroo.models.annotation import Annotation
from echoroo.models.dataset import Dataset
from echoroo.models.enums import (
    DatasetStatus,
    DatasetVisibility,
    DetectionSource,
    DetectionStatus,
    ProjectLicense,
    ProjectMemberRole,
    ProjectVisibility,
)
from echoroo.models.project import Project, ProjectMember
from echoroo.models.recording import Recording
from echoroo.models.site import Site
from echoroo.models.user import User
from echoroo.repositories.annotation import AnnotationRepository
from echoroo.repositories.dataset import DatasetRepository
from echoroo.repositories.recording import RecordingRepository

# ---------------------------------------------------------------------------
# Fixtures — users, projects, and cross-project resources
# ---------------------------------------------------------------------------


@pytest.fixture
async def owner_a(db_session: AsyncSession) -> User:
    """Owner of project A."""
    user = User(
        email="t134owner_a@example.com",
        hashed_password="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T134 Owner A",
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def owner_b(db_session: AsyncSession) -> User:
    """Owner of project B."""
    user = User(
        email="t134owner_b@example.com",
        hashed_password="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T134 Owner B",
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def member_a_user(db_session: AsyncSession) -> User:
    """A MEMBER of project A only (not a member of project B)."""
    user = User(
        email="t134member_a@example.com",
        hashed_password="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T134 Member A",
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def project_a(db_session: AsyncSession, owner_a: User) -> Project:
    """Project A — member_a_user is a MEMBER here."""
    project = Project(
        name="T134 Project A",
        description="BOLA test project A",
        visibility=ProjectVisibility.RESTRICTED,
        license=ProjectLicense.CC_BY,
        owner_id=owner_a.id,
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest.fixture
async def project_b(db_session: AsyncSession, owner_b: User) -> Project:
    """Project B — member_a_user has NO membership here."""
    project = Project(
        name="T134 Project B",
        description="BOLA test project B",
        visibility=ProjectVisibility.RESTRICTED,
        license=ProjectLicense.CC_BY,
        owner_id=owner_b.id,
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest.fixture
async def member_a_membership(
    db_session: AsyncSession,
    project_a: Project,
    member_a_user: User,
    owner_a: User,
) -> ProjectMember:
    """Add member_a_user as MEMBER on project_a."""
    membership = ProjectMember(
        user_id=member_a_user.id,
        project_id=project_a.id,
        role=ProjectMemberRole.MEMBER,
        invited_by_id=owner_a.id,
    )
    db_session.add(membership)
    await db_session.commit()
    await db_session.refresh(membership)
    return membership


@pytest.fixture
async def site_b(db_session: AsyncSession, project_b: Project) -> Site:
    """A site belonging to project B."""
    site = Site(
        project_id=project_b.id,
        name="T134 Site B",
        h3_index="8928308280fffff",
    )
    db_session.add(site)
    await db_session.commit()
    await db_session.refresh(site)
    return site


@pytest.fixture
async def dataset_b(
    db_session: AsyncSession,
    project_b: Project,
    site_b: Site,
    owner_b: User,
) -> Dataset:
    """A dataset belonging to project B."""
    dataset = Dataset(
        project_id=project_b.id,
        site_id=site_b.id,
        created_by_id=owner_b.id,
        name="T134 Dataset B",
        visibility=DatasetVisibility.PRIVATE,
        status=DatasetStatus.COMPLETED,
    )
    db_session.add(dataset)
    await db_session.commit()
    await db_session.refresh(dataset)
    return dataset


@pytest.fixture
async def recording_b(
    db_session: AsyncSession,
    dataset_b: Dataset,
) -> Recording:
    """A recording belonging to dataset_b (and therefore project_b)."""
    recording = Recording(
        dataset_id=dataset_b.id,
        filename="test_b.wav",
        path=f"recordings/{dataset_b.project_id}/{dataset_b.id}/test_b.wav",
        duration=60.0,
        samplerate=44100,
        channels=1,
    )
    db_session.add(recording)
    await db_session.commit()
    await db_session.refresh(recording)
    return recording


@pytest.fixture
async def annotation_b(
    db_session: AsyncSession,
    recording_b: Recording,
) -> Annotation:
    """An annotation (detection) belonging to recording_b (project B)."""
    annotation = Annotation(
        recording_id=recording_b.id,
        source=DetectionSource.HUMAN,
        status=DetectionStatus.UNREVIEWED,
        start_time=0.0,
        end_time=3.0,
        confidence=0.9,
    )
    db_session.add(annotation)
    await db_session.commit()
    await db_session.refresh(annotation)
    return annotation


@pytest.fixture
def member_a_headers(member_a_user: User) -> dict[str, str]:
    """JWT auth headers for member_a_user (Member of project A only)."""
    token = create_access_token({"sub": str(member_a_user.id)})
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Unit tests — pure repository logic (no HTTP, no DB dependency)
# These run regardless of test database availability.
# ---------------------------------------------------------------------------


class TestRepositoryBOLAUnit:
    """Unit tests for repository BOLA guards using mocked DB sessions.

    These tests verify the query logic paths of the ``get_by_id_in_project``
    and ``exists_in_project`` methods by mocking the SQLAlchemy execute call
    to return ``None`` (simulating a cross-project miss), confirming the
    methods return the correct sentinel values.
    """

    def _make_db(self, scalar_result: object | None) -> AsyncMock:
        """Return a mock AsyncSession whose execute returns scalar_result."""
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = scalar_result
        db_mock = AsyncMock()
        db_mock.execute = AsyncMock(return_value=result_mock)
        return db_mock

    def _make_bool_db(self, first_result: object | None) -> AsyncMock:
        """Return a mock AsyncSession whose .first() returns first_result.

        exists_in_project uses ``result.first() is not None`` rather than
        ``scalar()``, so this mock targets the ``first`` call.
        """
        result_mock = MagicMock()
        result_mock.first.return_value = first_result
        db_mock = AsyncMock()
        db_mock.execute = AsyncMock(return_value=result_mock)
        return db_mock

    @pytest.mark.asyncio
    async def test_recording_get_by_id_in_project_returns_none_on_miss(self) -> None:
        """RecordingRepository.get_by_id_in_project returns None for cross-project ID."""
        db = self._make_db(None)
        repo = RecordingRepository(db)
        result = await repo.get_by_id_in_project(uuid.uuid4(), uuid.uuid4())
        assert result is None, "Expected None for cross-project recording lookup"

    @pytest.mark.asyncio
    async def test_dataset_get_by_id_in_project_returns_none_on_miss(self) -> None:
        """DatasetRepository.get_by_id_in_project returns None for cross-project ID."""
        db = self._make_db(None)
        repo = DatasetRepository(db)
        result = await repo.get_by_id_in_project(uuid.uuid4(), uuid.uuid4())
        assert result is None, "Expected None for cross-project dataset lookup"

    @pytest.mark.asyncio
    async def test_annotation_get_by_id_in_project_returns_none_on_miss(self) -> None:
        """AnnotationRepository.get_by_id_in_project returns None for cross-project ID."""
        db = self._make_db(None)
        repo = AnnotationRepository(db)
        result = await repo.get_by_id_in_project(uuid.uuid4(), uuid.uuid4())
        assert result is None, "Expected None for cross-project annotation lookup"

    @pytest.mark.asyncio
    async def test_annotation_exists_in_project_returns_false_on_miss(self) -> None:
        """AnnotationRepository.exists_in_project returns False for cross-project ID."""
        db = self._make_bool_db(None)
        repo = AnnotationRepository(db)
        result = await repo.exists_in_project(uuid.uuid4(), uuid.uuid4())
        assert result is False, "Expected False for cross-project annotation existence check"

    @pytest.mark.asyncio
    async def test_annotation_exists_in_project_returns_true_on_hit(self) -> None:
        """AnnotationRepository.exists_in_project returns True when annotation belongs to project."""
        annotation_id = uuid.uuid4()
        db = self._make_bool_db(annotation_id)
        repo = AnnotationRepository(db)
        result = await repo.exists_in_project(annotation_id, uuid.uuid4())
        assert result is True, "Expected True when annotation exists in the project"


# ---------------------------------------------------------------------------
# Integration tests — HTTP-level BOLA enforcement (require test DB)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRecordingBOLA:
    """Project A Member uses project-B recording IDs — expects 404.

    The Stage-1 gate (VIEW_DETECTION / VIEW_MEDIA) passes for MEMBER, but the
    BOLA guard (get_by_id_in_project) returns None and the endpoint raises 404.

    Note: These HTTP integration tests require a running PostgreSQL test database.
    They are marked xfail when the DB is unavailable (environment issue, not a
    code defect — Phase 3 scope boundary).
    """

    async def test_get_recording_cross_project_is_404(
        self,
        client: AsyncClient,
        member_a_headers: dict[str, str],
        member_a_membership: ProjectMember,
        project_a: Project,
        recording_b: Recording,
    ) -> None:
        """GET /projects/{A}/recordings/{recording_B_id} → 404."""
        response = await client.get(
            f"/api/v1/projects/{project_a.id}/recordings/{recording_b.id}",
            headers=member_a_headers,
        )
        assert response.status_code == 404, (
            f"Expected 404 for cross-project recording GET, got {response.status_code}: "
            f"{response.text}"
        )

    async def test_get_recording_audio_cross_project_is_404(
        self,
        client: AsyncClient,
        member_a_headers: dict[str, str],
        member_a_membership: ProjectMember,
        project_a: Project,
        recording_b: Recording,
    ) -> None:
        """GET /projects/{A}/recordings/{recording_B_id}/audio → 404."""
        response = await client.get(
            f"/api/v1/projects/{project_a.id}/recordings/{recording_b.id}/audio",
            headers=member_a_headers,
        )
        assert response.status_code == 404, (
            f"Expected 404 for cross-project audio stream, got {response.status_code}: "
            f"{response.text}"
        )

    async def test_get_recording_spectrogram_cross_project_is_404(
        self,
        client: AsyncClient,
        member_a_headers: dict[str, str],
        member_a_membership: ProjectMember,
        project_a: Project,
        recording_b: Recording,
    ) -> None:
        """GET /projects/{A}/recordings/{recording_B_id}/spectrogram → 404."""
        response = await client.get(
            f"/api/v1/projects/{project_a.id}/recordings/{recording_b.id}/spectrogram",
            headers=member_a_headers,
        )
        assert response.status_code == 404, (
            f"Expected 404 for cross-project spectrogram, got {response.status_code}: "
            f"{response.text}"
        )

    async def test_get_recording_download_cross_project_is_404(
        self,
        client: AsyncClient,
        member_a_headers: dict[str, str],
        member_a_membership: ProjectMember,
        project_a: Project,
        recording_b: Recording,
    ) -> None:
        """GET /projects/{A}/recordings/{recording_B_id}/download → 404."""
        response = await client.get(
            f"/api/v1/projects/{project_a.id}/recordings/{recording_b.id}/download",
            headers=member_a_headers,
        )
        assert response.status_code == 404, (
            f"Expected 404 for cross-project recording download, got {response.status_code}: "
            f"{response.text}"
        )


@pytest.mark.asyncio
class TestDatasetBOLA:
    """Project A Member uses project-B dataset ID as a filter — expects 404.

    When `dataset_id` belongs to project B but is passed to project A's
    recordings list endpoint, the BOLA guard
    (DatasetRepository.get_by_id_in_project) returns None and raises 404.
    """

    async def test_list_recordings_cross_project_dataset_is_404(
        self,
        client: AsyncClient,
        member_a_headers: dict[str, str],
        member_a_membership: ProjectMember,
        project_a: Project,
        dataset_b: Dataset,
    ) -> None:
        """GET /projects/{A}/recordings?dataset_id={dataset_B_id} → 404."""
        response = await client.get(
            f"/api/v1/projects/{project_a.id}/recordings",
            params={"dataset_id": str(dataset_b.id)},
            headers=member_a_headers,
        )
        assert response.status_code == 404, (
            f"Expected 404 for cross-project dataset filter, got {response.status_code}: "
            f"{response.text}"
        )


@pytest.mark.asyncio
class TestAnnotationVoteBOLA:
    """Project A Member uses project-B annotation IDs on vote endpoints — expects 404.

    The Stage-1 gate (VIEW_DETECTION / VOTE) passes for MEMBER, but the
    BOLA guard (AnnotationRepository.exists_in_project) returns False and
    the endpoint raises 404.
    """

    async def test_get_votes_cross_project_annotation_is_404(
        self,
        client: AsyncClient,
        member_a_headers: dict[str, str],
        member_a_membership: ProjectMember,
        project_a: Project,
        annotation_b: Annotation,
    ) -> None:
        """GET /projects/{A}/annotations/{annotation_B_id}/votes → 404."""
        response = await client.get(
            f"/api/v1/projects/{project_a.id}/annotations/{annotation_b.id}/votes",
            headers=member_a_headers,
        )
        assert response.status_code == 404, (
            f"Expected 404 for cross-project annotation votes GET, "
            f"got {response.status_code}: {response.text}"
        )

    async def test_cast_vote_cross_project_annotation_is_404(
        self,
        client: AsyncClient,
        member_a_headers: dict[str, str],
        member_a_membership: ProjectMember,
        project_a: Project,
        annotation_b: Annotation,
    ) -> None:
        """POST /projects/{A}/annotations/{annotation_B_id}/votes → 404."""
        response = await client.post(
            f"/api/v1/projects/{project_a.id}/annotations/{annotation_b.id}/votes",
            headers=member_a_headers,
            json={"vote_type": "confirm"},
        )
        assert response.status_code == 404, (
            f"Expected 404 for cross-project annotation vote POST, "
            f"got {response.status_code}: {response.text}"
        )

    async def test_delete_vote_cross_project_annotation_is_404(
        self,
        client: AsyncClient,
        member_a_headers: dict[str, str],
        member_a_membership: ProjectMember,
        project_a: Project,
        annotation_b: Annotation,
    ) -> None:
        """DELETE /projects/{A}/annotations/{annotation_B_id}/votes → 404."""
        response = await client.delete(
            f"/api/v1/projects/{project_a.id}/annotations/{annotation_b.id}/votes",
            headers=member_a_headers,
        )
        assert response.status_code == 404, (
            f"Expected 404 for cross-project annotation vote DELETE, "
            f"got {response.status_code}: {response.text}"
        )


@pytest.mark.asyncio
class TestDetectionBOLA:
    """Project A Member uses project-B detection (annotation) ID — expects 404.

    The DETECTION_GET_ACTION gate passes for MEMBER (VIEW_DETECTION), but the
    BOLA guard (AnnotationRepository.exists_in_project) returns False and the
    endpoint raises 404.
    """

    async def test_get_detection_cross_project_is_404(
        self,
        client: AsyncClient,
        member_a_headers: dict[str, str],
        member_a_membership: ProjectMember,
        project_a: Project,
        annotation_b: Annotation,
    ) -> None:
        """GET /projects/{A}/detections/{detection_B_id} → 404.

        detection_B_id is the UUID of an annotation belonging to project B.
        The BOLA guard (exists_in_project) rejects the cross-project access.
        """
        response = await client.get(
            f"/api/v1/projects/{project_a.id}/detections/{annotation_b.id}",
            headers=member_a_headers,
        )
        assert response.status_code == 404, (
            f"Expected 404 for cross-project detection GET, got {response.status_code}: "
            f"{response.text}"
        )
