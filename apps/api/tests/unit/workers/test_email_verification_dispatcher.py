"""US1 unit tests for the verification-email outbox dispatcher."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from echoroo.workers import outbox_processor

_EVENT_TYPE = "auth.email_verification.requested"


def _payload(**overrides: Any) -> dict[str, Any]:
    base = {
        "user_id": "00000000-0000-0000-0000-000000000001",
        "email": "alice@example.com",
        "token": "A" * 43,
        "purpose": "verify_email",
        "requested_at": "2026-05-18T00:00:00+00:00",
    }
    base.update(overrides)
    return base


def test_verification_email_handler_is_registered() -> None:
    """The outbox processor must not dead-letter verification email events."""
    from echoroo.workers import email_verification_dispatcher  # noqa: F401

    handler = outbox_processor.OUTBOX_HANDLERS.get(_EVENT_TYPE)

    assert handler is not None
    assert handler.__module__ == "echoroo.workers.email_verification_dispatcher"


@pytest.mark.asyncio
async def test_dispatcher_delegates_to_email_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echoroo.workers import email_verification_dispatcher

    sender = AsyncMock()
    monkeypatch.setattr(
        email_verification_dispatcher,
        "send_verification_email",
        sender,
    )

    await email_verification_dispatcher.dispatch_email_verification(
        None,  # type: ignore[arg-type]
        _payload(),
    )

    sender.assert_awaited_once_with(
        to="alice@example.com",
        token="A" * 43,
    )


@pytest.mark.parametrize(
    "bad_payload",
    [
        {"email": ""},
        {"token": ""},
        {"email": "alice@example.com\nBcc: attacker@example.com"},
        {"token": "not a valid token"},
    ],
)
@pytest.mark.asyncio
async def test_dispatcher_rejects_malformed_payload(
    monkeypatch: pytest.MonkeyPatch,
    bad_payload: dict[str, str],
) -> None:
    from echoroo.workers import email_verification_dispatcher

    sender = AsyncMock()
    monkeypatch.setattr(
        email_verification_dispatcher,
        "send_verification_email",
        sender,
    )

    with pytest.raises(email_verification_dispatcher.EmailVerificationPayloadError):
        await email_verification_dispatcher.dispatch_email_verification(
            None,  # type: ignore[arg-type]
            _payload(**bad_payload),
        )

    sender.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatcher_resolves_pii_free_payload_and_delegates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echoroo.services.account_security_tokens import hash_account_security_token
    from echoroo.services.email_verification_service import (
        EMAIL_VERIFICATION_OUTBOX_TOKEN_VERSION,
        seal_email_verification_outbox_token,
    )
    from echoroo.workers import email_verification_dispatcher

    token = "B" * 43
    token_id = uuid4()
    session = AsyncMock()
    session.get = AsyncMock(
        return_value=SimpleNamespace(
            email_normalized="verified@example.com",
            token_hash=hash_account_security_token(token),
        )
    )
    sender = AsyncMock()
    monkeypatch.setattr(
        email_verification_dispatcher,
        "send_verification_email",
        sender,
    )

    await email_verification_dispatcher.dispatch_email_verification(
        session,
        {
            "token_id": str(token_id),
            "token_envelope": seal_email_verification_outbox_token(token),
            "token_envelope_version": EMAIL_VERIFICATION_OUTBOX_TOKEN_VERSION,
        },
    )

    session.get.assert_awaited_once()
    sender.assert_awaited_once_with(to="verified@example.com", token=token)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"token_id": str(uuid4()), "token_envelope": "sealed"},
        {"token_id": "not-a-uuid", "token_envelope": "sealed", "token_envelope_version": "v1"},
    ],
)
@pytest.mark.asyncio
async def test_dispatcher_rejects_invalid_pii_free_payload_metadata(
    payload: dict[str, str],
) -> None:
    from echoroo.workers import email_verification_dispatcher

    with pytest.raises(email_verification_dispatcher.EmailVerificationPayloadError):
        await email_verification_dispatcher.dispatch_email_verification(
            AsyncMock(),
            payload,
        )


@pytest.mark.asyncio
async def test_dispatcher_rejects_missing_token_row() -> None:
    from echoroo.services.email_verification_service import (
        EMAIL_VERIFICATION_OUTBOX_TOKEN_VERSION,
    )
    from echoroo.workers import email_verification_dispatcher

    session = AsyncMock()
    session.get = AsyncMock(return_value=None)

    with pytest.raises(email_verification_dispatcher.EmailVerificationPayloadError):
        await email_verification_dispatcher.dispatch_email_verification(
            session,
            {
                "token_id": str(uuid4()),
                "token_envelope": "sealed",
                "token_envelope_version": EMAIL_VERIFICATION_OUTBOX_TOKEN_VERSION,
            },
        )


@pytest.mark.asyncio
async def test_dispatcher_rejects_invalid_token_envelope() -> None:
    from echoroo.services.email_verification_service import (
        EMAIL_VERIFICATION_OUTBOX_TOKEN_VERSION,
    )
    from echoroo.workers import email_verification_dispatcher

    session = AsyncMock()
    session.get = AsyncMock(return_value=SimpleNamespace(token_hash="unused"))

    with pytest.raises(email_verification_dispatcher.EmailVerificationPayloadError):
        await email_verification_dispatcher.dispatch_email_verification(
            session,
            {
                "token_id": str(uuid4()),
                "token_envelope": "not-sealed",
                "token_envelope_version": EMAIL_VERIFICATION_OUTBOX_TOKEN_VERSION,
            },
        )


@pytest.mark.asyncio
async def test_dispatcher_rejects_token_envelope_hash_mismatch() -> None:
    from echoroo.services.email_verification_service import (
        EMAIL_VERIFICATION_OUTBOX_TOKEN_VERSION,
        seal_email_verification_outbox_token,
    )
    from echoroo.workers import email_verification_dispatcher

    session = AsyncMock()
    session.get = AsyncMock(
        return_value=SimpleNamespace(
            email_normalized="verified@example.com",
            token_hash="c" * 64,
        )
    )

    with pytest.raises(email_verification_dispatcher.EmailVerificationPayloadError):
        await email_verification_dispatcher.dispatch_email_verification(
            session,
            {
                "token_id": str(uuid4()),
                "token_envelope": seal_email_verification_outbox_token("C" * 43),
                "token_envelope_version": EMAIL_VERIFICATION_OUTBOX_TOKEN_VERSION,
            },
        )
