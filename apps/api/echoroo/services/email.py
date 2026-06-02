"""Email helper stubs — spec/011 zero-email deployment.

This module historically wrapped the Resend SDK and shipped transactional
email for verification, password reset, login notifications, etc. spec/011
(zero-email deployment) removes the outbound-email surface in favour of
in-app banners (FR-011-008, FR-011-301..310).

After Step 10 the module is intentionally retained per FR-011-008 ("The
module name may be retained or renamed to ``services/user_event.py``")
because:

* ``workers/trusted_expiry_dispatcher.py`` imports
  ``_safe_recipient_hash`` to keep recipient strings out of structured
  log lines.
* Phase 9 US7 (T610-T614) will rewrite the remaining silent-success
  stubs (``send_login_notification``, ``send_email_change_notification``,
  ``send_2fa_reset_dispatched``, ``send_api_key_revoke_email``,
  ``send_api_key_scope_degrade_email``) to enqueue audit-backed in-app
  banner events via ``services.user_banner.enqueue_event``.

The previously-included ``send_verification_email`` /
``send_password_reset_email`` stubs were removed in Step 10 alongside
the wholesale deletion of the email-verification + self-service
password-reset producers; the dispatcher / outbox event-types they
serviced are dead code in this commit.
"""

from __future__ import annotations

import logging
import unicodedata
from typing import Any, Final
from uuid import UUID

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
# In-app banner emitters (spec/011 US7, T610-T614)
#
# The former no-op email stubs are now thin wrappers around the
# in-app banner subsystem: each one writes a single ``platform_audit_log``
# row whose ``action`` is banner-eligible (see
# :data:`echoroo.services.user_banner.BANNER_ELIGIBLE_ACTIONS`) and whose
# ``detail`` carries ``target_user_id`` so the row surfaces to the
# *recipient* (not the actor) via ``user_banner.list_banners`` /
# ``list_activity``. The audit row itself IS the banner (the read side
# matches on ``detail->>'target_user_id'`` for non-self events).
#
# A-13 discipline: detail payloads carry only hashes / dates / non-PII
# enum values — NEVER a raw email address, API-key secret, or raw IP.
# The ``to`` parameter is retained on the signatures the call-sites
# already pass, but it is NEVER persisted; we only emit its non-PII
# surrogate hash into structured logs.
# ---------------------------------------------------------------------------


async def _emit_banner_audit(
    *,
    target_user_id: UUID,
    action: str,
    detail: dict[str, Any],
    actor_user_id: UUID | str | None = None,
    request_id: str = "",
) -> None:
    """Write a banner-eligible ``platform_audit_log`` row (fresh session).

    The :class:`AuditLogService` writer requires a *fresh* AsyncSession
    (the SERIALIZABLE upgrade + advisory lock are rejected once any SQL
    has run on the connection), so we open a dedicated session here and
    commit it independently — mirroring
    :func:`echoroo.services.admin_password_reset._write_audit_row` and
    :func:`echoroo.services.trusted_device_service._emit_revoke_all_audit`.

    ``target_user_id`` is ALWAYS injected into ``detail`` (overriding any
    caller-supplied value) because the banner read side keys off
    ``detail->>'target_user_id'`` for events whose actor is not the
    recipient (login dispatcher / worker-originated rows). Omitting it
    would make the banner silently never surface.

    Soft-alert on failure (FR-088): the originating state change has
    already committed by the time this runs, so a missing audit row must
    not bubble up as a hard error. We log a warning and continue.

    Note: the writer's ``ip`` / ``user_agent`` arguments are ALWAYS passed
    as ``""`` so the writer does not HMAC-hash anything into the
    ``ip_hash`` / ``user_agent_hash`` columns. Any pre-hashed IP / UA
    surrogate a caller wants to retain lives ONLY inside ``detail``
    (``detail.ip_hash`` / ``detail.ua_hash``) — passing the already-hashed
    value to the writer would produce a hash-of-a-hash. Mirrors
    :func:`echoroo.services.trusted_device_service._emit_revoke_all_audit`.
    """
    # Avoid a module-import cycle (audit_service imports nothing from
    # this module, but keeping the import local documents the one-way
    # dependency and matches the lazy-import convention used by the
    # admin-reset service).
    from echoroo.core.database import AsyncSessionLocal  # noqa: PLC0415
    from echoroo.services.audit_service import AuditLogService  # noqa: PLC0415

    payload = dict(detail)
    payload["target_user_id"] = str(target_user_id)
    try:
        async with AsyncSessionLocal() as audit_session:
            try:
                await AuditLogService(audit_session).write_platform_event(
                    actor_user_id=actor_user_id,
                    action=action,
                    request_id=request_id,
                    ip="",
                    user_agent="",
                    detail=payload,
                )
                await audit_session.commit()
            except Exception:
                await audit_session.rollback()
                raise
    except Exception as exc:  # noqa: BLE001 — soft alert
        logger.warning(
            "%s banner audit write failed (FR-088 soft alert): target=%s "
            "error=%r",
            action,
            target_user_id,
            exc,
        )


async def send_login_notification(
    *,
    to: str,
    user_id: UUID,
    ip_hash: str,
    ua_hash: str,
    timestamp: str,
    request_id: str = "",
) -> None:
    """Emit the new-device login banner (spec/011 US7 T610, FR-011-008).

    Args:
        to: Recipient email address — NEVER persisted; only its non-PII
            surrogate hash is logged.
        user_id: The user who signed in (banner recipient + actor).
        ip_hash: HMAC-SHA256 hex of the client IP.
        ua_hash: HMAC-SHA256 hex of the User-Agent header.
        timestamp: ISO-8601 timestamp of the sign-in.
        request_id: Request-envelope id for the audit row.
    """
    logger.info(
        "send_login_notification: emitting new-device banner "
        "(recipient_hash=%s, ip_hash=%s, ua_hash=%s, timestamp=%s)",
        _safe_recipient_hash(to),
        ip_hash,
        ua_hash,
        timestamp,
    )
    # The pre-hashed ``ip_hash`` / ``ua_hash`` surrogates are carried ONLY
    # inside ``detail`` — they are NOT forwarded to the audit writer's
    # ``ip`` / ``user_agent`` arguments, which would re-hash them into a
    # hash-of-a-hash in the ``ip_hash`` / ``user_agent_hash`` columns.
    await _emit_banner_audit(
        target_user_id=user_id,
        action="auth.login.new_device",
        actor_user_id=user_id,
        detail={
            "ip_hash": ip_hash,
            "ua_hash": ua_hash,
            "timestamp": timestamp,
        },
        request_id=request_id,
    )


async def send_email_change_notification(
    to: str,
    *,
    user_id: UUID,
    request_id: str = "",
) -> None:
    """Emit the email-change banner (spec/011 US7 T611, FR-011-008).

    Args:
        to: Previous recipient email address — NEVER persisted; only its
            non-PII surrogate hash is logged.
        user_id: The user whose email changed (banner recipient + actor).
        request_id: Request-envelope id for the audit row.
    """
    logger.info(
        "send_email_change_notification: emitting email-change banner "
        "(recipient_hash=%s)",
        _safe_recipient_hash(to),
    )
    await _emit_banner_audit(
        target_user_id=user_id,
        action="platform.user.email_changed",
        actor_user_id=user_id,
        detail={},
        request_id=request_id,
    )


async def send_2fa_reset_dispatched(
    to: str,
    *,
    user_id: UUID,
    dispatched_at_iso: str,
    actor_user_id: UUID | str | None = None,
    request_id: str = "",
) -> None:
    """Emit the admin-2FA-reset banner (spec/011 US7 T612, FR-011-008).

    Args:
        to: Recipient email address — NEVER persisted; only its non-PII
            surrogate hash is logged.
        user_id: The user whose 2FA was reset (banner recipient).
        dispatched_at_iso: ISO-8601 timestamp the reset was applied.
        actor_user_id: The superuser who initiated the reset; the
            recipient (``user_id``) is the banner target via
            ``detail.target_user_id``.
        request_id: Request-envelope id for the audit row.
    """
    logger.info(
        "send_2fa_reset_dispatched: emitting 2FA-reset banner "
        "(recipient_hash=%s, dispatched_at_iso=%s)",
        _safe_recipient_hash(to),
        dispatched_at_iso,
    )
    await _emit_banner_audit(
        target_user_id=user_id,
        action="platform.user.two_factor_reset_by_superuser",
        actor_user_id=actor_user_id,
        detail={"dispatched_at": dispatched_at_iso},
        request_id=request_id,
    )


async def send_api_key_revoke_email(
    *,
    to: str,
    user_id: UUID,
    api_key_prefix: str,
    created_at_iso: str,
    revoked_at_iso: str,
    request_id: str = "",
) -> None:
    """Emit the API-key-revoke banner (spec/011 US7 T613/T614, FR-011-008).

    Args:
        to: Recipient email address — NEVER persisted; only its non-PII
            surrogate hash is logged.
        user_id: The key owner (banner recipient).
        api_key_prefix: First-4 of the revoked key (non-secret prefix).
        created_at_iso: ISO-8601 timestamp the key was created.
        revoked_at_iso: ISO-8601 timestamp the key was revoked.
        request_id: Request-envelope id for the audit row.
    """
    logger.info(
        "send_api_key_revoke_email: emitting api-key-revoke banner "
        "(recipient_hash=%s, prefix=%s, created_at_iso=%s, revoked_at_iso=%s)",
        _safe_recipient_hash(to),
        api_key_prefix,
        created_at_iso,
        revoked_at_iso,
    )
    await _emit_banner_audit(
        target_user_id=user_id,
        action="platform.api_key.revoke",
        actor_user_id=None,
        detail={
            "api_key_prefix": api_key_prefix,
            "created_at": created_at_iso,
            "revoked_at": revoked_at_iso,
        },
        request_id=request_id,
    )


async def send_api_key_scope_degrade_email(
    *,
    to: str,
    user_id: UUID,
    api_key_prefix: str,
    created_at_iso: str,
    degraded_at_iso: str,
    grace_days_until_revoke: int,
    request_id: str = "",
) -> None:
    """Emit the API-key-scope-degrade banner (spec/011 US7 T613, FR-011-008).

    The ``platform.api_key.scope_degrade`` action is NOT in the
    banner-eligible enum (OQ6 keeps the contract enum unchanged in this
    slice), so this row surfaces in ``/me/activity`` but not as a
    standalone banner — which is the intended behaviour for the
    degrade-grace event.

    Args:
        to: Recipient email address — NEVER persisted; only its non-PII
            surrogate hash is logged.
        user_id: The key owner (banner recipient).
        api_key_prefix: First-4 of the affected key (non-secret prefix).
        created_at_iso: ISO-8601 timestamp the key was created.
        degraded_at_iso: ISO-8601 timestamp write-scope was stripped.
        grace_days_until_revoke: Days remaining before full revocation.
        request_id: Request-envelope id for the audit row.
    """
    logger.info(
        "send_api_key_scope_degrade_email: emitting scope-degrade event "
        "(recipient_hash=%s, prefix=%s, created_at_iso=%s, degraded_at_iso=%s, "
        "grace_days_until_revoke=%s)",
        _safe_recipient_hash(to),
        api_key_prefix,
        created_at_iso,
        degraded_at_iso,
        grace_days_until_revoke,
    )
    await _emit_banner_audit(
        target_user_id=user_id,
        action="platform.api_key.scope_degrade",
        actor_user_id=None,
        detail={
            "api_key_prefix": api_key_prefix,
            "created_at": created_at_iso,
            "degraded_at": degraded_at_iso,
            "grace_days_until_revoke": grace_days_until_revoke,
        },
        request_id=request_id,
    )
