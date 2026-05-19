"""Coverage uplift unit tests for ``echoroo.services.setup``."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException, status

from echoroo.schemas.setup import SetupInitializeRequest
from echoroo.services import setup as mod
from echoroo.services.setup import SetupService
from echoroo.services.superuser_service import AlreadySuperuserError, SuperuserServiceError


@pytest.mark.asyncio
async def test_initialize_setup_creates_bootstrap_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """initialize_setup creates a user, commits, and emits post-commit hooks."""
    db = MagicMock()
    no_user_result = MagicMock()
    no_user_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(side_effect=[no_user_result, MagicMock(), no_user_result])
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.add = MagicMock()

    async def _refresh(user: object) -> None:
        user.created_at = datetime(2026, 1, 1, tzinfo=UTC)
        user.updated_at = datetime(2026, 1, 1, tzinfo=UTC)

    db.refresh = AsyncMock(side_effect=_refresh)

    service = SetupService(db)
    service.system_repo.is_setup_completed = AsyncMock(side_effect=[False, False])  # type: ignore[method-assign]
    service.system_repo.mark_setup_completed = AsyncMock()  # type: ignore[method-assign]

    outcome = SimpleNamespace(
        action="superuser.add.direct",
        status="direct",
        superuser_id=uuid4(),
        request_id="req-1",
        ip="203.0.113.10",
        user_agent="pytest",
    )

    persist_bootstrap_token = AsyncMock()
    write_bootstrap_audit = AsyncMock()
    trigger_post_commit_audit = AsyncMock()

    monkeypatch.setattr(mod, "hash_password", lambda _password: "argon2-hash")
    monkeypatch.setattr(mod, "_security_stamp", lambda: "s" * 64)
    monkeypatch.setattr(mod, "_encrypt_totp_secret", lambda _secret: b"encrypted")
    monkeypatch.setattr(mod, "_current_dek_version", lambda: 1)
    monkeypatch.setattr(mod.pyotp, "random_base32", lambda length: "A" * length)
    monkeypatch.setattr(mod, "_generate_bootstrap_token", lambda: "B" * 32)
    monkeypatch.setattr(mod, "_bootstrap_token_ttl", lambda: timedelta(hours=24))
    monkeypatch.setattr(mod, "add_superuser", AsyncMock(return_value=outcome))
    monkeypatch.setattr(mod, "_persist_bootstrap_token", persist_bootstrap_token)
    monkeypatch.setattr(mod, "_write_bootstrap_audit", write_bootstrap_audit)
    monkeypatch.setattr(mod, "trigger_post_commit_audit", trigger_post_commit_audit)

    request = SetupInitializeRequest(
        email="admin@example.com",
        password="StrongPassw0rd!!",
        display_name="Admin",
    )
    response = await service.initialize_setup(
        request,
        request_id="req-1",
        ip="203.0.113.10",
        user_agent="pytest",
    )

    assert response.user.email == "admin@example.com"
    assert response.user.display_name == "Admin"
    assert response.user.two_factor_enabled is True
    assert response.totp_secret_base32 == "A" * 32
    assert response.bootstrap_token == "B" * 32
    assert response.webauthn_registration_url.endswith("B" * 32)
    db.commit.assert_awaited_once()
    db.rollback.assert_not_awaited()
    service.system_repo.mark_setup_completed.assert_awaited_once_with(outcome.superuser_id)
    write_bootstrap_audit.assert_awaited_once()
    write_audit_kwargs = write_bootstrap_audit.await_args.kwargs
    assert write_audit_kwargs["actor_user_id"] == response.user.id
    assert write_audit_kwargs["request_id"] == "req-1"
    assert write_audit_kwargs["ip"] == "203.0.113.10"
    assert write_audit_kwargs["user_agent"] == "pytest"
    assert write_audit_kwargs["detail"] == {
        "user_id": str(response.user.id),
        "superuser_id": str(outcome.superuser_id),
        "email": "admin@example.com",
        "display_name": "Admin",
        "bootstrap_token_expires_at": response.bootstrap_token_expires_at.isoformat(),
    }
    trigger_post_commit_audit.assert_awaited_once_with(outcome)
    assert trigger_post_commit_audit.await_args.args[0].action == "superuser.add.direct"


@pytest.mark.asyncio
async def test_initialize_setup_rejects_when_user_exists() -> None:
    """initialize_setup returns 403 when setup is no longer allowed."""
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = uuid4()
    db.execute = AsyncMock(return_value=result)

    service = SetupService(db)
    service.system_repo.is_setup_completed = AsyncMock(return_value=False)  # type: ignore[method-assign]
    request = SetupInitializeRequest(
        email="admin@example.com",
        password="StrongPassw0rd!!",
        display_name="Admin",
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.initialize_setup(request)
    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert exc_info.value.detail == "Setup already completed or users already exist"


@pytest.mark.parametrize(
    "service_error",
    [
        AlreadySuperuserError("already superuser"),
        SuperuserServiceError("genesis inconsistency"),
    ],
)
@pytest.mark.asyncio
async def test_initialize_setup_maps_superuser_service_errors_to_403(
    monkeypatch: pytest.MonkeyPatch,
    service_error: SuperuserServiceError,
) -> None:
    """Unexpected superuser genesis state is surfaced as the setup 403."""
    db = MagicMock()
    no_user_result = MagicMock()
    no_user_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(side_effect=[no_user_result, MagicMock(), no_user_result])
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.rollback = AsyncMock()
    db.add = MagicMock()

    service = SetupService(db)
    service.system_repo.is_setup_completed = AsyncMock(side_effect=[False, False])  # type: ignore[method-assign]

    monkeypatch.setattr(mod, "hash_password", lambda _password: "argon2-hash")
    monkeypatch.setattr(mod, "_security_stamp", lambda: "s" * 64)
    monkeypatch.setattr(mod, "_encrypt_totp_secret", lambda _secret: b"encrypted")
    monkeypatch.setattr(mod, "_current_dek_version", lambda: 1)
    monkeypatch.setattr(mod.pyotp, "random_base32", lambda length: "A" * length)
    monkeypatch.setattr(mod, "_generate_bootstrap_token", lambda: "B" * 32)
    monkeypatch.setattr(mod, "_bootstrap_token_ttl", lambda: timedelta(hours=24))
    monkeypatch.setattr(mod, "add_superuser", AsyncMock(side_effect=service_error))

    request = SetupInitializeRequest(
        email="admin@example.com",
        password="StrongPassw0rd!!",
        display_name="Admin",
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.initialize_setup(request)

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert exc_info.value.detail == "Setup already completed or users already exist"
    db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_setup_status_no_users_no_completion_returns_required() -> None:
    """get_setup_status returns setup_required=True when DB is empty (lines 51, 54)."""
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=result)

    service = SetupService(db)
    # Patch the system_repo method directly to avoid DB calls.
    service.system_repo.is_setup_completed = AsyncMock(return_value=False)  # type: ignore[method-assign]

    status_resp = await service.get_setup_status()
    assert status_resp.setup_required is True
    assert status_resp.setup_completed is False


@pytest.mark.asyncio
async def test_get_setup_status_completed_returns_not_required() -> None:
    """get_setup_status returns setup_required=False when setup_completed."""
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=result)

    service = SetupService(db)
    service.system_repo.is_setup_completed = AsyncMock(return_value=True)  # type: ignore[method-assign]

    status_resp = await service.get_setup_status()
    assert status_resp.setup_required is False
    assert status_resp.setup_completed is True
