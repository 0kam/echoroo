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


async def send_email_change_notification(to: str) -> None:
    """Notify a previous mailbox that the account email address changed."""
    recipient_hash = _safe_recipient_hash(to)

    if not settings.RESEND_API_KEY:
        logger.warning(
            "email change notification skipped — RESEND_API_KEY not configured "
            "(recipient_hash=%s)",
            recipient_hash,
        )
        return

    try:
        resend.Emails.send(
            {
                "from": settings.EMAIL_FROM,
                "to": to,
                "subject": "Your Echoroo email address was changed",
                "html": """
                    <h2>Email address changed</h2>
                    <p>The email address on your Echoroo account was changed.</p>
                    <p>If you did not make this change, reset your password and
                    contact support immediately.</p>
                """,
            }
        )
        logger.info("email change notification sent (recipient_hash=%s)", recipient_hash)
    except Exception:
        logger.exception(
            "email change notification delivery failed (recipient_hash=%s)",
            recipient_hash,
        )


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


def _two_factor_reset_magic_link_url(token: str) -> str:
    return (
        f"{settings.web_app_base_url.rstrip('/')}"
        f"/two-factor-reset/confirm?token={token}"
    )


async def send_2fa_reset_magic_link(to: str, token: str) -> None:
    """Send the support-initiated 2FA reset magic-link email (FR-072 / A-11).

    Phase 17 backlog A-11: a support agent invokes
    ``POST /web-api/v1/auth/confirm-identity-for-2fa-reset`` to start
    the workflow. The endpoint returns 202 unconditionally (enumeration
    defence, mirrors A-6) and — for known accounts — drops a magic
    link into the user's inbox. Clicking the link redeems the token
    and yields a short-lived confirmation token the support agent then
    pastes into the admin reset form.

    The token itself is never logged. Failure to deliver does NOT
    raise — the audit row written by the caller carries the failure
    signal (FR-101 + FR-105 alignment with the password-reset path).
    """
    recipient_hash = _safe_recipient_hash(to)
    if not settings.RESEND_API_KEY:
        logger.warning(
            "2fa reset magic link skipped — RESEND_API_KEY not configured "
            "(recipient_hash=%s)",
            recipient_hash,
        )
        return

    magic_url = _two_factor_reset_magic_link_url(token)
    try:
        resend.Emails.send(
            {
                "from": settings.EMAIL_FROM,
                "to": to,
                "subject": "Confirm your identity for an Echoroo 2FA reset",
                "html": f"""
                    <h2>2FA reset request</h2>
                    <p>An Echoroo support agent has started a request to reset
                    the two-factor authentication on your account.</p>
                    <p>If you asked support for help, click the link below to
                    confirm your identity. The link expires in 30 minutes and
                    can only be used once.</p>
                    <p><a href="{magic_url}">Confirm identity for 2FA reset</a></p>
                    <p>If you did <strong>not</strong> contact support, you can
                    safely ignore this email — no change will be made unless
                    the link is clicked.</p>
                """,
            }
        )
        logger.info(
            "2fa reset magic link sent (recipient_hash=%s)",
            recipient_hash,
        )
    except Exception:
        # Round-2 Fix-1: re-raise so the caller can write the
        # ``two_factor_reset.email_notification_failed`` audit row.
        # Previously this ``except`` swallowed the exception, leaving
        # the audit path unreachable. The HTTP handler still translates
        # the failure into 202 Accepted (enumeration defence) AFTER the
        # audit row is committed, so the user-facing posture does not
        # change.
        logger.exception(
            "2fa reset magic link delivery failed (recipient_hash=%s)",
            recipient_hash,
        )
        raise


async def send_2fa_reset_dispatched(
    to: str,
    *,
    dispatched_at_iso: str,
) -> None:
    """Notify the user that their 2FA reset has been applied (FR-072 / A-11)."""
    recipient_hash = _safe_recipient_hash(to)
    if not settings.RESEND_API_KEY:
        logger.warning(
            "2fa reset applied notification skipped — RESEND_API_KEY not configured "
            "(recipient_hash=%s)",
            recipient_hash,
        )
        return
    safe_when = _sanitise_email_field(dispatched_at_iso, field_name="dispatched_at_iso")
    try:
        resend.Emails.send(
            {
                "from": settings.EMAIL_FROM,
                "to": to,
                "subject": "Your Echoroo 2FA has been reset",
                "html": f"""
                    <h2>Two-factor authentication reset</h2>
                    <p>The two-factor authentication on your Echoroo account
                    was cleared at <strong>{html.escape(safe_when)}</strong>.</p>
                    <p>The next time you sign in, Echoroo will guide you
                    through enrolling a new authenticator. For 72 hours your
                    password cannot be reset — this is a security cool-down
                    that protects against follow-up attacks.</p>
                    <p>If you did not request this, please contact support
                    immediately and rotate your password from a trusted
                    device.</p>
                """,
            }
        )
        logger.info(
            "2fa reset applied notification sent (recipient_hash=%s)",
            recipient_hash,
        )
    except Exception:
        # Round-2 Fix-1: re-raise so the dispatch poller can write the
        # ``two_factor_reset.email_notification_failed`` audit row with
        # ``stage="applied_notification"``. The poller already wraps
        # this call in a defensive try/except so the request row stays
        # in ``applied`` even when the notification mail fails.
        logger.exception(
            "2fa reset applied notification delivery failed (recipient_hash=%s)",
            recipient_hash,
        )
        raise


async def send_api_key_scope_degrade_email(
    *,
    to: str,
    api_key_prefix: str,
    created_at_iso: str,
    degraded_at_iso: str,
    grace_days_until_revoke: int,
) -> None:
    """Notify a user that their API key has lost write scope (FR-083 / A-4).

    The 180-day mark strips every write permission from the key. The
    user keeps read access for the remainder of the grace window
    (default 90 days). Failure to deliver re-raises so the caller's
    audit path runs — same convention as the 2FA reset emails.
    """
    recipient_hash = _safe_recipient_hash(to)
    if not settings.RESEND_API_KEY:
        logger.warning(
            "api_key scope_degrade email skipped — RESEND_API_KEY not configured "
            "(recipient_hash=%s, prefix=%s)",
            recipient_hash,
            api_key_prefix,
        )
        return

    safe_prefix = _sanitise_email_field(api_key_prefix, field_name="api_key_prefix")
    safe_created = _sanitise_email_field(created_at_iso, field_name="created_at_iso")
    safe_degraded = _sanitise_email_field(degraded_at_iso, field_name="degraded_at_iso")
    safe_grace = _sanitise_email_field(
        str(int(grace_days_until_revoke)), field_name="grace_days_until_revoke"
    )

    try:
        resend.Emails.send(
            {
                "from": settings.EMAIL_FROM,
                "to": to,
                "subject": "Your Echoroo API key now read-only (180-day rotation)",
                "html": f"""
                    <h2>API key write access removed</h2>
                    <p>The Echoroo API key with prefix
                    <code>{html.escape(safe_prefix)}</code> (created
                    <strong>{html.escape(safe_created)}</strong>) reached
                    180 days of age on
                    <strong>{html.escape(safe_degraded)}</strong>.</p>
                    <p>To protect your account against credential stuffing
                    on long-lived secrets, write-shaped permissions
                    (upload, vote, manage, etc.) have been removed. Read
                    permissions are still active.</p>
                    <p>The key will be fully revoked in
                    <strong>{html.escape(safe_grace)} days</strong>.
                    Please rotate it from
                    <a href="https://echoroo.app/settings/api-keys">your
                    settings page</a> at your earliest convenience.</p>
                """,
            }
        )
        logger.info(
            "api_key scope_degrade email sent (recipient_hash=%s, prefix=%s)",
            recipient_hash,
            safe_prefix,
        )
    except Exception:
        logger.exception(
            "api_key scope_degrade email delivery failed "
            "(recipient_hash=%s, prefix=%s)",
            recipient_hash,
            safe_prefix,
        )
        raise


async def send_api_key_revoke_email(
    *,
    to: str,
    api_key_prefix: str,
    created_at_iso: str,
    revoked_at_iso: str,
) -> None:
    """Notify a user that their API key has been auto-revoked (FR-083 / A-4).

    Sent at the 270-day mark. The key is now unusable — any subsequent
    request returns 401. Failure to deliver re-raises so the caller's
    audit path runs.
    """
    recipient_hash = _safe_recipient_hash(to)
    if not settings.RESEND_API_KEY:
        logger.warning(
            "api_key revoke email skipped — RESEND_API_KEY not configured "
            "(recipient_hash=%s, prefix=%s)",
            recipient_hash,
            api_key_prefix,
        )
        return

    safe_prefix = _sanitise_email_field(api_key_prefix, field_name="api_key_prefix")
    safe_created = _sanitise_email_field(created_at_iso, field_name="created_at_iso")
    safe_revoked = _sanitise_email_field(revoked_at_iso, field_name="revoked_at_iso")

    try:
        resend.Emails.send(
            {
                "from": settings.EMAIL_FROM,
                "to": to,
                "subject": "Your Echoroo API key has been revoked (270-day cap)",
                "html": f"""
                    <h2>API key revoked</h2>
                    <p>The Echoroo API key with prefix
                    <code>{html.escape(safe_prefix)}</code> (created
                    <strong>{html.escape(safe_created)}</strong>) was
                    automatically revoked at
                    <strong>{html.escape(safe_revoked)}</strong> after
                    reaching the 270-day age cap (FR-083).</p>
                    <p>The key can no longer authenticate against the
                    Echoroo API. Please mint a new key from
                    <a href="https://echoroo.app/settings/api-keys">your
                    settings page</a> and migrate any integrations.</p>
                """,
            }
        )
        logger.info(
            "api_key revoke email sent (recipient_hash=%s, prefix=%s)",
            recipient_hash,
            safe_prefix,
        )
    except Exception:
        logger.exception(
            "api_key revoke email delivery failed "
            "(recipient_hash=%s, prefix=%s)",
            recipient_hash,
            safe_prefix,
        )
        raise


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
