"""Contract tests for setup endpoints."""

import re

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

_BOOTSTRAP_TOKEN = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_TOKEN_PATTERN = re.compile(r"^[A-Za-z1-9]{32}$")


@pytest.fixture(autouse=True)
def _patch_setup_external_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep setup contract tests independent from KMS and audit-chain services."""

    async def _noop_audit(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr(
        "echoroo.services.setup._encrypt_totp_secret",
        lambda _secret: b"encrypted",
    )
    monkeypatch.setattr("echoroo.services.setup._current_dek_version", lambda: 1)
    monkeypatch.setattr(
        "echoroo.services.setup._generate_bootstrap_token",
        lambda: _BOOTSTRAP_TOKEN,
    )
    monkeypatch.setattr("echoroo.services.setup._write_bootstrap_audit", _noop_audit)
    monkeypatch.setattr("echoroo.services.setup.trigger_post_commit_audit", _noop_audit)


@pytest.mark.asyncio
class TestSetupStatusEndpoint:
    """Test GET /api/v1/setup/status endpoint contract."""

    async def test_get_setup_status_initial(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Test setup status when no users exist (initial state).

        Expected:
            - Status 200
            - setup_required: true
            - setup_completed: false
        """
        response = await client.get("/api/v1/setup/status")

        assert response.status_code == 200
        data = response.json()
        assert "setup_required" in data
        assert "setup_completed" in data
        assert data["setup_required"] is True
        assert data["setup_completed"] is False

    async def test_get_setup_status_after_completion(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Test setup status after initial setup is completed.

        Expected:
            - Status 200
            - setup_required: false
            - setup_completed: true
        """
        # First, complete the initial setup
        await client.post(
            "/api/v1/setup/initialize",
            json={
                "email": "admin@example.com",
                "password": "SecurePassword123!",
                "display_name": "System Admin",
            },
        )

        # Then check status
        response = await client.get("/api/v1/setup/status")

        assert response.status_code == 200
        data = response.json()
        assert data["setup_required"] is False
        assert data["setup_completed"] is True


@pytest.mark.asyncio
class TestSetupInitializeEndpoint:
    """Test POST /api/v1/setup/initialize endpoint contract."""

    async def test_initialize_setup_success(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Test successful initial setup with first admin user.

        Expected:
            - Status 201
            - Returns user object with id, email, display_name
            - Password is NOT returned
            - User is marked as superuser and verified
        """
        response = await client.post(
            "/api/v1/setup/initialize",
            json={
                "email": "admin@example.com",
                "password": "SecurePassword123!",
                "display_name": "Admin User",
            },
        )

        assert response.status_code == 201
        data = response.json()

        # Verify response structure
        assert "user" in data
        assert "totp_secret_base32" in data
        assert "totp_provisioning_uri" in data
        assert "bootstrap_token" in data
        assert "bootstrap_token_expires_at" in data
        assert "webauthn_registration_url" in data

        user = data["user"]
        assert "id" in user
        assert "email" in user
        assert "display_name" in user
        assert "created_at" in user
        assert "updated_at" in user
        assert "two_factor_enabled" in user

        # Verify values
        assert user["email"] == "admin@example.com"
        assert user["display_name"] == "Admin User"
        assert user["two_factor_enabled"] is True
        assert data["bootstrap_token"] == _BOOTSTRAP_TOKEN
        assert _TOKEN_PATTERN.fullmatch(data["bootstrap_token"]) is not None
        assert set(data["bootstrap_token"]).isdisjoint({"0", "O", "I", "l"})
        assert data["webauthn_registration_url"].endswith(data["bootstrap_token"])

        # Ensure password is NOT in response
        assert "password" not in data
        assert "password_hash" not in data
        assert "password" not in user
        assert "password_hash" not in user

    async def test_initialize_setup_minimal_fields(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Test setup with only required fields (email and password).

        Expected:
            - Status 201
            - display_name is None or empty
        """
        response = await client.post(
            "/api/v1/setup/initialize",
            json={
                "email": "admin@example.com",
                "password": "SecurePassword123!",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["user"]["email"] == "admin@example.com"
        assert data["user"]["display_name"] == "admin"

    async def test_initialize_setup_invalid_email(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Test setup with invalid email format.

        Expected:
            - Status 422 (Validation Error)
        """
        response = await client.post(
            "/api/v1/setup/initialize",
            json={
                "email": "not-an-email",
                "password": "SecurePassword123!",
            },
        )

        assert response.status_code == 422

    async def test_initialize_setup_short_password(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Test setup with password shorter than 16 characters.

        Expected:
            - Status 422 (Validation Error)
        """
        response = await client.post(
            "/api/v1/setup/initialize",
            json={
                "email": "admin@example.com",
                "password": "short",
            },
        )

        assert response.status_code == 422

    async def test_initialize_setup_already_completed(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Test setup when already completed (second attempt).

        Expected:
            - Status 403 (Forbidden)
            - Error message indicating setup already completed
        """
        # First setup
        await client.post(
            "/api/v1/setup/initialize",
            json={
                "email": "admin@example.com",
                "password": "SecurePassword123!",
            },
        )

        # Second attempt should fail
        response = await client.post(
            "/api/v1/setup/initialize",
            json={
                "email": "another@example.com",
                "password": "AnotherPassword123!",
            },
        )

        assert response.status_code == 403
        data = response.json()
        assert "detail" in data

    async def test_initialize_setup_missing_required_fields(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Test setup without required fields.

        Expected:
            - Status 422 (Validation Error)
        """
        # Missing password
        response = await client.post(
            "/api/v1/setup/initialize",
            json={"email": "admin@example.com"},
        )
        assert response.status_code == 422

        # Missing email
        response = await client.post(
            "/api/v1/setup/initialize",
            json={"password": "SecurePassword123!"},
        )
        assert response.status_code == 422

        # Empty body
        response = await client.post("/api/v1/setup/initialize", json={})
        assert response.status_code == 422
