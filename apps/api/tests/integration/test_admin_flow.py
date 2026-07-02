"""Integration tests for admin flows.

Note (Phase 16 Batch 6b R2): split-skip rewrite.

The historical ``test_full_admin_flow`` mixed user management (Phase 4
stub returning 501) with system-settings (live JSONB-backed endpoint) in
a single linear scenario. We split the two halves so settings flow
coverage stays active while user-management remains skipped pending the
admin-API rewrite.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.superuser import Superuser
from echoroo.models.user import User
from tests.integration.conftest import bff_session_headers

# ---------------------------------------------------------------------------
# Shared fixtures (Phase 13 schema — Superuser SOT in dedicated table)
# ---------------------------------------------------------------------------


@pytest.fixture
async def superuser(db_session: AsyncSession) -> User:
    """Create a test superuser using the Phase 13 split schema."""
    user = User(
        email="superuser@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="Superuser",
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
    client: AsyncClient, db_session: AsyncSession, superuser: User
) -> dict[str, str]:
    """CSRF-capable ``/web-api/v1`` session headers for the superuser.

    W2-3 PR-11 unmounted the legacy ``/api/v1/admin/*`` Bearer routes; the
    settings flow now rides the cookie + CSRF ``/web-api/v1/admin/settings``
    BFF, so a real session (issued via ``POST /web-api/v1/auth/refresh``) is
    required — a plain ``create_access_token`` Bearer is treated as anonymous.
    """
    return await bff_session_headers(client, db_session, superuser)


# ---------------------------------------------------------------------------
# /web-api/v1/admin/settings — live endpoint, integration flow active.
# ---------------------------------------------------------------------------


async def test_full_admin_settings_flow(
    client: AsyncClient,
    superuser_headers: dict[str, str],
) -> None:
    """End-to-end flow for system settings: read → update → re-read.

    Mirrors the settings half of the legacy ``test_full_admin_flow`` and
    relies on the JSONB-backed ``system_settings`` endpoints implemented
    in :mod:`echoroo.services.admin` (now served by the
    ``/web-api/v1/admin/settings`` BFF). The ``updated_by_id`` FK is
    stamped automatically by the auth dependency
    (:func:`echoroo.middleware.auth._stamp_superuser_status`).
    """

    # 1. Initial read — empty until a write lands; the contract just
    #    requires a 200 with a JSON object body.
    response = await client.get(
        "/web-api/v1/admin/settings", headers=superuser_headers
    )
    assert response.status_code == 200
    initial = response.json()
    assert isinstance(initial, dict)

    # 2. Update three settings in a single PATCH.
    response = await client.patch(
        "/web-api/v1/admin/settings",
        headers=superuser_headers,
        json={
            "registration_mode": "invitation",
            "allow_registration": False,
            "session_timeout_minutes": 90,
        },
    )
    assert response.status_code == 200
    assert "message" in response.json()

    # 3. Re-read and confirm the JSONB values round-trip as native
    #    Python types (string / boolean / int).
    response = await client.get(
        "/web-api/v1/admin/settings", headers=superuser_headers
    )
    assert response.status_code == 200
    settings = response.json()
    assert settings["registration_mode"]["value"] == "invitation"
    assert settings["allow_registration"]["value"] is False
    assert settings["session_timeout_minutes"]["value"] == 90

    # 4. Partial update — only one field — must still 200 and persist.
    response = await client.patch(
        "/web-api/v1/admin/settings",
        headers=superuser_headers,
        json={"session_timeout_minutes": 45},
    )
    assert response.status_code == 200

    response = await client.get(
        "/web-api/v1/admin/settings", headers=superuser_headers
    )
    assert response.status_code == 200
    settings = response.json()
    assert settings["session_timeout_minutes"]["value"] == 45
    # Untouched keys retain the prior values.
    assert settings["registration_mode"]["value"] == "invitation"
    assert settings["allow_registration"]["value"] is False


# ---------------------------------------------------------------------------
# /web-api/v1/admin/users — skipped: activate/deactivate scenario no longer
# maps to the spec/006 schema. The paths are pre-pointed at the BFF surface
# (W2-3 PR-11) for when the scenario is rebuilt.
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason=(
        "Admin users integration flow — the underlying "
        "/web-api/v1/admin/users endpoint is live (spec/011 follow-up "
        "un-stub) but this scenario asserts an activate/deactivate "
        "round-trip that no longer maps to the spec/006 schema (no "
        "persisted ``is_active`` column). The smoke coverage in "
        "``tests/contract/test_admin.py`` TestListUsers + TestUpdateUser is "
        "the new authoritative surface."
    )
)
async def test_full_admin_user_management_flow(
    client: AsyncClient,
    superuser_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Full admin user-management flow.

    This test covers:
    1. Listing all users
    2. Finding the user through search
    3. Deactivating the user
    4. Verifying the user is inactive in the list
    5. Reactivating the user
    6. Promoting user to superuser
    """
    # 1. List all users initially
    response = await client.get("/web-api/v1/admin/users", headers=superuser_headers)
    assert response.status_code == 200
    initial_data = response.json()
    initial_count = initial_data["total"]

    # 2. Create a new user manually for testing
    new_user = User(
        email="newuser@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="New User",
        security_stamp="0" * 64,
    )
    db_session.add(new_user)
    await db_session.commit()
    await db_session.refresh(new_user)

    # 3. Find the new user through search
    response = await client.get(
        "/web-api/v1/admin/users",
        headers=superuser_headers,
        params={"search": "newuser"},
    )
    assert response.status_code == 200
    search_data = response.json()
    assert search_data["total"] >= 1
    found_user = next(u for u in search_data["items"] if u["email"] == "newuser@example.com")
    user_id = found_user["id"]

    # 4. Deactivate the user
    response = await client.patch(
        f"/web-api/v1/admin/users/{user_id}",
        headers=superuser_headers,
        json={"is_active": False},
    )
    assert response.status_code == 200

    # 5. Verify final user count
    response = await client.get("/web-api/v1/admin/users", headers=superuser_headers)
    assert response.status_code == 200
    final_data = response.json()
    assert final_data["total"] == initial_count + 1
