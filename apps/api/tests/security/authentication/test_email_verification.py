"""US1 security tests for email-verification token consumption."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from importlib import import_module
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.security import hash_password
from echoroo.models.user import User

pytestmark = pytest.mark.asyncio


async def _create_user(session: AsyncSession, email: str) -> User:
    user = User(
        email=email,
        password_hash=hash_password("CorrectHorseBatteryStaple123!"),
        display_name="Email Verification Test",
        security_stamp="security-stamp-for-email-verification-tests",
        two_factor_enabled=False,
        last_login_at=None,
        last_first_party_activity_at=datetime.now(UTC),
        email_verified_at=None,
    )
    session.add(user)
    await session.flush()
    return user


def _service_module() -> Any:
    return import_module("echoroo.services.email_verification_service")


async def test_concurrent_token_consume_allows_exactly_one_winner(
    db_session: AsyncSession,
) -> None:
    """Atomic consume prevents two concurrent submits from verifying the same token."""
    mod = _service_module()
    user = await _create_user(db_session, "concurrent-verify@example.com")
    service = mod.EmailVerificationService(db_session)
    issued = await service.issue_verification_token(
        user=user,
        email=user.email,
        ip="198.51.100.10",
        user_agent="pytest",
    )
    await db_session.commit()

    results = await asyncio.gather(
        service.verify_token(issued.token),
        service.verify_token(issued.token),
        return_exceptions=True,
    )

    successes = [result for result in results if isinstance(result, mod.EmailVerificationResult)]
    failures = [result for result in results if isinstance(result, mod.EmailVerificationError)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert failures[0].code == "ERR_EMAIL_VERIFICATION_REUSED"


async def test_reuse_after_success_is_rejected(
    db_session: AsyncSession,
) -> None:
    """A consumed token cannot be replayed after the first successful verification."""
    mod = _service_module()
    user = await _create_user(db_session, "reuse-verify@example.com")
    service = mod.EmailVerificationService(db_session)
    issued = await service.issue_verification_token(user=user, email=user.email)

    await service.verify_token(issued.token)
    with pytest.raises(mod.EmailVerificationError) as excinfo:
        await service.verify_token(issued.token)

    assert excinfo.value.code == "ERR_EMAIL_VERIFICATION_REUSED"


async def test_expired_token_is_rejected_without_setting_verified_at(
    db_session: AsyncSession,
) -> None:
    """Expired tokens fail and leave the account unverified."""
    mod = _service_module()
    user = await _create_user(db_session, "expired-verify@example.com")
    service = mod.EmailVerificationService(db_session)
    issued = await service.issue_verification_token(
        user=user,
        email=user.email,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    with pytest.raises(mod.EmailVerificationError) as excinfo:
        await service.verify_token(issued.token)

    assert excinfo.value.code == "ERR_EMAIL_VERIFICATION_EXPIRED"
    await db_session.refresh(user)
    assert user.email_verified_at is None


async def test_same_email_invitation_acceptance_marks_user_verified(
    db_session: AsyncSession,
) -> None:
    """Accepting a valid invitation for the same normalized email satisfies US1."""
    mod = _service_module()
    user = await _create_user(db_session, "invited@example.com")
    service = mod.EmailVerificationService(db_session)

    result = await service.mark_verified_from_same_email_invitation(
        user=user,
        invitation_email="INVITED@example.com",
        accepted_at=datetime.now(UTC),
    )

    assert result.verified is True
    await db_session.refresh(user)
    assert user.email_verified_at is not None


async def test_different_email_invitation_does_not_verify_account(
    db_session: AsyncSession,
) -> None:
    """Invitation acceptance may verify only when the normalized emails match."""
    mod = _service_module()
    user = await _create_user(db_session, "owner@example.com")
    service = mod.EmailVerificationService(db_session)

    result = await service.mark_verified_from_same_email_invitation(
        user=user,
        invitation_email="other@example.com",
        accepted_at=datetime.now(UTC),
    )

    assert result.verified is False
    await db_session.refresh(user)
    assert user.email_verified_at is None
