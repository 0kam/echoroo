"""US1 unit tests for the verification-email outbox dispatcher."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

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
