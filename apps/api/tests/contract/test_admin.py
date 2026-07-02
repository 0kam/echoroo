"""Contract tests for admin endpoints (``/web-api/v1/admin/*`` BFF).

Note (Phase 16 Batch 6b R2): split-skip rewrite.

W2-3 PR-11: the legacy ``/api/v1/admin/*`` routes were unmounted; their
behaviour now lives on the cookie + CSRF ``/web-api/v1/admin/*`` BFF
(``echoroo.api.web_v1._admin_users`` / ``_admin_settings``). Every
authenticated request therefore rides a real session issued via
``POST /web-api/v1/auth/refresh`` (a plain Bearer is treated as anonymous
on the BFF surface, and a non-member session without CSRF masks the
permission check). Superuser sessions reach the 2xx path; regular-user
sessions reach the 403 permission gate; no-auth requests stay at 401.

The ``/admin/users`` surface is reinstated against the spec/006
``superusers`` SOT (list + update, no ``is_active`` / ``is_verified`` /
``is_superuser`` columns on User). The ``/admin/settings`` surface is
fully implemented in :mod:`echoroo.services.admin` and persists rows to
the JSONB-backed ``system_settings`` table whose ``updated_by_id`` FK
points at ``superusers.id``.

``TestAdminAuthRequirements`` checks that *unauthenticated* callers hit
401 on the admin paths — independent of the backing service shape.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.superuser import Superuser
from echoroo.models.system import SystemSetting
from echoroo.models.user import User
from tests.contract.conftest import bff_session_headers

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def admin_superuser(db_session: AsyncSession) -> User:
    """Create a test superuser using the Phase 13 split schema.

    A ``users`` row is created without the dropped ``is_*`` flags, then a
    matching ``superusers`` row is inserted so the auth dependency
    (:func:`echoroo.middleware.auth._stamp_superuser_status`) resolves the
    user to an active superuser.
    """
    user = User(
        email="superuser@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="Superuser",
        security_stamp="0" * 64,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    # Promote via the dedicated entitlement table (FR-111 SOT).
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
    """Create a regular test user (non-superuser).

    Args:
        db_session: Database session

    Returns:
        Regular user instance
    """
    user = User(
        email="regular@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="Regular User",
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
    """CSRF-capable ``/web-api/v1`` session headers for the regular user.

    The regular user has a real session (so CSRF passes) but no superuser
    entitlement, so the request reaches the platform permission gate and
    is denied with 403 (rather than masked by a CSRF/auth 401/403).
    """
    return await bff_session_headers(client, db_session, regular_user)


@pytest.fixture
async def system_settings(
    db_session: AsyncSession,
    admin_superuser: User,  # noqa: ARG001 — fixture creates superuser dependency
) -> None:
    """Seed the three settings exercised by ``TestSystemSettings``.

    Phase 13 conftest no longer auto-seeds ``system_settings`` because the
    ``updated_by_id`` FK changed to NOT NULL → ``superusers.id``. We seed
    here against the live superuser fixture so the GET / PATCH tests have
    rows to read and update.
    """
    # Resolve the superuser id (FK target). A fresh ``superusers`` row was
    # just inserted by the ``superuser`` fixture; we re-fetch by user_id to
    # keep this seeding independent of in-memory ORM state.
    from sqlalchemy import select

    su_id = (
        await db_session.execute(
            select(Superuser.id).where(Superuser.revoked_at.is_(None))
        )
    ).scalar_one()

    db_session.add_all(
        [
            SystemSetting(
                key="registration_mode",
                value="open",
                updated_by_id=su_id,
            ),
            SystemSetting(
                key="allow_registration",
                value=True,
                updated_by_id=su_id,
            ),
            SystemSetting(
                key="session_timeout_minutes",
                value=60,
                updated_by_id=su_id,
            ),
        ]
    )
    await db_session.commit()


# ---------------------------------------------------------------------------
# /api/v1/admin/users — spec/011 follow-up un-stub.
#
# The legacy ``/api/v1/admin/users`` surface previously returned 501 (Phase
# 4 ``_raise_phase4_stub``). spec/011 follow-up reinstates the endpoints
# against the spec/006 superusers SOT: list + update with the new
# (no ``is_active`` / ``is_verified`` columns) shape. The promotion /
# demotion flow lives on ``POST /admin/superusers`` (M-of-N) — toggling
# ``is_superuser`` here is a deprecated no-op on the request body.
# ---------------------------------------------------------------------------


class TestListUsers:
    """Tests for GET /admin/users endpoint (spec/011 follow-up)."""

    async def test_list_users_as_superuser(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
        admin_superuser: User,  # noqa: ARG002 - needed to create user
        regular_user: User,  # noqa: ARG002 - needed to create user
    ) -> None:
        """Test listing users as superuser surfaces both seeded rows."""
        response = await client.get(
            "/web-api/v1/admin/users", headers=superuser_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "limit" in data
        assert data["total"] >= 2

    async def test_list_users_as_non_superuser_forbidden(
        self,
        client: AsyncClient,
        regular_user_headers: dict[str, str],
    ) -> None:
        """Test listing users as non-superuser returns 403."""
        response = await client.get(
            "/web-api/v1/admin/users", headers=regular_user_headers
        )

        assert response.status_code == 403
        data = response.json()
        assert "detail" in data

    async def test_list_users_with_search(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
        regular_user: User,  # noqa: ARG002 - needed to create user
    ) -> None:
        """Test listing users with the search parameter (display_name ILIKE)."""
        response = await client.get(
            "/web-api/v1/admin/users",
            headers=superuser_headers,
            params={"search": "Regular"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1

    async def test_list_users_pagination(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
        admin_superuser: User,  # noqa: ARG002 - needed to create user
        regular_user: User,  # noqa: ARG002 - needed to create user
    ) -> None:
        """Test user list pagination clamps to the requested limit."""
        response = await client.get(
            "/web-api/v1/admin/users",
            headers=superuser_headers,
            params={"page": 1, "limit": 1},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 1
        assert data["limit"] == 1
        assert len(data["items"]) == 1

    async def test_list_users_includes_is_superuser(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
        admin_superuser: User,
        regular_user: User,
    ) -> None:
        """``is_superuser`` reflects the ``superusers`` entitlement row.

        spec/009 follow-up: the admin user list previously returned
        :class:`~echoroo.schemas.auth.UserResponse` rows, which dropped
        the ``is_superuser`` field after spec/006 moved the flag into
        the ``superusers`` table. The admin UI showed every account as
        "Role: User" as a result. The list now uses
        :class:`AdminUserListItem`, which carries the JOIN-derived flag
        per row.
        """
        response = await client.get(
            "/web-api/v1/admin/users",
            headers=superuser_headers,
            params={"limit": 100},
        )

        assert response.status_code == 200
        data = response.json()
        items_by_id = {item["id"]: item for item in data["items"]}

        assert str(admin_superuser.id) in items_by_id, (
            "superuser fixture missing from admin list response"
        )
        assert str(regular_user.id) in items_by_id, (
            "regular_user fixture missing from admin list response"
        )

        su_item = items_by_id[str(admin_superuser.id)]
        regular_item = items_by_id[str(regular_user.id)]

        assert "is_superuser" in su_item, (
            "AdminUserListItem schema must surface is_superuser per row"
        )
        assert su_item["is_superuser"] is True
        assert regular_item["is_superuser"] is False


class TestUpdateUser:
    """Tests for PATCH /admin/users/{userId} endpoint (spec/011 follow-up)."""

    async def test_update_user_display_name(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
        regular_user: User,
    ) -> None:
        """display_name updates are persisted and reflected in the response."""
        response = await client.patch(
            f"/web-api/v1/admin/users/{regular_user.id}",
            headers=superuser_headers,
            json={"display_name": "Renamed"},
        )

        assert response.status_code == 200
        assert response.json()["display_name"] == "Renamed"

    async def test_update_user_ignores_deprecated_flags(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
        regular_user: User,
    ) -> None:
        """is_active / is_superuser / is_verified are accepted but ignored.

        spec/006 dropped the persisted ``users.is_active`` and
        ``users.is_superuser`` columns; spec/011 removed email
        verification. The fields stay on the request schema for SPA
        compatibility but the service silently drops them — sending them
        MUST NOT yield a 4xx (the SPA still ships pre-spec/006 payloads).
        """
        response = await client.patch(
            f"/web-api/v1/admin/users/{regular_user.id}",
            headers=superuser_headers,
            json={"is_active": False, "is_superuser": True, "is_verified": False},
        )

        assert response.status_code == 200

    async def test_update_user_as_non_superuser_forbidden(
        self,
        client: AsyncClient,
        regular_user_headers: dict[str, str],
        regular_user: User,
    ) -> None:
        """Test updating user as non-superuser returns 403."""
        response = await client.patch(
            f"/web-api/v1/admin/users/{regular_user.id}",
            headers=regular_user_headers,
            json={"display_name": "Hacked"},
        )

        assert response.status_code == 403

    async def test_update_nonexistent_user(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
    ) -> None:
        """Test updating a nonexistent user returns 404."""
        fake_uuid = "00000000-0000-0000-0000-000000000000"
        response = await client.patch(
            f"/web-api/v1/admin/users/{fake_uuid}",
            headers=superuser_headers,
            json={"display_name": "Ghost"},
        )

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# /api/v1/admin/settings — implemented endpoint, full HTTP coverage active.
# ---------------------------------------------------------------------------


class TestSystemSettings:
    """Tests for system settings endpoints (Phase 13 JSONB schema)."""

    async def test_get_system_settings(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
        system_settings: None,  # noqa: ARG002 - needed to create settings
    ) -> None:
        """Test getting all system settings."""
        response = await client.get("/web-api/v1/admin/settings", headers=superuser_headers)

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert "registration_mode" in data
        assert "allow_registration" in data
        assert "session_timeout_minutes" in data

        # Each setting carries a uniform shape derived from the JSONB value.
        setting = data["registration_mode"]
        assert "key" in setting
        assert "value" in setting
        assert "value_type" in setting
        assert "updated_at" in setting

    async def test_get_system_settings_as_non_superuser_forbidden(
        self,
        client: AsyncClient,
        regular_user_headers: dict[str, str],
    ) -> None:
        """Test getting system settings as non-superuser returns 403."""
        response = await client.get("/web-api/v1/admin/settings", headers=regular_user_headers)

        assert response.status_code == 403

    async def test_update_system_settings(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
        system_settings: None,  # noqa: ARG002 - needed to create settings
    ) -> None:
        """Test updating system settings."""
        response = await client.patch(
            "/web-api/v1/admin/settings",
            headers=superuser_headers,
            json={
                "registration_mode": "invitation",
                "allow_registration": False,
                "session_timeout_minutes": 120,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "message" in data

        # Verify settings were updated
        get_response = await client.get(
            "/web-api/v1/admin/settings", headers=superuser_headers
        )
        settings_data = get_response.json()
        assert settings_data["registration_mode"]["value"] == "invitation"
        assert settings_data["allow_registration"]["value"] is False
        assert settings_data["session_timeout_minutes"]["value"] == 120

    async def test_update_system_settings_partial(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
        system_settings: None,  # noqa: ARG002 - needed to create settings
    ) -> None:
        """Test updating only some system settings."""
        response = await client.patch(
            "/web-api/v1/admin/settings",
            headers=superuser_headers,
            json={"session_timeout_minutes": 30},
        )

        assert response.status_code == 200

    async def test_update_system_settings_validation(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
    ) -> None:
        """Test validation of system settings values."""
        # Invalid session_timeout_minutes (too low)
        response = await client.patch(
            "/web-api/v1/admin/settings",
            headers=superuser_headers,
            json={"session_timeout_minutes": 2},
        )
        assert response.status_code == 422

        # Invalid session_timeout_minutes (too high)
        response = await client.patch(
            "/web-api/v1/admin/settings",
            headers=superuser_headers,
            json={"session_timeout_minutes": 2000},
        )
        assert response.status_code == 422

        # Invalid registration_mode
        response = await client.patch(
            "/web-api/v1/admin/settings",
            headers=superuser_headers,
            json={"registration_mode": "invalid"},
        )
        assert response.status_code == 422

    async def test_update_system_settings_as_non_superuser_forbidden(
        self,
        client: AsyncClient,
        regular_user_headers: dict[str, str],
    ) -> None:
        """Test updating system settings as non-superuser returns 403."""
        response = await client.patch(
            "/web-api/v1/admin/settings",
            headers=regular_user_headers,
            json={"allow_registration": False},
        )

        assert response.status_code == 403


# ---------------------------------------------------------------------------
# Auth-required gate — independent of backing service shape, kept active.
# ---------------------------------------------------------------------------


class TestAdminAuthRequirements:
    """Tests for admin endpoint authentication requirements."""

    async def test_admin_endpoints_require_authentication(
        self,
        client: AsyncClient,
    ) -> None:
        """Test that admin endpoints require authentication."""
        # List users
        response = await client.get("/web-api/v1/admin/users")
        assert response.status_code == 401

        # Update user
        response = await client.patch(
            "/web-api/v1/admin/users/00000000-0000-0000-0000-000000000000",
            json={"is_active": False},
        )
        assert response.status_code == 401

        # Get settings
        response = await client.get("/web-api/v1/admin/settings")
        assert response.status_code == 401

        # Update settings
        response = await client.patch(
            "/web-api/v1/admin/settings",
            json={"allow_registration": False},
        )
        assert response.status_code == 401
