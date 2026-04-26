"""Unit coverage for the login-notification outbox handler (T179, FR-104, FR-101).

The handler must:

* Sanitise each payload field via NFKC + control-char rejection.
* Reject payloads carrying ASCII control characters (the canonical
  email-header-injection signal — a stray ``\\n`` in a User-Agent
  string lets an attacker craft Bcc headers).
* Truncate over-long fields to the documented cap.
* Surface email-send failures to the outbox processor so the row is
  retried (or eventually dead-lettered).

The Resend SDK is mocked at the ``resend.Emails.send`` boundary so the
test does not require a network connection or a configured API key.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from echoroo.workers import login_notification_dispatcher
from echoroo.workers.login_notification_dispatcher import (
    LoginNotificationPayloadError,
    dispatch_login_notification,
)

pytestmark = pytest.mark.asyncio


def _payload(**overrides: Any) -> dict[str, Any]:
    base = {
        "user_id": "00000000-0000-0000-0000-000000000001",
        "user_email": "alice@example.com",
        "ip": "192.0.2.10",
        "user_agent": "Mozilla/5.0 (X11; Linux x86_64)",
        "ip_hash": "h:ip",
        "ua_hash": "h:ua",
        "timestamp": "2026-04-25T10:00:00+00:00",
    }
    base.update(overrides)
    return base


@pytest.fixture
def patch_resend(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Stub ``resend.Emails.send`` and ensure a non-empty API key."""
    monkeypatch.setattr(
        login_notification_dispatcher.settings,
        "RESEND_API_KEY",
        "test-key",
    )
    sender = MagicMock()
    monkeypatch.setattr(
        login_notification_dispatcher.resend.Emails,
        "send",
        sender,
    )
    return sender


# ---------------------------------------------------------------------------
# Happy path: clean payload → exactly one email sent
# ---------------------------------------------------------------------------


async def test_dispatcher_sends_one_email_for_clean_payload(
    patch_resend: MagicMock,
) -> None:
    await dispatch_login_notification(
        None,  # type: ignore[arg-type] - handler does not use the session
        _payload(),
    )

    assert patch_resend.call_count == 1
    sent = patch_resend.call_args.args[0]
    assert sent["to"] == "alice@example.com"
    assert sent["subject"] == "New sign-in to your Echoroo account"
    # The IP and UA must be present in the body — that's the whole
    # point of the email.
    assert "192.0.2.10" in sent["html"]
    assert "Linux" in sent["html"]


# ---------------------------------------------------------------------------
# Header-injection protection (FR-101)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field, malicious_value",
    [
        ("user_email", "alice@example.com\nBcc: attacker@example.com"),
        ("ip", "192.0.2.10\r\nX-Header: pwned"),
        ("user_agent", "Mozilla\nSubject: Phish"),
        ("timestamp", "2026-04-25T10:00:00+00:00\nX-Inject: 1"),
    ],
)
async def test_dispatcher_rejects_payload_with_control_chars(
    patch_resend: MagicMock,
    field: str,
    malicious_value: str,
) -> None:
    """ASCII control characters in any payload field abort the dispatch."""
    with pytest.raises(LoginNotificationPayloadError):
        await dispatch_login_notification(
            None,  # type: ignore[arg-type]
            _payload(**{field: malicious_value}),
        )

    # The send was never called — header-injection candidates never
    # leak past sanitisation.
    assert patch_resend.call_count == 0


# ---------------------------------------------------------------------------
# Empty recipient must NOT silently succeed — the outbox row should be
# treated as a payload defect and dead-lettered after retries.
# ---------------------------------------------------------------------------


async def test_dispatcher_raises_on_empty_recipient(
    patch_resend: MagicMock,
) -> None:
    with pytest.raises(LoginNotificationPayloadError):
        await dispatch_login_notification(
            None,  # type: ignore[arg-type]
            _payload(user_email=""),
        )
    assert patch_resend.call_count == 0


# ---------------------------------------------------------------------------
# Resend SDK failure surfaces as an exception so the outbox processor
# records the row failure and schedules the next retry.
# ---------------------------------------------------------------------------


async def test_dispatcher_propagates_resend_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        login_notification_dispatcher.settings,
        "RESEND_API_KEY",
        "test-key",
    )

    def _boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("smtp-down")

    monkeypatch.setattr(
        login_notification_dispatcher.resend.Emails,
        "send",
        _boom,
    )

    with pytest.raises(RuntimeError, match="smtp-down"):
        await dispatch_login_notification(
            None,  # type: ignore[arg-type]
            _payload(),
        )


# ---------------------------------------------------------------------------
# Missing API key short-circuits to a logged warning rather than raising.
# This matches the existing ``send_password_reset_email`` semantics so
# dev environments without Resend configured do not move every login row
# to ``dead_letter``.
# ---------------------------------------------------------------------------


async def test_dispatcher_no_op_when_resend_api_key_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        login_notification_dispatcher.settings,
        "RESEND_API_KEY",
        "",
    )

    sender = MagicMock()
    monkeypatch.setattr(
        login_notification_dispatcher.resend.Emails,
        "send",
        sender,
    )

    # Should NOT raise — the handler returns cleanly so the outbox row
    # advances to ``done`` and we don't dead-letter unconfigured dev
    # environments.
    await dispatch_login_notification(
        None,  # type: ignore[arg-type]
        _payload(),
    )

    assert sender.call_count == 0
