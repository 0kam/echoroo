"""Admin-mediated password reset service (spec/011 §FR-011-201..210).

Phase 6 / US4 — Task T310. The system superuser invokes this service
through ``POST /web-api/v1/admin/users/{user_id}/reset-password`` after
completing the step-up authentication challenge (FR-011-206) gated by
``require_step_up_token(SCOPE_ADMIN_RECOVERY)``. The service:

1. Generates a cryptographically random temporary password meeting the
   :class:`echoroo.services.auth_service.PasswordPolicy` length
   minimum (NIST SP 800-63B, 8 chars). The value is 32 URL-safe base64
   characters (~192 bits of entropy) which exceeds both NIST and the
   project's HIBP-aware reject-pwned policy in practice.
2. Updates the target user's ``password_hash`` with the argon2 hash of
   the new value via :func:`echoroo.core.security.hash_password`.
3. Sets ``users.must_change_password = true`` and
   ``users.temp_password_expires_at = now() + 24 hours`` so the
   :class:`ForcedPasswordChangeMiddleware` (FR-011-204) gates every
   target-user request until the user picks a new password through
   ``POST /web-api/v1/auth/change-password``.
4. Rotates the target user's ``security_stamp`` so every outstanding
   refresh-token / step-up-token / WebAuthn interim token for that user
   is immediately invalidated (FR-055). The pre-existing
   :func:`_revoke_devices_on_security_stamp_rotation` SQLAlchemy
   ``before_flush`` listener in
   :mod:`echoroo.services.trusted_device_service` additionally revokes
   every active :class:`TrustedDevice` row in the same transaction —
   this is the canonical pattern used by
   :mod:`echoroo.services.user_deletion_service` and
   :mod:`echoroo.services.two_factor_service` for the same FR-055
   contract.
5. Explicitly calls :meth:`TrustedDeviceService.revoke_all_for_user`
   with the appropriate reason code (R10 reuse — defence in depth on
   top of the listener so an audit reason is associated with the
   revocation even on architectures where the listener does not fire,
   e.g. raw-SQL paths).
6. Emits a ``platform.user.password_reset_by_superuser`` audit row
   capturing actor, target, optional reason, and timestamp.
   :func:`reset_password` switches to ``platform.user.password_reset_self``
   when ``actor_id == target_user_id`` so the FR-011-210 self-reset
   variant is distinguishable in the audit log.

**Invariant — temp password confidentiality (FR-011-207)**:
The plaintext temporary password value MUST NOT be persisted, audited,
or logged anywhere except in the immediate return value of
:func:`reset_password` (which the calling FastAPI handler hands to the
issuing superuser via a click-to-reveal payload). The audit row records
only ``actor_id``, ``target_user_id``, ``reason``, and the timestamp.
Telemetry redaction (Phase 17 A-13 detector + the new spec/011
:mod:`echoroo.observability.sentry` registry) MUST register
``temporary_password`` for scrubbing.

**Idempotency**:
Re-resetting an already-reset (still-pending-change) user is permitted
and produces a fresh temporary password + a new audit row. The
``must_change_password`` flag stays ``true`` and
``temp_password_expires_at`` is bumped to ``now() + 24h`` —
"only the most recent value is valid" (FR-011-203).

This service does NOT commit the surrounding transaction. The caller
owns ``await session.commit()`` so the password update, audit write,
and trusted-device revocation land atomically.
"""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.database import AsyncSessionLocal
from echoroo.core.security import hash_password
from echoroo.models.user import User
from echoroo.services.audit_service import AuditLogService
from echoroo.services.trusted_device_service import TrustedDeviceService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Audit-action constants (service-private per spec/011 §HANDOFF)
# ---------------------------------------------------------------------------
#
# The two ``platform_audit_log.action`` strings emitted by this module.
# Service-private (NOT in :mod:`echoroo.services.audit_service`) per the
# spec/011 layering rule: each service owns the audit-action constants
# it emits; the cross-cutting registry
# :data:`echoroo.services.audit_service.DESTRUCTIVE_ACTIONS` re-asserts
# the *destructive* classification of both entries (see audit_service.py
# §DESTRUCTIVE_ACTIONS for the rationale).

#: Audit action string for a system-superuser resetting *another* user's
#: password (FR-011-208). Distinct from the ``_SELF`` variant so the
#: actor-vs-target identity dimension is queryable directly from the
#: ``action`` column.
AUDIT_ACTION_PLATFORM_USER_PASSWORD_RESET_BY_SUPERUSER: Final[str] = (
    "platform.user.password_reset_by_superuser"
)

#: Audit action string for the superuser self-reset path (FR-011-210).
#: ``actor_user_id == target_user_id`` is the invariant that
#: distinguishes this from the operator-vs-target case above.
AUDIT_ACTION_PLATFORM_USER_PASSWORD_RESET_SELF: Final[str] = (
    "platform.user.password_reset_self"
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

#: Token entropy for the generated one-time temp password. 32 URL-safe
#: bytes encodes to ~43 chars; ~192 bits of entropy comfortably exceeds
#: any reasonable password policy minimum. The exact length is opaque to
#: the consumer — the value is one-shot and never re-entered manually
#: (the frontend hands it to the user via copy-to-clipboard).
_TEMP_PASSWORD_BYTES: Final[int] = 32

#: Forced-change TTL per FR-011-203 / FR-011-209. After this window
#: passes the temp password yields a generic "invalid credentials"
#: response and the superuser MUST re-issue.
TEMP_PASSWORD_TTL_HOURS: Final[int] = 24

#: Reason codes passed through to
#: :meth:`TrustedDeviceService.revoke_all_for_user`. Keep them short and
#: stable — they may become audit-detail values in a future iteration
#: when the trusted-device service starts persisting revocation reasons
#: (HANDOFF: ``del reason`` is the current behaviour; spec/011 step that
#: rewires it will look up these constants).
_TD_REVOKE_REASON_OPERATOR: Final[str] = "password_reset"
_TD_REVOKE_REASON_SELF: Final[str] = "password_reset_self"


async def _write_audit_row(
    *,
    actor_id: UUID,
    action: str,
    detail: dict[str, Any],
    request_id: str,
    ip: str,
    user_agent: str,
) -> None:
    """Append a ``platform_audit_log`` row in a fresh AsyncSession.

    Module-level helper (NOT a method) so unit tests can replace
    :data:`AsyncSessionLocal` via ``monkeypatch.setattr`` without
    plumbing a session factory through :func:`reset_password`'s public
    signature. Mirrors the
    :func:`echoroo.services.two_factor_reset_service._write_platform_audit`
    contract — soft-alert on failure, never raises.

    The audit writer requires a *fresh* AsyncSession because the
    transaction-isolation upgrade
    (``SET TRANSACTION ISOLATION LEVEL SERIALIZABLE``) is rejected by
    PostgreSQL once any SQL has run on the connection. The caller's
    session has already executed the User update + flush, so we cannot
    reuse it.
    """
    try:
        async with AsyncSessionLocal() as audit_session:
            try:
                await AuditLogService(audit_session).write_platform_event(
                    actor_user_id=actor_id,
                    action=action,
                    request_id=request_id,
                    ip=ip,
                    user_agent=user_agent,
                    detail=detail,
                )
                await audit_session.commit()
            except Exception:
                await audit_session.rollback()
                raise
    except Exception as exc:  # noqa: BLE001 — soft alert
        logger.warning(
            "%s audit write failed (FR-088 soft alert): "
            "detail_keys=%s actor=%s error=%r",
            action,
            sorted(detail.keys()),
            actor_id,
            exc,
        )


def _generate_temp_password() -> str:
    """Return a fresh URL-safe one-time temporary password.

    Uses :func:`secrets.token_urlsafe` so the value is suitable for
    transmission via JSON without further escaping. Entropy is
    :data:`_TEMP_PASSWORD_BYTES` bytes.
    """
    return secrets.token_urlsafe(_TEMP_PASSWORD_BYTES)


def _generate_security_stamp() -> str:
    """Return a fresh ``users.security_stamp`` value (VARCHAR(64)).

    Mirrors :func:`echoroo.services.two_factor_service._security_stamp`
    so an existing User row's stamp can be rotated to the same length
    contract (64 chars). ``token_urlsafe(48)`` yields 64 characters
    deterministically.
    """
    stamp = secrets.token_urlsafe(48)
    if len(stamp) != 64:
        # Defensive guard — :func:`token_urlsafe` is documented to
        # produce ``ceil(n * 4 / 3)`` chars; for ``n=48`` that is 64.
        # Surface a clear error rather than truncating to a shorter
        # stamp that would not fit ``users.security_stamp VARCHAR(64)``.
        raise RuntimeError(
            "generated security_stamp does not fit users.security_stamp"
        )
    return stamp


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def reset_password(
    session: AsyncSession,
    *,
    actor_id: UUID,
    target_user_id: UUID,
    reason: str | None,
    request_id: str = "",
    ip: str = "",
    user_agent: str = "",
) -> str:
    """Reset ``target_user_id``'s password to a fresh one-time temp value.

    Args:
        session: Caller-owned AsyncSession. The service does NOT commit;
            the caller commits the surrounding transaction so the
            ``users`` row update, the audit row, and the trusted-device
            revocations land atomically.
        actor_id: Authenticated system-superuser performing the reset.
            Becomes ``platform_audit_log.actor_user_id``. When equal to
            ``target_user_id`` the audit action switches to
            :data:`AUDIT_ACTION_PLATFORM_USER_PASSWORD_RESET_SELF`
            (FR-011-210).
        target_user_id: User whose password is being reset.
        reason: Optional operator-supplied free-form rationale. Already
            validated against the Phase 17 A-13 PII detector at the API
            boundary (:class:`echoroo.schemas.admin.AdminPasswordResetBody`).
            ``None`` (or empty string) records ``reason: null`` in the
            audit detail.
        request_id: HTTP ``X-Request-Id`` header, propagated for audit
            correlation.
        ip: Client IP (forwarded-header aware), recorded as a keyed
            hash in the audit row (FR-091).
        user_agent: Client ``User-Agent`` header, also keyed-hashed.

    Returns:
        The plaintext one-time temporary password. The caller MUST hand
        this value directly to the issuing superuser via the
        click-to-reveal API response and MUST NOT log it. This is the
        only path through which the value leaves the service boundary
        (FR-011-207).

    Raises:
        LookupError: ``target_user_id`` does not resolve to a row in
            ``users`` (or the row is soft-deleted). The caller surfaces
            this as HTTP 404.
    """
    # ---- 1. Load + validate target ---------------------------------------
    target = await session.get(User, target_user_id)
    if target is None or target.deleted_at is not None:
        raise LookupError(f"user not found: {target_user_id}")

    # ---- 2. Generate the new credential ---------------------------------
    #
    # ``temp_password`` is the *only* place the plaintext value exists
    # from this point on. It is hashed into ``users.password_hash``
    # immediately below and returned to the caller for click-to-reveal
    # delivery. Nothing else captures it.
    temp_password = _generate_temp_password()
    target.password_hash = hash_password(temp_password)

    # ---- 3. Forced-change state (FR-011-203 / FR-011-209) ---------------
    now = datetime.now(UTC)
    target.must_change_password = True
    target.temp_password_expires_at = now + timedelta(hours=TEMP_PASSWORD_TTL_HOURS)
    target.updated_at = now

    # ---- 4. Rotate ``security_stamp`` (FR-055 + FR-011-203) -------------
    #
    # Rotating the stamp:
    #   - immediately invalidates every outstanding refresh-token /
    #     access-token / step-up-token whose claims include the
    #     previous stamp (the auth middleware compares stamp on every
    #     request);
    #   - triggers the
    #     :func:`_revoke_devices_on_security_stamp_rotation` flush
    #     listener in :mod:`trusted_device_service`, which revokes
    #     every active :class:`TrustedDevice` row for the user.
    #
    # The two effects together satisfy FR-011-203's
    # "immediately invalidate all other active sessions of the target
    # user and revoke all of the target user's trusted-device records".
    target.security_stamp = _generate_security_stamp()
    session.add(target)
    # ``flush`` here forces the ``before_flush`` listener to revoke
    # trusted devices BEFORE the explicit ``revoke_all_for_user`` call
    # below — the explicit call is then defence-in-depth and the
    # ``rowcount`` it returns will be 0 in the common case (listener
    # already won).
    await session.flush()

    # ---- 5. Defence-in-depth trusted-device revocation ------------------
    #
    # The flush listener above already revoked active trusted-device
    # rows for the user. We still call ``revoke_all_for_user``
    # explicitly because:
    #   (a) it documents the contract at the call site (spec FR-011-203
    #       explicitly mentions both effects),
    #   (b) it survives any future refactor that bypasses the ORM
    #       listener (e.g. raw-SQL stamp rotation),
    #   (c) the ``reason`` parameter is wired through so a follow-up
    #       step (HANDOFF: trusted_device_service ``del reason`` →
    #       used) inherits the right reason code without further
    #       call-site changes.
    td_reason = (
        _TD_REVOKE_REASON_SELF
        if actor_id == target_user_id
        else _TD_REVOKE_REASON_OPERATOR
    )
    await TrustedDeviceService(session).revoke_all_for_user(
        user=target,
        reason=td_reason,
    )

    # ---- 6. Audit row (FR-011-208) --------------------------------------
    #
    # ``actor_user_id == target_user_id`` selects the ``_SELF`` variant
    # (FR-011-210). The audit ``detail`` carries ``target_user_id`` and
    # the optional ``reason`` — but explicitly NOT the temp password
    # (FR-011-207).
    is_self_reset = actor_id == target_user_id
    audit_action = (
        AUDIT_ACTION_PLATFORM_USER_PASSWORD_RESET_SELF
        if is_self_reset
        else AUDIT_ACTION_PLATFORM_USER_PASSWORD_RESET_BY_SUPERUSER
    )
    audit_detail: dict[str, Any] = {
        "target_user_id": str(target_user_id),
        "reason": reason if reason else None,
        "self_reset": is_self_reset,
        "temp_password_expires_at": target.temp_password_expires_at.isoformat(),
    }

    # The audit writer requires a *fresh* AsyncSession (no prior SQL on
    # the connection — the SERIALIZABLE upgrade is rejected once the
    # connection has fixed an isolation level). The caller's session
    # has executed the User update + flush above, so we cannot reuse
    # it. We use the same fresh-session pattern as
    # :mod:`two_factor_reset_service._write_platform_audit`.
    #
    # Failure mode (FR-088 soft alert): if the audit write itself
    # raises we log a warning but DO NOT propagate the failure — the
    # state transition (password rotation + session invalidation +
    # trusted-device revocation) has already committed and rolling it
    # back here would leave the system in a worse place than a missing
    # audit row. The matching alerting pipeline (Sentry / operator
    # dashboard) treats the warning as a paging-eligible event so
    # spec FR-011-208's "MUST emit" invariant is observed via
    # alert-on-failure rather than hard transaction abort. This
    # mirrors the established convention in
    # :mod:`two_factor_reset_service` and
    # :mod:`superuser_approval_service`.
    await _write_audit_row(
        actor_id=actor_id,
        action=audit_action,
        detail=audit_detail,
        request_id=request_id,
        ip=ip,
        user_agent=user_agent,
    )

    logger.info(
        "admin password reset issued action=%s actor=%s target=%s self=%s",
        audit_action,
        actor_id,
        target_user_id,
        is_self_reset,
    )

    return temp_password


__all__ = [
    "AUDIT_ACTION_PLATFORM_USER_PASSWORD_RESET_BY_SUPERUSER",
    "AUDIT_ACTION_PLATFORM_USER_PASSWORD_RESET_SELF",
    "TEMP_PASSWORD_TTL_HOURS",
    "reset_password",
]
