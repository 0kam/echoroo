"""Email helper stubs — spec/011 zero-email deployment (Step 2 + Step 4 reduction).

This module historically wrapped the Resend SDK and shipped transactional
email for verification, password reset, login notifications, etc. As part
of spec/011 (zero-email deployment) the outbound-email surface is being
removed in favour of in-app banners (FR-011-008, FR-011-301..310).

Step 2 of the Implementation Phasing performed a conservative reduction
that left every helper compiling under a **silent-success** contract
(return ``None``) so callers + outbox dispatchers could continue to mark
work complete while the upstream producers awaited deletion. Step 4
(T403) goes one step further by deleting the
``send_2fa_reset_magic_link`` helper outright — its single caller
(``services.two_factor_reset_service.issue_magic_link``) no longer
invokes any email helper. The matching ``EmailDeliverySuppressed``
exception type is gone with it.

After Step 4 there is exactly **one** stub flavour:

* **Silent success** (return ``None``). Used by callers that have no
  rollback path tied to email delivery. The outbox dispatcher treats
  a returning handler as "success" and marks the outbox row complete,
  so producers like
  :meth:`services.email_verification_service.EmailVerificationService.issue_verification_token`
  do not accumulate dead-letter rows while the producer side awaits
  deletion in Step 10. Active members of this flavour:
  ``send_login_notification``, ``send_email_change_notification``,
  ``send_2fa_reset_dispatched``, ``send_api_key_revoke_email``,
  ``send_api_key_scope_degrade_email``, ``send_verification_email``,
  ``send_password_reset_email``.

The small text-handling helpers ``_safe_recipient_hash``,
``_sanitise_email_field``, and ``EmailHeaderInjectionError`` are
retained because they are imported from outside this module
(``workers/trusted_expiry_dispatcher.py`` reaches for
``_safe_recipient_hash``; the coverage-uplift test fixture
``tests/unit/services/test_email_service_coverage_uplift.py`` imports
all three).

Full rewrite of the silent-success stubs to the
``services.user_banner.enqueue_event`` surface lands in Phase 9 US7
(``tasks.md`` T610-T614). Until then, those stubs are intentionally
inert so a misconfigured deploy that still tries to dispatch a login
notification (or similar) silently no-ops rather than 5xx-ing on a
missing ``RESEND_API_KEY`` or a deleted helper.
"""

from __future__ import annotations

import logging
import unicodedata
from typing import Final

from echoroo.core.kms import compute_pii_hash
from echoroo.core.text import has_control_chars

logger = logging.getLogger(__name__)


def _safe_recipient_hash(value: str | None) -> str:
    """Return a non-PII surrogate for ``value`` suitable for log output.

    Retained because ``workers/trusted_expiry_dispatcher.py`` imports it
    directly to avoid spilling raw recipient addresses into log
    storage. The hashing path matches the pre-spec/011 implementation
    so any historical log line stays correlatable.
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


#: Hard cap for any user-controlled string that historically flowed
#: into email headers or bodies. Retained alongside
#: :func:`_sanitise_email_field` so dependent tests still load.
_EMAIL_FIELD_MAX_LEN: Final[int] = 500


class EmailHeaderInjectionError(ValueError):
    """Raised when an email field carries ASCII control characters.

    Retained for backwards compatibility with code that catches this
    error type. No production caller raises it after the Step 2
    reduction (the no-op stubs do not perform field sanitisation), but
    the type itself is preserved so existing ``except`` clauses keep
    compiling.
    """


def _sanitise_email_field(value: object, *, field_name: str) -> str:
    """NFKC-normalise, reject control chars, and truncate to a hard cap.

    Retained for the coverage-uplift unit tests that still exercise it.
    No production call path uses it after the Step 2 reduction.
    """
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


# ---------------------------------------------------------------------------
# No-op stubs (signatures preserved for in-tree call-sites)
#
# Every helper below is a Phase 9 US7 (``tasks.md`` T610-T614) target;
# it will be rewritten to enqueue an in-app banner audit event via
# ``services.user_banner``. Until then the stubs intentionally do
# nothing besides log a single deprecation-grade warning so operators
# can detect any caller that is still wired into the old email path.
# ---------------------------------------------------------------------------


async def send_login_notification(
    *,
    to: str,
    ip_hash: str,
    ua_hash: str,
    timestamp: str,
) -> None:
    """Stub for spec/011 zero-email deployment (Step 2 T100).

    The full rewrite to ``services.user_banner.enqueue_event`` lands in
    Phase 9 US7 (``tasks.md`` T610-T614). For now this is a no-op that
    logs a deprecation warning so call-sites can be left in place
    during the incremental refactor.

    Args:
        to: Recipient email address (unused; preserved for signature parity).
        ip_hash: HMAC-SHA256 hex of the client IP.
        ua_hash: HMAC-SHA256 hex of the User-Agent header.
        timestamp: ISO-8601 timestamp of the sign-in.
    """
    recipient_hash = _safe_recipient_hash(to)
    logger.warning(
        "send_login_notification stub invoked — see spec/011 §FR-011-008 / "
        "tasks.md T100. Caller will be rewritten to user_banner.enqueue_event "
        "in Phase 9 US7 (recipient_hash=%s, ip_hash=%s, ua_hash=%s, "
        "timestamp=%s)",
        recipient_hash,
        ip_hash,
        ua_hash,
        timestamp,
    )


async def send_email_change_notification(to: str) -> None:
    """Stub for spec/011 zero-email deployment (Step 2 T100).

    The full rewrite to ``services.user_banner.enqueue_event`` lands in
    Phase 9 US7 (``tasks.md`` T610-T614).

    Args:
        to: Previous recipient email address (unused; preserved for signature parity).
    """
    recipient_hash = _safe_recipient_hash(to)
    logger.warning(
        "send_email_change_notification stub invoked — see spec/011 §FR-011-008 / "
        "tasks.md T100. Caller will be rewritten to user_banner.enqueue_event "
        "in Phase 9 US7 (recipient_hash=%s)",
        recipient_hash,
    )


async def send_verification_email(to: str, token: str) -> None:
    """Stub for spec/011 zero-email deployment (Step 2 T100).

    The producer side
    :meth:`services.email_verification_service.EmailVerificationService.issue_verification_token`
    still enqueues an ``auth.email_verification.requested`` outbox row,
    which the (still-registered) outbox dispatcher
    :mod:`workers.email_verification_dispatcher` will hand back to
    this helper. Returning ``None`` lets the dispatcher mark the
    outbox row complete so we do not accumulate dead-letter retries
    while the email-verification subsystem awaits wholesale removal.

    Step 10 (US1) deletes the producer + dispatcher + this helper as
    one PR. Until then this is a silent no-op: a single warning log
    line is emitted so operators can spot any environment that is
    still configured to issue verification tokens (the verification
    feature flag should be off in every spec/011-deployed env).

    The raw ``token`` is **never** echoed (a verification token in
    logs is an account-takeover vector); only its length surfaces in
    the warning record alongside the hashed recipient surrogate.

    Args:
        to: Recipient email address (unused beyond the hashed log line).
        token: Plaintext verification token (length-logged only).
    """
    recipient_hash = _safe_recipient_hash(to)
    logger.warning(
        "send_verification_email stub invoked — see spec/011 §FR-011-008 / "
        "tasks.md T100. Email is silently suppressed; producer side will be "
        "removed in Step 10 (US1). "
        "(recipient_hash=%s, token_len=%d)",
        recipient_hash,
        len(token) if token else 0,
    )


async def send_password_reset_email(to: str, token: str) -> None:
    """Stub for spec/011 zero-email deployment (Step 2 T100).

    The producer is :func:`api.web_v1.auth.request_password_reset`
    (line ~1078) which enqueues ``event_type="password_reset_email"``
    into the outbox. No dispatcher is registered for that event in
    the current tree (pre-existing dead code — confirmed via
    ``grep "password_reset_email" apps/api/echoroo``), so this helper
    is not reached by any production path today. The stub exists
    purely as defence-in-depth: if a future change wires a dispatcher
    (or if the producer is invoked via a non-outbox path), the call
    will silently no-op rather than crash with ``AttributeError`` /
    ``NotImplementedError``.

    Step 10 (US1) deletes the producer + this helper as one PR.

    The raw ``token`` is **never** echoed (a password-reset token in
    logs is an account-takeover vector); only its length surfaces in
    the warning record alongside the hashed recipient surrogate.

    Args:
        to: Recipient email address (unused beyond the hashed log line).
        token: Plaintext password-reset token (length-logged only).
    """
    recipient_hash = _safe_recipient_hash(to)
    logger.warning(
        "send_password_reset_email stub invoked — see spec/011 §FR-011-008 / "
        "tasks.md T100. Email is silently suppressed; producer side will be "
        "removed in Step 10 (US1). "
        "(recipient_hash=%s, token_len=%d)",
        recipient_hash,
        len(token) if token else 0,
    )


async def send_2fa_reset_dispatched(
    to: str,
    *,
    dispatched_at_iso: str,
) -> None:
    """Stub for spec/011 zero-email deployment (Step 2 T100).

    The full rewrite to ``services.user_banner.enqueue_event`` lands in
    Phase 9 US7 (``tasks.md`` T610-T614).

    Args:
        to: Recipient email address (unused; preserved for signature parity).
        dispatched_at_iso: ISO-8601 timestamp the reset was applied.
    """
    recipient_hash = _safe_recipient_hash(to)
    logger.warning(
        "send_2fa_reset_dispatched stub invoked — see spec/011 §FR-011-008 / "
        "tasks.md T100. Caller will be rewritten to user_banner.enqueue_event "
        "in Phase 9 US7 (recipient_hash=%s, dispatched_at_iso=%s)",
        recipient_hash,
        dispatched_at_iso,
    )


async def send_api_key_revoke_email(
    *,
    to: str,
    api_key_prefix: str,
    created_at_iso: str,
    revoked_at_iso: str,
) -> None:
    """Stub for spec/011 zero-email deployment (Step 2 T100).

    The full rewrite to ``services.user_banner.enqueue_event`` lands in
    Phase 9 US7 (``tasks.md`` T610-T614).

    Args:
        to: Recipient email address (unused; preserved for signature parity).
        api_key_prefix: First-4 of the revoked key.
        created_at_iso: ISO-8601 timestamp the key was created.
        revoked_at_iso: ISO-8601 timestamp the key was revoked.
    """
    recipient_hash = _safe_recipient_hash(to)
    logger.warning(
        "send_api_key_revoke_email stub invoked — see spec/011 §FR-011-008 / "
        "tasks.md T100. Caller will be rewritten to user_banner.enqueue_event "
        "in Phase 9 US7 (recipient_hash=%s, prefix=%s, created_at_iso=%s, "
        "revoked_at_iso=%s)",
        recipient_hash,
        api_key_prefix,
        created_at_iso,
        revoked_at_iso,
    )


async def send_api_key_scope_degrade_email(
    *,
    to: str,
    api_key_prefix: str,
    created_at_iso: str,
    degraded_at_iso: str,
    grace_days_until_revoke: int,
) -> None:
    """Stub for spec/011 zero-email deployment (Step 2 T100).

    The full rewrite to ``services.user_banner.enqueue_event`` lands in
    Phase 9 US7 (``tasks.md`` T610-T614).

    Args:
        to: Recipient email address (unused; preserved for signature parity).
        api_key_prefix: First-4 of the affected key.
        created_at_iso: ISO-8601 timestamp the key was created.
        degraded_at_iso: ISO-8601 timestamp write-scope was stripped.
        grace_days_until_revoke: Days remaining before full revocation.
    """
    recipient_hash = _safe_recipient_hash(to)
    logger.warning(
        "send_api_key_scope_degrade_email stub invoked — see spec/011 "
        "§FR-011-008 / tasks.md T100. Caller will be rewritten to "
        "user_banner.enqueue_event in Phase 9 US7 "
        "(recipient_hash=%s, prefix=%s, created_at_iso=%s, degraded_at_iso=%s, "
        "grace_days_until_revoke=%s)",
        recipient_hash,
        api_key_prefix,
        created_at_iso,
        degraded_at_iso,
        grace_days_until_revoke,
    )
