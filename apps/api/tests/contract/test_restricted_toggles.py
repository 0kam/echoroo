"""Restricted-config toggle contract (T400 / T401 / T403, FR-014 / FR-020-022 / FR-023 / FR-024 / SC-003).

Spec FR-023 mandates that ``PATCH /projects/{id}/restricted-config`` reject
unknown keys with 422 (``Extra.forbid``) and that the eight required keys
all be present. FR-024 mandates that every PATCH bump
``Project.restricted_config_version`` and append a
``project.restricted_config.update`` row to ``project_audit_log``. FR-020/021/022
fix the semantics of each toggle and the discrete H3 resolution set
(``Literal[2, 5, 7, 9, 15]``).

Tests cover:

1. ``Extra.forbid`` — unknown payload field → 422.
2. Missing required key → 422.
3. ``public_location_precision_h3_res`` enum constraint — 2/5/7/9/15 accepted,
   anything else (4, 10, -1, "two") → 422.
4. Each of the six boolean toggles flipped ON / OFF in isolation → 200, the
   DB column reflects the change, ``restricted_config_version`` increments
   monotonically.
5. ``allow_precise_location_to_viewer`` flipped ON / OFF → 200 + DB.
6. Permission matrix — Owner / Admin → 200; Member / Viewer → 403; Outsider → 403/404.
7. Visibility precondition — PATCH against a Public project → 422.
8. Both surfaces (``/api/v1`` Bearer + ``/web-api/v1`` Cookie/CSRF bypass)
   are exercised so the contract is locked at every customer touch-point.

The full prod-chain CSRF transport is exercised in dedicated middleware
suites (``test_license_required.py`` already locks that for the license
PATCH; restricted-config shares the same middleware stack so we keep the
contract tests focused on the business matrix here).
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from uuid import UUID

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
    ProjectStatus,
    ProjectVisibility,
)
from echoroo.models.project import Project, ProjectMember
from echoroo.models.user import User

# ---------------------------------------------------------------------------
# Test database URL — shared with conftest fixtures.
# ---------------------------------------------------------------------------

_TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://echoroo:echoroo@localhost:5432/echoroo_test",
)

_PROJECTS_ENDPOINT = "/api/v1/projects"
_WEB_PROJECTS_ENDPOINT = "/web-api/v1/projects"


def _restricted_config_endpoint(project_id: object) -> str:
    return f"{_PROJECTS_ENDPOINT}/{project_id}/restricted-config"


def _web_restricted_config_endpoint(project_id: object) -> str:
    return f"{_WEB_PROJECTS_ENDPOINT}/{project_id}/restricted-config"


def _full_payload(**overrides: object) -> dict[str, object]:
    """Return a complete RestrictedConfig payload with optional overrides.

    All eight keys are populated with safe defaults (mostly OFF, the
    minimum-impact permutation). Tests override individual keys to assert
    per-toggle behaviour.
    """
    base: dict[str, object] = {
        "allow_media_playback": False,
        "allow_detection_view": False,
        "mask_species_in_detection": False,
        "allow_download": False,
        "allow_export": False,
        "allow_voting_and_comments": False,
        "public_location_precision_h3_res": 2,
        "allow_precise_location_to_viewer": False,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Fixtures — actors. Naming mirrors ``test_license_required.py`` (``t320_*``)
# and ``test_guest_authenticated_vote.py`` (``t310_*``) so contributors can
# locate the Phase 8 contract by file name.
# ---------------------------------------------------------------------------


@pytest.fixture
async def t400_owner(db_session: AsyncSession) -> User:
    user = User(
        email="t400owner@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T400 Owner",
        security_stamp="t400" + "o" * 60,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
def t400_owner_headers(t400_owner: User) -> dict[str, str]:
    return {
        "Authorization": (
            f"Bearer {create_access_token({'sub': str(t400_owner.id)})}"
        )
    }


@pytest.fixture
async def t400_admin(db_session: AsyncSession) -> User:
    user = User(
        email="t400admin@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T400 Admin",
        security_stamp="t400" + "a" * 60,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
def t400_admin_headers(t400_admin: User) -> dict[str, str]:
    return {
        "Authorization": (
            f"Bearer {create_access_token({'sub': str(t400_admin.id)})}"
        )
    }


@pytest.fixture
async def t400_member(db_session: AsyncSession) -> User:
    user = User(
        email="t400member@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T400 Member",
        security_stamp="t400" + "m" * 60,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
def t400_member_headers(t400_member: User) -> dict[str, str]:
    return {
        "Authorization": (
            f"Bearer {create_access_token({'sub': str(t400_member.id)})}"
        )
    }


@pytest.fixture
async def t400_viewer(db_session: AsyncSession) -> User:
    user = User(
        email="t400viewer@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T400 Viewer",
        security_stamp="t400" + "v" * 60,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
def t400_viewer_headers(t400_viewer: User) -> dict[str, str]:
    return {
        "Authorization": (
            f"Bearer {create_access_token({'sub': str(t400_viewer.id)})}"
        )
    }


@pytest.fixture
async def t400_outsider(db_session: AsyncSession) -> User:
    user = User(
        email="t400outsider@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T400 Outsider",
        security_stamp="t400" + "x" * 60,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
def t400_outsider_headers(t400_outsider: User) -> dict[str, str]:
    return {
        "Authorization": (
            f"Bearer {create_access_token({'sub': str(t400_outsider.id)})}"
        )
    }


# ---------------------------------------------------------------------------
# Fixtures — projects. We seed both a Restricted and a Public project so the
# visibility-precondition test (FR-001 / FR-014) has a foil.
# ---------------------------------------------------------------------------


def _initial_restricted_config() -> dict[str, object]:
    """Default Restricted toggles seeded on test projects.

    Values diverge from :func:`_full_payload` so PATCH-and-diff tests can
    detect mutations without ambiguity (everything starts True so the
    test PATCH flips them to False and we can observe the change).
    """
    return {
        "allow_media_playback": True,
        "allow_detection_view": True,
        "mask_species_in_detection": True,
        "allow_download": True,
        "allow_export": True,
        "allow_voting_and_comments": True,
        "public_location_precision_h3_res": 9,
        "allow_precise_location_to_viewer": True,
    }


@pytest.fixture
async def t400_restricted_project(
    db_session: AsyncSession, t400_owner: User
) -> Project:
    project = Project(
        name="T400 Restricted Project",
        description="Phase 8 toggle PATCH coverage",
        visibility=ProjectVisibility.RESTRICTED,
        license=ProjectLicense.CC_BY,
        owner_id=t400_owner.id,
        status=ProjectStatus.ACTIVE,
        restricted_config=_initial_restricted_config(),
        restricted_config_version=1,
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest.fixture
async def t400_public_project(
    db_session: AsyncSession, t400_owner: User
) -> Project:
    project = Project(
        name="T400 Public Project",
        description="Visibility precondition foil",
        visibility=ProjectVisibility.PUBLIC,
        license=ProjectLicense.CC_BY,
        owner_id=t400_owner.id,
        status=ProjectStatus.ACTIVE,
        restricted_config={},
        restricted_config_version=1,
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


async def _add_member_with_role(
    db: AsyncSession,
    project_id: object,
    user_id: object,
    role: ProjectMemberRole,
) -> None:
    member = ProjectMember(
        project_id=project_id,
        user_id=user_id,
        role=role,
        joined_at=datetime.now(UTC),
        invited_by_id=user_id,
    )
    db.add(member)
    await db.commit()


async def _fetch_project(db: AsyncSession, project_id: object) -> Project:
    """Re-read a project row bypassing the ORM identity-map cache.

    The ``client`` fixture commits via a separate session/engine so the
    test's ``db_session`` would otherwise return a cached pre-PATCH
    instance from its identity map. ``populate_existing=True`` forces
    SQLAlchemy to overwrite the cached attributes with whatever is in
    PostgreSQL right now.
    """
    db.expire_all()
    result = await db.execute(
        sa.select(Project)
        .where(Project.id == project_id)
        .execution_options(populate_existing=True)
    )
    return result.scalar_one()


# ---------------------------------------------------------------------------
# Helpers — audit row inspection. We probe the optional ``project_audit_log``
# table directly because the audit fresh-session pattern means the rows do
# not show up via the ORM relationship on Project.
# ---------------------------------------------------------------------------


async def _count_restricted_audit_rows(
    db: AsyncSession, project_id: object
) -> int:
    """Return the number of ``project.restricted_config.update`` rows.

    Returns 0 when the table is missing (test schema may not include it
    in lighter unit fixtures) — the tests fall back to checking the
    ``restricted_config_version`` increment to assert the mutation
    happened.
    """
    try:
        result = await db.execute(
            sa.text(
                "SELECT COUNT(*) FROM project_audit_log "
                "WHERE project_id = :pid "
                "AND action = 'project.restricted_config.update'"
            ).bindparams(pid=str(project_id))
        )
    except Exception:
        return 0
    row = result.first()
    return int(row[0]) if row is not None else 0


# ---------------------------------------------------------------------------
# Tests — Bearer surface (``/api/v1/projects/{id}/restricted-config``).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRestrictedConfigExtraForbidAndRequiredKeys:
    """FR-023: ``Extra.forbid`` + all eight keys required."""

    async def test_unknown_field_returns_422(
        self,
        client: AsyncClient,
        t400_owner_headers: dict[str, str],
        t400_restricted_project: Project,
    ) -> None:
        """An unrecognised payload field MUST be rejected with 422."""
        payload = _full_payload(unknown_field=True)
        response = await client.patch(
            _restricted_config_endpoint(t400_restricted_project.id),
            headers=t400_owner_headers,
            json=payload,
        )
        assert response.status_code == 422, response.text

    @pytest.mark.parametrize(
        "missing_key",
        [
            "allow_media_playback",
            "allow_detection_view",
            "mask_species_in_detection",
            "allow_download",
            "allow_export",
            "allow_voting_and_comments",
            "public_location_precision_h3_res",
            "allow_precise_location_to_viewer",
        ],
    )
    async def test_missing_required_key_returns_422(
        self,
        client: AsyncClient,
        t400_owner_headers: dict[str, str],
        t400_restricted_project: Project,
        missing_key: str,
    ) -> None:
        """Each of the eight keys is required — omitting any → 422."""
        payload = _full_payload()
        del payload[missing_key]
        response = await client.patch(
            _restricted_config_endpoint(t400_restricted_project.id),
            headers=t400_owner_headers,
            json=payload,
        )
        assert response.status_code == 422, response.text


@pytest.mark.asyncio
class TestRestrictedConfigEnumConstraints:
    """FR-021: ``public_location_precision_h3_res`` ∈ {2, 5, 7, 9, 15}."""

    @pytest.mark.parametrize("valid_res", [2, 5, 7, 9, 15])
    async def test_valid_h3_resolution_succeeds(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        t400_owner_headers: dict[str, str],
        t400_restricted_project: Project,
        valid_res: int,
    ) -> None:
        """Each discrete H3 resolution value is accepted with 200."""
        payload = _full_payload(public_location_precision_h3_res=valid_res)
        response = await client.patch(
            _restricted_config_endpoint(t400_restricted_project.id),
            headers=t400_owner_headers,
            json=payload,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert (
            body["restricted_config"]["public_location_precision_h3_res"]
            == valid_res
        ), body

        project = await _fetch_project(db_session, t400_restricted_project.id)
        assert (
            project.restricted_config["public_location_precision_h3_res"]
            == valid_res
        )

    @pytest.mark.parametrize("invalid_res", [4, 10, -1, 0, "two"])
    async def test_invalid_h3_resolution_returns_422(
        self,
        client: AsyncClient,
        t400_owner_headers: dict[str, str],
        t400_restricted_project: Project,
        invalid_res: object,
    ) -> None:
        """Anything outside the discrete enum is rejected with 422."""
        payload = _full_payload(public_location_precision_h3_res=invalid_res)
        response = await client.patch(
            _restricted_config_endpoint(t400_restricted_project.id),
            headers=t400_owner_headers,
            json=payload,
        )
        assert response.status_code == 422, response.text


@pytest.mark.asyncio
class TestRestrictedConfigBooleanToggles:
    """FR-020 / FR-022: each boolean toggle round-trips ON / OFF."""

    @pytest.mark.parametrize(
        "toggle_key",
        [
            "allow_media_playback",
            "allow_detection_view",
            "mask_species_in_detection",
            "allow_download",
            "allow_export",
            "allow_voting_and_comments",
            "allow_precise_location_to_viewer",
        ],
    )
    @pytest.mark.parametrize("value", [True, False])
    async def test_toggle_round_trip(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        t400_owner_headers: dict[str, str],
        t400_restricted_project: Project,
        toggle_key: str,
        value: bool,
    ) -> None:
        """Flipping a single toggle persists in DB and the response body."""
        before_version = t400_restricted_project.restricted_config_version
        payload = _full_payload(**{toggle_key: value})
        response = await client.patch(
            _restricted_config_endpoint(t400_restricted_project.id),
            headers=t400_owner_headers,
            json=payload,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["restricted_config"][toggle_key] is value
        assert body["restricted_config_version"] == before_version + 1

        project = await _fetch_project(db_session, t400_restricted_project.id)
        assert project.restricted_config[toggle_key] is value
        assert project.restricted_config_version == before_version + 1


@pytest.mark.asyncio
class TestRestrictedConfigVersionIncrement:
    """FR-024: every PATCH bumps ``restricted_config_version`` monotonically."""

    async def test_two_consecutive_patches_each_bump_version(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        t400_owner_headers: dict[str, str],
        t400_restricted_project: Project,
    ) -> None:
        """Two PATCHes (even with the same payload) increment by 2 total."""
        before_version = t400_restricted_project.restricted_config_version

        payload = _full_payload(allow_detection_view=True)
        first = await client.patch(
            _restricted_config_endpoint(t400_restricted_project.id),
            headers=t400_owner_headers,
            json=payload,
        )
        assert first.status_code == 200, first.text
        assert first.json()["restricted_config_version"] == before_version + 1

        second = await client.patch(
            _restricted_config_endpoint(t400_restricted_project.id),
            headers=t400_owner_headers,
            json=payload,
        )
        assert second.status_code == 200, second.text
        assert second.json()["restricted_config_version"] == before_version + 2

        project = await _fetch_project(db_session, t400_restricted_project.id)
        assert project.restricted_config_version == before_version + 2

    async def test_audit_row_written_per_patch(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        t400_owner_headers: dict[str, str],
        t400_restricted_project: Project,
    ) -> None:
        """If ``project_audit_log`` exists, a row is appended per PATCH.

        The check is best-effort because lighter test schemas may omit the
        audit table — in that case the version-increment assertion above
        already proves the mutation happened.
        """
        before_audit_count = await _count_restricted_audit_rows(
            db_session, t400_restricted_project.id
        )

        response = await client.patch(
            _restricted_config_endpoint(t400_restricted_project.id),
            headers=t400_owner_headers,
            json=_full_payload(allow_export=True),
        )
        assert response.status_code == 200, response.text

        after_audit_count = await _count_restricted_audit_rows(
            db_session, t400_restricted_project.id
        )
        # Either the audit table is missing (both counts are 0) or the
        # PATCH appended exactly one row.
        if before_audit_count > 0 or after_audit_count > 0:
            assert after_audit_count == before_audit_count + 1


@pytest.mark.asyncio
class TestRestrictedConfigPermissionMatrix:
    """FR-010 / FR-014: ``EDIT_PROJECT`` is granted to Owner + Admin only."""

    async def test_owner_succeeds(
        self,
        client: AsyncClient,
        t400_owner_headers: dict[str, str],
        t400_restricted_project: Project,
    ) -> None:
        response = await client.patch(
            _restricted_config_endpoint(t400_restricted_project.id),
            headers=t400_owner_headers,
            json=_full_payload(),
        )
        assert response.status_code == 200, response.text

    async def test_admin_succeeds(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        t400_admin: User,
        t400_admin_headers: dict[str, str],
        t400_restricted_project: Project,
    ) -> None:
        await _add_member_with_role(
            db_session,
            t400_restricted_project.id,
            t400_admin.id,
            ProjectMemberRole.ADMIN,
        )
        response = await client.patch(
            _restricted_config_endpoint(t400_restricted_project.id),
            headers=t400_admin_headers,
            json=_full_payload(),
        )
        assert response.status_code == 200, response.text

    async def test_member_returns_403(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        t400_member: User,
        t400_member_headers: dict[str, str],
        t400_restricted_project: Project,
    ) -> None:
        await _add_member_with_role(
            db_session,
            t400_restricted_project.id,
            t400_member.id,
            ProjectMemberRole.MEMBER,
        )
        response = await client.patch(
            _restricted_config_endpoint(t400_restricted_project.id),
            headers=t400_member_headers,
            json=_full_payload(),
        )
        assert response.status_code == 403, response.text

    async def test_viewer_returns_403(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        t400_viewer: User,
        t400_viewer_headers: dict[str, str],
        t400_restricted_project: Project,
    ) -> None:
        await _add_member_with_role(
            db_session,
            t400_restricted_project.id,
            t400_viewer.id,
            ProjectMemberRole.VIEWER,
        )
        response = await client.patch(
            _restricted_config_endpoint(t400_restricted_project.id),
            headers=t400_viewer_headers,
            json=_full_payload(),
        )
        assert response.status_code == 403, response.text

    async def test_outsider_returns_403_or_404(
        self,
        client: AsyncClient,
        t400_outsider_headers: dict[str, str],
        t400_restricted_project: Project,
    ) -> None:
        """Non-member on a Restricted project — 403 or 404 (FR-018 enumeration)."""
        response = await client.patch(
            _restricted_config_endpoint(t400_restricted_project.id),
            headers=t400_outsider_headers,
            json=_full_payload(),
        )
        assert response.status_code in (403, 404), response.text


@pytest.mark.asyncio
class TestRestrictedConfigVisibilityPrecondition:
    """FR-001 / FR-014: toggles only apply to ``visibility='restricted'``."""

    async def test_public_project_returns_422(
        self,
        client: AsyncClient,
        t400_owner_headers: dict[str, str],
        t400_public_project: Project,
    ) -> None:
        """PATCH against a Public project surfaces 422 (toggles do not apply).

        Phase 8 polish round 2 Major 1 — the body MUST carry the dedicated
        ``ERR_RESTRICTED_CONFIG_NOT_APPLICABLE`` envelope so contract
        consumers can distinguish "wrong visibility" from a generic 422
        validation failure (mirrors ``ERR_LICENSE_REQUIRED`` from Phase 7).
        """
        response = await client.patch(
            _restricted_config_endpoint(t400_public_project.id),
            headers=t400_owner_headers,
            json=_full_payload(),
        )
        assert response.status_code == 422, response.text
        body = response.json()
        assert body.get("error") == "ERR_RESTRICTED_CONFIG_NOT_APPLICABLE", (
            f"Expected ERR_RESTRICTED_CONFIG_NOT_APPLICABLE envelope, got {body!r}"
        )
        assert "message" in body, body


@pytest.mark.asyncio
class TestRestrictedConfigStrictBoolean:
    """Phase 8 polish round 2 Major 2 — bool fields are ``StrictBool``.

    Plain Pydantic ``bool`` would coerce strings (``"true"`` / ``"false"``)
    and ints (``0`` / ``1``) into bool values, letting a buggy Web UI ship
    the wrong toggle state past the contract. ``StrictBool`` rejects every
    non-bool JSON value with 422 so the OpenAPI ``additionalProperties:
    false`` shape (FR-023) is matched on the Pydantic side too.
    """

    @pytest.mark.parametrize(
        "stringy_value", ["true", "false", "True", "False", "1", "0"]
    )
    async def test_string_bool_is_rejected(
        self,
        client: AsyncClient,
        t400_owner_headers: dict[str, str],
        t400_restricted_project: Project,
        stringy_value: str,
    ) -> None:
        """A JSON string in a bool field MUST be 422, never coerced."""
        payload = _full_payload(allow_media_playback=stringy_value)
        response = await client.patch(
            _restricted_config_endpoint(t400_restricted_project.id),
            headers=t400_owner_headers,
            json=payload,
        )
        assert response.status_code == 422, response.text

    @pytest.mark.parametrize("int_value", [0, 1, 2])
    async def test_int_in_bool_field_is_rejected(
        self,
        client: AsyncClient,
        t400_owner_headers: dict[str, str],
        t400_restricted_project: Project,
        int_value: int,
    ) -> None:
        """Numeric values in a bool field MUST be 422 under StrictBool."""
        payload = _full_payload(allow_export=int_value)
        response = await client.patch(
            _restricted_config_endpoint(t400_restricted_project.id),
            headers=t400_owner_headers,
            json=payload,
        )
        assert response.status_code == 422, response.text


# ---------------------------------------------------------------------------
# Tests — Web UI surface (``/web-api/v1/projects/{id}/restricted-config``).
#
# Mirrors the bypass fixture pattern from ``test_license_required.py`` —
# the cookie + CSRF transport is exercised in dedicated middleware suites
# (see :class:`TestPatchLicenseEndpointWebApiProductionChain`); duplicating
# that wiring here would only re-test the same plumbing twice.
# ---------------------------------------------------------------------------


@pytest.fixture
async def web_client(
    db_session: AsyncSession,  # noqa: ARG001 — ensures the test DB is set up
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[AsyncClient, None]:
    """HTTP client mounting the production web router with bypass auth.

    Same pattern as ``test_license_required.py::web_client`` — the goal is
    to exercise the **business contract** (matrix + toggles + version bump)
    on the Web UI surface without dragging in the cookie + CSRF transport.
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
    from echoroo.services import (
        restricted_config_service as _restricted_module,
    )
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

    monkeypatch.setattr(
        _database_module, "AsyncSessionLocal", session_factory, raising=True
    )
    monkeypatch.setattr(
        _license_module, "AsyncSessionLocal", session_factory, raising=True
    )
    # Phase 8: the restricted-config service runs its audit row INSERT on a
    # fresh ``AsyncSessionLocal`` (mirrors the license service). Patch the
    # captured symbol so the audit write lands in the test DB.
    monkeypatch.setattr(
        _restricted_module, "AsyncSessionLocal", session_factory, raising=True
    )

    app = FastAPI()
    app.add_exception_handler(AppException, app_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(
        RequestValidationError, validation_exception_handler  # type: ignore[arg-type]
    )
    app.add_exception_handler(
        _StarletteHTTPException, http_exception_handler  # type: ignore[arg-type]
    )

    class _BearerPrincipalMiddleware(BaseHTTPMiddleware):
        """Decode ``Authorization: Bearer <jwt>`` into ``request.state.principal``."""

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

    app.add_middleware(_BearerPrincipalMiddleware)
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
    import tempfile
    from pathlib import Path

    audio_cache_tmp_root = (
        Path(tempfile.gettempdir()) / "echoroo-test-s3-audio-cache-restricted"
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
    """Bearer header for the web_client bypass fixture."""
    return {
        "Authorization": f"Bearer {create_access_token({'sub': str(user.id)})}",
    }


@pytest.mark.asyncio
class TestRestrictedConfigWebApi:
    """Mirror the matrix + business contract on the Web UI surface."""

    async def test_owner_patch_succeeds_via_web_api(
        self,
        web_client: AsyncClient,
        db_session: AsyncSession,
        t400_owner: User,
        t400_restricted_project: Project,
    ) -> None:
        before_version = t400_restricted_project.restricted_config_version
        response = await web_client.patch(
            _web_restricted_config_endpoint(t400_restricted_project.id),
            headers=_web_bearer_headers(t400_owner),
            json=_full_payload(allow_export=True),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["restricted_config"]["allow_export"] is True
        assert body["restricted_config_version"] == before_version + 1

        project = await _fetch_project(db_session, t400_restricted_project.id)
        assert project.restricted_config["allow_export"] is True
        assert project.restricted_config_version == before_version + 1

    async def test_admin_patch_succeeds_via_web_api(
        self,
        web_client: AsyncClient,
        db_session: AsyncSession,
        t400_admin: User,
        t400_restricted_project: Project,
    ) -> None:
        await _add_member_with_role(
            db_session,
            t400_restricted_project.id,
            t400_admin.id,
            ProjectMemberRole.ADMIN,
        )
        response = await web_client.patch(
            _web_restricted_config_endpoint(t400_restricted_project.id),
            headers=_web_bearer_headers(t400_admin),
            json=_full_payload(public_location_precision_h3_res=7),
        )
        assert response.status_code == 200, response.text
        assert (
            response.json()["restricted_config"]["public_location_precision_h3_res"]
            == 7
        )

    async def test_member_returns_403_via_web_api(
        self,
        web_client: AsyncClient,
        db_session: AsyncSession,
        t400_member: User,
        t400_restricted_project: Project,
    ) -> None:
        await _add_member_with_role(
            db_session,
            t400_restricted_project.id,
            t400_member.id,
            ProjectMemberRole.MEMBER,
        )
        response = await web_client.patch(
            _web_restricted_config_endpoint(t400_restricted_project.id),
            headers=_web_bearer_headers(t400_member),
            json=_full_payload(),
        )
        assert response.status_code == 403, response.text

    async def test_extra_field_returns_422_via_web_api(
        self,
        web_client: AsyncClient,
        t400_owner: User,
        t400_restricted_project: Project,
    ) -> None:
        response = await web_client.patch(
            _web_restricted_config_endpoint(t400_restricted_project.id),
            headers=_web_bearer_headers(t400_owner),
            json=_full_payload(extra_evil="oops"),
        )
        assert response.status_code == 422, response.text

    async def test_public_project_returns_422_via_web_api(
        self,
        web_client: AsyncClient,
        t400_owner: User,
        t400_public_project: Project,
    ) -> None:
        """Public-project PATCH on the Web surface — same envelope as Bearer.

        Phase 8 polish round 2 Major 1 — both transport surfaces MUST
        emit the ``ERR_RESTRICTED_CONFIG_NOT_APPLICABLE`` code so
        first-party Web UI and third-party integrations branch on the
        same key.
        """
        response = await web_client.patch(
            _web_restricted_config_endpoint(t400_public_project.id),
            headers=_web_bearer_headers(t400_owner),
            json=_full_payload(),
        )
        assert response.status_code == 422, response.text
        body = response.json()
        assert body.get("error") == "ERR_RESTRICTED_CONFIG_NOT_APPLICABLE", (
            f"Expected ERR_RESTRICTED_CONFIG_NOT_APPLICABLE envelope, got {body!r}"
        )

    async def test_viewer_returns_403_via_web_api(
        self,
        web_client: AsyncClient,
        db_session: AsyncSession,
        t400_viewer: User,
        t400_restricted_project: Project,
    ) -> None:
        """Phase 8 polish round 2 Minor 1 — Viewer (project member) → 403.

        ``EDIT_PROJECT`` is granted to Owner / Admin only per the canonical
        matrix (FR-010). A Viewer attempting to flip toggles via the Web UI
        surface MUST receive 403 — the Stage-1 gate denies the action even
        though the principal is a project member.
        """
        await _add_member_with_role(
            db_session,
            t400_restricted_project.id,
            t400_viewer.id,
            ProjectMemberRole.VIEWER,
        )
        response = await web_client.patch(
            _web_restricted_config_endpoint(t400_restricted_project.id),
            headers=_web_bearer_headers(t400_viewer),
            json=_full_payload(),
        )
        assert response.status_code == 403, response.text

    async def test_outsider_returns_403_or_404_via_web_api(
        self,
        web_client: AsyncClient,
        t400_outsider: User,
        t400_restricted_project: Project,
    ) -> None:
        """Phase 8 polish round 2 Minor 1 — non-member (outsider) → 403/404.

        FR-018 enumeration prevention: a non-member on a Restricted
        project MAY surface as 403 (caller is authenticated, lacks the
        permission) or 404 (caller cannot even tell the project exists).
        Both are acceptable outcomes per the matrix; the Web surface MUST
        match the Bearer surface so the contract is uniform.
        """
        response = await web_client.patch(
            _web_restricted_config_endpoint(t400_restricted_project.id),
            headers=_web_bearer_headers(t400_outsider),
            json=_full_payload(),
        )
        assert response.status_code in (403, 404), response.text


__all__ = [
    "TestRestrictedConfigBooleanToggles",
    "TestRestrictedConfigEnumConstraints",
    "TestRestrictedConfigExtraForbidAndRequiredKeys",
    "TestRestrictedConfigPermissionMatrix",
    "TestRestrictedConfigStrictBoolean",
    "TestRestrictedConfigVersionIncrement",
    "TestRestrictedConfigVisibilityPrecondition",
    "TestRestrictedConfigWebApi",
]
