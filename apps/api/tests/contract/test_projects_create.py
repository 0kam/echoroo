"""Contract tests for ``POST /projects`` license handling (spec/012 T015).

Covers the spec/012 Phase 3 project-creation contract:

* The API accepts ``license_id`` as the ``licenses.id`` primary key
  (e.g. ``"cc-by"``), NOT the human-facing short_name. The response field
  stays ``license`` and carries the joined ``short_name`` string
  (e.g. ``"CC-BY"``).

* Valid ``license_id`` (from the master table) → 201,
  ``response["license"]`` is the plain short_name string (not an enum or
  object). Pins research §R1 to the wire contract for the create surface.

* Unknown ``license_id`` → 422 with ``error_code == "license_not_found"``.

* Missing ``license_id`` field → 422 (Pydantic required-field enforcement).

* ``GET /projects/{id}`` for a project created with a known license returns
  ``license`` as a plain string, not an enum or nested object.

* The created project's license-history row stores the human-facing
  ``short_name`` (e.g. ``"CC-BY"``), NOT the raw ``license_id`` — this
  guards the highest-risk coupling: the request value changed meaning
  (id vs short_name) but the history/audit columns must keep the short_name.

Both the Bearer (``/api/v1/projects``) and BFF (``/web-api/v1/projects``)
surfaces are exercised so the contract is locked at both customer
touch-points.  The BFF surface (``POST /web-api/v1/projects``) is covered by
``TestProjectCreateBFF`` below, which mirrors the Bearer tests using a
session-cookie + Bearer auth pair.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.auth import issue_access_token
from echoroo.core.jwt import create_access_token
from echoroo.core.settings import get_settings
from echoroo.middleware.csrf import issue_csrf_token
from echoroo.models.user import User
from tests.conftest import seed_canonical_test_licenses

_API_PROJECTS = "/api/v1/projects"
_WEB_PROJECTS = "/web-api/v1/projects/"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def t015_user(db_session: AsyncSession) -> User:
    """Plain authenticated user — owner of the projects under test."""
    user = User(
        email="t015-owner@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T015 Owner",
        security_stamp="t015" + "o" * 60,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
def t015_api_headers(t015_user: User) -> dict[str, str]:
    return {
        "Authorization": (
            f"Bearer {create_access_token({'sub': str(t015_user.id)})}"
        )
    }


@pytest.fixture
async def t015_bff_auth(
    db_session: AsyncSession,
    t015_user: User,
) -> dict[str, dict[str, str]]:
    """Session cookie + Bearer header + CSRF token for BFF surface requests."""
    import uuid

    session_id = uuid.uuid4()
    await db_session.execute(
        sa.text(
            "INSERT INTO token_families (family_id, user_id, created_at) "
            "VALUES (:family_id, :user_id, NOW())"
        ),
        {"family_id": session_id, "user_id": t015_user.id},
    )
    await db_session.commit()

    settings = get_settings()
    access_token = issue_access_token(
        user_id=t015_user.id,
        security_stamp=t015_user.security_stamp,
    )
    csrf_token = issue_csrf_token(
        str(session_id),
        session_secret=settings.web_session_secret,
    )
    return {
        "headers": {
            "Authorization": f"Bearer {access_token}",
            "X-CSRF-Token": csrf_token,
        },
        "cookies": {settings.web_session_cookie_name: str(session_id)},
    }


# ---------------------------------------------------------------------------
# T015a — unknown license short_name returns 422 (Bearer surface)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestProjectCreateUnknownLicense:
    """T015 — unknown / missing ``license_id`` returns 422.

    Phase 3: ``license_id`` carries the ``licenses.id`` primary key. An id
    with no matching row → 422 with ``error_code == "license_not_found"``.
    A missing field is a standard Pydantic 422 (required-field).
    """

    async def test_unknown_license_returns_422_bearer(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        t015_api_headers: dict[str, str],
    ) -> None:
        """Unknown ``license_id`` → 422 with ``error_code == license_not_found``."""
        await seed_canonical_test_licenses(db_session)

        response = await client.post(
            _API_PROJECTS,
            headers=t015_api_headers,
            json={
                "name": "T015 Unknown License Project",
                "visibility": "public",
                "license_id": "cc-by-nonexistent-xyz",
            },
        )
        assert response.status_code == 422, response.text
        body = response.json()
        assert body.get("error_code") == "license_not_found", (
            f"Expected error_code 'license_not_found' for unknown id; got {body!r}"
        )

    async def test_missing_license_returns_422_bearer(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        t015_api_headers: dict[str, str],
    ) -> None:
        """Missing ``license_id`` field → 422 (FR-005 required-at-create contract)."""
        await seed_canonical_test_licenses(db_session)

        response = await client.post(
            _API_PROJECTS,
            headers=t015_api_headers,
            json={
                "name": "T015 No License Project",
                "visibility": "public",
            },
        )
        assert response.status_code == 422, response.text


# ---------------------------------------------------------------------------
# T015b — valid license short_name → 201, response.license is plain string
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestProjectCreateValidLicense:
    """T015 — valid license short_name succeeds; response carries plain string."""

    async def test_valid_license_creates_project_bearer(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        t015_api_headers: dict[str, str],
    ) -> None:
        """``license_id: "cc-by"`` → 201; ``response["license"]`` is ``"CC-BY"``."""
        await seed_canonical_test_licenses(db_session)

        response = await client.post(
            _API_PROJECTS,
            headers=t015_api_headers,
            json={
                "name": "T015 Valid License Project",
                "visibility": "public",
                "license_id": "cc-by",
            },
        )
        assert response.status_code == 201, response.text
        data = response.json()
        assert data["license"] == "CC-BY", (
            f"Expected plain string 'CC-BY'; got {data['license']!r}"
        )
        assert isinstance(data["license"], str), (
            f"license MUST be a plain string, not {type(data['license'])!r}"
        )

    async def test_license_history_stores_short_name_not_id_bearer(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        t015_api_headers: dict[str, str],
    ) -> None:
        """Coupling guard: creating via id ``cc-by`` stores short_name ``CC-BY``.

        The request value changed meaning (id vs short_name) but the
        ``project_license_history`` table must keep storing the human-facing
        short_name. Feeding the raw id into the history row would silently
        corrupt the audit trail — this assertion pins the resolution.
        """
        await seed_canonical_test_licenses(db_session)

        response = await client.post(
            _API_PROJECTS,
            headers=t015_api_headers,
            json={
                "name": "T015 History Short Name Project",
                "visibility": "public",
                "license_id": "cc-by",
            },
        )
        assert response.status_code == 201, response.text
        project_id = response.json()["id"]

        row = (
            await db_session.execute(
                sa.text(
                    "SELECT old_license, new_license FROM project_license_history "
                    "WHERE project_id = :pid"
                ),
                {"pid": project_id},
            )
        ).mappings().one()
        assert row["old_license"] is None, (
            f"Initial history row must have old_license=None; got {row['old_license']!r}"
        )
        assert row["new_license"] == "CC-BY", (
            "History row MUST store the short_name 'CC-BY', not the id 'cc-by'; "
            f"got {row['new_license']!r}"
        )

    async def test_get_project_after_create_returns_license_string_bearer(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        t015_api_headers: dict[str, str],
    ) -> None:
        """``GET /projects/{id}`` returns ``license`` as plain string (not enum/object).

        Pins research §R1: the wire contract for ``ProjectResponse.license``
        is ``string | null``.
        """
        await seed_canonical_test_licenses(db_session)

        create_resp = await client.post(
            _API_PROJECTS,
            headers=t015_api_headers,
            json={
                "name": "T015 GET License Shape Project",
                "visibility": "public",
                "license_id": "cc0",
            },
        )
        assert create_resp.status_code == 201, create_resp.text
        project_id = create_resp.json()["id"]

        get_resp = await client.get(
            f"{_API_PROJECTS}/{project_id}",
            headers=t015_api_headers,
        )
        assert get_resp.status_code == 200, get_resp.text
        data = get_resp.json()
        assert "license" in data, "ProjectResponse MUST carry a 'license' field"
        assert data["license"] == "CC0", (
            f"Expected plain string 'CC0'; got {data['license']!r}"
        )
        assert isinstance(data["license"], str), (
            f"license MUST be a plain string, not {type(data['license'])!r}"
        )


# ---------------------------------------------------------------------------
# T015c — BFF surface (``POST /web-api/v1/projects``)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestProjectCreateBFF:
    """T015 — BFF surface mirrors Bearer contract for project-create license handling.

    Exercises ``POST /web-api/v1/projects`` with a session-cookie + Bearer
    auth pair to ensure the cookie-authenticated surface enforces the same
    license contract as the programmatic Bearer surface.
    """

    async def test_valid_license_creates_project_bff(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        t015_bff_auth: dict[str, dict[str, str]],
    ) -> None:
        """``license_id: "cc-by"`` via BFF → 201; ``response["license"]`` is ``"CC-BY"``."""
        await seed_canonical_test_licenses(db_session)

        response = await client.post(
            _WEB_PROJECTS,
            **t015_bff_auth,
            json={
                "name": "T015 BFF Valid License Project",
                "visibility": "public",
                "license_id": "cc-by",
            },
        )
        assert response.status_code == 201, response.text
        data = response.json()
        assert data["license"] == "CC-BY", (
            f"BFF: expected plain string 'CC-BY'; got {data['license']!r}"
        )
        assert isinstance(data["license"], str), (
            f"BFF: license MUST be a plain string, not {type(data['license'])!r}"
        )

    async def test_license_history_stores_short_name_not_id_bff(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        t015_bff_auth: dict[str, dict[str, str]],
    ) -> None:
        """BFF coupling guard: create via id ``cc-by`` stores short_name ``CC-BY``."""
        await seed_canonical_test_licenses(db_session)

        response = await client.post(
            _WEB_PROJECTS,
            **t015_bff_auth,
            json={
                "name": "T015 BFF History Short Name Project",
                "visibility": "public",
                "license_id": "cc-by",
            },
        )
        assert response.status_code == 201, response.text
        project_id = response.json()["id"]

        row = (
            await db_session.execute(
                sa.text(
                    "SELECT new_license FROM project_license_history "
                    "WHERE project_id = :pid"
                ),
                {"pid": project_id},
            )
        ).mappings().one()
        assert row["new_license"] == "CC-BY", (
            "BFF: history row MUST store short_name 'CC-BY', not id 'cc-by'; "
            f"got {row['new_license']!r}"
        )

    async def test_unknown_license_returns_422_bff(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        t015_bff_auth: dict[str, dict[str, str]],
    ) -> None:
        """Unknown ``license_id`` via BFF → 422 with ``error_code license_not_found``."""
        await seed_canonical_test_licenses(db_session)

        response = await client.post(
            _WEB_PROJECTS,
            **t015_bff_auth,
            json={
                "name": "T015 BFF Unknown License Project",
                "visibility": "public",
                "license_id": "cc-by-nonexistent-xyz",
            },
        )
        assert response.status_code == 422, response.text
        body = response.json()
        assert body.get("error_code") == "license_not_found", (
            f"BFF: expected error_code 'license_not_found' for unknown id; got {body!r}"
        )

    async def test_missing_license_returns_422_bff(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        t015_bff_auth: dict[str, dict[str, str]],
    ) -> None:
        """Missing ``license_id`` field via BFF → 422 (required-at-create contract)."""
        await seed_canonical_test_licenses(db_session)

        response = await client.post(
            _WEB_PROJECTS,
            **t015_bff_auth,
            json={
                "name": "T015 BFF No License Project",
                "visibility": "public",
            },
        )
        assert response.status_code == 422, response.text
