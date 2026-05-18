"""US1 unit tests for the email-verification service contract."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from importlib import import_module
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.security import hash_password
from echoroo.models.email_verification_token import EmailVerificationToken
from echoroo.models.user import User

pytestmark = pytest.mark.asyncio


async def _create_user(session: AsyncSession, email: str) -> User:
    user = User(
        email=email,
        password_hash=hash_password("CorrectHorseBatteryStaple123!"),
        display_name="Email Verification Unit",
        security_stamp="security-stamp-for-email-verification-unit-tests",
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


async def test_issue_verification_token_stores_hash_only_and_enqueues_outbox(
    db_session: AsyncSession,
) -> None:
    mod = _service_module()
    user = await _create_user(db_session, "issue-token@example.com")
    service = mod.EmailVerificationService(db_session)

    issued = await service.issue_verification_token(
        user=user,
        email=user.email,
        ip="203.0.113.5",
        user_agent="pytest",
    )

    assert issued.token
    assert len(issued.token) == 43
    assert issued.outbox_event_id is not None
    rows = (
        await db_session.execute(
            select(EmailVerificationToken).where(
                EmailVerificationToken.user_id == user.id,
                EmailVerificationToken.purpose == "verify_email",
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].token_hash != issued.token
    assert rows[0].email_normalized == "issue-token@example.com"
    assert rows[0].expires_at > datetime.now(UTC)


async def test_issue_verification_token_supersedes_previous_active_token(
    db_session: AsyncSession,
) -> None:
    mod = _service_module()
    user = await _create_user(db_session, "supersede-token@example.com")
    service = mod.EmailVerificationService(db_session)

    first = await service.issue_verification_token(user=user, email=user.email)
    second = await service.issue_verification_token(user=user, email=user.email)

    assert first.token != second.token
    rows = (
        await db_session.execute(
            select(EmailVerificationToken)
            .where(EmailVerificationToken.user_id == user.id)
            .order_by(EmailVerificationToken.created_at.asc())
        )
    ).scalars().all()
    assert len(rows) == 2
    assert rows[0].superseded_at is not None
    assert rows[1].superseded_at is None
    assert rows[1].consumed_at is None


async def test_verify_token_sets_email_verified_at_and_consumes_token(
    db_session: AsyncSession,
) -> None:
    mod = _service_module()
    user = await _create_user(db_session, "consume-token@example.com")
    service = mod.EmailVerificationService(db_session)
    issued = await service.issue_verification_token(user=user, email=user.email)

    result = await service.verify_token(issued.token)

    assert result.user_id == user.id
    assert result.email == user.email
    assert result.email_verified_at is not None
    row = (
        await db_session.execute(
            select(EmailVerificationToken).where(
                EmailVerificationToken.user_id == user.id,
            )
        )
    ).scalar_one()
    assert row.consumed_at is not None


async def test_verify_token_rejects_superseded_token(
    db_session: AsyncSession,
) -> None:
    mod = _service_module()
    user = await _create_user(db_session, "superseded-consume@example.com")
    service = mod.EmailVerificationService(db_session)
    first = await service.issue_verification_token(user=user, email=user.email)
    await service.issue_verification_token(user=user, email=user.email)

    with pytest.raises(mod.EmailVerificationError) as excinfo:
        await service.verify_token(first.token)

    assert excinfo.value.code == "ERR_EMAIL_VERIFICATION_REUSED"
    await db_session.refresh(user)
    assert user.email_verified_at is None


async def test_verify_token_rejects_when_account_email_changed(
    db_session: AsyncSession,
) -> None:
    mod = _service_module()
    user = await _create_user(db_session, "before-change@example.com")
    service = mod.EmailVerificationService(db_session)
    issued = await service.issue_verification_token(user=user, email=user.email)
    user.email = "after-change@example.com"
    await db_session.flush()

    with pytest.raises(mod.EmailVerificationError) as excinfo:
        await service.verify_token(issued.token)

    assert excinfo.value.code == "ERR_EMAIL_VERIFICATION_INVALID"
    assert user.email_verified_at is None


async def test_same_email_invitation_helper_is_idempotent(
    db_session: AsyncSession,
) -> None:
    mod = _service_module()
    user = await _create_user(db_session, "same-email-helper@example.com")
    service = mod.EmailVerificationService(db_session)
    accepted_at = datetime.now(UTC) - timedelta(seconds=5)

    first = await service.mark_verified_from_same_email_invitation(
        user=user,
        invitation_email="same-email-helper@example.com",
        accepted_at=accepted_at,
    )
    second = await service.mark_verified_from_same_email_invitation(
        user=user,
        invitation_email="SAME-EMAIL-HELPER@example.com",
        accepted_at=datetime.now(UTC),
    )

    assert first.verified is True
    assert second.verified is True
    assert user.email_verified_at == accepted_at
