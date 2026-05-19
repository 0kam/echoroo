"""Integration tests for complete setup workflow."""

import re

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.superuser import Superuser
from echoroo.models.system import SystemSetting
from echoroo.models.user import User

_BOOTSTRAP_TOKEN = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_TOKEN_PATTERN = re.compile(r"^[A-Za-z1-9]{32}$")


@pytest.fixture(autouse=True)
def _patch_setup_external_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep setup integration tests independent from KMS and audit-chain services."""

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
class TestSetupFlow:
    """Test complete setup workflow end-to-end."""

    async def test_full_setup_flow(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Test complete setup workflow from start to finish.

        Workflow:
            1. Check initial setup status (required)
            2. Initialize setup with first admin user
            3. Verify setup status (completed)
            4. Verify user was created in database
            5. Verify system settings were updated
            6. Attempt second setup (should fail)
        """
        # Step 1: Check initial status
        response = await client.get("/api/v1/setup/status")
        assert response.status_code == 200
        assert response.json()["setup_required"] is True
        assert response.json()["setup_completed"] is False

        # Step 2: Initialize setup
        setup_data = {
            "email": "admin@echoroo.app",
            "password": "SuperSecurePassword123!",
            "display_name": "System Administrator",
        }
        response = await client.post("/api/v1/setup/initialize", json=setup_data)
        assert response.status_code == 201

        data = response.json()
        user_data = data["user"]
        assert user_data["email"] == "admin@echoroo.app"
        assert user_data["display_name"] == "System Administrator"
        assert user_data["two_factor_enabled"] is True
        assert data["totp_secret_base32"]
        assert data["totp_provisioning_uri"].startswith("otpauth://totp/")
        assert data["bootstrap_token"] == _BOOTSTRAP_TOKEN
        assert _TOKEN_PATTERN.fullmatch(data["bootstrap_token"]) is not None
        assert set(data["bootstrap_token"]).isdisjoint({"0", "O", "I", "l"})
        assert data["webauthn_registration_url"].endswith(data["bootstrap_token"])

        # Step 3: Verify setup status changed
        response = await client.get("/api/v1/setup/status")
        assert response.status_code == 200
        assert response.json()["setup_required"] is False
        assert response.json()["setup_completed"] is True

        # Step 4: Verify user exists in database
        result = await db_session.execute(
            select(User).where(User.email == "admin@echoroo.app")
        )
        user = result.scalar_one_or_none()
        assert user is not None
        assert user.email == "admin@echoroo.app"
        assert user.display_name == "System Administrator"
        assert user.two_factor_enabled is True
        assert user.two_factor_secret_encrypted == b"encrypted"
        assert user.two_factor_secret_dek_version == 1
        assert user.two_factor_backup_codes_hashed is None
        assert user.security_stamp
        assert user.password_hash is not None
        assert not user.password_hash.startswith("Super")  # Not plain text

        superuser_result = await db_session.execute(
            select(Superuser).where(Superuser.user_id == user.id)
        )
        superuser = superuser_result.scalar_one_or_none()
        assert superuser is not None
        assert superuser.revoked_at is None

        # Step 5: Verify system settings updated
        setting_result = await db_session.execute(
            select(SystemSetting).where(SystemSetting.key == "setup_completed")
        )
        setting = setting_result.scalar_one_or_none()
        assert setting is not None
        assert setting.value is True
        assert setting.updated_by_id == superuser.id

        token_result = await db_session.execute(
            select(SystemSetting).where(
                SystemSetting.key == "break_glass_credential_setup_token"
            )
        )
        token_setting = token_result.scalar_one_or_none()
        assert token_setting is not None
        assert token_setting.value["token"] == data["bootstrap_token"]
        assert token_setting.updated_by_id == superuser.id

        # Step 6: Attempt second setup (should fail)
        response = await client.post(
            "/api/v1/setup/initialize",
            json={
                "email": "second@example.com",
                "password": "AnotherPassword123!",
            },
        )
        assert response.status_code == 403

    async def test_setup_with_existing_user(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Test that setup fails if any user already exists.

        This tests the condition where a user was created outside setup.
        """
        # Manually create a user
        from echoroo.core.security import hash_password

        user = User(
            email="existing@example.com",
            password_hash=hash_password("password123"),
            display_name="Existing",
            security_stamp="x" * 64,
        )
        db_session.add(user)
        await db_session.commit()

        # Attempt setup
        response = await client.post(
            "/api/v1/setup/initialize",
            json={
                "email": "admin@example.com",
                "password": "SecurePassword123!",
            },
        )

        # Should fail because users already exist
        assert response.status_code == 403
