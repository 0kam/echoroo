"""Unit coverage for the login-notification outbox handler (T179, FR-104, FR-105, FR-101).

The handler must:

* Sanitise each payload field via NFKC + control-char rejection.
* Reject payloads carrying ASCII control characters (the canonical
  email-header-injection signal — a stray ``\\n`` in a User-Agent
  string lets an attacker craft Bcc headers).
* Truncate over-long fields to the documented cap.
* Delegate the actual email send to the unified
  :func:`echoroo.services.email.send_login_notification` helper so the
  Resend SDK is invoked from a single place (no duplicated logic).
* Pass only the **hashed** (``ip_hash``, ``ua_hash``) values to the
  email helper — the raw IP / User-Agent strings must never cross
  into durable storage (logs, email body, etc.) per FR-105.
* Surface email-send failures to the outbox processor so the row is
  retried (or eventually dead-lettered).

The email-service helper is mocked at the
:func:`echoroo.workers.login_notification_dispatcher.send_login_notification`
boundary so the test exercises the dispatcher contract without
touching the Resend SDK or a network connection.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

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
def patch_email(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Stub :func:`send_login_notification` at the dispatcher boundary.

    The dispatcher imports the helper as a module-level name; replacing
    that binding lets us assert on the keyword arguments passed without
    touching :mod:`echoroo.services.email` itself.
    """
    sender = AsyncMock()
    monkeypatch.setattr(
        login_notification_dispatcher,
        "send_login_notification",
        sender,
    )
    return sender


# ---------------------------------------------------------------------------
# Happy path: clean payload → exactly one email send via the unified helper
# ---------------------------------------------------------------------------


async def test_dispatcher_delegates_to_email_service_with_hashes_only(
    patch_email: AsyncMock,
) -> None:
    """The dispatcher must forward only hashed values, never the raw IP / UA."""
    await dispatch_login_notification(
        None,  # type: ignore[arg-type] - handler does not use the session
        _payload(),
    )

    assert patch_email.await_count == 1
    kwargs = patch_email.await_args.kwargs
    assert kwargs["to"] == "alice@example.com"
    assert kwargs["ip_hash"] == "h:ip"
    assert kwargs["ua_hash"] == "h:ua"
    assert kwargs["timestamp"] == "2026-04-25T10:00:00+00:00"
    # The raw IP / UA must NOT be passed to the email helper — the
    # FR-105 contract is that durable surfaces (email body + logs)
    # only ever see the hashed forms.
    assert "ip" not in kwargs
    assert "user_agent" not in kwargs


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
    patch_email: AsyncMock,
    field: str,
    malicious_value: str,
) -> None:
    """ASCII control characters in any payload field abort the dispatch.

    For payloads where the malicious value sits in a field whose
    pre-computed hash is also present (``ip``, ``user_agent``), the
    sanitiser short-circuits via the hash path. We strip the hash
    key here so the test definitely exercises the raw-value branch.
    """
    payload = _payload(**{field: malicious_value})
    if field == "ip":
        payload.pop("ip_hash", None)
    if field == "user_agent":
        payload.pop("ua_hash", None)

    with pytest.raises(LoginNotificationPayloadError):
        await dispatch_login_notification(
            None,  # type: ignore[arg-type]
            payload,
        )

    # The email helper was never called — header-injection candidates
    # never leak past sanitisation.
    assert patch_email.await_count == 0


# ---------------------------------------------------------------------------
# Empty recipient must NOT silently succeed — the outbox row should be
# treated as a payload defect and dead-lettered after retries.
# ---------------------------------------------------------------------------


async def test_dispatcher_raises_on_empty_recipient(
    patch_email: AsyncMock,
) -> None:
    with pytest.raises(LoginNotificationPayloadError):
        await dispatch_login_notification(
            None,  # type: ignore[arg-type]
            _payload(user_email=""),
        )
    assert patch_email.await_count == 0


# ---------------------------------------------------------------------------
# Email-helper failure surfaces as an exception so the outbox processor
# records the row failure and schedules the next retry.
# ---------------------------------------------------------------------------


async def test_dispatcher_propagates_email_helper_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _boom(**_kwargs: Any) -> None:
        raise RuntimeError("smtp-down")

    monkeypatch.setattr(
        login_notification_dispatcher,
        "send_login_notification",
        _boom,
    )

    with pytest.raises(RuntimeError, match="smtp-down"):
        await dispatch_login_notification(
            None,  # type: ignore[arg-type]
            _payload(),
        )


# ---------------------------------------------------------------------------
# Hash fallback: payloads missing pre-computed hashes still resolve via
# :func:`compute_pii_hash`. This exercises the historical-row path so
# the worker stays robust against rows enqueued before the hash fields
# were added.
# ---------------------------------------------------------------------------


async def test_dispatcher_recomputes_hash_when_payload_lacks_it(
    patch_email: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        login_notification_dispatcher,
        "compute_pii_hash",
        lambda value: f"h:{value}",
    )

    payload = _payload()
    payload.pop("ip_hash")
    payload.pop("ua_hash")

    await dispatch_login_notification(
        None,  # type: ignore[arg-type]
        payload,
    )

    assert patch_email.await_count == 1
    kwargs = patch_email.await_args.kwargs
    assert kwargs["ip_hash"] == "h:192.0.2.10"
    assert kwargs["ua_hash"] == "h:Mozilla/5.0 (X11; Linux x86_64)"
