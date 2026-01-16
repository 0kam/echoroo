"""Integration tests for API token authentication."""

import pytest
from httpx import AsyncClient


class TestAPITokenAuthentication:
    """Tests for authenticating with API tokens."""

    @pytest.mark.asyncio
    async def test_api_token_authentication(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test that API tokens can be used for authentication."""
        # Create an API token
        create_response = await client.post(
            "/api/v1/users/me/api-tokens",
            json={"name": "Auth Test Token"},
            headers=auth_headers,
        )
        assert create_response.status_code == 201
        token = create_response.json()["token"]

        # Use the API token to authenticate
        api_token_headers = {"Authorization": f"Bearer {token}"}
        response = await client.get("/api/v1/users/me", headers=api_token_headers)

        assert response.status_code == 200
        data = response.json()
        assert "email" in data

    @pytest.mark.asyncio
    async def test_api_token_invalid(
        self,
        client: AsyncClient,
    ) -> None:
        """Test that invalid API tokens are rejected."""
        invalid_token = "ecr_invalidtoken12345678901234567"
        api_token_headers = {"Authorization": f"Bearer {invalid_token}"}

        response = await client.get("/api/v1/users/me", headers=api_token_headers)

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_api_token_revoked(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test that revoked API tokens are rejected."""
        # Create an API token
        create_response = await client.post(
            "/api/v1/users/me/api-tokens",
            json={"name": "Revoked Test Token"},
            headers=auth_headers,
        )
        assert create_response.status_code == 201
        token_id = create_response.json()["id"]
        token = create_response.json()["token"]

        # Revoke the token
        revoke_response = await client.delete(
            f"/api/v1/users/me/api-tokens/{token_id}",
            headers=auth_headers,
        )
        assert revoke_response.status_code == 204

        # Try to use the revoked token
        api_token_headers = {"Authorization": f"Bearer {token}"}
        response = await client.get("/api/v1/users/me", headers=api_token_headers)

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_api_token_expired(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test that expired API tokens are rejected."""
        # Create an API token with past expiration
        create_response = await client.post(
            "/api/v1/users/me/api-tokens",
            json={
                "name": "Expired Test Token",
                "expires_at": "2020-01-01T00:00:00Z",  # Past date
            },
            headers=auth_headers,
        )
        assert create_response.status_code == 201
        token = create_response.json()["token"]

        # Try to use the expired token
        api_token_headers = {"Authorization": f"Bearer {token}"}
        response = await client.get("/api/v1/users/me", headers=api_token_headers)

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_api_token_updates_last_used_at(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test that using an API token updates last_used_at."""
        # Create an API token
        create_response = await client.post(
            "/api/v1/users/me/api-tokens",
            json={"name": "Last Used Test Token"},
            headers=auth_headers,
        )
        assert create_response.status_code == 201
        token = create_response.json()["token"]
        token_id = create_response.json()["id"]

        # Use the API token
        api_token_headers = {"Authorization": f"Bearer {token}"}
        await client.get("/api/v1/users/me", headers=api_token_headers)

        # Check that last_used_at was updated
        list_response = await client.get(
            "/api/v1/users/me/api-tokens",
            headers=auth_headers,
        )
        tokens = list_response.json()
        target_token = next(t for t in tokens if t["id"] == token_id)
        assert target_token["last_used_at"] is not None
