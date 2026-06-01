"""Self-service password change service (spec/011 §FR-011-204 / US4 T320).

This is the inverse companion of
:mod:`echoroo.services.admin_password_reset`. Where the admin-reset
service *enters* the forced-change state (sets
``users.must_change_password = true`` + ``temp_password_expires_at =
now() + 24h`` after a superuser step-up), this service *exits* it: the
target user supplies their current credential (the live password OR the
admin-issued temporary password while it is still inside its TTL) plus a
new password, and on success:

1. Verifies ``current_password`` against ``users.password_hash`` via
   :func:`echoroo.core.security.verify_password`. Because the admin
   reset stored the temp password directly in ``password_hash`` (see
   :mod:`admin_password_reset` §2), a single constant-time hash check
   accepts BOTH the live password and the in-window temp password —
   there is no separate temp-password column.
2. Rejects the change when the account is in forced-change
   (``must_change_password = true``) AND the temp password has expired
   (``temp_password_expires_at <= now()``): per FR-011-203 / FR-011-209
   an expired temp password yields a generic invalid-credentials
   response and the superuser MUST re-issue.
3. Validates ``new_password`` against the shared
   :func:`echoroo.services.auth_service.enforce_password_policy`
   (NIST SP 800-63B + HIBP) — the SAME validator the registration flow
   uses, so the rules are not duplicated here.
4. Rejects reusing the current password (mirrors the legacy
   :meth:`echoroo.services.user.UserService.change_password`
   "must be different" rule).
5. Writes the new argon2 hash into ``users.password_hash``, clears the
   forced-change state (``must_change_password = false`` +
   ``temp_password_expires_at = NULL``), and rotates
   ``users.security_stamp``. The stamp rotation immediately invalidates
   every OTHER outstanding refresh-token / step-up-token for the user
   and triggers the
   :func:`echoroo.services.trusted_device_service._revoke_devices_on_security_stamp_rotation`
   ``before_flush`` listener (FR-055).
6. Explicitly calls :meth:`TrustedDeviceService.revoke_all_for_user`
   (defence in depth on top of the listener, with a stable reason
   code), mirroring :mod:`admin_password_reset` §5.
7. Emits an ``auth.password_changed`` platform audit row carrying ONLY
   ``user_id`` + ``forced_change`` — never the password values
   (FR-011-207 confidentiality invariant).

This service does NOT commit the surrounding transaction. The caller
owns ``await session.commit()`` so the password update, security-stamp
rotation, and trusted-device revocations land atomically. The audit row
is written in its own fresh session inside this module (the SERIALIZABLE
isolation upgrade is rejected once the caller's connection has run SQL —
identical constraint to :mod:`admin_password_reset`).

Both the BFF endpoint (``POST /web-api/v1/auth/change-password``) and
its v1 mirror (``POST /api/v1/auth/change-password``) call
:func:`change_password`, so the two surfaces behave identically by
construction.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.database import AsyncSessionLocal
from echoroo.core.security import hash_password, verify_password
from echoroo.models.user import User
from echoroo.services.audit_service import AuditLogService
from echoroo.services.auth_service import (
    DEFAULT_PASSWORD_POLICY,
    HibpChecker,
    PasswordPolicy,
    enforce_password_policy,
)
from echoroo.services.trusted_device_service import TrustedDeviceService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Audit-action constant (service-private per spec/011 §HANDOFF layering)
# ---------------------------------------------------------------------------

#: ``platform_audit_log.action`` string emitted on a successful
#: self-service password change. Distinct from the admin-reset actions
#: (``platform.user.password_reset_{by_superuser,self}``) so a forensic
#: query can tell apart "operator reset this user" from "the user picked
#: a new password themselves". Self-service changes are NOT classified as
#: destructive — they are a routine credential rotation — so this string
#: is intentionally absent from
#: :data:`echoroo.services.audit_service.DESTRUCTIVE_ACTIONS`.
AUDIT_ACTION_AUTH_PASSWORD_CHANGED: Final[str] = "auth.password_changed"

#: Reason code passed to :meth:`TrustedDeviceService.revoke_all_for_user`.
#: Matches the legacy :meth:`UserService.change_password` reason so the
#: two code paths converge on a single audit vocabulary. spec/011 T630
#: remapped the historical ``"password_changed"`` to the canonical
#: ``"password_change"`` (the member declared in
#: :data:`echoroo.services.trusted_device_service.REVOKE_ALL_REASONS`).
_TD_REVOKE_REASON: Final[str] = "password_change"


class EmailChangeCooldownActiveError(Exception):
    """The user is inside the 24-hour email-change cool-off (FR-011-305).

    During the window opened by a self-service email change, a
    self-service password change is rejected. The caller maps this to a
    409 with ``error_code=email_change_cooldown_active`` (OQ9).
    """

    def __init__(self, cooldown_until: datetime) -> None:
        super().__init__(
            "email change cool-off active; password change is blocked"
        )
        self.cooldown_until = cooldown_until


class CurrentPasswordMismatchError(Exception):
    """Supplied ``current_password`` does not match the stored hash.

    Also raised when the account is in forced-change and the temporary
    password has expired (FR-011-209) — the caller maps both to the same
    generic 401 so an attacker cannot distinguish "wrong password" from
    "temp password expired".
    """


class NewPasswordReusedError(Exception):
    """``new_password`` is identical to the current password."""


def _generate_security_stamp() -> str:
    """Return a fresh ``users.security_stamp`` value (VARCHAR(64)).

    Delegates to the admin-reset helper so the 64-char contract is
    enforced in exactly one place.
    """
    # Imported lazily to avoid a module-import cycle: admin_password_reset
    # imports nothing from this module, but keeping the dependency
    # one-directional and local makes the relationship obvious.
    from echoroo.services.admin_password_reset import (  # noqa: PLC0415
        _generate_security_stamp as _admin_stamp,
    )

    return _admin_stamp()


async def _write_audit_row(
    *,
    user_id: UUID,
    forced_change: bool,
    request_id: str,
    ip: str,
    user_agent: str,
) -> None:
    """Append the ``auth.password_changed`` row in a fresh AsyncSession.

    Soft-alert on failure (FR-088): the credential rotation has already
    committed by the time this runs, so a missing audit row must not
    surface as a hard error to the user. Mirrors
    :func:`echoroo.services.admin_password_reset._write_audit_row`.
    """
    detail: dict[str, Any] = {
        "user_id": str(user_id),
        "forced_change": forced_change,
    }
    try:
        async with AsyncSessionLocal() as audit_session:
            try:
                await AuditLogService(audit_session).write_platform_event(
                    actor_user_id=user_id,
                    action=AUDIT_ACTION_AUTH_PASSWORD_CHANGED,
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
            "%s audit write failed (FR-088 soft alert): user=%s error=%r",
            AUDIT_ACTION_AUTH_PASSWORD_CHANGED,
            user_id,
            exc,
        )


async def change_password(
    session: AsyncSession,
    *,
    user: User,
    current_password: str,
    new_password: str,
    hibp: HibpChecker | None = None,
    policy: PasswordPolicy = DEFAULT_PASSWORD_POLICY,
    now: datetime | None = None,
    request_id: str = "",
    ip: str = "",
    user_agent: str = "",
) -> None:
    """Change ``user``'s password and clear the forced-change flag.

    Args:
        session: Caller-owned AsyncSession. This service does NOT commit;
            the caller commits the surrounding transaction so the
            ``users`` row update + trusted-device revocations land
            atomically.
        user: The authenticated user changing their own password. Must
            be a live ORM instance attached to ``session`` (the BFF /
            v1 handlers resolve it via the ``CurrentUser`` dependency).
        current_password: The live password OR the admin-issued
            temporary password (accepted only while
            ``temp_password_expires_at > now()`` during forced-change).
        new_password: The candidate replacement. Validated against
            ``policy`` (+ optional ``hibp``).
        hibp: Optional HIBP checker; when provided the policy rejects
            breached passwords. The handlers pass the shared
            ``_hibp_checker``.
        policy: Password policy parameters (defaults to NIST 8-char).
        now: Injectable clock for the temp-password expiry check
            (tests). Defaults to ``datetime.now(UTC)``.
        request_id / ip / user_agent: Request-envelope context for the
            audit row.

    Raises:
        CurrentPasswordMismatchError: ``current_password`` is wrong, or
            the account is in forced-change with an expired temp
            password. The caller maps this to a generic 401.
        NewPasswordReusedError: ``new_password`` equals the current
            password. The caller maps this to 400.
        PasswordPolicyError: ``new_password`` fails the shared policy.
            The caller maps this to 422.
    """
    tick = now or datetime.now(UTC)

    # ---- 0. Email-change cool-off gate (FR-011-305 / T621) --------------
    #
    # A self-service email change opens a 24-hour cool-off that ALSO
    # blocks self-service password changes for the same user. The
    # operator recovery path (``admin_password_reset.reset_password``)
    # does NOT read this column and therefore bypasses the cool-off
    # (OQ10). The gate runs first so a cooled-off user gets the cool-off
    # error regardless of whether their current credential is correct.
    cooldown_until = user.email_change_cooldown_until
    if cooldown_until is not None:
        if cooldown_until.tzinfo is None:
            cooldown_until = cooldown_until.replace(tzinfo=UTC)
        if tick < cooldown_until:
            raise EmailChangeCooldownActiveError(cooldown_until)

    # ---- 1. Forced-change temp-password expiry gate (FR-011-209) --------
    #
    # The temp password lives in ``password_hash`` exactly like the live
    # password, so the hash check below cannot by itself tell whether the
    # supplied value is an *expired* temp password. We therefore reject
    # the change up-front when the account is in forced-change and the
    # temp window has lapsed — BEFORE the (constant-time) hash verify, so
    # an expired-temp user gets the same generic failure regardless of
    # whether they typed the (now stale) temp value correctly.
    if user.must_change_password and user.temp_password_expires_at is not None:
        expires_at = user.temp_password_expires_at
        if expires_at.tzinfo is None:
            # ``temp_password_expires_at`` is stored timezone-aware, but a
            # naive value (e.g. from a raw-SQL test fixture) is coerced to
            # UTC so the comparison below never raises.
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at <= tick:
            raise CurrentPasswordMismatchError(
                "temporary password expired; request a new admin reset"
            )

    # ---- 2. Verify the supplied current credential ----------------------
    #
    # Single constant-time check covers BOTH the live password and the
    # in-window temp password (the admin reset stored the temp value in
    # ``password_hash``). A mismatch is the generic 401 path.
    if not verify_password(current_password, user.password_hash):
        raise CurrentPasswordMismatchError("current password mismatch")

    # ---- 3. Reject reusing the current password -------------------------
    #
    # Mirrors the legacy ``UserService.change_password`` invariant. This
    # also blocks a forced-change user from "changing" to the temp
    # password they were just handed.
    if verify_password(new_password, user.password_hash):
        raise NewPasswordReusedError(
            "new password must be different from the current password"
        )

    # ---- 4. Enforce the shared password policy (raises on failure) ------
    await enforce_password_policy(new_password, policy=policy, hibp=hibp)

    # ---- 5. Apply the new credential + clear forced-change state --------
    forced_change = bool(user.must_change_password)
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    user.temp_password_expires_at = None
    user.updated_at = tick

    # ---- 6. Rotate ``security_stamp`` (FR-055 + FR-011-203) -------------
    #
    # Invalidates every OTHER outstanding session token and triggers the
    # trusted-device flush listener in trusted_device_service.
    user.security_stamp = _generate_security_stamp()
    session.add(user)
    await session.flush()

    # ---- 7. Defence-in-depth trusted-device revocation ------------------
    await TrustedDeviceService(session).revoke_all_for_user(
        user=user,
        reason=_TD_REVOKE_REASON,
    )

    # ---- 8. Audit (fresh session, soft-alert on failure) ----------------
    await _write_audit_row(
        user_id=user.id,
        forced_change=forced_change,
        request_id=request_id,
        ip=ip,
        user_agent=user_agent,
    )

    logger.info(
        "self-service password change user=%s forced_change=%s",
        user.id,
        forced_change,
    )


__all__ = [
    "AUDIT_ACTION_AUTH_PASSWORD_CHANGED",
    "CurrentPasswordMismatchError",
    "EmailChangeCooldownActiveError",
    "NewPasswordReusedError",
    "change_password",
]
