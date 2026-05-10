"""Coverage uplift unit tests for ``echoroo.services.user_deletion_service``.

Phase 17 §C Batch 6+7 (25-35pp gap): covers soft_delete_user (UserNotFoundError,
UserAlreadyDeletedError, success path) and trigger_post_commit_audit (success
and exception paths) so the module clears the 85% threshold without touching
production code.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from echoroo.services.user_deletion_service import (
    UserAlreadyDeletedError,
    UserNotFoundError,
    UserSoftDeleteOutcome,
    soft_delete_user,
    trigger_post_commit_audit,
)


def _make_session() -> MagicMock:
    session = MagicMock()
    session.execute = AsyncMock()
    return session


def _make_user_row(*, deleted_at: object = None) -> MagicMock:
    user = MagicMock()
    user.id = uuid4()
    user.deleted_at = deleted_at
    user.email = "user@example.com"
    user.display_name = "Test User"
    user.password_hash = "$argon2id$..."
    user.two_factor_secret_encrypted = None
    user.two_factor_secret_dek_version = None
    user.two_factor_backup_codes_hashed = None
    user.two_factor_enabled = False
    user.security_stamp = "old_stamp"
    user.updated_at = None
    return user


@pytest.mark.asyncio
async def test_soft_delete_raises_user_not_found_when_user_missing() -> None:
    """soft_delete_user raises UserNotFoundError when user not found (lines 205-207)."""
    session = _make_session()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=result)

    user_id = uuid4()
    with pytest.raises(UserNotFoundError, match=str(user_id)):
        await soft_delete_user(session, user_id=user_id)


@pytest.mark.asyncio
async def test_soft_delete_raises_already_deleted_when_deleted_at_set() -> None:
    """soft_delete_user raises UserAlreadyDeletedError when already deleted (lines 212-215)."""
    session = _make_session()
    user = _make_user_row(deleted_at=datetime.now(UTC))
    result = MagicMock()
    result.scalar_one_or_none.return_value = user
    session.execute = AsyncMock(return_value=result)

    with pytest.raises(UserAlreadyDeletedError):
        await soft_delete_user(session, user_id=uuid4())


@pytest.mark.asyncio
async def test_soft_delete_anonymises_user_row_and_returns_outcome() -> None:
    """soft_delete_user anonymises user fields and returns outcome (lines 216-241)."""
    session = _make_session()
    user_id = uuid4()
    user = _make_user_row(deleted_at=None)
    user.id = user_id
    result = MagicMock()
    result.scalar_one_or_none.return_value = user
    session.execute = AsyncMock(return_value=result)

    outcome = await soft_delete_user(
        session,
        user_id=user_id,
        request_id="req-test",
        ip="192.168.1.1",
        user_agent="TestAgent",
    )

    # Email is anonymised to sentinel pattern
    assert user.email.startswith("deleted_")
    assert "@deleted.echoroo.invalid" in user.email
    # Password is sentinel
    assert user.password_hash == "$deleted$"
    # Display name is sentinel
    assert user.display_name == "[deleted user]"
    # 2FA fields cleared
    assert user.two_factor_secret_encrypted is None
    assert user.two_factor_enabled is False
    # deleted_at is set
    assert user.deleted_at is not None
    # Security stamp rotated
    assert user.security_stamp != "old_stamp"

    assert isinstance(outcome, UserSoftDeleteOutcome)
    assert outcome.user_id == user_id
    assert outcome.request_id == "req-test"
    assert outcome.ip == "192.168.1.1"
    assert outcome.user_agent == "TestAgent"


@pytest.mark.asyncio
async def test_trigger_post_commit_audit_writes_audit_log() -> None:
    """trigger_post_commit_audit writes platform audit event (lines 262-283)."""
    outcome = UserSoftDeleteOutcome(
        user_id=uuid4(),
        deleted_at=datetime.now(UTC),
        request_id="req-123",
        ip="10.0.0.1",
        user_agent="TestBrowser",
        audit_detail={"user_id": str(uuid4())},
    )

    mock_audit_service = MagicMock()
    mock_audit_service.write_platform_event = AsyncMock()

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.commit = AsyncMock()

    with (
        patch(
            "echoroo.services.user_deletion_service.AsyncSessionLocal",
            return_value=mock_session,
        ),
        patch(
            "echoroo.services.user_deletion_service.AuditLogService",
            return_value=mock_audit_service,
        ),
    ):
        await trigger_post_commit_audit(outcome)

    mock_audit_service.write_platform_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_trigger_post_commit_audit_logs_warning_on_exception() -> None:
    """trigger_post_commit_audit logs warning on failure without re-raising (lines 280-283)."""
    outcome = UserSoftDeleteOutcome(
        user_id=uuid4(),
        deleted_at=datetime.now(UTC),
    )

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.commit = AsyncMock(side_effect=Exception("db error"))

    mock_audit_service = MagicMock()
    mock_audit_service.write_platform_event = AsyncMock()

    with (
        patch(
            "echoroo.services.user_deletion_service.AsyncSessionLocal",
            return_value=mock_session,
        ),
        patch(
            "echoroo.services.user_deletion_service.AuditLogService",
            return_value=mock_audit_service,
        ),
        patch("echoroo.services.user_deletion_service.logger") as mock_logger,
    ):
        # Should NOT raise — warning only
        await trigger_post_commit_audit(outcome)

    mock_logger.warning.assert_called()
