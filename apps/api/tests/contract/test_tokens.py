"""Contract tests for API token endpoints."""

import pytest
from httpx import AsyncClient


class TestListTokens:
    """Tests for GET /users/me/api-tokens endpoint."""

    @pytest.mark.asyncio
    async def test_list_tokens_empty(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test listing tokens when user has none."""
        response = await client.get("/api/v1/users/me/api-tokens", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 0

    @pytest.mark.asyncio
    async def test_list_tokens_with_data(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test listing tokens when user has created tokens."""
        # Create a token first
        create_response = await client.post(
            "/api/v1/users/me/api-tokens",
            json={"name": "Test Token"},
            headers=auth_headers,
        )
        assert create_response.status_code == 201

        # List tokens
        response = await client.get("/api/v1/users/me/api-tokens", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["name"] == "Test Token"
        assert data[0]["is_active"] is True
        # Token should not be returned in list
        assert "token" not in data[0]

    @pytest.mark.asyncio
    async def test_list_tokens_unauthorized(
        self,
        client: AsyncClient,
    ) -> None:
        """Test listing tokens without authentication."""
        response = await client.get("/api/v1/users/me/api-tokens")

        assert response.status_code == 401


class TestCreateToken:
    """Tests for POST /users/me/api-tokens endpoint."""

    @pytest.mark.asyncio
    async def test_create_token_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test creating a new API token."""
        response = await client.post(
            "/api/v1/users/me/api-tokens",
            json={"name": "My API Token"},
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "My API Token"
        assert data["is_active"] is True
        assert data["expires_at"] is None
        assert "token" in data
        assert data["token"].startswith("ecr_")
        assert len(data["token"]) == 36  # ecr_ + 32 chars

    @pytest.mark.asyncio
    async def test_create_token_with_expiry(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test creating a token with expiration date."""
        response = await client.post(
            "/api/v1/users/me/api-tokens",
            json={
                "name": "Expiring Token",
                "expires_at": "2030-12-31T23:59:59Z",
            },
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Expiring Token"
        assert data["expires_at"] is not None
        assert "2030-12-31" in data["expires_at"]

    @pytest.mark.asyncio
    async def test_create_token_name_too_long(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test creating a token with name exceeding max length."""
        long_name = "a" * 101
        response = await client.post(
            "/api/v1/users/me/api-tokens",
            json={"name": long_name},
            headers=auth_headers,
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_create_token_unauthorized(
        self,
        client: AsyncClient,
    ) -> None:
        """Test creating a token without authentication."""
        response = await client.post(
            "/api/v1/users/me/api-tokens",
            json={"name": "Test Token"},
        )

        assert response.status_code == 401


class TestRevokeToken:
    """Tests for DELETE /users/me/api-tokens/{tokenId} endpoint."""

    @pytest.mark.asyncio
    async def test_revoke_token_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test revoking an existing token."""
        # Create a token first
        create_response = await client.post(
            "/api/v1/users/me/api-tokens",
            json={"name": "Token to Revoke"},
            headers=auth_headers,
        )
        assert create_response.status_code == 201
        token_id = create_response.json()["id"]

        # Revoke the token
        response = await client.delete(
            f"/api/v1/users/me/api-tokens/{token_id}",
            headers=auth_headers,
        )

        assert response.status_code == 204

        # Verify token is no longer in list
        list_response = await client.get(
            "/api/v1/users/me/api-tokens",
            headers=auth_headers,
        )
        tokens = list_response.json()
        assert not any(t["id"] == token_id for t in tokens)

    @pytest.mark.asyncio
    async def test_revoke_nonexistent_token(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test revoking a token that does not exist."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.delete(
            f"/api/v1/users/me/api-tokens/{fake_id}",
            headers=auth_headers,
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_revoke_other_users_token(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        auth_headers_other: dict[str, str],
    ) -> None:
        """Test that a user cannot revoke another user's token."""
        # Create a token with test_user
        create_response = await client.post(
            "/api/v1/users/me/api-tokens",
            json={"name": "Test User Token"},
            headers=auth_headers,
        )
        assert create_response.status_code == 201
        token_id = create_response.json()["id"]

        # Try to revoke with other_user
        response = await client.delete(
            f"/api/v1/users/me/api-tokens/{token_id}",
            headers=auth_headers_other,
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_revoke_token_unauthorized(
        self,
        client: AsyncClient,
    ) -> None:
        """Test revoking a token without authentication."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.delete(f"/api/v1/users/me/api-tokens/{fake_id}")

        assert response.status_code == 401
