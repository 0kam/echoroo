"""Contract tests for license admin endpoints (``/web-api/v1/admin/licenses``).

W2-3 PR-11: the legacy ``/api/v1/admin/licenses`` routes were unmounted;
their behaviour now lives on the cookie + CSRF ``/web-api/v1/admin/licenses``
BFF (``echoroo.api.web_v1._admin_licenses``). Every authenticated request
rides a real session issued via ``POST /web-api/v1/auth/refresh`` (a plain
Bearer is treated as anonymous on the BFF surface, and a non-member session
without CSRF masks the permission check). The superuser is now promoted via
the spec/006 ``superusers`` allow-list table (not the dropped
``users.is_superuser`` column), so the suite runs unskipped against the new
SOT: superuser session → 2xx, regular-user session → 403, no-auth → 401.
"""

from uuid import uuid4

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.license import License
from echoroo.models.user import User
from tests.contract.conftest import bff_session_headers


@pytest.fixture
async def superuser(db_session: AsyncSession) -> User:
    """Create a platform superuser (User row + active ``superusers`` entry).

    spec/006 moved the superuser flag out of ``users.is_superuser`` and into
    the ``superusers`` allow-list table; the auth middleware stamps
    ``is_superuser`` when an active row is found. Seed both so the BFF admin
    gate resolves the caller as a superuser.
    """
    user = User(
        email="superuser@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="Superuser",
        security_stamp="licenses-stamp-superuser",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    await db_session.execute(
        sa.text(
            """
            INSERT INTO superusers (id, user_id, added_by_id, added_at)
            VALUES (:id, :uid, :uid, NOW())
            """
        ),
        {"id": uuid4(), "uid": user.id},
    )
    await db_session.commit()
    return user


@pytest.fixture
async def superuser_headers(
    client: AsyncClient, db_session: AsyncSession, superuser: User
) -> dict[str, str]:
    """CSRF-capable ``/web-api/v1`` session headers for the superuser."""
    return await bff_session_headers(client, db_session, superuser)


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
        security_stamp="licenses-stamp-regular",
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
    entitlement, so the request reaches the platform permission gate and is
    denied with 403 (rather than masked by a CSRF/auth 401/403).
    """
    return await bff_session_headers(client, db_session, regular_user)


@pytest.fixture
async def test_license(db_session: AsyncSession) -> License:
    """Create a test license.

    Args:
        db_session: Database session

    Returns:
        License instance
    """
    license = License(
        id="BY-NC-SA",
        name="Creative Commons Attribution Non-Commercial Share Alike 4.0",
        short_name="CC BY-NC-SA 4.0",
        url="https://creativecommons.org/licenses/by-nc-sa/4.0/",
        description="This license allows others to remix, tweak, and build upon your work non-commercially, as long as they credit you and license their new creations under identical terms.",
    )
    db_session.add(license)
    await db_session.commit()
    await db_session.refresh(license)
    return license


class TestListLicenses:
    """Tests for listing licenses."""

    async def test_list_licenses_returns_seeded_master(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
    ) -> None:
        """The spec/012 license master is seeded by migration; every item
        exposes the full response shape."""
        response = await client.get("/web-api/v1/admin/licenses", headers=superuser_headers)

        assert response.status_code == 200
        data = response.json()
        listed_ids = {item["id"] for item in data["items"]}
        assert {"cc0", "cc-by", "cc-by-nc", "cc-by-sa"} <= listed_ids
        for item in data["items"]:
            assert {"id", "name", "short_name", "url", "description"} <= set(item.keys())

    async def test_list_licenses_with_data(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
        test_license: License,
    ) -> None:
        """A newly created license appears in the list alongside the seeded master."""
        response = await client.get("/web-api/v1/admin/licenses", headers=superuser_headers)

        assert response.status_code == 200
        data = response.json()
        matches = [item for item in data["items"] if item["id"] == test_license.id]
        assert len(matches) == 1
        assert matches[0]["name"] == test_license.name
        assert matches[0]["short_name"] == test_license.short_name
        assert matches[0]["url"] == test_license.url
        assert matches[0]["description"] == test_license.description

    async def test_list_licenses_multiple(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
        db_session: AsyncSession,
    ) -> None:
        """Test that multiple newly created licenses all appear in the list."""
        # Use ids outside the seeded spec/012 master to avoid PK collisions.
        licenses_data = [
            {
                "id": "test-multi-a",
                "name": "Test Multi License A",
                "short_name": "TEST-MULTI-A",
                "url": "https://example.com/licenses/test-multi-a/",
                "description": "First of two licenses created by the multiple-list contract test.",
            },
            {
                "id": "test-multi-b",
                "name": "Test Multi License B",
                "short_name": "TEST-MULTI-B",
                "url": "https://example.com/licenses/test-multi-b/",
                "description": "Second of two licenses created by the multiple-list contract test.",
            },
        ]

        for lic_data in licenses_data:
            license = License(**lic_data)
            db_session.add(license)
        await db_session.commit()

        response = await client.get("/web-api/v1/admin/licenses", headers=superuser_headers)
        assert response.status_code == 200
        data = response.json()
        listed_ids = {item["id"] for item in data["items"]}
        assert {"test-multi-a", "test-multi-b"} <= listed_ids

    async def test_list_licenses_as_non_superuser_forbidden(
        self,
        client: AsyncClient,
        regular_user_headers: dict[str, str],
    ) -> None:
        """Test listing licenses as non-superuser returns 403."""
        response = await client.get("/web-api/v1/admin/licenses", headers=regular_user_headers)

        assert response.status_code == 403

    async def test_list_licenses_unauthorized(
        self,
        client: AsyncClient,
    ) -> None:
        """Test listing licenses without authentication returns 401."""
        response = await client.get("/web-api/v1/admin/licenses")

        assert response.status_code == 401


class TestCreateLicense:
    """Tests for creating licenses."""

    async def test_create_license_success(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
    ) -> None:
        """Test successful license creation."""
        response = await client.post(
            "/web-api/v1/admin/licenses",
            headers=superuser_headers,
            json={
                "id": "BY-NC",
                "name": "Creative Commons Attribution Non-Commercial 4.0",
                "short_name": "CC BY-NC 4.0",
                "url": "https://creativecommons.org/licenses/by-nc/4.0/",
                "description": "This license allows others to remix, tweak, and build upon this work non-commercially, and although their new works must also acknowledge you and be non-commercial, they don't have to license their derivative works on the same terms.",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["id"] == "BY-NC"
        assert data["name"] == "Creative Commons Attribution Non-Commercial 4.0"
        assert data["short_name"] == "CC BY-NC 4.0"
        assert data["url"] == "https://creativecommons.org/licenses/by-nc/4.0/"
        assert data["description"] is not None
        assert "created_at" in data
        assert "updated_at" in data

    async def test_create_license_minimal_fields(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
    ) -> None:
        """Test creating license with only required fields."""
        response = await client.post(
            "/web-api/v1/admin/licenses",
            headers=superuser_headers,
            json={
                "id": "CC0",
                "name": "Creative Commons Zero 1.0",
                "short_name": "CC0 1.0",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["id"] == "CC0"
        assert data["name"] == "Creative Commons Zero 1.0"
        assert data["short_name"] == "CC0 1.0"
        assert data["url"] is None
        assert data["description"] is None

    async def test_create_license_duplicate_id(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
        test_license: License,
    ) -> None:
        """Test creating license with duplicate ID returns 409."""
        response = await client.post(
            "/web-api/v1/admin/licenses",
            headers=superuser_headers,
            json={
                "id": test_license.id,
                "name": "Another License",
                "short_name": "AL",
            },
        )

        assert response.status_code == 409
        data = response.json()
        assert "already exists" in data["detail"].lower()

    async def test_create_license_missing_required_fields(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
    ) -> None:
        """Test creating license without required fields returns 422."""
        response = await client.post(
            "/web-api/v1/admin/licenses",
            headers=superuser_headers,
            json={"id": "incomplete"},
        )

        assert response.status_code == 422

    async def test_create_license_as_non_superuser_forbidden(
        self,
        client: AsyncClient,
        regular_user_headers: dict[str, str],
    ) -> None:
        """Test creating license as non-superuser returns 403."""
        response = await client.post(
            "/web-api/v1/admin/licenses",
            headers=regular_user_headers,
            json={
                "id": "test",
                "name": "Test License",
                "short_name": "TL",
            },
        )

        assert response.status_code == 403

    async def test_create_license_without_auth_unauthorized(
        self,
        client: AsyncClient,
    ) -> None:
        """Test creating license without authentication returns 401."""
        response = await client.post(
            "/web-api/v1/admin/licenses",
            json={
                "id": "test",
                "name": "Test License",
                "short_name": "TL",
            },
        )

        assert response.status_code == 401


class TestGetLicense:
    """Tests for getting a specific license."""

    async def test_get_license_success(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
        test_license: License,
    ) -> None:
        """Test getting a license by ID."""
        response = await client.get(
            f"/web-api/v1/admin/licenses/{test_license.id}",
            headers=superuser_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == test_license.id
        assert data["name"] == test_license.name
        assert data["short_name"] == test_license.short_name
        assert data["url"] == test_license.url
        assert data["description"] == test_license.description

    async def test_get_license_not_found(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
    ) -> None:
        """Test getting non-existent license returns 404."""
        response = await client.get(
            "/web-api/v1/admin/licenses/NONEXISTENT",
            headers=superuser_headers,
        )

        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"].lower()

    async def test_get_license_as_non_superuser_forbidden(
        self,
        client: AsyncClient,
        regular_user_headers: dict[str, str],
        test_license: License,
    ) -> None:
        """Test getting license as non-superuser returns 403."""
        response = await client.get(
            f"/web-api/v1/admin/licenses/{test_license.id}",
            headers=regular_user_headers,
        )

        assert response.status_code == 403

    async def test_get_license_without_auth_unauthorized(
        self,
        client: AsyncClient,
        test_license: License,
    ) -> None:
        """Test getting license without authentication returns 401."""
        response = await client.get(
            f"/web-api/v1/admin/licenses/{test_license.id}",
        )

        assert response.status_code == 401


class TestUpdateLicense:
    """Tests for updating licenses."""

    async def test_update_license_success(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
        test_license: License,
    ) -> None:
        """Test successful license update."""
        response = await client.patch(
            f"/web-api/v1/admin/licenses/{test_license.id}",
            headers=superuser_headers,
            json={
                "name": "Updated License Name",
                "short_name": "Updated Short",
                "url": "https://example.com/updated",
                "description": "Updated description",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == test_license.id
        assert data["name"] == "Updated License Name"
        assert data["short_name"] == "Updated Short"
        assert data["url"] == "https://example.com/updated"
        assert data["description"] == "Updated description"

    async def test_update_license_partial(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
        test_license: License,
    ) -> None:
        """Test partial update of license."""
        response = await client.patch(
            f"/web-api/v1/admin/licenses/{test_license.id}",
            headers=superuser_headers,
            json={"short_name": "Updated Short"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == test_license.id
        assert data["name"] == test_license.name  # Unchanged
        assert data["short_name"] == "Updated Short"  # Updated
        assert data["url"] == test_license.url  # Unchanged

    async def test_update_license_partial_name_only(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
        test_license: License,
    ) -> None:
        """Test updating only license name."""
        response = await client.patch(
            f"/web-api/v1/admin/licenses/{test_license.id}",
            headers=superuser_headers,
            json={"name": "New Name"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "New Name"
        assert data["short_name"] == test_license.short_name

    async def test_update_license_partial_description_only(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
        test_license: License,
    ) -> None:
        """Test updating only license description."""
        new_desc = "New description for the license"
        response = await client.patch(
            f"/web-api/v1/admin/licenses/{test_license.id}",
            headers=superuser_headers,
            json={"description": new_desc},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["description"] == new_desc
        assert data["name"] == test_license.name

    async def test_update_license_not_found(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
    ) -> None:
        """Test updating non-existent license returns 404."""
        response = await client.patch(
            "/web-api/v1/admin/licenses/NONEXISTENT",
            headers=superuser_headers,
            json={"name": "Test"},
        )

        assert response.status_code == 404

    async def test_update_license_as_non_superuser_forbidden(
        self,
        client: AsyncClient,
        regular_user_headers: dict[str, str],
        test_license: License,
    ) -> None:
        """Test updating license as non-superuser returns 403."""
        response = await client.patch(
            f"/web-api/v1/admin/licenses/{test_license.id}",
            headers=regular_user_headers,
            json={"name": "Test"},
        )

        assert response.status_code == 403

    async def test_update_license_without_auth_unauthorized(
        self,
        client: AsyncClient,
        test_license: License,
    ) -> None:
        """Test updating license without authentication returns 401."""
        response = await client.patch(
            f"/web-api/v1/admin/licenses/{test_license.id}",
            json={"name": "Test"},
        )

        assert response.status_code == 401


class TestDeleteLicense:
    """Tests for deleting licenses."""

    async def test_delete_license_success(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
        test_license: License,
    ) -> None:
        """Test successful license deletion."""
        response = await client.delete(
            f"/web-api/v1/admin/licenses/{test_license.id}",
            headers=superuser_headers,
        )

        assert response.status_code == 204

        # Verify license is deleted
        get_response = await client.get(
            f"/web-api/v1/admin/licenses/{test_license.id}",
            headers=superuser_headers,
        )
        assert get_response.status_code == 404

    async def test_delete_license_not_found(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
    ) -> None:
        """Test deleting non-existent license returns 404."""
        response = await client.delete(
            "/web-api/v1/admin/licenses/NONEXISTENT",
            headers=superuser_headers,
        )

        assert response.status_code == 404

    async def test_delete_license_as_non_superuser_forbidden(
        self,
        client: AsyncClient,
        regular_user_headers: dict[str, str],
        test_license: License,
    ) -> None:
        """Test deleting license as non-superuser returns 403."""
        response = await client.delete(
            f"/web-api/v1/admin/licenses/{test_license.id}",
            headers=regular_user_headers,
        )

        assert response.status_code == 403

    async def test_delete_license_without_auth_unauthorized(
        self,
        client: AsyncClient,
        test_license: License,
    ) -> None:
        """Test deleting license without authentication returns 401."""
        response = await client.delete(
            f"/web-api/v1/admin/licenses/{test_license.id}",
        )

        assert response.status_code == 401
