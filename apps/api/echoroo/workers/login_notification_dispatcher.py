"""Celery worker that emails users about new-device logins (FR-104).

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

1. Sanitises the payload — Unicode-NFKC normalises strings, rejects
   ASCII control characters, and truncates the IP / UA fields to
   reasonable lengths (FR-101 email header injection protection).
2. Sends a templated transactional email via
   :func:`echoroo.services.email.send_login_notification_email` (a
   thin wrapper added by this module to keep the existing
   ``email.py`` API surface stable).
3. Returns control; the outbox processor will call ``mark_done`` in
   the surrounding transaction. On exception, the row's retry
   counter advances and the outbox state machine eventually moves
   it to ``dead_letter`` after :data:`outbox_service.MAX_RETRY`.

The outbox processor itself enforces the 3-attempt Celery retry +
5-attempt per-row retry policy (research.md §6); this module does
not need its own retry loop.
"""

from __future__ import annotations

import logging
import unicodedata
from typing import Any, Final

import resend
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.settings import get_settings
from echoroo.core.text import has_control_chars
from echoroo.services.login_notification_service import LOGIN_NOTIFICATION_EVENT_TYPE
from echoroo.workers.outbox_processor import register_outbox_handler

logger = logging.getLogger(__name__)
settings = get_settings()

#: Hard cap for fields that flow into the email body. Real-world
#: User-Agent strings rarely exceed a few hundred characters; longer
#: values are almost certainly noise (or an attacker probing for
#: header-injection bugs) and we truncate aggressively.
_MAX_FIELD_LEN: Final[int] = 500


class LoginNotificationPayloadError(ValueError):
    """Raised when the outbox payload fails sanitisation."""


def _sanitise_field(value: object, *, field_name: str) -> str:
    """NFKC-normalise, reject control chars, and truncate to a hard cap.

    Header-injection defence (FR-101): any ASCII control character in a
    string we are about to put into a To/Subject/header context aborts
    the dispatch. The Resend client itself escapes the body, but the
    subject line and headers are constructed by us — we cannot allow a
    raw newline.
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


def _build_email_html(
    *,
    ip: str,
    user_agent: str,
    timestamp: str,
) -> str:
    """Build the user-facing HTML body.

    All three fields are pre-sanitised by :func:`_sanitise_field`; we
    HTML-escape them once more here as a defence-in-depth measure
    against XSS in any downstream HTML viewer that does not auto-escape.
    """
    import html

    return (
        "<h2>New sign-in to your Echoroo account</h2>"
        f"<p>We detected a sign-in from a new device or location at "
        f"<strong>{html.escape(timestamp)}</strong>.</p>"
        "<ul>"
        f"<li>IP address: <code>{html.escape(ip)}</code></li>"
        f"<li>Browser/User-Agent: <code>{html.escape(user_agent)}</code></li>"
        "</ul>"
        "<p>If this was you, no action is needed. If you do not "
        "recognise this sign-in, please reset your password "
        "immediately and contact support.</p>"
    )


async def send_login_notification_email(
    *,
    to: str,
    ip: str,
    user_agent: str,
    timestamp: str,
) -> None:
    """Send a templated new-device email via Resend.

    Header-injection defence: this is the LAST point at which we still
    have the bare IP / UA strings in process memory; the call to
    :meth:`resend.Emails.send` builds the SMTP envelope from them. The
    sanitisation step happens BEFORE we get here so this function can
    treat its inputs as already-safe.

    Failures are propagated so the outbox dispatcher can retry the row.
    A best-effort log is emitted on the failure path because the
    business email is the user-visible side-effect of FR-104 and
    silent drops are unacceptable.
    """
    if not settings.RESEND_API_KEY:
        logger.warning(
            "login_notification: Resend API key not configured; "
            "would have sent email to %s for IP %s",
            to,
            ip,
        )
        return

    resend.api_key = settings.RESEND_API_KEY

    subject = "New sign-in to your Echoroo account"
    if has_control_chars(subject):  # pragma: no cover - constant string
        raise LoginNotificationPayloadError(
            "subject contains control characters (compile-time invariant violated)"
        )

    try:
        resend.Emails.send(
            {
                "from": settings.EMAIL_FROM,
                "to": to,
                "subject": subject,
                "html": _build_email_html(
                    ip=ip,
                    user_agent=user_agent,
                    timestamp=timestamp,
                ),
            }
        )
    except Exception:
        logger.exception("login_notification: Resend send failed for to=%s", to)
        raise


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
    """
    try:
        recipient = _sanitise_field(payload.get("user_email"), field_name="user_email")
        ip = _sanitise_field(payload.get("ip"), field_name="ip")
        user_agent = _sanitise_field(payload.get("user_agent"), field_name="user_agent")
        timestamp = _sanitise_field(payload.get("timestamp"), field_name="timestamp")
    except LoginNotificationPayloadError as exc:
        # Re-raise so the outbox processor records the failure; the
        # row will be retried up to MAX_RETRY before moving to
        # ``dead_letter``. We deliberately don't squelch the exception
        # because a malformed payload represents a real defect upstream.
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

    await send_login_notification_email(
        to=recipient,
        ip=ip,
        user_agent=user_agent,
        timestamp=timestamp,
    )


__all__ = [
    "LoginNotificationPayloadError",
    "dispatch_login_notification",
    "send_login_notification_email",
]
