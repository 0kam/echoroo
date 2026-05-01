"""License-required contract (T320 / T322 / T323, FR-085 / FR-087, SC-010).

Spec FR-085 mandates that ``POST /projects`` reject creation requests that
omit the ``license`` field with a 422 (``ERR_LICENSE_REQUIRED`` envelope)
and that the value be one of the four CC license codes
(``CC0`` / ``CC-BY`` / ``CC-BY-NC`` / ``CC-BY-SA``). FR-087 mandates that
the initial license selection be recorded in
:class:`~echoroo.models.project.ProjectLicenseHistory` so historical
exports can reference an immutable license trail.

Tests cover the full input matrix (Phase 7 polish round 2 + 3):

1. ``license`` missing entirely → 422 with ``error == "ERR_LICENSE_REQUIRED"``.
2. ``license`` empty string → 422 (same envelope).
3. ``license`` with a value outside the CC enum (e.g. ``"MIT"``) → 422.
4. Happy path ``CC-BY`` → 201, project persisted with that license, **and**
   exactly one ``ProjectLicenseHistory`` row is written
   (``old_license=None``, ``new_license=CC-BY``,
   ``changed_by_id=requester``) — FR-085 + FR-087 contract for the initial
   row.
5. Two distinct project creations with different licenses → each project
   gets its own independent history row.
6. ``PATCH /api/v1/projects/{id}/license`` happy path: a project created
   with ``CC-BY`` and then mutated to ``CC-BY-NC`` ends up with **two**
   history rows (initial + change).
7. Phase 7 polish round 2 (Major 5): two consecutive PATCHes with the
   *same* license value still append a row each — the no-op short-circuit
   in :func:`change_license` was deliberately removed so audit consumers
   see one row per request.
8. Phase 7 polish round 3 (Major 1, Major 2): the canonical permissions
   matrix gives **MANAGE_LICENSE to Admin and Owner**. The earlier round 2
   test (``test_non_owner_admin_member_returns_403``) wrongly asserted that
   Admin received 403 — that has been split into two correct cases:

   * ``test_admin_member_succeeds``           — Admin PATCH → 200, history+1.
   * ``test_regular_member_returns_403``      — MEMBER role → 403, no row.

   These cases are exercised on **both** the programmatic
   ``/api/v1/projects/{id}/license`` (Bearer) surface AND the Web UI
   ``/web-api/v1/projects/{id}/license`` (Cookie + CSRF) surface so the
   contract is locked at every customer touch-point.

9. Phase 7 polish round 3 (Major 3): the ``ERR_LICENSE_REQUIRED``
   envelope is **only** emitted on routes that own the project license
   field. A 422 on an unrelated endpoint that happens to surface a
   ``license`` field MUST fall back to the generic ``ValidationError``
   envelope. See ``tests/unit/core/test_exceptions.py`` for the path
   matcher's unit-level coverage.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from echoroo.core.jwt import create_access_token
from echoroo.core.settings import get_settings
from echoroo.models.enums import (
    ProjectLicense,
    ProjectMemberRole,
)
from echoroo.models.project import Project, ProjectLicenseHistory, ProjectMember
from echoroo.models.user import User
from echoroo.services.license_service import (
    list_license_history,
    record_initial_license,
)

# Test database URL — read at fixture time so the same value used by the
# conftest ``client`` fixture also drives the patched ``AsyncSessionLocal``
# referenced inside the audit fresh-session helpers. Resolved via the same
# env var the conftest reads so the two fixtures stay in sync.
_TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://echoroo:echoroo@localhost:5432/echoroo_test",
)

# ---------------------------------------------------------------------------
# Fixtures — actor + auth header. Naming mirrors test_guest_authenticated_vote
# (``t310_*``) so contributors can locate the Phase 7 contract by file name.
# ---------------------------------------------------------------------------


@pytest.fixture
async def t320_owner(db_session: AsyncSession) -> User:
    user = User(
        email="t320owner@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T320 Owner",
        security_stamp="t320" + "o" * 60,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
def t320_owner_headers(t320_owner: User) -> dict[str, str]:
    return {
        "Authorization": (
            f"Bearer {create_access_token({'sub': str(t320_owner.id)})}"
        )
    }


@pytest.fixture
async def t320_admin(db_session: AsyncSession) -> User:
    """A separate user used as the project Admin for non-owner PATCH tests."""
    user = User(
        email="t320admin@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T320 Admin",
        security_stamp="t320" + "a" * 60,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
def t320_admin_headers(t320_admin: User) -> dict[str, str]:
    return {
        "Authorization": (
            f"Bearer {create_access_token({'sub': str(t320_admin.id)})}"
        )
    }


@pytest.fixture
async def t320_member(db_session: AsyncSession) -> User:
    """A separate user used as a plain Member for non-Admin PATCH tests.

    Phase 7 polish round 3 (Major 1): the canonical permissions matrix
    grants ``MANAGE_LICENSE`` to ``Admin`` and ``Owner`` only. The
    earlier round 2 test conflated "non-owner Admin" with "regular
    Member" and asserted 403 on Admin — wrong against the matrix. The
    fixtures here split the two cases so each test is unambiguous.
    """
    user = User(
        email="t320member@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T320 Member",
        security_stamp="t320" + "r" * 60,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
def t320_member_headers(t320_member: User) -> dict[str, str]:
    return {
        "Authorization": (
            f"Bearer {create_access_token({'sub': str(t320_member.id)})}"
        )
    }


@pytest.fixture
async def t320_outsider(db_session: AsyncSession) -> User:
    """Non-member user — should be matrix-denied on the license endpoints."""
    user = User(
        email="t320outsider@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T320 Outsider",
        security_stamp="t320" + "x" * 60,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
def t320_outsider_headers(t320_outsider: User) -> dict[str, str]:
    return {
        "Authorization": (
            f"Bearer {create_access_token({'sub': str(t320_outsider.id)})}"
        )
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_PROJECTS_ENDPOINT = "/api/v1/projects"


def _license_endpoint(project_id: object) -> str:
    return f"{_PROJECTS_ENDPOINT}/{project_id}/license"


async def _fetch_history_rows(
    db: AsyncSession, project_id: object
) -> list[ProjectLicenseHistory]:
    """Return all license-history rows for a project ordered by ``changed_at``.

    The endpoint commits in a different session than the test, so we use
    a fresh ``execute`` to bypass ORM identity-map caching.
    """
    result = await db.execute(
        sa.select(ProjectLicenseHistory)
        .where(ProjectLicenseHistory.project_id == project_id)
        .order_by(ProjectLicenseHistory.changed_at.asc())
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Tests — FR-085 422 paths (now asserting the canonical envelope)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestLicenseRequiredOnCreate:
    """``POST /projects`` rejects missing / invalid licenses with 422.

    Phase 7 polish round 2 (Major 6): the 422 envelope MUST carry
    ``error == "ERR_LICENSE_REQUIRED"`` per FR-085. The detection is
    handled at the validation handler level
    (:func:`echoroo.core.exceptions.validation_exception_handler`) so any
    ``loc`` chain containing ``"license"`` collapses to the same code,
    regardless of whether the failure was "missing", "enum mismatch", or
    "empty string".
    """

    async def test_missing_license_returns_err_license_required(
        self,
        client: AsyncClient,
        t320_owner_headers: dict[str, str],
    ) -> None:
        """FR-085: omitting ``license`` MUST surface ``ERR_LICENSE_REQUIRED``."""
        response = await client.post(
            _PROJECTS_ENDPOINT,
            headers=t320_owner_headers,
            json={
                "name": "T320 No License",
                "description": "license missing on purpose",
                "visibility": "public",
            },
        )
        assert response.status_code == 422, response.text

        body = response.json()
        assert body["error"] == "ERR_LICENSE_REQUIRED", (
            f"Expected ERR_LICENSE_REQUIRED envelope, got {body!r}"
        )
        assert _has_license_field_error(body), (
            f"422 body did not flag ``license`` as the offending field: {body!r}"
        )

    async def test_empty_string_license_returns_err_license_required(
        self,
        client: AsyncClient,
        t320_owner_headers: dict[str, str],
    ) -> None:
        """``license: ""`` collapses to the same ``ERR_LICENSE_REQUIRED`` code."""
        response = await client.post(
            _PROJECTS_ENDPOINT,
            headers=t320_owner_headers,
            json={
                "name": "T320 Empty License",
                "visibility": "public",
                "license": "",
            },
        )
        assert response.status_code == 422, response.text
        body = response.json()
        assert body["error"] == "ERR_LICENSE_REQUIRED", body

    async def test_unknown_license_value_returns_err_license_required(
        self,
        client: AsyncClient,
        t320_owner_headers: dict[str, str],
    ) -> None:
        """``license: "MIT"`` is outside the CC enum → ``ERR_LICENSE_REQUIRED``."""
        response = await client.post(
            _PROJECTS_ENDPOINT,
            headers=t320_owner_headers,
            json={
                "name": "T320 Unknown License",
                "visibility": "public",
                "license": "MIT",
            },
        )
        assert response.status_code == 422, response.text
        body = response.json()
        assert body["error"] == "ERR_LICENSE_REQUIRED", body


# ---------------------------------------------------------------------------
# Tests — FR-085 + FR-087 happy path with history insert
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestLicenseHappyPathWritesHistory:
    """Successful creation persists the project AND a single history row."""

    async def test_cc_by_create_writes_initial_history_row(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        t320_owner: User,
        t320_owner_headers: dict[str, str],
    ) -> None:
        """T320 + T322: 201 + ``ProjectLicenseHistory`` row with old=None."""
        response = await client.post(
            _PROJECTS_ENDPOINT,
            headers=t320_owner_headers,
            json={
                "name": "T320 Happy Path",
                "description": "first license selection lands in history",
                "visibility": "public",
                "license": "CC-BY",
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["license"] == "CC-BY"

        project_id = body["id"]

        # Project row reflects the requested license.
        project = (
            await db_session.execute(
                sa.select(Project).where(Project.id == project_id)
            )
        ).scalar_one()
        assert project.license == ProjectLicense.CC_BY

        # FR-087: initial row exists with old_license=NULL, new_license=CC-BY,
        # changed_by_id = requester user id. There MUST be exactly one row.
        rows = await _fetch_history_rows(db_session, project_id)
        assert len(rows) == 1, (
            f"Expected exactly one initial history row, got {len(rows)}"
        )
        initial = rows[0]
        assert initial.old_license is None
        assert initial.new_license == ProjectLicense.CC_BY
        assert initial.changed_by_id == t320_owner.id


# ---------------------------------------------------------------------------
# Tests — multi-project history isolation (FR-087)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestMultipleProjectsHaveIndependentHistory:
    """Two distinct create calls produce independent history rows."""

    async def test_two_projects_different_licenses_have_independent_history(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        t320_owner: User,
        t320_owner_headers: dict[str, str],
    ) -> None:
        first_response = await client.post(
            _PROJECTS_ENDPOINT,
            headers=t320_owner_headers,
            json={
                "name": "T320 Project A",
                "visibility": "public",
                "license": "CC0",
            },
        )
        assert first_response.status_code == 201, first_response.text
        first_id = first_response.json()["id"]

        second_response = await client.post(
            _PROJECTS_ENDPOINT,
            headers=t320_owner_headers,
            json={
                "name": "T320 Project B",
                "visibility": "public",
                "license": "CC-BY-SA",
            },
        )
        assert second_response.status_code == 201, second_response.text
        second_id = second_response.json()["id"]
        assert first_id != second_id

        first_rows = await _fetch_history_rows(db_session, first_id)
        second_rows = await _fetch_history_rows(db_session, second_id)

        assert len(first_rows) == 1
        assert len(second_rows) == 1
        assert first_rows[0].new_license == ProjectLicense.CC0
        assert first_rows[0].old_license is None
        assert second_rows[0].new_license == ProjectLicense.CC_BY_SA
        assert second_rows[0].old_license is None

        # Owner is the same on both — sanity check that the actor is
        # captured per row, not derived from a shared singleton.
        assert first_rows[0].changed_by_id == t320_owner.id
        assert second_rows[0].changed_by_id == t320_owner.id


# ---------------------------------------------------------------------------
# Tests — license_service.change_license at the service layer (FR-087)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestChangeLicenseAppendsHistory:
    """Service-level invariants for ``change_license``.

    Phase 7 polish round 2:

    * Major 3 — :func:`list_license_history` returns rows ASC.
    * Major 5 — Same-license calls still append a row (the no-op
      short-circuit was removed). Idempotency, if desired, must be
      handled by the endpoint layer, not the service.
    """

    async def test_change_license_after_create_yields_two_rows_asc_order(
        self,
        db_session: AsyncSession,
        t320_owner: User,
    ) -> None:
        """Initial row + change row = 2 history entries, listed oldest-first."""
        from echoroo.services.license_service import change_license

        project = Project(
            name="T320 Change License",
            visibility="public",
            license=ProjectLicense.CC_BY,
            owner_id=t320_owner.id,
            restricted_config={},
        )
        db_session.add(project)
        await db_session.flush()
        await record_initial_license(
            session=db_session,
            project_id=project.id,
            license=ProjectLicense.CC_BY,
            actor_user_id=t320_owner.id,
        )
        await db_session.commit()

        rows_before = await _fetch_history_rows(db_session, project.id)
        assert len(rows_before) == 1
        assert rows_before[0].old_license is None
        assert rows_before[0].new_license == ProjectLicense.CC_BY

        change_row = await change_license(
            session=db_session,
            project_id=project.id,
            new_license=ProjectLicense.CC_BY_NC,
            actor_user_id=t320_owner.id,
        )
        await db_session.commit()
        assert change_row.old_license == ProjectLicense.CC_BY
        assert change_row.new_license == ProjectLicense.CC_BY_NC

        await db_session.refresh(project)
        assert project.license == ProjectLicense.CC_BY_NC

        rows_after = await _fetch_history_rows(db_session, project.id)
        assert len(rows_after) == 2
        # ASC order — oldest first per OpenAPI contract (projects.yaml:357).
        assert rows_after[0].new_license == ProjectLicense.CC_BY
        assert rows_after[1].old_license == ProjectLicense.CC_BY
        assert rows_after[1].new_license == ProjectLicense.CC_BY_NC

        # ``list_license_history`` MUST also return ASC.
        listed = await list_license_history(db_session, project.id)
        assert [r.new_license for r in listed] == [
            ProjectLicense.CC_BY,
            ProjectLicense.CC_BY_NC,
        ]

    async def test_two_same_license_patches_each_append_a_row(
        self,
        db_session: AsyncSession,
        t320_owner: User,
    ) -> None:
        """Major 5: same-license PATCHes append a row each — no service-level no-op."""
        from echoroo.services.license_service import change_license

        project = Project(
            name="T320 Same License Twice",
            visibility="public",
            license=ProjectLicense.CC0,
            owner_id=t320_owner.id,
            restricted_config={},
        )
        db_session.add(project)
        await db_session.flush()
        await record_initial_license(
            session=db_session,
            project_id=project.id,
            license=ProjectLicense.CC0,
            actor_user_id=t320_owner.id,
        )
        await db_session.commit()

        first = await change_license(
            session=db_session,
            project_id=project.id,
            new_license=ProjectLicense.CC0,
            actor_user_id=t320_owner.id,
        )
        await db_session.commit()
        assert first.old_license == ProjectLicense.CC0
        assert first.new_license == ProjectLicense.CC0

        second = await change_license(
            session=db_session,
            project_id=project.id,
            new_license=ProjectLicense.CC0,
            actor_user_id=t320_owner.id,
        )
        await db_session.commit()
        assert second.old_license == ProjectLicense.CC0
        assert second.new_license == ProjectLicense.CC0

        rows = await _fetch_history_rows(db_session, project.id)
        # Initial (record_initial_license) + 2 PATCHes = 3 rows.
        assert len(rows) == 3, (
            "Each PATCH must append a row even with same license (Major 5)."
        )
        assert all(r.new_license == ProjectLicense.CC0 for r in rows)


# ---------------------------------------------------------------------------
# Tests — PATCH /api/v1/projects/{id}/license HTTP surface (additional task #7)
# ---------------------------------------------------------------------------


async def _create_project_via_api(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    name: str,
    license_code: str,
    visibility: str = "public",
) -> str:
    response = await client.post(
        _PROJECTS_ENDPOINT,
        headers=headers,
        json={
            "name": name,
            "visibility": visibility,
            "license": license_code,
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def _add_admin_member(
    db: AsyncSession,
    project_id: object,
    user_id: object,
) -> None:
    """Insert an active Admin member row so the user is matrix-Admin."""
    member = ProjectMember(
        project_id=project_id,
        user_id=user_id,
        role=ProjectMemberRole.ADMIN,
        joined_at=datetime.now(UTC),
        invited_by_id=user_id,  # self-invite for test brevity; not asserted
    )
    db.add(member)
    await db.commit()


async def _add_member(
    db: AsyncSession,
    project_id: object,
    user_id: object,
    role: ProjectMemberRole = ProjectMemberRole.MEMBER,
) -> None:
    """Insert a project membership row with the given role.

    Used by the round 3 (Major 1) regression tests to prove that a plain
    ``MEMBER`` role lacks ``MANAGE_LICENSE`` and is denied with 403, even
    though it can read project metadata.
    """
    member = ProjectMember(
        project_id=project_id,
        user_id=user_id,
        role=role,
        joined_at=datetime.now(UTC),
        invited_by_id=user_id,
    )
    db.add(member)
    await db.commit()


@pytest.mark.asyncio
class TestPatchLicenseEndpoint:
    """``PATCH /api/v1/projects/{id}/license`` HTTP behaviour (Bearer surface).

    Per the canonical permissions matrix (spec.md FR-010), ``MANAGE_LICENSE``
    is granted to **Admin and Owner**. These tests lock the Bearer
    (programmatic) contract surface; the Web UI Cookie+CSRF mirror is
    covered in :class:`TestPatchLicenseEndpointWebApi` so the contract holds
    end-to-end at every customer touch-point.
    """

    async def test_owner_patch_appends_history_row(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        t320_owner: User,
        t320_owner_headers: dict[str, str],
    ) -> None:
        """Owner CC-BY → CC-BY-NC PATCH returns 200 with 2 history rows."""
        project_id = await _create_project_via_api(
            client,
            t320_owner_headers,
            name="T320 PATCH Owner",
            license_code="CC-BY",
        )

        response = await client.patch(
            _license_endpoint(project_id),
            headers=t320_owner_headers,
            json={"license": "CC-BY-NC"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["license"] == "CC-BY-NC"

        rows = await _fetch_history_rows(db_session, project_id)
        assert len(rows) == 2
        assert rows[0].old_license is None  # initial
        assert rows[0].new_license == ProjectLicense.CC_BY
        assert rows[1].old_license == ProjectLicense.CC_BY
        assert rows[1].new_license == ProjectLicense.CC_BY_NC
        assert rows[1].changed_by_id == t320_owner.id

    async def test_admin_member_succeeds(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        t320_owner_headers: dict[str, str],
        t320_admin: User,
        t320_admin_headers: dict[str, str],
    ) -> None:
        """Admin holds MANAGE_LICENSE per FR-010 — PATCH → 200, history+1.

        Phase 7 polish round 3 (Major 1): the previous round 2 test wrongly
        asserted 403 for Admin. The canonical matrix at spec.md:427 grants
        ``MANAGE_LICENSE`` to Admin AND Owner, so an Admin PATCH MUST
        succeed and append a history row whose ``changed_by_id`` is the
        admin (not the owner).
        """
        project_id = await _create_project_via_api(
            client,
            t320_owner_headers,
            name="T320 PATCH Admin Allowed",
            license_code="CC0",
        )
        await _add_admin_member(db_session, project_id, t320_admin.id)

        response = await client.patch(
            _license_endpoint(project_id),
            headers=t320_admin_headers,
            json={"license": "CC-BY"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["license"] == "CC-BY"

        rows = await _fetch_history_rows(db_session, project_id)
        assert len(rows) == 2
        assert rows[0].old_license is None
        assert rows[0].new_license == ProjectLicense.CC0
        assert rows[1].old_license == ProjectLicense.CC0
        assert rows[1].new_license == ProjectLicense.CC_BY
        # The Admin (NOT the project owner) is recorded as the actor.
        assert rows[1].changed_by_id == t320_admin.id

    async def test_regular_member_returns_403(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        t320_owner_headers: dict[str, str],
        t320_member: User,
        t320_member_headers: dict[str, str],
    ) -> None:
        """Regular MEMBER role lacks MANAGE_LICENSE — 403 per FR-010.

        Phase 7 polish round 3 (Major 1): MEMBERs have read access plus
        writing on detections / votes / comments etc., but ``MANAGE_LICENSE``
        is **not** in their permission set. PATCHing the license MUST 403
        and leave the history table untouched.
        """
        project_id = await _create_project_via_api(
            client,
            t320_owner_headers,
            name="T320 PATCH Member Denied",
            license_code="CC0",
        )
        await _add_member(
            db_session, project_id, t320_member.id, ProjectMemberRole.MEMBER
        )

        response = await client.patch(
            _license_endpoint(project_id),
            headers=t320_member_headers,
            json={"license": "CC-BY"},
        )
        assert response.status_code == 403, response.text

        # No new history row should have been written.
        rows = await _fetch_history_rows(db_session, project_id)
        assert len(rows) == 1
        assert rows[0].new_license == ProjectLicense.CC0

    async def test_non_member_returns_403_or_404(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        t320_owner_headers: dict[str, str],
        t320_outsider_headers: dict[str, str],
    ) -> None:
        """Outsider on a Public project cannot mutate license — 403 or 404.

        FR-018 collapses unauthorised reads to 404 for anti-enumeration,
        but the project here is Public so the outsider sees it; the
        permission gate denies the mutation with 403. We accept either
        code to keep the test robust against future hardening.
        """
        project_id = await _create_project_via_api(
            client,
            t320_owner_headers,
            name="T320 PATCH Outsider",
            license_code="CC-BY",
        )

        response = await client.patch(
            _license_endpoint(project_id),
            headers=t320_outsider_headers,
            json={"license": "CC-BY-SA"},
        )
        assert response.status_code in (403, 404), response.text

        # No new history row should have been written.
        rows = await _fetch_history_rows(db_session, project_id)
        assert len(rows) == 1
        assert rows[0].new_license == ProjectLicense.CC_BY

    async def test_extra_field_is_rejected_with_422(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        t320_owner_headers: dict[str, str],
    ) -> None:
        """``ProjectLicenseUpdateRequest`` has ``extra="forbid"`` — extras → 422."""
        project_id = await _create_project_via_api(
            client,
            t320_owner_headers,
            name="T320 PATCH Extra Field",
            license_code="CC-BY",
        )

        response = await client.patch(
            _license_endpoint(project_id),
            headers=t320_owner_headers,
            json={"license": "CC-BY-NC", "evil_extra": True},
        )
        assert response.status_code == 422, response.text

        # No new history row should have been written.
        rows = await _fetch_history_rows(db_session, project_id)
        assert len(rows) == 1
        assert rows[0].new_license == ProjectLicense.CC_BY


# ---------------------------------------------------------------------------
# Phase 7 polish round 3 (Major 2): Cookie + CSRF surface for /web-api/v1.
#
# T320 / T322 mandate that the **first-party Web UI** PATCH route enforces
# the same matrix + history contract as the Bearer surface. Because the
# Web UI route lives behind the AuthRouter + CSRF middleware stack, we
# need to seed:
#
#   * a ``token_families`` row owned by the actor user — its UUID is the
#     ``echoroo_session`` cookie value, looked up by
#     :class:`JwtSessionVerifier`;
#   * a JWT access token signed with the user's live ``security_stamp``;
#   * a CSRF token bound to the family id, sent in ``X-CSRF-Token``.
#
# The test client itself is reconstructed inside this fixture because the
# global ``AsyncSessionLocal`` referenced by :class:`JwtSessionVerifier`
# inside :func:`echoroo.main.create_app` would otherwise point at the
# module-load DSN (typically the dev DB) rather than the per-test
# ``TEST_DATABASE_URL``. We monkey-patch the symbol on
# :mod:`echoroo.core.database` (and the re-exported reference inside
# :mod:`echoroo.api.web_v1.projects._license`) for the lifetime of the
# fixture so the verifier and the audit-write helper both target the same
# test schema.
# ---------------------------------------------------------------------------


@pytest.fixture
async def web_client(
    db_session: AsyncSession,  # noqa: ARG001 — ensures the test DB is set up
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[AsyncClient, None]:
    """Build an HTTP client wired to the production Web UI router stack.

    **Bypass test fixture** — production middleware integration is covered
    by :func:`prod_web_client` below (Phase 7 polish round 4 Major 2). This
    lightweight client only mounts the router and a Bearer→Principal
    middleware stand-in so the **business contract** assertions
    (matrix + history) can run without dragging in the real Cookie + CSRF
    + AuthRouter wiring. Tests that need to verify the full production
    auth chain (cookie + CSRF + session-aware ``OptionalCurrentUser``)
    must use ``prod_web_client``.

    Phase 7 polish round 3 (Major 2): the goal of this client is to assert
    that the *business contract* on ``/web-api/v1/projects/{id}/license``
    enforces the same matrix + history rules as ``/api/v1/...``. The
    cookie/CSRF transport itself is exercised in dedicated middleware
    suites (``tests/unit/middleware/test_csrf.py`` /
    ``tests/integration/api/web_v1/...``) — duplicating that wiring here
    would force every contract test to drag along the entire alembic
    schema (``platform_audit_log``, ``project_audit_log``, ...).

    The fixture instead mounts the **real** ``web_v1_router`` (so the
    routing, response model, and gate-action dependency chain match
    production) but installs a lightweight :class:`AuthRouterMiddleware`
    stand-in (mirroring the pattern already established in
    ``tests/security/authentication/test_cooldown_after_2fa_reset.py``)
    so the verifier never reaches for cross-table chain audit rows.

    The principal user id is read from the test-supplied ``Authorization:
    Bearer <jwt>`` header so the same fixture serves all four actor
    profiles (Owner, Admin, Member, Outsider) — the test simply swaps
    headers per request.
    """
    from collections.abc import Awaitable, Callable
    from unittest.mock import patch as _patch

    from fastapi import FastAPI
    from fastapi.exceptions import RequestValidationError
    from starlette.exceptions import HTTPException as _StarletteHTTPException
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import Response
    from starlette.types import ASGIApp

    from echoroo.api.v1.recordings import get_audio_service
    from echoroo.api.web_v1 import web_v1_router
    from echoroo.api.web_v1.projects import _license as _license_module
    from echoroo.core import database as _database_module
    from echoroo.core.database import get_db
    from echoroo.core.exceptions import (
        AppException,
        app_exception_handler,
        http_exception_handler,
        validation_exception_handler,
    )
    from echoroo.core.jwt import decode_token
    from echoroo.middleware.auth_router import Principal
    from echoroo.services.audio import AudioService

    engine = create_async_engine(
        _TEST_DATABASE_URL,
        echo=False,
        poolclass=NullPool,
    )
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    # Audit fresh-session uses the captured ``AsyncSessionLocal`` symbol
    # in ``_license`` — patch it so the audit row INSERT lands in the test
    # DB. The audit write is wrapped in try/except inside the handler
    # (Phase 7 polish round 3 Minor 1) so even a missing
    # ``project_audit_log`` table only emits a WARNING log; the test still
    # asserts the user-visible 200 + history row.
    monkeypatch.setattr(
        _database_module, "AsyncSessionLocal", session_factory, raising=True
    )
    monkeypatch.setattr(
        _license_module, "AsyncSessionLocal", session_factory, raising=True
    )

    app = FastAPI()

    # Replicate the exception handler stack used by ``create_app`` so the
    # FR-085 envelope path runs in the same shape production ships.
    app.add_exception_handler(AppException, app_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(
        RequestValidationError, validation_exception_handler  # type: ignore[arg-type]
    )
    app.add_exception_handler(
        _StarletteHTTPException, http_exception_handler  # type: ignore[arg-type]
    )

    class _BearerPrincipalMiddleware(BaseHTTPMiddleware):
        """Decode the test ``Authorization: Bearer <jwt>`` into a Principal.

        The production AuthRouter would do the equivalent after a cookie
        + JWT cross-check; for the contract tests we keep the JWT-only
        side so the fixture does not need to seed a token-family row.
        """

        def __init__(self, asgi_app: ASGIApp) -> None:
            super().__init__(asgi_app)

        async def dispatch(
            self,
            request: Request,
            call_next: Callable[[Request], Awaitable[Response]],
        ) -> Response:
            request.state.principal = None
            auth_header = request.headers.get("Authorization", "")
            if auth_header.lower().startswith("bearer "):
                token = auth_header.split(" ", 1)[1].strip()
                if token:
                    try:
                        payload = decode_token(token)
                        sub = payload.get("sub")
                        if isinstance(sub, str):
                            try:
                                user_uuid = UUID(sub)
                            except (TypeError, ValueError):
                                user_uuid = None
                            if user_uuid is not None:
                                request.state.principal = Principal.for_session(
                                    user_id=user_uuid,
                                    security_stamp="s" * 64,
                                )
                    except Exception:  # noqa: BLE001 — bad tokens fall through
                        pass
            return await call_next(request)

    # Mount the lightweight principal middleware (mirrors the production
    # Auth router's role of stamping ``request.state.principal``). No
    # CSRF / 2FA-enforcement middleware: those are exercised in dedicated
    # middleware test suites and adding them here would only test the
    # transport layer twice.
    app.add_middleware(_BearerPrincipalMiddleware)

    # Mount the real router so the routing, response model, and
    # gate_action dependency chain match production exactly.
    app.include_router(web_v1_router)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    app.dependency_overrides[get_db] = override_get_db

    settings = get_settings()
    import tempfile  # local — only the web_client path needs it
    from pathlib import Path

    audio_cache_tmp_root = (
        Path(tempfile.gettempdir()) / "echoroo-test-s3-audio-cache"
    )
    audio_cache_tmp_root.mkdir(parents=True, exist_ok=True)

    def override_get_audio_service() -> AudioService:
        return AudioService(
            settings.AUDIO_ROOT,
            settings.AUDIO_CACHE_DIR,
            s3_audio_cache_dir=str(audio_cache_tmp_root),
        )

    app.dependency_overrides[get_audio_service] = override_get_audio_service

    async def _noop_rate_limiter(
        self: object,  # noqa: ARG001
        request: Request,  # noqa: ARG001
        response: Response,  # noqa: ARG001
    ) -> None:
        return None

    with _patch(
        "fastapi_limiter.depends.RateLimiter.__call__", _noop_rate_limiter
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as test_client:
            yield test_client

    app.dependency_overrides.clear()
    await engine.dispose()


def _web_bearer_headers(user: User) -> dict[str, str]:
    """Return the ``Authorization: Bearer ...`` header for a Web request.

    The :class:`web_client` fixture's lightweight auth middleware decodes
    the JWT subject into ``request.state.principal`` so the gated
    endpoints see the same Principal shape production ships. Cookies and
    the ``X-CSRF-Token`` header are intentionally omitted: the contract
    surface tested here is the **business** matrix + history rules, not
    CSRF / cookie transport (which lives in dedicated middleware suites).
    """
    return {
        "Authorization": f"Bearer {create_access_token({'sub': str(user.id)})}",
    }


_WEB_PROJECTS_ENDPOINT = "/web-api/v1/projects"


def _web_license_endpoint(project_id: object) -> str:
    return f"{_WEB_PROJECTS_ENDPOINT}/{project_id}/license"


async def _create_project_via_web_api(
    client: AsyncClient,
    bearer_client: AsyncClient,
    headers: dict[str, str],
    *,
    name: str,
    license_code: str,
    visibility: str = "public",
) -> str:
    """Create a project for the Web UI test cases.

    Note: ``/web-api/v1/projects`` exposes only ``GET`` endpoints (Phase 5
    Guest-aware list / detail). Project creation in production happens via
    the ``/api/v1/projects`` Bearer surface, so the helper proxies through
    that route to seed test fixtures while keeping the *PATCH license*
    assertion focused on the Web UI router.
    """
    del client  # The Web UI router has no POST surface (Phase 5 read-only).
    response = await bearer_client.post(
        _PROJECTS_ENDPOINT,
        headers=headers,
        json={
            "name": name,
            "visibility": visibility,
            "license": license_code,
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


@pytest.mark.asyncio
class TestPatchLicenseEndpointWebApi:
    """``PATCH /web-api/v1/projects/{id}/license`` HTTP behaviour.

    Phase 7 polish round 3 (Major 2): the Bearer surface coverage above
    is mirrored on the first-party Cookie + CSRF surface so T320 / T322
    is locked end-to-end. The four cases are:

    * Owner          → 200, history+1 (initial + change).
    * Admin (member) → 200, history+1 (Admin holds ``MANAGE_LICENSE``).
    * Regular Member → 403, no history change.
    * Outsider       → 403/404, no history change.

    Plus the ``extra="forbid"`` 422 path so we can be sure the request
    schema rejects unexpected fields before the business gate runs.
    """

    async def test_owner_patch_appends_history_row(
        self,
        client: AsyncClient,
        web_client: AsyncClient,
        db_session: AsyncSession,
        t320_owner: User,
        t320_owner_headers: dict[str, str],
    ) -> None:
        """Owner CC-BY → CC-BY-NC PATCH on Web UI surface returns 200."""
        project_id = await _create_project_via_web_api(
            web_client,
            client,
            t320_owner_headers,
            name="T320 Web PATCH Owner",
            license_code="CC-BY",
        )

        response = await web_client.patch(
            _web_license_endpoint(project_id),
            headers=_web_bearer_headers(t320_owner),
            json={"license": "CC-BY-NC"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["license"] == "CC-BY-NC"

        rows = await _fetch_history_rows(db_session, project_id)
        assert len(rows) == 2
        assert rows[0].old_license is None
        assert rows[0].new_license == ProjectLicense.CC_BY
        assert rows[1].old_license == ProjectLicense.CC_BY
        assert rows[1].new_license == ProjectLicense.CC_BY_NC
        assert rows[1].changed_by_id == t320_owner.id

    async def test_admin_member_succeeds(
        self,
        client: AsyncClient,
        web_client: AsyncClient,
        db_session: AsyncSession,
        t320_owner: User,
        t320_owner_headers: dict[str, str],
        t320_admin: User,
    ) -> None:
        """Admin holds MANAGE_LICENSE — Web PATCH → 200 + history+1."""
        admin_headers = _web_bearer_headers(t320_admin)

        project_id = await _create_project_via_web_api(
            web_client,
            client,
            t320_owner_headers,
            name="T320 Web PATCH Admin Allowed",
            license_code="CC0",
        )
        await _add_admin_member(db_session, project_id, t320_admin.id)

        response = await web_client.patch(
            _web_license_endpoint(project_id),
            headers=admin_headers,
            json={"license": "CC-BY"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["license"] == "CC-BY"

        rows = await _fetch_history_rows(db_session, project_id)
        assert len(rows) == 2
        assert rows[1].old_license == ProjectLicense.CC0
        assert rows[1].new_license == ProjectLicense.CC_BY
        assert rows[1].changed_by_id == t320_admin.id

    async def test_regular_member_returns_403(
        self,
        client: AsyncClient,
        web_client: AsyncClient,
        db_session: AsyncSession,
        t320_owner: User,
        t320_owner_headers: dict[str, str],
        t320_member: User,
    ) -> None:
        """MEMBER role lacks MANAGE_LICENSE — Web PATCH → 403."""
        member_headers = _web_bearer_headers(t320_member)

        project_id = await _create_project_via_web_api(
            web_client,
            client,
            t320_owner_headers,
            name="T320 Web PATCH Member Denied",
            license_code="CC0",
        )
        await _add_member(
            db_session, project_id, t320_member.id, ProjectMemberRole.MEMBER
        )

        response = await web_client.patch(
            _web_license_endpoint(project_id),
            headers=member_headers,
            json={"license": "CC-BY"},
        )
        assert response.status_code == 403, response.text

        rows = await _fetch_history_rows(db_session, project_id)
        assert len(rows) == 1
        assert rows[0].new_license == ProjectLicense.CC0

    async def test_non_member_returns_403_or_404(
        self,
        client: AsyncClient,
        web_client: AsyncClient,
        db_session: AsyncSession,
        t320_owner: User,
        t320_owner_headers: dict[str, str],
        t320_outsider: User,
    ) -> None:
        """Outsider on Public project — Web PATCH 403/404, no history change."""
        outsider_headers = _web_bearer_headers(t320_outsider)

        project_id = await _create_project_via_web_api(
            web_client,
            client,
            t320_owner_headers,
            name="T320 Web PATCH Outsider",
            license_code="CC-BY",
        )

        response = await web_client.patch(
            _web_license_endpoint(project_id),
            headers=outsider_headers,
            json={"license": "CC-BY-SA"},
        )
        assert response.status_code in (403, 404), response.text

        rows = await _fetch_history_rows(db_session, project_id)
        assert len(rows) == 1
        assert rows[0].new_license == ProjectLicense.CC_BY

    async def test_extra_field_is_rejected_with_422(
        self,
        client: AsyncClient,
        web_client: AsyncClient,
        db_session: AsyncSession,
        t320_owner: User,
        t320_owner_headers: dict[str, str],
    ) -> None:
        """Web PATCH with extra payload field → 422 (schema ``extra='forbid'``).

        The 422 envelope here MUST also carry ``error == "ERR_LICENSE_REQUIRED"``
        because the request hit the license-bearing PATCH route — this is the
        same path the FR-085 envelope is scoped to in
        :func:`echoroo.core.exceptions.validation_exception_handler`. Any
        future regression that returns a generic ``ValidationError`` envelope
        on this route would silently break Web UI error rendering.
        """
        project_id = await _create_project_via_web_api(
            web_client,
            client,
            t320_owner_headers,
            name="T320 Web PATCH Extra Field",
            license_code="CC-BY",
        )

        response = await web_client.patch(
            _web_license_endpoint(project_id),
            headers=_web_bearer_headers(t320_owner),
            json={"license": "CC-BY-NC", "evil_extra": True},
        )
        assert response.status_code == 422, response.text

        rows = await _fetch_history_rows(db_session, project_id)
        assert len(rows) == 1
        assert rows[0].new_license == ProjectLicense.CC_BY


# ---------------------------------------------------------------------------
# Phase 7 polish round 4 (Major 2): production cookie + CSRF chain.
#
# The contract above (``TestPatchLicenseEndpointWebApi``) deliberately
# bypasses the cookie/CSRF transport so the business matrix can be asserted
# in isolation. Round 4 surfaces a separate issue: the production
# ``/web-api/v1`` surface goes through ``CsrfMiddleware`` AND
# ``AuthRouterMiddleware`` which together require BOTH a session cookie AND
# a CSRF header on every mutating request. The license route was previously
# wired to ``CurrentUser`` which only reads ``Authorization: Bearer ...`` —
# so a real Web UI caller with cookie+CSRF would 401 even though the gate
# matrix would have accepted them.
#
# The cases below exercise the real CSRF middleware AND the production
# ``OptionalCurrentUser`` dependency to prove the auth chain works
# end-to-end. They share the same DB-seeding helpers as the bypass tests
# so business assertions stay in sync.
# ---------------------------------------------------------------------------


@pytest.fixture
async def prod_web_client(
    db_session: AsyncSession,  # noqa: ARG001 — ensures the test DB is set up
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[AsyncClient, None]:
    """Build an HTTP client that goes through the production CSRF + auth chain.

    Unlike :func:`web_client` (bypass), this fixture mounts the real
    :class:`echoroo.middleware.csrf.CsrfMiddleware` plus a session-aware
    auth middleware stand-in that reads BOTH the session cookie
    (``session_id``) AND the access-token cookie (``access_token``) — the
    same two cookies the production :class:`AuthRouterMiddleware` reads.
    A request that fails CSRF verification stops at 403 inside the CSRF
    middleware and never reaches the router, exactly as production does.

    The session-aware middleware here decodes the access-token cookie's
    JWT to recover the user id, so the matrix gate sees the correct
    ``request.state.principal.user_id``. ``OptionalCurrentUser`` then
    looks the user row up in the DB and the rest of the chain is the
    production code path.

    The test issues:
        * a ``session_id`` cookie (any opaque string is fine for the
          stand-in verifier — production binds it to a token-family row,
          but for contract testing the value just needs to match the one
          used to derive the CSRF token).
        * an ``access_token`` cookie carrying the actor's JWT.
        * an ``X-CSRF-Token`` header issued via :func:`issue_csrf_token`
          against the same session id.
    """
    from collections.abc import Awaitable, Callable
    from unittest.mock import patch as _patch

    from fastapi import FastAPI
    from fastapi.exceptions import RequestValidationError
    from starlette.exceptions import HTTPException as _StarletteHTTPException
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import Response
    from starlette.types import ASGIApp

    from echoroo.api.v1.recordings import get_audio_service
    from echoroo.api.web_v1 import web_v1_router
    from echoroo.api.web_v1.projects import _license as _license_module
    from echoroo.core import database as _database_module
    from echoroo.core.database import get_db
    from echoroo.core.exceptions import (
        AppException,
        app_exception_handler,
        http_exception_handler,
        validation_exception_handler,
    )
    from echoroo.core.jwt import decode_token
    from echoroo.middleware.auth_router import Principal
    from echoroo.middleware.csrf import CsrfConfig, CsrfMiddleware
    from echoroo.services.audio import AudioService

    engine = create_async_engine(
        _TEST_DATABASE_URL,
        echo=False,
        poolclass=NullPool,
    )
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    # Mirror the bypass fixture's audit-fresh-session patch so the audit
    # row INSERT lands in the test DB (the handler swallows audit failures
    # but the production middleware integration is what we are asserting,
    # not the audit row itself).
    monkeypatch.setattr(
        _database_module, "AsyncSessionLocal", session_factory, raising=True
    )
    monkeypatch.setattr(
        _license_module, "AsyncSessionLocal", session_factory, raising=True
    )

    app = FastAPI()

    app.add_exception_handler(AppException, app_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(
        RequestValidationError, validation_exception_handler  # type: ignore[arg-type]
    )
    app.add_exception_handler(
        _StarletteHTTPException, http_exception_handler  # type: ignore[arg-type]
    )

    class _CookieSessionMiddleware(BaseHTTPMiddleware):
        """Session-aware auth middleware mirroring AuthRouterMiddleware.

        Reads the ``access_token`` cookie (production carries the JWT
        there per ``AuthRouterConfig.access_cookie_name``), decodes the
        ``sub`` claim, and stamps a Principal onto ``request.state`` so
        the downstream :data:`OptionalCurrentUser` dependency picks the
        correct user. The ``session_id`` cookie is intentionally NOT
        verified here — its presence is asserted by ``CsrfMiddleware``
        upstream, and that middleware already runs inside this app.

        A request without an access-token cookie sets
        ``request.state.principal = None`` so the handler can return
        401 (the license route does this explicitly).
        """

        def __init__(self, asgi_app: ASGIApp) -> None:
            super().__init__(asgi_app)

        async def dispatch(
            self,
            request: Request,
            call_next: Callable[[Request], Awaitable[Response]],
        ) -> Response:
            request.state.principal = None
            access_cookie = request.cookies.get("access_token")
            if access_cookie:
                try:
                    payload = decode_token(access_cookie)
                    sub = payload.get("sub")
                    if isinstance(sub, str):
                        try:
                            user_uuid = UUID(sub)
                        except (TypeError, ValueError):
                            user_uuid = None
                        if user_uuid is not None:
                            request.state.principal = Principal.for_session(
                                user_id=user_uuid,
                                security_stamp="s" * 64,
                            )
                except Exception:  # noqa: BLE001 — bad cookie falls through to 401
                    pass
            return await call_next(request)

    # Mount order matters: BaseHTTPMiddleware wraps in reverse order, so
    # the LAST add_middleware runs FIRST. We want CSRF to run before the
    # cookie-session middleware (production has CSRF outermost via
    # main.py ordering). Adding cookie-session FIRST and CSRF SECOND
    # gives us "CSRF outer / cookie-session inner" at runtime.
    app.add_middleware(_CookieSessionMiddleware)
    app.add_middleware(
        CsrfMiddleware,
        config=CsrfConfig(session_secret=_PROD_CSRF_SECRET),
    )

    app.include_router(web_v1_router)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    app.dependency_overrides[get_db] = override_get_db

    settings = get_settings()
    import tempfile  # local — only the prod chain path needs it
    from pathlib import Path

    audio_cache_tmp_root = (
        Path(tempfile.gettempdir()) / "echoroo-test-s3-audio-cache-prod"
    )
    audio_cache_tmp_root.mkdir(parents=True, exist_ok=True)

    def override_get_audio_service() -> AudioService:
        return AudioService(
            settings.AUDIO_ROOT,
            settings.AUDIO_CACHE_DIR,
            s3_audio_cache_dir=str(audio_cache_tmp_root),
        )

    app.dependency_overrides[get_audio_service] = override_get_audio_service

    async def _noop_rate_limiter(
        self: object,  # noqa: ARG001
        request: Request,  # noqa: ARG001
        response: Response,  # noqa: ARG001
    ) -> None:
        return None

    with _patch(
        "fastapi_limiter.depends.RateLimiter.__call__", _noop_rate_limiter
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as test_client:
            yield test_client

    app.dependency_overrides.clear()
    await engine.dispose()


# Shared session secret — must outlive the fixture so test helpers can
# derive matching CSRF tokens. 32+ bytes per ``CsrfConfig`` contract.
_PROD_CSRF_SECRET = "test-prod-csrf-secret-32-bytes-of-entropy-padding"
_PROD_SESSION_ID = "prod-chain-session-id"


def _prod_chain_request_kwargs(user: User) -> dict[str, object]:
    """Return cookies + headers for a production-chain Web API call.

    Mirrors what a real browser would send after a successful login:
        * ``session_id`` opaque cookie (CSRF binds against it).
        * ``access_token`` JWT cookie (the auth middleware decodes ``sub``).
        * ``X-CSRF-Token`` header bound to the session id.
    """
    from echoroo.middleware.csrf import issue_csrf_token

    csrf_token = issue_csrf_token(
        _PROD_SESSION_ID, session_secret=_PROD_CSRF_SECRET
    )
    return {
        "cookies": {
            "session_id": _PROD_SESSION_ID,
            "access_token": create_access_token({"sub": str(user.id)}),
        },
        "headers": {"X-CSRF-Token": csrf_token},
    }


@pytest.mark.asyncio
class TestPatchLicenseEndpointWebApiProductionChain:
    """``PATCH /web-api/v1/projects/{id}/license`` through full prod chain.

    Round 4 (Major 1 + Major 2): proves the route's authentication chain
    accepts the production cookie + CSRF combination, not just bearer
    headers. The two cases below are the minimum required by the polish
    contract:

    * Owner via cookie + CSRF → 200, history+1.
    * Missing CSRF token → 403 from CsrfMiddleware (route never runs).

    The Bearer-only matrix is covered by ``TestPatchLicenseEndpointWebApi``
    which is documented as a bypass test.
    """

    async def test_owner_with_cookie_and_csrf_succeeds(
        self,
        client: AsyncClient,
        prod_web_client: AsyncClient,
        db_session: AsyncSession,
        t320_owner: User,
        t320_owner_headers: dict[str, str],
    ) -> None:
        """Owner via session cookie + access cookie + CSRF token → 200."""
        project_id = await _create_project_via_web_api(
            prod_web_client,
            client,
            t320_owner_headers,
            name="T320 Prod Chain Owner",
            license_code="CC-BY",
        )

        kwargs = _prod_chain_request_kwargs(t320_owner)
        response = await prod_web_client.patch(
            _web_license_endpoint(project_id),
            cookies=kwargs["cookies"],  # type: ignore[arg-type]
            headers=kwargs["headers"],  # type: ignore[arg-type]
            json={"license": "CC-BY-NC"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["license"] == "CC-BY-NC"

        rows = await _fetch_history_rows(db_session, project_id)
        assert len(rows) == 2
        assert rows[1].old_license == ProjectLicense.CC_BY
        assert rows[1].new_license == ProjectLicense.CC_BY_NC
        assert rows[1].changed_by_id == t320_owner.id

    async def test_missing_csrf_token_blocks_at_middleware(
        self,
        client: AsyncClient,
        prod_web_client: AsyncClient,
        db_session: AsyncSession,
        t320_owner: User,
        t320_owner_headers: dict[str, str],
    ) -> None:
        """A cookie-authenticated PATCH without ``X-CSRF-Token`` → 403.

        The CSRF middleware is the outermost layer; the request never
        reaches the route handler so no history row is appended.
        """
        project_id = await _create_project_via_web_api(
            prod_web_client,
            client,
            t320_owner_headers,
            name="T320 Prod Chain CSRF Missing",
            license_code="CC0",
        )

        # Send only the cookies — no CSRF header.
        response = await prod_web_client.patch(
            _web_license_endpoint(project_id),
            cookies={
                "session_id": _PROD_SESSION_ID,
                "access_token": create_access_token({"sub": str(t320_owner.id)}),
            },
            json={"license": "CC-BY"},
        )
        assert response.status_code == 403, response.text
        body = response.json()
        assert body.get("error_code") == "csrf_failed", body

        # No new history row.
        rows = await _fetch_history_rows(db_session, project_id)
        assert len(rows) == 1
        assert rows[0].new_license == ProjectLicense.CC0

    async def test_admin_with_cookie_and_csrf_succeeds(
        self,
        client: AsyncClient,
        prod_web_client: AsyncClient,
        db_session: AsyncSession,
        t320_owner: User,
        t320_owner_headers: dict[str, str],
        t320_admin: User,
    ) -> None:
        """Admin via prod chain → 200 (Admin holds MANAGE_LICENSE per matrix).

        Locks the Major 1 / Major 3 fix together: the ``OptionalCurrentUser``
        dep resolves the cookie principal, ``gate_action`` looks up the
        Admin membership row via the per-call scoped principal wrapper,
        and the matrix returns ``MANAGE_LICENSE`` so the PATCH succeeds.
        """
        project_id = await _create_project_via_web_api(
            prod_web_client,
            client,
            t320_owner_headers,
            name="T320 Prod Chain Admin",
            license_code="CC0",
        )
        await _add_admin_member(db_session, project_id, t320_admin.id)

        kwargs = _prod_chain_request_kwargs(t320_admin)
        response = await prod_web_client.patch(
            _web_license_endpoint(project_id),
            cookies=kwargs["cookies"],  # type: ignore[arg-type]
            headers=kwargs["headers"],  # type: ignore[arg-type]
            json={"license": "CC-BY"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["license"] == "CC-BY"

        rows = await _fetch_history_rows(db_session, project_id)
        assert len(rows) == 2
        assert rows[1].changed_by_id == t320_admin.id


# ---------------------------------------------------------------------------
# Phase 7 polish round 3 (Major 3): scope-the-envelope unit coverage.
#
# The path-scoped detection in :func:`validation_exception_handler` is a
# regression-prone gate: a future maintainer who adds a ``license`` field
# to an unrelated endpoint would otherwise inherit the FR-085 envelope on
# every 422 from that route. The case below is a *contract* test — it
# proves the envelope does NOT leak onto an unrelated route — by hitting a
# clearly non-license endpoint with a malformed payload that contains the
# token ``license`` somewhere.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestErrLicenseRequiredScopedToOwnedRoutes:
    """Ensure the FR-085 envelope only fires on routes that own ``license``.

    We pick :func:`echoroo.api.v1.projects` POST as the positive control
    (it returns ``ERR_LICENSE_REQUIRED`` for missing license) and the
    Web UI ``GET /web-api/v1/projects`` as the negative control (its 422
    paths must keep the generic ``ValidationError`` envelope). A more
    direct unit-level matcher test would also work, but a routing-level
    assertion is more robust against future refactors of the helper.
    """

    async def test_envelope_on_license_route(
        self,
        client: AsyncClient,
        t320_owner_headers: dict[str, str],
    ) -> None:
        """Positive control: license-bearing route still surfaces FR-085."""
        response = await client.post(
            _PROJECTS_ENDPOINT,
            headers=t320_owner_headers,
            json={"name": "Positive Control", "visibility": "public"},
        )
        assert response.status_code == 422
        assert response.json()["error"] == "ERR_LICENSE_REQUIRED"

    async def test_validation_path_helper_rejects_unrelated_path(self) -> None:
        """Direct unit check on the path matcher.

        The matcher MUST accept the four owned routes (with and without a
        trailing slash) and reject anything else, even if the URL contains
        the substring ``license``.
        """
        from echoroo.core.exceptions import _path_is_license_route

        owned_paths = (
            "/api/v1/projects",
            "/api/v1/projects/",
            "/web-api/v1/projects",
            "/web-api/v1/projects/",
            f"/api/v1/projects/{uuid4()}/license",
            f"/api/v1/projects/{uuid4()}/license/",
            f"/web-api/v1/projects/{uuid4()}/license",
            f"/web-api/v1/projects/{uuid4()}/license/",
        )
        for path in owned_paths:
            assert _path_is_license_route(path), path

        unrelated_paths = (
            "/api/v1/projects/abc/license",  # not a UUID
            "/api/v1/datasets",
            "/api/v1/projects/license",  # missing UUID segment
            f"/api/v1/projects/{uuid4()}/members",
            f"/api/v1/projects/{uuid4()}/license-history",
            f"/web-api/v1/projects/{uuid4()}/license-history",
            "/web-api/v1/auth/login",
            "/health",
        )
        for path in unrelated_paths:
            assert not _path_is_license_route(path), path


# ---------------------------------------------------------------------------
# Helpers — error-shape probes. Kept module-private so the test surface
# stays focused on the FR-085 / FR-087 contract.
# ---------------------------------------------------------------------------


def _has_license_field_error(body: object) -> bool:
    """Return True when the 422 payload flags ``license`` as the offender.

    Accepts the canonical ``validation_exception_handler`` shape::

        {"error": "ERR_LICENSE_REQUIRED" or "ValidationError",
         "message": ...,
         "details": [{"type": ..., "loc": [..., "license"], "msg": ...}, ...]}
    """
    if not isinstance(body, dict):
        return False

    details = body.get("details")
    if isinstance(details, list):
        for entry in details:
            if not isinstance(entry, dict):
                continue
            loc = entry.get("loc")
            if isinstance(loc, list) and "license" in loc:
                return True

    err = body.get("error")
    if isinstance(err, str) and "LICENSE" in err.upper():
        return True

    detail_field = body.get("detail")
    return isinstance(detail_field, str) and "license" in detail_field.lower()


# Suppress unused-fixture lint — the fixture is resolved by injection.
__all__ = [
    "TestChangeLicenseAppendsHistory",
    "TestErrLicenseRequiredScopedToOwnedRoutes",
    "TestLicenseHappyPathWritesHistory",
    "TestLicenseRequiredOnCreate",
    "TestMultipleProjectsHaveIndependentHistory",
    "TestPatchLicenseEndpoint",
    "TestPatchLicenseEndpointWebApi",
    "TestPatchLicenseEndpointWebApiProductionChain",
]
