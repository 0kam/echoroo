"""API-shape regression test for ``ProjectResponse.license`` (spec/012 T035).

Pins research §R1: ``GET /projects/{id}`` MUST return ``license`` as a plain
``string | null`` — never as an enum value, a nested object, or a typed
constant. This guards against the ORM hybrid property returning an unexpected
type as the SQLAlchemy model evolves from an enum column to an FK-backed
property.

Cases:
    * ``GET /projects/{id}`` for a project created with a known license
      returns ``license: "CC-BY"`` (plain string).
    * ``GET /projects/{id}`` for a project whose ``license_id IS NULL``
      returns ``license: null`` (JSON null, not the string ``"None"`` or
      a missing key).
    * The ``license`` field is present on EVERY ``ProjectResponse`` — it
      MUST NOT be conditionally omitted.

Both the Bearer (``/api/v1/projects``) and BFF (``/web-api/v1/projects``)
surfaces are tested so the regression guard applies to both customer
touch-points.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.auth import issue_access_token
from echoroo.core.jwt import create_access_token
from echoroo.core.settings import get_settings
from echoroo.models.enums import ProjectStatus, ProjectVisibility
from echoroo.models.project import Project
from echoroo.models.user import User
from tests.conftest import seed_canonical_test_licenses

_API_PROJECTS = "/api/v1/projects"
_WEB_PROJECTS = "/web-api/v1/projects"

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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def t035_user(db_session: AsyncSession) -> User:
    """Plain authenticated user — owner of the projects under test."""
    user = User(
        email="t035-owner@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T035 Owner",
        security_stamp="t035" + "o" * 60,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
def t035_api_headers(t035_user: User) -> dict[str, str]:
    return {
        "Authorization": (
            f"Bearer {create_access_token({'sub': str(t035_user.id)})}"
        )
    }


@pytest.fixture
async def t035_bff_auth(
    db_session: AsyncSession,
    t035_user: User,
) -> dict[str, dict[str, str]]:
    """Session cookie + Bearer header for BFF surface requests."""
    from uuid import uuid4

    session_id = uuid4()
    await db_session.execute(
        sa.text(
            "INSERT INTO token_families (family_id, user_id, created_at) "
            "VALUES (:family_id, :user_id, NOW())"
        ),
        {"family_id": session_id, "user_id": t035_user.id},
    )
    await db_session.commit()

    access_token = issue_access_token(
        user_id=t035_user.id,
        security_stamp=t035_user.security_stamp,
    )
    return {
        "headers": {"Authorization": f"Bearer {access_token}"},
        "cookies": {get_settings().web_session_cookie_name: str(session_id)},
    }


@pytest.fixture
async def t035_project_with_license(
    db_session: AsyncSession,
    t035_user: User,
) -> Project:
    """Project seeded directly via ORM with ``license_id = "cc-by"``."""
    await seed_canonical_test_licenses(db_session)
    project = Project(
        name="T035 License Shape Project",
        description="API-shape regression test project",
        visibility=ProjectVisibility.RESTRICTED,
        license_id="cc-by",
        owner_id=t035_user.id,
        status=ProjectStatus.ACTIVE,
        restricted_config=dict(_DEFAULT_RESTRICTED_CONFIG),
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest.fixture
async def t035_project_null_license(
    db_session: AsyncSession,
    t035_user: User,
) -> Project:
    """Project seeded with ``license_id IS NULL`` — simulates a legacy row."""
    project = Project(
        name="T035 Null License Project",
        description="API-shape regression test — null license",
        visibility=ProjectVisibility.RESTRICTED,
        license_id=None,
        owner_id=t035_user.id,
        status=ProjectStatus.ACTIVE,
        restricted_config=dict(_DEFAULT_RESTRICTED_CONFIG),
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


# ---------------------------------------------------------------------------
# Tests — Bearer surface (``/api/v1/projects``)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestProjectLicenseShapeBearer:
    """T035 — ``GET /api/v1/projects/{id}`` license field shape (Bearer)."""

    async def test_license_is_plain_string(
        self,
        client: AsyncClient,
        t035_project_with_license: Project,
        t035_api_headers: dict[str, str],
    ) -> None:
        """``GET /projects/{id}`` returns ``license`` as a plain ``str``.

        Regression guard: the hybrid property on ``Project`` must resolve
        to the License ``short_name`` string, never to the raw ORM row or an
        enum constant.
        """
        response = await client.get(
            f"{_API_PROJECTS}/{t035_project_with_license.id}",
            headers=t035_api_headers,
        )
        assert response.status_code == 200, response.text
        data = response.json()

        assert "license" in data, (
            "ProjectResponse MUST carry a 'license' key (even when null)."
        )
        assert data["license"] == "CC-BY", (
            f"Expected plain string 'CC-BY'; got {data['license']!r}"
        )
        assert isinstance(data["license"], str), (
            f"'license' MUST be a plain string, not {type(data['license'])!r}"
        )

    async def test_null_license_is_json_null(
        self,
        client: AsyncClient,
        t035_project_null_license: Project,
        t035_api_headers: dict[str, str],
    ) -> None:
        """Legacy project with ``license_id IS NULL`` → ``license: null`` in JSON.

        Guards against the ORM returning the string ``"None"`` or omitting
        the key entirely.
        """
        response = await client.get(
            f"{_API_PROJECTS}/{t035_project_null_license.id}",
            headers=t035_api_headers,
        )
        assert response.status_code == 200, response.text
        data = response.json()

        assert "license" in data, (
            "ProjectResponse MUST carry a 'license' key even for null license."
        )
        assert data["license"] is None, (
            f"Expected JSON null for null license; got {data['license']!r}"
        )


# ---------------------------------------------------------------------------
# Tests — BFF surface (``/web-api/v1/projects``)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestProjectLicenseShapeBFF:
    """T035 — ``GET /web-api/v1/projects/{id}`` license field shape (BFF)."""

    async def test_license_is_plain_string(
        self,
        client: AsyncClient,
        t035_project_with_license: Project,
        t035_bff_auth: dict[str, dict[str, str]],
    ) -> None:
        """BFF surface: ``license`` is a plain string, not an enum/object."""
        response = await client.get(
            f"{_WEB_PROJECTS}/{t035_project_with_license.id}",
            **t035_bff_auth,
        )
        assert response.status_code == 200, response.text
        data = response.json()

        assert "license" in data, (
            "ProjectResponse MUST carry a 'license' key."
        )
        assert data["license"] == "CC-BY", (
            f"Expected plain string 'CC-BY'; got {data['license']!r}"
        )
        assert isinstance(data["license"], str), (
            f"'license' MUST be a plain string, not {type(data['license'])!r}"
        )

    async def test_null_license_is_json_null(
        self,
        client: AsyncClient,
        t035_project_null_license: Project,
        t035_bff_auth: dict[str, dict[str, str]],
    ) -> None:
        """BFF surface: legacy null-license project returns ``license: null``."""
        response = await client.get(
            f"{_WEB_PROJECTS}/{t035_project_null_license.id}",
            **t035_bff_auth,
        )
        assert response.status_code == 200, response.text
        data = response.json()

        assert "license" in data, (
            "ProjectResponse MUST carry a 'license' key even for null license."
        )
        assert data["license"] is None, (
            f"Expected JSON null for null license; got {data['license']!r}"
        )
