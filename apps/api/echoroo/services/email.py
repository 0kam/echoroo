"""Email service using Resend for transactional emails.

This module is the single outbound-email integration point for the
backend (FR-104, FR-101, FR-105). Every transactional email — account
verification, password reset, new-device login notification — funnels
through one of the helpers below so that:

* The Resend SDK is imported in exactly one place.
* Header-injection defence (NFKC normalise + ASCII control char
  rejection) lives next to the email-rendering code.
* Long-term PII does not leak into outbound bodies. Login-notification
  emails carry only the **hashed** (``ip_hash``, ``ua_hash``) values —
  the user already knows which device they were using; the raw IP and
  User-Agent are not required to deliver the security signal.
"""

from __future__ import annotations

import html
import logging
import unicodedata
from typing import Final

import resend

from echoroo.core.kms import compute_pii_hash
from echoroo.core.settings import get_settings
from echoroo.core.text import has_control_chars

settings = get_settings()
logger = logging.getLogger(__name__)


def _safe_recipient_hash(value: str | None) -> str:
    """Return a non-PII surrogate for ``value`` suitable for log output.

    All log statements in this module funnel through this helper so we
    never spill the raw recipient address into durable log storage
    (Datadog, syslog, etc.) — FR-105 treats email addresses as PII just
    like raw IP / UA strings. We deliberately keep the call infallible:
    if KMS is briefly unreachable we fall back to a static placeholder
    rather than re-raise (which would mask the *real* error the caller
    is already trying to report).
    """
    if not value:
        return "<missing>"
    try:
        return compute_pii_hash(value)
    except Exception:  # pragma: no cover — defensive fallback
        # Never let a logging-side failure mask the real exception or
        # leak the raw value. The static surrogate keeps log lines
        # parseable while still being PII-free.
        return "<hash-unavailable>"

# Configure Resend API key
resend.api_key = settings.RESEND_API_KEY


#: Hard cap for any user-controlled string that flows into the email
#: body or headers. Real-world User-Agent strings rarely exceed a few
#: hundred characters; longer values are almost certainly noise (or an
#: attacker probing for header-injection bugs). Mirrors the cap in
#: :mod:`echoroo.workers.login_notification_dispatcher`.
_EMAIL_FIELD_MAX_LEN: Final[int] = 500


class EmailHeaderInjectionError(ValueError):
    """Raised when an email field carries ASCII control characters.

    A stray ``\\n`` in an attacker-controlled User-Agent (or any other
    header-bound field) lets them craft Bcc / Subject headers (FR-101).
    The transactional senders reject such inputs before constructing
    the SMTP envelope.
    """


def _sanitise_email_field(value: object, *, field_name: str) -> str:
    """NFKC-normalise, reject control chars, and truncate to a hard cap."""
    if value is None:
        return ""
    raw = str(value)
    normalised = unicodedata.normalize("NFKC", raw).strip()
    if has_control_chars(normalised):
        raise EmailHeaderInjectionError(
            f"email field {field_name!r} contains ASCII control characters"
        )
    if len(normalised) > _EMAIL_FIELD_MAX_LEN:
        normalised = normalised[:_EMAIL_FIELD_MAX_LEN]
    return normalised


async def send_verification_email(to: str, token: str) -> None:
    """Send email verification email.

    Args:
        to: Recipient email address
        token: Verification token

    Example:
        ```python
        await send_verification_email(user.email, verification_token)
        ```
    """
    recipient_hash = _safe_recipient_hash(to)

    # If Resend is not configured, skip sending (development mode).
    # NOTE: the verification token is intentionally not logged — even in
    # dev, leaking a verification token to log storage would let anyone
    # with log access claim the account (FR-105 + FR-101).
    if not settings.RESEND_API_KEY:
        logger.warning(
            "verification email skipped — RESEND_API_KEY not configured "
            "(recipient_hash=%s)",
            recipient_hash,
        )
        return

    verification_url = f"{settings.APP_URL}/verify-email?token={token}"

    try:
        resend.Emails.send(
            {
                "from": settings.EMAIL_FROM,
                "to": to,
                "subject": "Verify your Echoroo account",
                "html": f"""
                    <h2>Welcome to Echoroo!</h2>
                    <p>Please verify your email address by clicking the link below:</p>
                    <p><a href="{verification_url}">Verify Email</a></p>
                    <p>This link will expire in 24 hours.</p>
                    <p>If you didn't create an account, you can safely ignore this email.</p>
                """,
            }
        )
        logger.info("verification email sent (recipient_hash=%s)", recipient_hash)
    except Exception:
        logger.exception(
            "verification email delivery failed (recipient_hash=%s)",
            recipient_hash,
        )
        # Don't raise exception - email failure shouldn't block registration


async def send_password_reset_email(to: str, token: str) -> None:
    """Send password reset email.

    Args:
        to: Recipient email address
        token: Password reset token

    Example:
        ```python
        await send_password_reset_email(user.email, reset_token)
        ```
    """
    recipient_hash = _safe_recipient_hash(to)

    # If Resend is not configured, skip sending (development mode).
    # NOTE: the reset token is intentionally not logged — leaking it to
    # log storage would let anyone with log access take over the
    # account (FR-105 + FR-101).
    if not settings.RESEND_API_KEY:
        logger.warning(
            "password reset email skipped — RESEND_API_KEY not configured "
            "(recipient_hash=%s)",
            recipient_hash,
        )
        return

    reset_url = f"{settings.APP_URL}/reset-password?token={token}"

    try:
        resend.Emails.send(
            {
                "from": settings.EMAIL_FROM,
                "to": to,
                "subject": "Reset your Echoroo password",
                "html": f"""
                    <h2>Password Reset Request</h2>
                    <p>You requested to reset your password. Click the link below:</p>
                    <p><a href="{reset_url}">Reset Password</a></p>
                    <p>This link will expire in 1 hour.</p>
                    <p>If you didn't request this, you can safely ignore this email.</p>
                """,
            }
        )
        logger.info("password reset email sent (recipient_hash=%s)", recipient_hash)
    except Exception:
        logger.exception(
            "password reset email delivery failed (recipient_hash=%s)",
            recipient_hash,
        )
        # Don't raise exception - always return success for security


async def send_login_notification(
    *,
    to: str,
    ip_hash: str,
    ua_hash: str,
    timestamp: str,
) -> None:
    """Send a "new sign-in" notification email (FR-104, FR-105).

    Only **hashed** IP and User-Agent values cross the email boundary.
    The user already knows which device / network they were on; the raw
    values would only add long-term PII exposure (the email is durable
    on the recipient's mail server) without improving the security
    signal. The hashes line up with the
    :class:`echoroo.services.login_notification_service.LoginNotificationService`
    seen-table so the user can ask support for a correlated lookup if
    they need to investigate.

    Args:
        to: Recipient email address.
        ip_hash: HMAC-SHA256 hex of the client IP (FR-091, FR-091b).
        ua_hash: HMAC-SHA256 hex of the User-Agent header.
        timestamp: ISO-8601 timestamp of the sign-in (used in the body).

    Raises:
        EmailHeaderInjectionError: If any field carries ASCII control
            characters — these are textbook header-injection candidates
            and the dispatcher must NOT swallow them silently (FR-101).
        Exception: Any Resend SDK error propagates so the outbox
            processor can retry / dead-letter the row.
    """
    recipient = _sanitise_email_field(to, field_name="to")
    safe_ip_hash = _sanitise_email_field(ip_hash, field_name="ip_hash")
    safe_ua_hash = _sanitise_email_field(ua_hash, field_name="ua_hash")
    safe_timestamp = _sanitise_email_field(timestamp, field_name="timestamp")

    if not recipient:
        # Caller bug — surface as an exception so the outbox row
        # eventually moves to ``dead_letter`` after the retry budget.
        raise EmailHeaderInjectionError("send_login_notification requires a recipient")

    # FR-105: never let the raw recipient address cross into log
    # storage. Every log statement below uses ``recipient_hash`` (a
    # KMS-keyed HMAC of the address) instead. The hashed IP / UA values
    # are already non-PII surrogates and can be logged as-is.
    recipient_hash = _safe_recipient_hash(recipient)

    if not settings.RESEND_API_KEY:
        # Dev / test mode: log only the hashed values. We deliberately
        # do NOT log the raw IP / UA / email — logs are durable PII
        # storage and FR-105 forbids that path. The recipient_hash is a
        # stable surrogate that lets operators correlate this skip with
        # the seen-table row without ever exposing the address.
        logger.warning(
            "login_notification email skipped — RESEND_API_KEY not configured "
            "(recipient_hash=%s, ip_hash=%s, ua_hash=%s)",
            recipient_hash,
            safe_ip_hash,
            safe_ua_hash,
        )
        return

    subject = "New sign-in to your Echoroo account"
    if has_control_chars(subject):  # pragma: no cover — constant string
        raise EmailHeaderInjectionError(
            "subject contains control characters (compile-time invariant)"
        )

    body_html = (
        "<h2>New sign-in to your Echoroo account</h2>"
        f"<p>We detected a sign-in to your account at "
        f"<strong>{html.escape(safe_timestamp)}</strong>.</p>"
        "<p>For your privacy we do not include the raw IP address or "
        "browser identifier in this email. The hashed device fingerprints "
        "below match what we store internally, so support can correlate "
        "this sign-in with your account record if you need to investigate.</p>"
        "<ul>"
        f"<li>Device fingerprint (IP): <code>{html.escape(safe_ip_hash)}</code></li>"
        f"<li>Device fingerprint (browser): <code>{html.escape(safe_ua_hash)}</code></li>"
        "</ul>"
        "<p>If this was you, no action is needed. If you do not recognise "
        "this sign-in, please reset your password immediately and contact "
        "support.</p>"
    )

    resend.api_key = settings.RESEND_API_KEY
    try:
        resend.Emails.send(
            {
                "from": settings.EMAIL_FROM,
                "to": recipient,
                "subject": subject,
                "html": body_html,
            }
        )
    except Exception:
        # Re-raise so the outbox dispatcher can retry / dead-letter
        # the row. The diagnostic log line carries only non-PII
        # surrogates (recipient_hash + ip_hash) — never the raw email,
        # IP, or UA. FR-105 forbids the raw forms in any durable log.
        logger.exception(
            "login_notification email delivery failed "
            "(recipient_hash=%s, ip_hash=%s)",
            recipient_hash,
            safe_ip_hash,
        )
        raise
