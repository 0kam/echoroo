"""Self-service account soft-delete (Phase 14 / T901, FR-105 / FR-109).

Anonymises the ``users`` row in place so first-party PII (email,
display name, 2FA secrets, password hash) cannot be re-personalised
after a GDPR Subject Erasure Request, while keeping the immutable
``users.id`` PK so downstream rows that carry the user as a foreign
key (``project_members``, ``annotation_votes``,
``project_invitations.invited_by_id``,
``project_audit_log.actor_user_id_hash`` resolve target …) keep
referential integrity. The PII the user actually owns lives on the
``users`` row itself; the audit log is keyed by HMAC hashes
(FR-091a / FR-091b) so it does not need cascading.

Sentinel pattern
----------------
The ``users`` table declares ``email`` and ``password_hash`` as
``NOT NULL`` (and ``email`` UNIQUE). Rather than running a schema
migration we anonymise to fixed sentinel values:

* ``email``         → ``deleted_<32-hex>@deleted.echoroo.invalid``
                       — UNIQUE-safe. The 32-character local part is
                       the **full** ``users.id`` UUID hex (128 bits
                       of entropy); a hypothetical collision sits at
                       ~3.4×10^38, so the constraint cannot fire on
                       any realistic account count. Determinism makes
                       the sentinel idempotent: replaying the
                       soft-delete on an already-anonymised row
                       reproduces the exact same address.
* ``display_name``  → ``"[deleted user]"``.
* ``password_hash`` → ``"$deleted$"`` (a non-Argon2 prefix that
                       :func:`echoroo.services.auth.verify_password`
                       always rejects).
* ``two_factor_secret_encrypted``        → ``NULL``.
* ``two_factor_secret_dek_version``      → ``NULL``.
* ``two_factor_backup_codes_hashed``     → ``NULL``.
* ``two_factor_enabled``                 → ``False``.
* ``security_stamp``                     → fresh 64-char token so
                                             every existing access /
                                             refresh token bound to
                                             the row is invalidated
                                             immediately (FR-055
                                             rotation pattern).
* ``deleted_at``                         → ``now()``.

The auth layer already short-circuits ``users.deleted_at IS NOT NULL``
in :mod:`echoroo.services.auth` and
:mod:`echoroo.services.session_verification` so a stale cookie
forwarded after deletion lands on a 401 / re-auth flow.

Audit session contract (Phase 13 P1 R3)
---------------------------------------
:class:`AuditLogService` issues
``SET TRANSACTION ISOLATION LEVEL SERIALIZABLE`` as the very first
statement on its session. We follow the
:mod:`echoroo.services.superuser_approval_service` /
:mod:`echoroo.services.ownership_service` pattern: mutate the
``users`` row inside the caller-owned :class:`AsyncSession`, return a
:class:`UserSoftDeleteOutcome` capturing the audit envelope, and
defer the platform-scope audit insert to
:func:`trigger_post_commit_audit` which spins up a fresh
:class:`AsyncSessionLocal`. Failures are warning-logged so a flaky
audit chain never rolls back a successful deletion (FR-088 soft-alert
posture).
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.database import AsyncSessionLocal
from echoroo.models.user import User
from echoroo.services.audit_service import AuditLogService
from echoroo.services.trusted_device_service import TrustedDeviceService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Audit constants
# ---------------------------------------------------------------------------

#: Platform-scope audit action recorded against the deletion. Stable
#: literal — ops dashboards group by ``action`` so renaming this is
#: effectively a breaking change for log queries.
AUDIT_ACTION_USER_SELF_DELETE: str = "user.self_delete"


# ---------------------------------------------------------------------------
# Sentinels
# ---------------------------------------------------------------------------

#: Non-Argon2 prefix that ``verify_password`` always rejects. Kept as a
#: module-level constant so the test fixtures can assert against it.
_PASSWORD_SENTINEL: str = "$deleted$"

#: Replacement for ``display_name``. The square brackets make the
#: sentinel visually distinct in admin tooling that surfaces names
#: without further sanitisation.
_DISPLAY_NAME_SENTINEL: str = "[deleted user]"

#: Synthetic local part width. We use the FULL 32-character UUID
#: hex so the sentinel inherits the source ``users.id``'s 128-bit
#: entropy. A truncated prefix (the original 8-char form) collided
#: at the birthday bound of ~65 K accounts — well inside the lifetime
#: of a successful platform — and would have surfaced as a 500 from
#: the ``users_email_key`` UNIQUE constraint. The full hex pushes the
#: collision probability to ~3.4×10^38, i.e. effectively zero.
_SENTINEL_HEX_WIDTH: int = 32

#: Suffix used to build the sentinel email address. ``.invalid`` is
#: reserved by RFC 6761 §6.4 so the address can never be a real
#: routable mailbox.
_SENTINEL_EMAIL_SUFFIX: str = "@deleted.echoroo.invalid"


def _build_sentinel_email(user_id: UUID) -> str:
    """Return the deterministic sentinel email for a user.

    The local part is the **full** 32-character ``users.id`` UUID hex
    (``_SENTINEL_HEX_WIDTH``). Using the full hex inherits the row's
    own 128-bit entropy (collision ~3.4×10^38) so the
    ``users_email_key`` UNIQUE constraint cannot fire on any realistic
    account count — a previous truncated 8-char prefix collided at
    the ~65 K birthday bound and could have surfaced a 500 from the
    delete endpoint. Determinism makes the operation idempotent:
    retrying a soft-delete on an already-deleted row reproduces the
    exact same sentinel.
    """
    prefix = user_id.hex[:_SENTINEL_HEX_WIDTH]
    return f"deleted_{prefix}{_SENTINEL_EMAIL_SUFFIX}"


# ---------------------------------------------------------------------------
# Outcome dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UserSoftDeleteOutcome:
    """Result of :func:`soft_delete_user`.

    The caller commits the main transaction first, then passes this
    outcome to :func:`trigger_post_commit_audit` which writes the
    ``platform_audit_log`` row in a fresh session.
    """

    user_id: UUID
    deleted_at: datetime
    request_id: str = ""
    ip: str = ""
    user_agent: str = ""
    audit_detail: dict[str, Any] = field(default_factory=dict)


class UserAlreadyDeletedError(RuntimeError):
    """Raised when ``soft_delete_user`` is called on a row that already has ``deleted_at`` set."""


class UserNotFoundError(RuntimeError):
    """Raised when ``soft_delete_user`` cannot locate the target user row."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def soft_delete_user(
    session: AsyncSession,
    *,
    user_id: UUID,
    request_id: str = "",
    ip: str = "",
    user_agent: str = "",
) -> UserSoftDeleteOutcome:
    """Anonymise the ``users`` row for ``user_id`` (FR-105).

    Args:
        session: Caller-owned :class:`AsyncSession`. The caller MUST
            ``await session.commit()`` after the function returns and
            then invoke :func:`trigger_post_commit_audit` so the audit
            row is written from a fresh session.
        user_id: PK of the user to soft-delete.
        request_id / ip / user_agent: Audit envelope captured for the
            ``platform_audit_log`` row.

    Returns:
        :class:`UserSoftDeleteOutcome` capturing the deletion timestamp
        and the audit envelope so the post-commit hook can write the
        platform-scope audit row in a fresh session.

    Raises:
        UserNotFoundError: if no row matches ``user_id``.
        UserAlreadyDeletedError: if the row already has ``deleted_at``
            stamped. The endpoint should treat this as a 401 since the
            auth middleware would have already rejected the session.
    """
    now = datetime.now(UTC)

    stmt = (
        sa.select(User)
        .where(User.id == user_id)
        .with_for_update()
    )
    user = (await session.execute(stmt)).scalar_one_or_none()
    if user is None:
        raise UserNotFoundError(f"user {user_id} not found")
    if user.deleted_at is not None:
        raise UserAlreadyDeletedError(
            f"user {user_id} already deleted at {user.deleted_at.isoformat()}"
        )

    sentinel_email = _build_sentinel_email(user_id)

    user.email = sentinel_email
    user.display_name = _DISPLAY_NAME_SENTINEL
    user.password_hash = _PASSWORD_SENTINEL
    user.two_factor_secret_encrypted = None
    user.two_factor_secret_dek_version = None
    user.two_factor_backup_codes_hashed = None
    user.two_factor_enabled = False
    # ``security_stamp`` is the FR-055 invalidation knob — rotating it
    # immediately revokes every refresh-token family + access token
    # whose claims include the previous stamp.
    user.security_stamp = secrets.token_hex(32)
    user.deleted_at = now
    user.updated_at = now
    revoked_trusted_devices = await TrustedDeviceService(session).revoke_all_for_user(
        user=user,
        reason="user_deleted",
    )

    audit_detail: dict[str, Any] = {
        "user_id": str(user_id),
        "deleted_at": now.isoformat(),
        "trusted_devices_revoked": revoked_trusted_devices,
    }

    return UserSoftDeleteOutcome(
        user_id=user_id,
        deleted_at=now,
        request_id=request_id,
        ip=ip,
        user_agent=user_agent,
        audit_detail=audit_detail,
    )


async def trigger_post_commit_audit(outcome: UserSoftDeleteOutcome) -> None:
    """Write the ``platform_audit_log`` row for a self-delete outcome.

    Mirrors :func:`echoroo.services.superuser_approval_service.trigger_apply_post_commit_audit`:
    the writer needs a fresh :class:`AsyncSessionLocal` because
    :class:`AuditLogService` issues
    ``SET TRANSACTION ISOLATION LEVEL SERIALIZABLE`` as the FIRST
    statement on its connection. Failures are WARNING-logged so a
    flaky audit chain never rolls back the persisted deletion (FR-088
    soft-alert posture).
    """
    try:
        async with AsyncSessionLocal() as audit_session:
            try:
                # The actor IS the deleted user — we record their (now
                # anonymised) UUID in ``actor_user_id`` so the
                # downstream FR-091 keyed hash matches every other
                # platform_audit_log row keyed on ``users.id``. The
                # row itself carries no raw PII (email / display name
                # are not in the detail), satisfying FR-091a.
                await AuditLogService(audit_session).write_platform_event(
                    actor_user_id=outcome.user_id,
                    action=AUDIT_ACTION_USER_SELF_DELETE,
                    request_id=outcome.request_id,
                    ip=outcome.ip,
                    user_agent=outcome.user_agent,
                    detail=outcome.audit_detail,
                    created_at=outcome.deleted_at,
                )
                await audit_session.commit()
            except Exception:
                await audit_session.rollback()
                raise
    except Exception as exc:  # noqa: BLE001 — soft alert; never blocks domain mutation
        logger.warning(
            "%s platform_audit_log write failed (FR-088 soft alert): "
            "user_id=%s error=%r",
            AUDIT_ACTION_USER_SELF_DELETE,
            outcome.user_id,
            exc,
        )


__all__ = [
    "AUDIT_ACTION_USER_SELF_DELETE",
    "UserAlreadyDeletedError",
    "UserNotFoundError",
    "UserSoftDeleteOutcome",
    "soft_delete_user",
    "trigger_post_commit_audit",
]
