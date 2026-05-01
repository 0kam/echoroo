"""Celery worker that emails users about new-device logins (FR-104, FR-105).

Wiring overview
---------------
:class:`echoroo.services.login_notification_service.LoginNotificationService`
enqueues an :class:`OutboxEvent` with
``event_type="login_notification"`` whenever a successful sign-in
arrives from a (IP, UA) tuple that has not been seen in the last 30
days. This module owns the *processing* side: it registers an
:func:`echoroo.workers.outbox_processor.register_outbox_handler`
handler that consumes those rows on the ``worker-cpu`` Celery queue.

Per row, the handler:

1. Sanitises the payload — Unicode-NFKC normalises strings and
   rejects ASCII control characters (FR-101 email header injection
   protection).
2. Delegates to :func:`echoroo.services.email.send_login_notification`,
   the single outbound-email integration point. The email body
   contains only the **hashed** IP / UA values (FR-105) — the user
   already knows which device they were using; the raw values would
   only add durable PII exposure (the email itself sits on the
   recipient's mail server forever).
3. Returns control; the outbox processor will call ``mark_done`` in
   the surrounding transaction. On exception, the row's retry counter
   advances and the outbox state machine eventually moves it to
   ``dead_letter`` after :data:`outbox_service.MAX_RETRY`.

The outbox processor itself enforces the 3-attempt Celery retry +
5-attempt per-row retry policy (research.md §6); this module does not
need its own retry loop.

PII discipline
--------------
The transient outbox payload still carries the raw IP and User-Agent
strings (the dispatcher needs *something* to compute the hash from
for the seen-table lookup, and the service path captures both the
raw and the hashed forms in a single transaction). Once
:func:`echoroo.services.outbox_service.mark_done` runs the payload is
scrubbed (FR-105). This handler must NEVER log the raw IP / UA or
forward them to anywhere durable — only the hashes are safe to
persist outside the request scope.
"""

from __future__ import annotations

import logging
import unicodedata
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.kms import compute_pii_hash
from echoroo.core.text import has_control_chars
from echoroo.services.email import send_login_notification
from echoroo.services.login_notification_service import LOGIN_NOTIFICATION_EVENT_TYPE
from echoroo.workers.outbox_processor import register_outbox_handler

logger = logging.getLogger(__name__)

#: Hard cap for fields that flow into the email body. Real-world
#: User-Agent strings rarely exceed a few hundred characters; longer
#: values are almost certainly noise (or an attacker probing for
#: header-injection bugs) and we truncate aggressively. Mirrors the
#: cap in :mod:`echoroo.services.email`.
_MAX_FIELD_LEN: Final[int] = 500


class LoginNotificationPayloadError(ValueError):
    """Raised when the outbox payload fails sanitisation."""


def _sanitise_field(value: object, *, field_name: str) -> str:
    """NFKC-normalise, reject control chars, and truncate to a hard cap.

    Header-injection defence (FR-101): any ASCII control character in a
    string we are about to feed into a To/Subject/header context aborts
    the dispatch. The Resend client itself escapes the body, but the
    subject line and headers are constructed by us — we cannot allow a
    raw newline.

    The same sanitisation runs again inside
    :func:`echoroo.services.email.send_login_notification`; doing it
    here too lets us fail fast with a payload-shaped error before
    crossing into the email service boundary.
    """
    if value is None:
        return ""
    raw = str(value)
    normalised = unicodedata.normalize("NFKC", raw).strip()
    if has_control_chars(normalised):
        raise LoginNotificationPayloadError(
            f"login_notification payload field {field_name!r} contains control characters"
        )
    if len(normalised) > _MAX_FIELD_LEN:
        normalised = normalised[:_MAX_FIELD_LEN]
    return normalised


def _resolve_hash(
    payload: dict[str, Any],
    *,
    hash_key: str,
    raw_key: str,
    field_name: str,
) -> str:
    """Return the hashed form for a payload field.

    Prefers the pre-computed hash already stamped onto the payload by
    :class:`LoginNotificationService` (so the worker does not need to
    talk to KMS on the hot path). Falls back to recomputing from the
    raw value if the hash is missing — this keeps the handler robust
    against historical rows enqueued before the hash fields were added.
    """
    candidate = payload.get(hash_key)
    if isinstance(candidate, str) and candidate:
        return _sanitise_field(candidate, field_name=hash_key)
    raw_value = _sanitise_field(payload.get(raw_key), field_name=field_name)
    if not raw_value:
        return ""
    return compute_pii_hash(raw_value)


@register_outbox_handler(LOGIN_NOTIFICATION_EVENT_TYPE)
async def dispatch_login_notification(
    _session: AsyncSession,
    payload: dict[str, Any],
) -> None:
    """Outbox handler for ``event_type='login_notification'``.

    The handler treats every payload field as untrusted: each goes
    through :func:`_sanitise_field` before being passed to the email
    sender. A payload that fails sanitisation raises
    :class:`LoginNotificationPayloadError`, which the outbox processor
    treats as a per-row failure and either retries (3 attempts) or
    moves to ``dead_letter`` (5 attempts).

    Privacy note (FR-105): only the *hashed* IP / UA crosses into the
    email. The raw values stay inside the transient outbox payload
    until :func:`echoroo.services.outbox_service.mark_done` scrubs the
    row, and never reach durable logs.
    """
    try:
        recipient = _sanitise_field(payload.get("user_email"), field_name="user_email")
        timestamp = _sanitise_field(payload.get("timestamp"), field_name="timestamp")
        ip_hash = _resolve_hash(payload, hash_key="ip_hash", raw_key="ip", field_name="ip")
        ua_hash = _resolve_hash(
            payload, hash_key="ua_hash", raw_key="user_agent", field_name="user_agent"
        )
    except LoginNotificationPayloadError as exc:
        # Re-raise so the outbox processor records the failure; the
        # row will be retried up to MAX_RETRY before moving to
        # ``dead_letter``. We deliberately don't squelch the exception
        # because a malformed payload represents a real defect upstream.
        # Log only payload key names — never the raw values.
        logger.error(
            "login_notification: payload sanitisation failed: %s; payload_keys=%s",
            exc,
            sorted(payload.keys()),
        )
        raise

    if not recipient:
        # An empty recipient indicates a service-side bug; abort the
        # dispatch so the row moves to ``dead_letter`` after retries.
        raise LoginNotificationPayloadError(
            "login_notification payload missing recipient email"
        )

    user_id = payload.get("user_id")
    event_id = payload.get("event_id") or payload.get("idempotency_key")
    logger.info(
        "login_notification: dispatching email user_id=%s ip_hash=%s ua_hash=%s event_id=%s",
        user_id,
        ip_hash,
        ua_hash,
        event_id,
    )

    await send_login_notification(
        to=recipient,
        ip_hash=ip_hash,
        ua_hash=ua_hash,
        timestamp=timestamp,
    )


__all__ = [
    "LoginNotificationPayloadError",
    "dispatch_login_notification",
]
