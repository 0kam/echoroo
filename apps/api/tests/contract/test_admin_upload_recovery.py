"""Contract tests for the admin upload-session recovery surface.

Covers ``GET /web-api/v1/admin/uploads/stuck`` (list stuck sessions) and
``POST /web-api/v1/admin/uploads/{session_id}/fail`` (force-fail a wedged
session). Both are platform-scope, superuser-only endpoints: a real
superuser session reaches the 2xx path; a regular-user session reaches
the 403 permission gate.

The fixtures mirror :mod:`tests.contract.test_admin` — a ``users`` row
plus a matching ``superusers`` entitlement row for the superuser, and a
plain user for the negative case. A minimal Project -> Site -> Dataset
-> UploadSession chain is seeded so the endpoint can resolve
``project_id`` via ``dataset.project_id``.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.dataset import Dataset
from echoroo.models.enums import (
    DatasetVisibility,
    ProjectMemberRole,
    ProjectVisibility,
    UploadSessionStatus,
)
from echoroo.models.project import Project, ProjectMember
from echoroo.models.site import Site
from echoroo.models.superuser import Superuser
from echoroo.models.upload import UploadSession
from echoroo.models.user import User
from echoroo.repositories.upload import UploadSessionRepository
from tests.contract.conftest import bff_session_headers

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def admin_superuser(db_session: AsyncSession) -> User:
    """Create a superuser (users row + active superusers entitlement)."""
    user = User(
        email="upload-recovery-su@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="Recovery Superuser",
        security_stamp="0" * 64,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    su = Superuser(
        user_id=user.id,
        added_by_id=None,
        added_at=datetime.now(UTC) - timedelta(days=1),
        webauthn_credentials=[],
        allowed_ip_cidrs=[],
        revoked_at=None,
    )
    db_session.add(su)
    await db_session.commit()
    await db_session.refresh(su)
    return user


@pytest.fixture
async def superuser_headers(
    client: AsyncClient, db_session: AsyncSession, admin_superuser: User
) -> dict[str, str]:
    """CSRF-capable ``/web-api/v1`` session headers for the superuser."""
    return await bff_session_headers(client, db_session, admin_superuser)


@pytest.fixture
async def regular_user(db_session: AsyncSession) -> User:
    """Create a plain (non-superuser) user."""
    user = User(
        email="upload-recovery-user@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="Recovery Regular User",
        security_stamp="0" * 64,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def regular_user_headers(
    client: AsyncClient, db_session: AsyncSession, regular_user: User
) -> dict[str, str]:
    """CSRF-capable ``/web-api/v1`` session headers for the regular user."""
    return await bff_session_headers(client, db_session, regular_user)


async def _seed_upload_session(
    db_session: AsyncSession,
    owner: User,
    *,
    status: UploadSessionStatus,
    updated_at: datetime | None = None,
) -> tuple[UploadSession, UUID]:
    """Seed a Project -> Site -> Dataset -> UploadSession chain.

    Returns the session and its owning project id (for project_id assertions).
    """
    project = Project(
        name="Recovery Project",
        description="Upload recovery contract test project",
        owner_id=owner.id,
        # PUBLIC keeps the restricted_config CHECK constraint satisfied with an
        # empty default config (the endpoint under test is visibility-agnostic).
        visibility=ProjectVisibility.PUBLIC,
    )
    db_session.add(project)
    await db_session.flush()

    db_session.add(
        ProjectMember(
            project_id=project.id,
            user_id=owner.id,
            role=ProjectMemberRole.ADMIN,
            invited_by_id=owner.id,
        )
    )

    site = Site(
        project_id=project.id,
        name="Recovery Site",
        h3_index_member="8928308280fffff",
        h3_index_member_resolution=9,
    )
    db_session.add(site)
    await db_session.flush()

    dataset = Dataset(
        project_id=project.id,
        site_id=site.id,
        created_by_id=owner.id,
        name="Recovery Dataset",
        visibility=DatasetVisibility.PRIVATE,
    )
    db_session.add(dataset)
    await db_session.flush()

    session = UploadSession(
        dataset_id=dataset.id,
        created_by_id=owner.id,
        status=status,
        total_files=3,
        total_bytes=1024,
        validated_files=1,
        imported_files=0,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db_session.add(session)
    await db_session.flush()

    if updated_at is not None:
        session.updated_at = updated_at

    await db_session.commit()
    await db_session.refresh(session)
    return session, project.id


# ---------------------------------------------------------------------------
# GET /admin/uploads/stuck
# ---------------------------------------------------------------------------


class TestListStuckUploads:
    async def test_list_as_superuser_returns_stuck_session(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        superuser_headers: dict[str, str],
        admin_superuser: User,
    ) -> None:
        session, project_id = await _seed_upload_session(
            db_session,
            admin_superuser,
            status=UploadSessionStatus.IMPORTING,
            updated_at=datetime.now(UTC) - timedelta(hours=2),
        )

        response = await client.get(
            "/web-api/v1/admin/uploads/stuck", headers=superuser_headers
        )

        assert response.status_code == 200, response.text
        items = response.json()["items"]
        by_id = {item["id"]: item for item in items}
        assert str(session.id) in by_id
        row = by_id[str(session.id)]
        assert row["project_id"] == str(project_id)
        assert row["dataset_id"] == str(session.dataset_id)
        assert row["status"] == UploadSessionStatus.IMPORTING.value
        assert row["total_files"] == 3

    async def test_older_than_seconds_filters_recent_sessions(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        superuser_headers: dict[str, str],
        admin_superuser: User,
    ) -> None:
        session, _ = await _seed_upload_session(
            db_session,
            admin_superuser,
            status=UploadSessionStatus.VALIDATING,
            updated_at=datetime.now(UTC) - timedelta(seconds=30),
        )

        # A 1-hour window excludes a session updated 30s ago.
        response = await client.get(
            "/web-api/v1/admin/uploads/stuck?older_than_seconds=3600",
            headers=superuser_headers,
        )
        assert response.status_code == 200, response.text
        ids = {item["id"] for item in response.json()["items"]}
        assert str(session.id) not in ids

    async def test_list_as_non_superuser_forbidden(
        self,
        client: AsyncClient,
        regular_user_headers: dict[str, str],
    ) -> None:
        response = await client.get(
            "/web-api/v1/admin/uploads/stuck", headers=regular_user_headers
        )
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# POST /admin/uploads/{session_id}/fail
# ---------------------------------------------------------------------------


class TestForceFailUpload:
    async def test_force_fail_non_terminal_session(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        superuser_headers: dict[str, str],
        admin_superuser: User,
    ) -> None:
        session, _ = await _seed_upload_session(
            db_session,
            admin_superuser,
            status=UploadSessionStatus.IMPORTING,
        )

        response = await client.post(
            f"/web-api/v1/admin/uploads/{session.id}/fail",
            headers=superuser_headers,
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == UploadSessionStatus.FAILED.value
        assert body["error"] == "Force-failed by admin (recovery)"

    async def test_force_fail_already_terminal_conflict(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        superuser_headers: dict[str, str],
        admin_superuser: User,
    ) -> None:
        session, _ = await _seed_upload_session(
            db_session,
            admin_superuser,
            status=UploadSessionStatus.IMPORTED,
        )

        response = await client.post(
            f"/web-api/v1/admin/uploads/{session.id}/fail",
            headers=superuser_headers,
        )
        assert response.status_code == 409, response.text

    async def test_force_fail_unknown_session_not_found(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
    ) -> None:
        response = await client.post(
            f"/web-api/v1/admin/uploads/{uuid4()}/fail",
            headers=superuser_headers,
        )
        assert response.status_code == 404, response.text

    async def test_force_fail_as_non_superuser_forbidden(
        self,
        client: AsyncClient,
        regular_user_headers: dict[str, str],
    ) -> None:
        response = await client.post(
            f"/web-api/v1/admin/uploads/{uuid4()}/fail",
            headers=regular_user_headers,
        )
        assert response.status_code == 403

    async def test_force_fail_passes_cas_and_409_on_concurrent_transition(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        superuser_headers: dict[str, str],
        admin_superuser: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The handler must CAS on the read status and 409 on a lost race.

        We spy ``UploadSessionRepository.update_status`` to (a) prove the
        handler forwards ``expected_status`` (the compare-and-set guard) and
        (b) simulate the background import winning the race by returning
        ``False`` (0 rows matched). The handler must then re-fetch and reply
        409 instead of reporting a misleading 200.
        """
        session, _ = await _seed_upload_session(
            db_session,
            admin_superuser,
            status=UploadSessionStatus.IMPORTING,
        )

        captured: dict[str, Any] = {}

        async def fake_update_status(
            self: UploadSessionRepository,
            session_id: UUID,
            status: UploadSessionStatus,
            error: str | None = None,
            expected_status: UploadSessionStatus | None = None,
        ) -> bool:
            captured["expected_status"] = expected_status
            captured["status"] = status
            return False  # simulate a concurrent transition (0 rows matched)

        monkeypatch.setattr(
            UploadSessionRepository, "update_status", fake_update_status
        )

        response = await client.post(
            f"/web-api/v1/admin/uploads/{session.id}/fail",
            headers=superuser_headers,
        )

        assert response.status_code == 409, response.text
        assert "transitioned concurrently" in response.json()["detail"]
        # The CAS guard was forwarded with the status we read (IMPORTING).
        assert captured["expected_status"] == UploadSessionStatus.IMPORTING
        assert captured["status"] == UploadSessionStatus.FAILED

    async def test_force_fail_audit_logs_pre_call_previous_status(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        superuser_headers: dict[str, str],
        admin_superuser: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The audit ``previous_status`` is the pre-UPDATE status.

        The ORM-enabled UPDATE mutates the in-memory session to FAILED, so a
        naive read after the write would always log ``"failed"``. We spy the
        audit emit to capture the ``detail`` payload (the real KMS-backed
        hash-chain write is unavailable in the contract harness and is a
        best-effort soft alert anyway) and assert it carries ``"importing"``.
        """
        session, _ = await _seed_upload_session(
            db_session,
            admin_superuser,
            status=UploadSessionStatus.IMPORTING,
        )

        captured: dict[str, Any] = {}

        async def fake_write_platform_event(
            self: Any, **kwargs: Any
        ) -> UUID:
            captured.update(kwargs)
            return uuid4()

        monkeypatch.setattr(
            "echoroo.services.audit_service.AuditLogService.write_platform_event",
            fake_write_platform_event,
        )

        response = await client.post(
            f"/web-api/v1/admin/uploads/{session.id}/fail",
            headers=superuser_headers,
        )
        assert response.status_code == 200, response.text

        assert captured.get("action") == "platform.upload.recover"
        detail = captured["detail"]
        assert detail["session_id"] == str(session.id)
        assert detail["previous_status"] == UploadSessionStatus.IMPORTING.value
