"""Admin 2FA reset workflow service (Phase 17 backlog A-11).

This module owns the entire lifecycle of the support-initiated 2FA
reset described in FR-072 / PHASE17_BACKLOG.md A-11:

* Magic-link issuance + redeem (drives the 4-factor identity proof).
* ``two_factor_reset_requests`` row creation (delayed-dispatch state
  machine), with optional M-of-N approval branch when
  ``skip_delay=True``.
* Beat-poller dispatch (``run_dispatch_due_requests``) that picks up
  rows where ``dispatch_at <= now()`` and finally clears the user's
  2FA state via the existing
  :func:`echoroo.services.two_factor_service.TwoFactorService.reset_user_two_factor`
  primitive.
* Expiry / cancellation passes for rows the dispatcher should NOT
  apply (user re-enabled 2FA in the meantime, ticket sat past
  ``expires_at`` etc.).

Audit philosophy
================
Every state transition writes a ``platform_audit_log`` row through
:class:`AuditLogService` (FR-089 / FR-111). Audit failures are
warning-logged so a flaky audit chain never rolls back a successful
domain mutation — same posture as
:mod:`echoroo.services.superuser_approval_service`.

PII handling
============
The user's raw email never crosses into audit detail or log lines.
We use :func:`echoroo.core.kms.compute_pii_hash` for surrogate
identifiers and only the recipient address itself crosses into
:mod:`echoroo.services.email` (which has its own header-injection
defence).
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.database import AsyncSessionLocal
from echoroo.core.kms import compute_pii_hash
from echoroo.models.superuser_approval_request import SuperuserApprovalRequest
from echoroo.models.two_factor_reset_request import (
    DISPATCHABLE_STATUSES,
    STATUS_APPROVED,
    STATUS_CANCELLED,
    STATUS_DISPATCHING,
    STATUS_FAILED,
    STATUS_PENDING_APPROVAL,
    STATUS_PENDING_DELAY,
    TwoFactorResetMagicLink,
    TwoFactorResetRequest,
)
from echoroo.models.user import User
from echoroo.services import email as email_service
from echoroo.services.audit_service import AuditLogService
from echoroo.services.superuser_service import (
    ACTION_TWO_FACTOR_RESET_SKIP_DELAY,
)
from echoroo.services.two_factor_confirmation_token import (
    PURPOSE_ADMIN_RESET_2FA,
    ConfirmationTokenError,
    consume_confirmation_token,
    issue_confirmation_token,
)
from echoroo.services.two_factor_service import TwoFactorService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

#: Default delay before the dispatch poller is allowed to clear the
#: user's 2FA state. Spec FR-072 calls for 24 hours; the operator can
#: shortcut this with ``skip_delay=True`` + an M-of-N approval.
DEFAULT_DISPATCH_DELAY = timedelta(hours=24)

#: Total lifetime of a request row before it auto-expires (whether or
#: not it was dispatched). 72 hours mirrors the existing 2FA cooldown.
REQUEST_TTL = timedelta(hours=72)

#: Magic-link lifetime. 30 minutes balances "user has time to read the
#: email" with "operator should not leave a token sitting around".
MAGIC_LINK_TTL = timedelta(minutes=30)

#: Magic-link random length in bytes. After base64url encoding this
#: yields a ~43-char URL-safe token; the SHA-256 hash stored in the DB
#: is 64 hex chars.
_MAGIC_LINK_BYTES = 32

#: Round-2 Fix-2: a row that has been in ``dispatching`` longer than
#: this is considered orphaned by a crashed worker and reverted to
#: ``pending_delay`` by the reclaim sweep at the top of every poll
#: tick. Five minutes is generous: a healthy ``_apply_one`` call
#: completes in well under a second, but a worker process kill
#: typically leaves the OS-level connection draining for a couple of
#: minutes.
DISPATCH_RECLAIM_TIMEOUT = timedelta(minutes=5)

#: Round-3 Fix R2-4: name of the partial unique index that enforces
#: "one in-flight 2FA reset request per user". Captured as a Final
#: constant so the admin endpoint's IntegrityError translation does
#: not have to hard-code the literal string in two places — a future
#: index rename only has to update this single value. Mirrors the
#: definition in ``alembic/versions/0014_two_factor_reset_requests.py``.
ACTIVE_REQUEST_UNIQUE_CONSTRAINT: Final[str] = (
    "ux_two_factor_reset_requests_active_user"
)


# ---------------------------------------------------------------------------
# Audit action labels
# ---------------------------------------------------------------------------

AUDIT_ACTION_REQUESTED = "two_factor_reset.requested"
AUDIT_ACTION_TOKEN_VERIFIED = "two_factor_reset.token_verified"
AUDIT_ACTION_DISPATCHED = "two_factor_reset.dispatched"
AUDIT_ACTION_APPLIED = "two_factor_reset.applied"
AUDIT_ACTION_EXPIRED = "two_factor_reset.expired"
AUDIT_ACTION_CANCELLED = "two_factor_reset.cancelled"
AUDIT_ACTION_FAILED = "two_factor_reset.failed"
AUDIT_ACTION_EMAIL_FAILED = "two_factor_reset.email_notification_failed"
AUDIT_ACTION_TOKEN_ISSUED = "two_factor_reset.confirmation_token_issued"
AUDIT_ACTION_TOKEN_REDEEMED = "two_factor_reset.confirmation_token_redeemed"
#: Round-2 Fix-2: emitted by the dispatch poller when it reverts a
#: stale ``dispatching`` row back to ``pending_delay`` because a worker
#: crashed mid-reset and never reached the ``applied`` / ``failed``
#: terminal state.
AUDIT_ACTION_DISPATCHING_RECLAIMED = "two_factor_reset.dispatching_reclaimed"
#: Round-2 Fix-4: emitted when the admin reset endpoint sees a replay
#: of a confirmation token that was already consumed. The audit row
#: surfaces the per-user / per-request envelope so on-call can spot a
#: brute force or a leaked-token event.
AUDIT_ACTION_CONFIRMATION_TOKEN_REPLAY = (
    "two_factor_reset.confirmation_token_replay_attempted"
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class TwoFactorResetServiceError(RuntimeError):
    """Base class for 2FA reset workflow errors."""


class ActiveResetRequestExistsError(TwoFactorResetServiceError):
    """Raised when a non-terminal request already exists for the user."""


class UserAlreadyHasNoTwoFactorError(TwoFactorResetServiceError):
    """Raised when the target user has no 2FA enabled — nothing to reset."""


class MagicLinkInvalidError(TwoFactorResetServiceError):
    """Raised when a magic-link token is invalid / expired / consumed."""


# ---------------------------------------------------------------------------
# Outcome dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CreateRequestOutcome:
    """Returned by :func:`create_request` for the admin handler."""

    request_id: UUID
    status: str
    dispatch_at: datetime | None
    expires_at: datetime
    approval_request_id: UUID | None
    confirmation_token_nonce: str


@dataclass(frozen=True)
class RedeemMagicLinkOutcome:
    """Returned by :func:`redeem_magic_link` for the auth handler."""

    confirmation_token: str
    expires_at: datetime
    user_id: UUID


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hash_magic_link(token: str) -> str:
    """SHA-256 hex of the raw magic-link token (matches the column width)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def _get_active_request(
    session: AsyncSession,
    user_id: UUID,
) -> TwoFactorResetRequest | None:
    stmt = sa.select(TwoFactorResetRequest).where(
        TwoFactorResetRequest.user_id == user_id,
        TwoFactorResetRequest.status.in_(
            [
                STATUS_PENDING_DELAY,
                STATUS_PENDING_APPROVAL,
                STATUS_APPROVED,
                STATUS_DISPATCHING,
            ]
        ),
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def _write_platform_audit(
    *,
    actor_user_id: UUID | None,
    action: str,
    detail: dict[str, Any],
    request_id: str = "",
    ip: str = "",
    user_agent: str = "",
) -> None:
    """Write a platform-scope audit row in a fresh session.

    Failure is warning-logged — the surrounding state transition
    already committed and we mirror the FR-088 soft-alert posture
    used by :mod:`echoroo.services.superuser_approval_service`.
    """
    try:
        async with AsyncSessionLocal() as audit_session:
            try:
                await AuditLogService(audit_session).write_platform_event(
                    actor_user_id=actor_user_id,
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
            "%s audit write failed (FR-088 soft alert): detail_keys=%s error=%r",
            action,
            sorted(detail.keys()),
            exc,
        )


# ---------------------------------------------------------------------------
# Magic-link issuance + redeem (used by the auth router)
# ---------------------------------------------------------------------------


async def issue_magic_link(
    session: AsyncSession,
    *,
    user: User,
    ip: str = "",
    user_agent: str = "",
    now: datetime | None = None,
) -> str:
    """Generate a magic-link token and persist its SHA-256 hash.

    The caller is responsible for committing the surrounding
    transaction.

    Round-3 Fix R2-1 (audit-path coherence):
    Email dispatch failures used to be swallowed here, which silently
    left a usable magic-link row in the DB while the caller still
    audited the request as ``magic_link_dispatched`` — a confusing
    "delivered" claim for an undelivered token. The contract is now:

    * On email success, return the raw token; the caller commits the
      surrounding TX and writes the dispatched audit row.
    * On email failure, write a service-layer
      ``two_factor_reset.email_notification_failed`` audit row (with
      ``stage='magic_link_issuance'``), roll back the surrounding TX
      so the magic-link DB row is NOT persisted, and re-raise. The
      caller's existing ``except`` arm already writes a second
      ``email_notification_failed`` audit row (with the request
      envelope) and returns 202 to preserve enumeration defence.

    Net audit trail on failure:
    * service:  ``email_notification_failed`` (stage=magic_link_issuance, no envelope)
    * caller:   ``email_notification_failed`` (stage=magic_link_issuance, with envelope)
    No ``magic_link_dispatched`` row is written, so the dashboard never
    sees a phantom "delivered" event for an undelivered token.
    """
    issued_at = now or datetime.now(UTC)
    raw = secrets.token_urlsafe(_MAGIC_LINK_BYTES)
    token_hash = _hash_magic_link(raw)
    expires_at = issued_at + MAGIC_LINK_TTL

    session.add(
        TwoFactorResetMagicLink(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at,
            requested_ip=ip[:45] if ip else None,
            requested_user_agent=user_agent[:500] if user_agent else None,
        )
    )

    try:
        await email_service.send_2fa_reset_magic_link(user.email, raw)
    except Exception as exc:  # noqa: BLE001 — propagate to caller for rollback
        # Service-layer audit (no request envelope yet — caller owns
        # that). Written in a fresh session so the rollback below does
        # not erase it.
        await _write_platform_audit(
            actor_user_id=user.id,
            action=AUDIT_ACTION_EMAIL_FAILED,
            detail={
                "stage": "magic_link_issuance",
                "user_id": str(user.id),
                "email_hash": compute_pii_hash(user.email),
                "error": exc.__class__.__name__,
            },
        )
        # Drop the unsendable magic-link row so the caller's outer TX
        # cannot accidentally commit a token nobody received.
        await session.rollback()
        raise
    return raw


async def redeem_magic_link(
    session: AsyncSession,
    *,
    raw_token: str,
    now: datetime | None = None,
) -> RedeemMagicLinkOutcome:
    """Atomically consume a magic link and mint a confirmation token.

    Raises :class:`MagicLinkInvalidError` for any of: unknown hash,
    already redeemed, expired. The caller is responsible for the final
    ``await session.commit()`` so the consumption + confirmation-token
    insert land in one transaction.
    """
    current = now or datetime.now(UTC)
    token_hash = _hash_magic_link(raw_token)

    # Atomic redeem: ``UPDATE ... WHERE redeemed_at IS NULL RETURNING user_id``.
    update_stmt = sa.text(
        """
        UPDATE two_factor_reset_magic_links
           SET redeemed_at = :now
         WHERE token_hash = :token_hash
           AND redeemed_at IS NULL
           AND expires_at > :now
        RETURNING user_id
        """
    )
    result = await session.execute(
        update_stmt,
        {"now": current, "token_hash": token_hash},
    )
    row = result.first()
    if row is None:
        raise MagicLinkInvalidError("magic-link token is invalid, expired, or used")
    user_id = UUID(str(row[0]))

    confirmation_token, payload = await issue_confirmation_token(
        session,
        user_id=user_id,
        purpose=PURPOSE_ADMIN_RESET_2FA,
        now=current,
    )

    # Audit: token issued. Redeem audit is logged separately by the
    # caller (so it sees the request envelope).
    await _write_platform_audit(
        actor_user_id=user_id,
        action=AUDIT_ACTION_TOKEN_ISSUED,
        detail={
            "user_id": str(user_id),
            "purpose": PURPOSE_ADMIN_RESET_2FA,
            "nonce": payload.nonce,
            "expires_at": payload.expires_at.isoformat(),
        },
    )

    return RedeemMagicLinkOutcome(
        confirmation_token=confirmation_token,
        expires_at=payload.expires_at,
        user_id=user_id,
    )


# ---------------------------------------------------------------------------
# create_request — entry point used by the admin handler
# ---------------------------------------------------------------------------


async def create_request(
    session: AsyncSession,
    *,
    target_user: User,
    requested_by_superuser_id: UUID,
    confirmation_token: str,
    support_ticket_id: str,
    reason: str,
    skip_delay: bool,
    request_id: str = "",  # noqa: ARG001 — reserved for future audit envelope passthrough
    ip: str = "",  # noqa: ARG001 — same
    user_agent: str = "",  # noqa: ARG001 — same
    now: datetime | None = None,
) -> CreateRequestOutcome:
    """Validate the confirmation token, then insert the state-machine row.

    Caller commits. The function performs:

    1. Confirmation-token consume (HMAC + DB nonce one-time-use).
    2. Active-request guard via the partial unique index — translated
       into :class:`ActiveResetRequestExistsError` for a clean 409.
    3. Insert the row in ``pending_delay`` (default) or
       ``pending_approval`` (skip_delay=True). The latter also opens
       the matching ``superuser_approval_requests`` row and links it
       via ``approval_request_id``.
    """
    current = now or datetime.now(UTC)

    # 1. Consume the confirmation token. Failure → caller maps to 409.
    try:
        payload = await consume_confirmation_token(
            session,
            token=confirmation_token,
            expected_user_id=target_user.id,
            expected_purpose=PURPOSE_ADMIN_RESET_2FA,
            now=current,
        )
    except ConfirmationTokenError:
        raise

    # 2. Guard against a duplicate active request. The DB-level partial
    # unique index will catch this on commit, but a pre-check gives us
    # a deterministic 409 path AND avoids the "phantom row" footgun
    # where the IntegrityError swallows the FK / nonce row mid-flight.
    existing = await _get_active_request(session, target_user.id)
    if existing is not None:
        raise ActiveResetRequestExistsError(
            f"user {target_user.id} already has an in-flight 2FA reset request "
            f"(id={existing.id}, status={existing.status})"
        )

    # 3. Insert.
    expires_at = current + REQUEST_TTL
    if skip_delay:
        # Open the M-of-N approval ticket. ``approve_request`` will
        # call back into :func:`mark_approved_after_quorum` once the
        # second co-signer signs.
        approval_ticket = SuperuserApprovalRequest(
            action=ACTION_TWO_FACTOR_RESET_SKIP_DELAY,
            detail={
                "target_user_id": str(target_user.id),
                "support_ticket_id": support_ticket_id,
                "reason": reason,
            },
            requested_by_id=requested_by_superuser_id,
            approvals=[],
            status="pending",
        )
        session.add(approval_ticket)
        await session.flush()

        row = TwoFactorResetRequest(
            user_id=target_user.id,
            requested_by_superuser_id=requested_by_superuser_id,
            support_ticket_id=support_ticket_id,
            reason=reason,
            status=STATUS_PENDING_APPROVAL,
            skip_delay=True,
            dispatch_at=None,
            expires_at=expires_at,
            confirmation_token_nonce=payload.nonce,
            approval_request_id=approval_ticket.id,
        )
        session.add(row)
        # Stash the request id on the approval ticket detail so the
        # quorum hook (``mark_approved_after_quorum``) can resolve it
        # without a second SELECT.
        await session.flush()
        approval_ticket.detail = {
            **(approval_ticket.detail or {}),
            "two_factor_reset_request_id": str(row.id),
        }
        approval_request_id = approval_ticket.id
    else:
        row = TwoFactorResetRequest(
            user_id=target_user.id,
            requested_by_superuser_id=requested_by_superuser_id,
            support_ticket_id=support_ticket_id,
            reason=reason,
            status=STATUS_PENDING_DELAY,
            skip_delay=False,
            dispatch_at=current + DEFAULT_DISPATCH_DELAY,
            expires_at=expires_at,
            confirmation_token_nonce=payload.nonce,
            approval_request_id=None,
        )
        session.add(row)
        await session.flush()
        approval_request_id = None

    # Defer the audit row until after the caller commits (the audit
    # writer needs a fresh session for SERIALIZABLE — see
    # superuser_approval_service for the same pattern). We capture
    # everything we need in the outcome.
    return CreateRequestOutcome(
        request_id=row.id,
        status=row.status,
        dispatch_at=row.dispatch_at,
        expires_at=row.expires_at,
        approval_request_id=approval_request_id,
        confirmation_token_nonce=payload.nonce,
    )


async def trigger_create_request_audit(
    *,
    outcome: CreateRequestOutcome,
    actor_user_id: UUID,
    target_user_id: UUID,
    support_ticket_id: str,
    reason: str,
    skip_delay: bool,
    confirmation_token_nonce: str,
    request_id: str = "",
    ip: str = "",
    user_agent: str = "",
) -> None:
    """Write the ``two_factor_reset.requested`` + ``token_verified`` rows."""
    detail: dict[str, Any] = {
        "request_id": str(outcome.request_id),
        "target_user_id": str(target_user_id),
        "support_ticket_id": support_ticket_id,
        # Reason is operator-supplied free-form text and is bounded at
        # 2000 chars by the schema; truncate for audit storage to keep
        # the JSONB row from blowing up dashboards.
        "reason_excerpt": reason[:200],
        "skip_delay": skip_delay,
        "status": outcome.status,
        "dispatch_at": outcome.dispatch_at.isoformat() if outcome.dispatch_at else None,
        "expires_at": outcome.expires_at.isoformat(),
        "approval_request_id": (
            str(outcome.approval_request_id)
            if outcome.approval_request_id
            else None
        ),
        "confirmation_token_nonce": confirmation_token_nonce,
    }
    await _write_platform_audit(
        actor_user_id=actor_user_id,
        action=AUDIT_ACTION_REQUESTED,
        detail=detail,
        request_id=request_id,
        ip=ip,
        user_agent=user_agent,
    )
    await _write_platform_audit(
        actor_user_id=actor_user_id,
        action=AUDIT_ACTION_TOKEN_VERIFIED,
        detail={
            "request_id": str(outcome.request_id),
            "target_user_id": str(target_user_id),
            "confirmation_token_nonce": confirmation_token_nonce,
        },
        request_id=request_id,
        ip=ip,
        user_agent=user_agent,
    )


# ---------------------------------------------------------------------------
# mark_approved_after_quorum — hook called from superuser_service.approve_request
# ---------------------------------------------------------------------------


async def mark_approved_after_quorum(
    session: AsyncSession,
    *,
    approval_request_id: UUID,
    now: datetime,
) -> None:
    """Flip the linked request row from ``pending_approval`` to ``approved``.

    Sets ``dispatch_at = now()`` so the next beat tick picks it up.
    The atomic UPDATE pattern keeps a re-entrant approval (e.g. the
    quorum hook firing twice during a retry) idempotent.

    Raises :class:`TwoFactorResetServiceError` if the matching request
    cannot be located — that is a contract violation between
    :mod:`superuser_service` and this module and must roll back the
    surrounding TX so the approvals JSONB stays consistent with the
    domain row.
    """
    update_stmt = sa.text(
        """
        UPDATE two_factor_reset_requests
           SET status = 'approved',
               dispatch_at = :now,
               updated_at = :now
         WHERE approval_request_id = :approval_id
           AND status = 'pending_approval'
        RETURNING id, user_id, requested_by_superuser_id
        """
    )
    result = await session.execute(
        update_stmt,
        {"now": now, "approval_id": approval_request_id},
    )
    row = result.first()
    if row is None:
        # Either no matching request or the request already moved on
        # (race with a competing dispatcher). The first case is a real
        # bug — every skip_delay ticket MUST have a paired request row.
        # The second case is benign but rare; either way logging it is
        # the right move so on-call notices.
        existing_stmt = sa.select(TwoFactorResetRequest).where(
            TwoFactorResetRequest.approval_request_id == approval_request_id
        )
        existing = (await session.execute(existing_stmt)).scalar_one_or_none()
        if existing is None:
            raise TwoFactorResetServiceError(
                f"no two_factor_reset_requests row for approval_id={approval_request_id} "
                "(superuser_service quorum hook fired without a paired domain row)"
            )
        # Already past pending_approval — log and accept.
        logger.warning(
            "two_factor_reset.mark_approved_after_quorum no-op: approval_id=%s "
            "request_id=%s existing_status=%s",
            approval_request_id,
            existing.id,
            existing.status,
        )
        return

    request_id, user_id, requested_by_superuser_id = row
    logger.info(
        "two_factor_reset request %s approved via quorum (approval_id=%s); "
        "dispatch_at set to %s",
        request_id,
        approval_request_id,
        now.isoformat(),
    )


@dataclass(frozen=True)
class CancelledAfterRejectionAuditPayload:
    """Audit envelope returned by :func:`mark_cancelled_after_rejection`.

    Round-3 Fix R2-3: the reject endpoint owns the audit write so the
    audit row only lands in ``platform_audit_log`` after the outer
    transaction (which carries the approval-row mutation + this
    helper's domain UPDATE) commits. Writing the audit inline used a
    fresh session and committed *before* the outer ``db.commit()`` —
    if the outer commit then failed, dashboards would show a phantom
    "cancelled" event for a domain row that was rolled back.
    """

    request_id: UUID
    target_user_id: UUID
    approval_request_id: UUID
    rejector_superuser_id: UUID
    rejected_reason_excerpt: str


async def mark_cancelled_after_rejection(
    session: AsyncSession,
    *,
    approval_request_id: UUID,
    rejector_superuser_id: UUID,
    reason: str,
    now: datetime,
) -> CancelledAfterRejectionAuditPayload | None:
    """Round-2 Fix-5: cancel the domain row when its approval ticket is rejected.

    ``superuser_service.reject_request`` only flips the
    ``superuser_approval_requests`` row to ``rejected`` — without this
    hook the linked ``two_factor_reset_requests`` row would sit in
    ``pending_approval`` forever, holding the partial unique index
    slot for the user and confusing dashboards.

    The atomic UPDATE keeps the call idempotent so a re-entered
    rejection (e.g. retries surfaced by the orchestrator) does not
    bury a freshly-opened request.

    Round-3 Fix R2-3 (audit ordering):
    Returns a :class:`CancelledAfterRejectionAuditPayload` when the
    domain row was successfully cancelled. The caller MUST hand this
    to the post-commit audit hook so the
    ``two_factor_reset.cancelled`` row is only written after the
    outer TX (which holds both the approval mutation and this
    helper's domain UPDATE) successfully commits. Returns ``None``
    when the call was a no-op (already past pending_approval, or no
    paired domain row).
    """
    update_stmt = sa.text(
        """
        UPDATE two_factor_reset_requests
           SET status = 'cancelled',
               failure_reason = :reason,
               updated_at = :now
         WHERE approval_request_id = :approval_id
           AND status = 'pending_approval'
        RETURNING id, user_id, requested_by_superuser_id
        """
    )
    result = await session.execute(
        update_stmt,
        {
            "now": now,
            "approval_id": approval_request_id,
            "reason": f"approval_rejected: {reason}"[:500],
        },
    )
    row = result.first()
    if row is None:
        # Either no paired domain row (would be a bug — every
        # skip_delay ticket MUST have one) OR the row already moved on.
        # Probe so we can distinguish the two cases for forensics.
        existing_stmt = sa.select(TwoFactorResetRequest).where(
            TwoFactorResetRequest.approval_request_id == approval_request_id
        )
        existing = (await session.execute(existing_stmt)).scalar_one_or_none()
        if existing is None:
            logger.warning(
                "two_factor_reset.mark_cancelled_after_rejection: no paired "
                "request for approval_id=%s — orphaned reject ticket",
                approval_request_id,
            )
            return None
        logger.info(
            "two_factor_reset.mark_cancelled_after_rejection no-op: "
            "approval_id=%s request_id=%s existing_status=%s",
            approval_request_id,
            existing.id,
            existing.status,
        )
        return None

    request_id, user_id, _requested_by_superuser_id = row
    return CancelledAfterRejectionAuditPayload(
        request_id=UUID(str(request_id)),
        target_user_id=UUID(str(user_id)),
        approval_request_id=approval_request_id,
        rejector_superuser_id=rejector_superuser_id,
        rejected_reason_excerpt=reason[:200],
    )


# Note: a standalone ``write_cancelled_after_rejection_audit`` helper
# was considered for the reject post-commit hook (Round-3 Fix R2-3)
# but the cleaner integration point is to attach a
# :class:`SuperuserActionOutcome` to the parent's ``extra_audit``
# tuple. ``trigger_post_commit_audit`` already drains that tuple after
# the outer commit, so we re-use the existing post-commit machinery
# instead of introducing a parallel one.


# ---------------------------------------------------------------------------
# Beat poller — run_dispatch_due_requests
# ---------------------------------------------------------------------------


@dataclass
class DispatchSummary:
    """Aggregate counters returned by :func:`run_dispatch_due_requests`."""

    inspected: int = 0
    applied: int = 0
    cancelled: int = 0
    expired: int = 0
    failed: int = 0


async def run_dispatch_due_requests(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    batch_size: int = 25,
) -> DispatchSummary:
    """Process up to ``batch_size`` due requests in one beat tick.

    The poller selects rows where ``status IN
    ('pending_delay','approved') AND dispatch_at <= now()`` with
    ``FOR UPDATE SKIP LOCKED`` so multiple worker-cpu processes can
    co-exist without dispatching the same row twice.

    For each row:

    1. Flip status to ``dispatching`` (so a crash leaves a sentinel).
    2. Re-load the user; if the user re-enabled 2FA OR has a future
       cooldown OR is now deleted, mark the row ``cancelled``.
    3. Else call :meth:`TwoFactorService.reset_user_two_factor`,
       flip the row to ``applied``, send the user-facing email.
    4. Catch any exception → flip to ``failed`` with a short reason.

    Always commits each row's transition independently. Audit rows
    are written in fresh sessions (FR-088 soft-alert posture).
    """
    summary = DispatchSummary()
    current = now or datetime.now(UTC)

    # Round-2 Fix-2: stale-``dispatching`` reclaim sweep BEFORE the
    # expiry pass. A worker crash between the ``dispatching`` commit
    # and the ``applied`` / ``failed`` terminal flip leaves the row
    # holding the partial unique index slot for the user; reverting
    # to ``pending_delay`` lets the next tick claim it.
    await _reclaim_stale_dispatching(session, current=current)

    # Step 0: opportunistic expiry sweep — any pending_delay row past
    # ``expires_at`` should not be dispatched. Done first so the same
    # tick can still process freshly-due rows.
    summary.expired += await _expire_overdue_requests(session, current=current)

    # Round-4 Fix R3-Blocker1: claim + stamp in a SINGLE atomic UPDATE
    # ... RETURNING. The previous implementation used SELECT FOR UPDATE
    # SKIP LOCKED + per-row stamp UPDATE inside a per-row commit loop;
    # that left a fatal race window where the FIRST iteration's
    # ``await session.commit()`` released the row locks for ALL
    # remaining selected rows (PostgreSQL releases ALL row locks at
    # commit, not just the row whose state we mutated). Another worker
    # could then claim, apply, AND finalize one of "our" remaining
    # rows. Our subsequent ``UPDATE ... WHERE id = :id`` (no status
    # filter) would happily re-stamp it back to ``dispatching``, undoing
    # the other worker's terminal flip and producing a phantom second
    # dispatch.
    #
    # The single UPDATE ... WHERE id IN (SELECT ... FOR UPDATE SKIP
    # LOCKED) form holds the row lock through the UPDATE itself, so
    # claim and stamp are inseparable. The transaction commits below
    # in one shot for the entire batch, then per-row apply runs in
    # subsequent transactions gated on the captured per-row lease.
    stamp_now = datetime.now(UTC)
    claim_stmt = sa.text(
        """
        UPDATE two_factor_reset_requests
           SET status = 'dispatching',
               dispatching_started_at = :now,
               updated_at = :now
         WHERE id IN (
             SELECT id
               FROM two_factor_reset_requests
              WHERE status = ANY(:dispatchable)
                AND dispatch_at IS NOT NULL
                AND dispatch_at <= :current
                AND expires_at > :current
              ORDER BY dispatch_at ASC
              LIMIT :batch_size
              FOR UPDATE SKIP LOCKED
         )
        RETURNING id, dispatching_started_at
        """
    )
    claim_result = await session.execute(
        claim_stmt,
        {
            "now": stamp_now,
            "current": current,
            "batch_size": batch_size,
            "dispatchable": list(DISPATCHABLE_STATUSES),
        },
    )
    claimed = claim_result.fetchall()
    # Single batch-wide commit publishes the ``dispatching`` markers so
    # a worker crash leaves a forensic trail and the next beat tick
    # will not re-claim them (status not in DISPATCHABLE_STATUSES).
    await session.commit()

    # Re-load each claimed row's ORM object plus capture its lease.
    # The lease is the EXACT bit-pattern Postgres persisted in
    # ``dispatching_started_at`` so the CAS comparisons below match.
    claimed_pairs: list[tuple[UUID, datetime]] = [
        (UUID(str(r[0])), r[1]) for r in claimed
    ]

    for row_id, lease in claimed_pairs:
        summary.inspected += 1
        # Re-fetch the ORM row in the current session for ``_apply_one``
        # which still needs ``row.user_id`` etc. (the claim UPDATE was
        # raw SQL so no ORM identity-map entry was created).
        row = await session.get(TwoFactorResetRequest, row_id)
        if row is None:
            # Row deleted between batch claim and per-row processing.
            # No side effects to clean up because the row is gone; skip.
            continue
        await session.refresh(row)
        # Round-3 Fix R2-2: each terminal UPDATE below gates on
        # ``dispatching_started_at = :lease`` so a stale-reclaim sweep
        # firing in another worker (which CAS-clears the lease back to
        # NULL) cannot overlap with this worker's terminal flip.

        try:
            applied_ok = await _apply_one(
                session, row=row, current=current, lease=lease
            )
            if applied_ok:
                summary.applied += 1
            # else: lease was reclaimed mid-apply. The reset itself may
            # still have happened (TwoFactorService.reset_user_two_factor
            # is idempotent for an already-reset user — a second pass
            # finds two_factor_enabled=False and is a no-op via the
            # ``_apply_one`` user re-check); we just skip our terminal
            # bookkeeping so we do not double-count and do not double-
            # audit the dispatched/applied pair.
        except _CancelledMidDispatch as cancel_exc:
            # Round-8 Fix R7-1 (Major): ``_terminal_cas_update`` performs
            # ``await session.rollback()`` internally on CAS miss (line
            # 1072), which expires the AsyncSession identity map. Any
            # subsequent ``row.*`` attribute access — even ``row.id`` —
            # would trigger a lazy-load outside the async greenlet
            # context (MissingGreenlet) on the cancel-skip / audit
            # envelope path. Capture every attribute we need AFTER the
            # CAS into local variables BEFORE the call, mirroring the
            # ``except Exception`` arm below and the ``aborted_row_id``
            # capture in ``_apply_one``'s pre-CAS branch.
            cancelled_row_id = row.id
            cancelled_actor_id = row.requested_by_superuser_id
            cancelled_target_user_id = row.user_id
            cancelled_ok = await _terminal_cas_update(
                session,
                row_id=cancelled_row_id,
                lease=lease,
                new_status=STATUS_CANCELLED,
                failure_reason=cancel_exc.reason[:500],
                applied_at=None,
            )
            if cancelled_ok:
                summary.cancelled += 1
                await _write_platform_audit(
                    actor_user_id=cancelled_actor_id,
                    action=AUDIT_ACTION_CANCELLED,
                    detail={
                        "request_id": str(cancelled_row_id),
                        "target_user_id": str(cancelled_target_user_id),
                        "reason": cancel_exc.reason,
                    },
                )
            else:
                logger.warning(
                    "two_factor_reset dispatch cancel skipped — lease "
                    "reclaimed by another worker: request_id=%s",
                    cancelled_row_id,
                )
        except Exception as exc:  # noqa: BLE001
            # Round-7 Fix (R6 Major): capture every ORM attribute we
            # will need AFTER the rollback into local variables BEFORE
            # the rollback runs. ``await session.rollback()`` expires
            # the AsyncSession identity map; any subsequent ``row.*``
            # access would trigger an attribute lazy-load outside the
            # async greenlet context (MissingGreenlet) and the
            # ``_terminal_cas_update`` + audit envelope path would
            # never publish the ``failed`` CAS — leaving the silent
            # "user 2FA wiped, request stuck in dispatching" Round-5
            # Codex was originally chasing. Mirrors the
            # ``aborted_row_id`` capture pattern in ``_apply_one``'s
            # pre-CAS branch.
            captured_row_id = row.id
            captured_actor_id = row.requested_by_superuser_id
            captured_target_user_id = row.user_id
            exc_class_name = exc.__class__.__name__
            failure_reason = f"{exc_class_name}: {str(exc)[:400]}"
            logger.exception(
                "two_factor_reset dispatch failed: request_id=%s",
                captured_row_id,
            )
            # Round-6 Fix R5-Blocker (defense-in-depth): the destructive
            # ``reset_user_two_factor(commit=False)`` call above stages
            # the user 2FA wipe via ``session.flush()`` but leaves the
            # outer transaction open. If anything between that flush
            # and our ``await session.commit()`` raises (KMS hiccup,
            # cancelled-mid-flush, future refactor that adds I/O), the
            # user dirty mutation MUST be rolled back BEFORE the
            # ``failed`` CAS publishes the request row's terminal
            # status. Without this rollback, autoflush inside
            # ``_terminal_cas_update``'s UPDATE would re-stage the user
            # mutation alongside the ``failed`` flip and ``commit()``
            # would persist BOTH — leaving the silent
            # "request=failed, user 2FA wiped" inconsistency Round-5
            # Codex flagged.
            #
            # The rollback releases the request row's pessimistic lock
            # acquired by the pre-CAS UPDATE, which is fine: the
            # ``_terminal_cas_update`` re-acquires the row via its own
            # ``UPDATE … WHERE id = :id AND status = 'dispatching' AND
            # dispatching_started_at = :lease`` so the lease check still
            # serves as the CAS gate against a concurrent reclaim sweep.
            # If a reclaim swept us between rollback and CAS, the CAS
            # affects 0 rows and we skip the audit — same lost-race
            # semantics as the lease-reclaimed branch above.
            await session.rollback()
            failed_ok = await _terminal_cas_update(
                session,
                row_id=captured_row_id,
                lease=lease,
                new_status=STATUS_FAILED,
                failure_reason=failure_reason,
                applied_at=None,
            )
            if failed_ok:
                summary.failed += 1
                await _write_platform_audit(
                    actor_user_id=captured_actor_id,
                    action=AUDIT_ACTION_FAILED,
                    detail={
                        "request_id": str(captured_row_id),
                        "target_user_id": str(captured_target_user_id),
                        "error_class": exc_class_name,
                    },
                )
            else:
                logger.warning(
                    "two_factor_reset dispatch failure skipped — lease "
                    "reclaimed by another worker: request_id=%s",
                    captured_row_id,
                )
    return summary


async def _terminal_cas_update(
    session: AsyncSession,
    *,
    row_id: UUID,
    lease: datetime,
    new_status: str,
    failure_reason: str | None,
    applied_at: datetime | None,
) -> bool:
    """CAS-update a ``dispatching`` row to a terminal status.

    Round-3 Fix R2-2 helper. The match condition includes
    ``dispatching_started_at = :lease`` so a reclaim sweep that has
    already cleared the lease (because this worker stalled past
    ``DISPATCH_RECLAIM_TIMEOUT``) will cause our terminal UPDATE to
    affect 0 rows. The caller MUST treat ``False`` as "abort, the row
    has been re-claimed" and skip side effects so we don't double-fire
    audit, double-count, or stomp on a fresher cycle.
    """
    now = datetime.now(UTC)
    update_stmt = sa.text(
        """
        UPDATE two_factor_reset_requests
           SET status = :new_status,
               failure_reason = :failure_reason,
               applied_at = :applied_at,
               dispatching_started_at = NULL,
               updated_at = :now
         WHERE id = :id
           AND status = 'dispatching'
           AND dispatching_started_at = :lease
        RETURNING id
        """
    )
    result = await session.execute(
        update_stmt,
        {
            "new_status": new_status,
            "failure_reason": failure_reason,
            "applied_at": applied_at,
            "now": now,
            "id": row_id,
            "lease": lease,
        },
    )
    row = result.first()
    if row is None:
        # Roll back any pending ORM state on this session so the next
        # iteration starts clean — we never want to accidentally flush
        # a stale ORM mutation that lost the CAS race.
        await session.rollback()
        return False
    await session.commit()
    return True


class _CancelledMidDispatch(Exception):
    """Internal control-flow marker for the cancellation branch."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


async def _apply_one(
    session: AsyncSession,
    *,
    row: TwoFactorResetRequest,
    current: datetime,
    lease: datetime,
) -> bool:
    """Re-load the target user and either reset or cancel.

    Round-5 Fix R4-Blocker (A-11 lease race — root resolution):
    The pre-CAS lease re-confirmation, the destructive
    :func:`TwoFactorService.reset_user_two_factor` call, and the
    terminal ``applied`` CAS UPDATE now run inside a SINGLE transaction.
    The pre-CAS UPDATE both proves the lease and acquires the row's
    pessimistic lock; that lock is held — without an intermediate
    commit — through the user-state mutation and the terminal flip,
    then the whole batch is published in one ``session.commit()``.

    Why this matters
    ----------------
    The previous Round-4 implementation committed *immediately after*
    the pre-CAS check (to "release the row lock", line 1142). That
    intermediate commit reopened the race we set out to close:

      1. pre-CAS UPDATE succeeds, status=dispatching, lease=L.
      2. ``await session.commit()`` releases the row lock.
      3. Reclaim sweep on another worker observes
         ``dispatching_started_at < now() - 5min`` (or simply the lease
         from a previous tick that is now stale) and CAS-clears the
         lease back to NULL with status=pending_delay.
      4. We call ``reset_user_two_factor`` → user 2FA wiped + committed.
      5. Our terminal CAS UPDATE matches 0 rows (lease is gone).
      6. Next tick re-claims the row, sees ``two_factor_enabled=False``,
         and marks the request CANCELLED — even though the reset
         actually happened, with NO audit trail of the apply.

    By keeping the lock from the pre-CAS UPDATE all the way through
    the terminal CAS UPDATE in one transaction, the reclaim sweep's
    ``UPDATE … WHERE status='dispatching' …`` blocks on PostgreSQL
    row-level locking until we commit. After our commit the row is
    ``applied`` (status not in 'dispatching'), so the reclaimer's
    WHERE no longer matches. The race window is closed.

    Returns:
        ``True`` when the row was successfully advanced to ``applied``
        and side effects (audit, notification mail) were fired.
        ``False`` when the lease was reclaimed mid-flight (only
        possible BEFORE the pre-CAS step succeeds).
    """
    # Round-5 Fix R4-Major2: ``populate_existing=True`` evicts any
    # stale ``User`` instance that the caller-owned session might have
    # left in its identity map (``expire_on_commit=False`` keeps
    # ``two_factor_enabled`` etc. cached). Without this we could read
    # a stale ``two_factor_enabled=True`` for a user who has already
    # been reset by a prior cycle and incorrectly proceed.
    user = await session.get(User, row.user_id, populate_existing=True)
    if user is None or user.deleted_at is not None:
        raise _CancelledMidDispatch("target user is missing or deleted")

    # If the user has already pulled themselves out of the locked
    # state (re-enrolled 2FA, or sat through a previous cooldown that
    # is now in the future), do NOT clear their 2FA — that would be
    # disruptive and unauthorised.
    if not user.two_factor_enabled:
        raise _CancelledMidDispatch("target user no longer has 2FA enabled")

    cooldown_until = user.two_factor_reset_cooldown_until
    if cooldown_until is not None and cooldown_until > current:
        # A prior reset is still cooling down — refuse to stack a
        # second one. The operator should wait for the cooldown to
        # lapse before issuing a fresh ticket.
        raise _CancelledMidDispatch(
            "target user has an active 2FA reset cooldown; refusing to overwrite"
        )

    # Round-5 Fix R4-Blocker step 1: pre-CAS UPDATE — both proves we
    # still own the lease AND acquires the row-level lock for the
    # entire remainder of this transaction. We do NOT commit between
    # this UPDATE and the terminal flip below; the lock is held
    # continuously, so a concurrent reclaim sweep on another worker is
    # blocked at its own ``UPDATE … WHERE status='dispatching' …``
    # until we commit (and by then status is no longer 'dispatching',
    # so the reclaim WHERE no longer matches).
    pre_check_result = await session.execute(
        sa.text(
            """
            UPDATE two_factor_reset_requests
               SET updated_at = :now
             WHERE id = :id
               AND status = 'dispatching'
               AND dispatching_started_at = :lease
            RETURNING id
            """
        ),
        {"now": datetime.now(UTC), "id": row.id, "lease": lease},
    )
    if pre_check_result.first() is None:
        # The lease was reclaimed by a stale-reclaim sweep on another
        # worker BEFORE we even got to the destructive call. The user's
        # 2FA state is intact. Abort without writing any audit row;
        # the new cycle that now owns the row will write its own.
        # Capture row.id BEFORE rollback because rollback expires the
        # ORM identity-map and any subsequent attribute access on
        # ``row`` would trigger an autoload outside the async greenlet
        # context.
        aborted_row_id = row.id
        await session.rollback()
        logger.warning(
            "two_factor_reset apply aborted before reset — lease "
            "reclaimed by another worker: request_id=%s",
            aborted_row_id,
        )
        return False

    # Round-5 Fix R4-Blocker step 2: destructive user mutation under
    # the SAME transaction (``commit=False``). The user UPDATE pushes
    # to the wire via ``session.flush()`` so it acquires its own row
    # lock, but the surrounding TX stays open — the request row's
    # lock from the pre-CAS step is still held.
    #
    # Round-6 Fix R5-Blocker: ``commit=False`` now ALSO defers the
    # ``two_factor.reset_completed`` audit write — the call returns
    # an envelope that we hand to the post-commit audit hook below.
    # The previous behaviour wrote that audit from inside
    # ``reset_user_two_factor`` BEFORE this method's outer commit; if
    # the audit raised, our ``except Exception`` arm in
    # :func:`run_dispatch_due_requests` ran a "failed" CAS on the same
    # session whose autoflush would persist the user dirty mutation —
    # producing the silent "user reset, request marked failed, no
    # reset_completed audit" inconsistency Codex Round-5 flagged.
    service = TwoFactorService(session)
    reset_audit_envelope = await service.reset_user_two_factor(
        user,
        actor_id=row.requested_by_superuser_id,
        reason=f"admin_reset_2fa request_id={row.id}",
        commit=False,
    )

    # Round-5 Fix R4-Blocker step 3: terminal CAS UPDATE under the
    # SAME transaction. The CAS gate is now defensive only (the lock
    # has been held continuously since the pre-CAS UPDATE so this
    # cannot fail in practice) but we keep it for belt-and-suspenders
    # against future refactors that might split the transaction.
    applied_at = datetime.now(UTC)
    result = await session.execute(
        sa.text(
            """
            UPDATE two_factor_reset_requests
               SET status = 'applied',
                   applied_at = :applied_at,
                   dispatching_started_at = NULL,
                   updated_at = :applied_at
             WHERE id = :id
               AND status = 'dispatching'
               AND dispatching_started_at = :lease
            RETURNING id
            """
        ),
        {"applied_at": applied_at, "id": row.id, "lease": lease},
    )
    if result.first() is None:
        # Defensive branch — should be unreachable now that we hold
        # the row lock continuously from pre-CAS to here. If we somehow
        # reach this state (e.g. a future refactor introduces a commit
        # between pre-CAS and this UPDATE) we MUST roll back the user
        # mutation we staged via flush above so we don't leave the
        # user in a partially-reset state without an audit trail.
        #
        # Round-8 Fix R7-2 (Major): capture ``row.id`` BEFORE the
        # rollback — ``await session.rollback()`` expires the
        # AsyncSession identity map and any subsequent ``row.*`` access
        # would lazy-load outside the async greenlet context
        # (MissingGreenlet). Today this branch is unreachable under the
        # continuous-row-lock invariant, but the capture protects
        # against future refactor regressions where this branch
        # actually fires.
        missed_row_id = row.id
        await session.rollback()
        logger.error(
            "two_factor_reset terminal CAS missed despite continuous "
            "row lock — possible refactor regression: request_id=%s",
            missed_row_id,
        )
        return False

    # Round-5 Fix R4-Blocker step 4: ONE commit publishes the user
    # mutation, the terminal request flip, and releases the row lock.
    # All audit writes happen post-commit so a successful state
    # transition is reflected in audit even if the audit-side session
    # has a transient failure (FR-088 soft-alert posture).
    await session.commit()

    # Post-commit audit envelope: dispatched + reset_completed +
    # applied. We collapse these events into back-to-back writes (vs
    # the old "dispatched before commit, applied after commit" pattern)
    # so the audit chain remains coherent — none of these rows is
    # written unless the state transition actually committed.
    #
    # Round-6 Fix R5-Major: the ``two_factor.reset_completed`` row used
    # to be written from inside ``reset_user_two_factor`` BEFORE this
    # outer commit (and BEFORE the terminal CAS), which produced both a
    # phantom audit on outer-commit failure AND an audit-failure-poisons-
    # CAS path (Round-6 Fix R5-Blocker). It now lands here, post-commit,
    # via the envelope ``reset_user_two_factor(commit=False)`` returned
    # above. The fresh-session ``_write_platform_audit`` is soft-alert
    # (FR-088) so an audit hiccup will not retroactively un-commit the
    # state transition.
    await _write_platform_audit(
        actor_user_id=row.requested_by_superuser_id,
        action=AUDIT_ACTION_DISPATCHED,
        detail={
            "request_id": str(row.id),
            "target_user_id": str(row.user_id),
            "skip_delay": row.skip_delay,
        },
    )
    if reset_audit_envelope is not None:
        await _write_platform_audit(
            actor_user_id=reset_audit_envelope.actor_id,
            action=reset_audit_envelope.action,
            detail=reset_audit_envelope.detail,
        )
    await _write_platform_audit(
        actor_user_id=row.requested_by_superuser_id,
        action=AUDIT_ACTION_APPLIED,
        detail={
            "request_id": str(row.id),
            "target_user_id": str(row.user_id),
            "applied_at": applied_at.isoformat(),
        },
    )

    # User-facing notification. Failure is best-effort but logged
    # via an audit row so on-call has signal.
    try:
        await email_service.send_2fa_reset_dispatched(
            user.email,
            dispatched_at_iso=applied_at.isoformat(),
        )
    except Exception as exc:  # noqa: BLE001
        await _write_platform_audit(
            actor_user_id=row.requested_by_superuser_id,
            action=AUDIT_ACTION_EMAIL_FAILED,
            detail={
                "stage": "applied_notification",
                "request_id": str(row.id),
                "target_user_id": str(row.user_id),
                "error": exc.__class__.__name__,
            },
        )
    return True


async def _reclaim_stale_dispatching(
    session: AsyncSession,
    *,
    current: datetime,
) -> int:
    """Revert orphaned ``dispatching`` rows back to ``pending_delay``.

    Round-2 Fix-2 for the A-11 admin 2FA reset flow. A worker crash
    after the ``dispatching`` commit (but before the terminal flip
    inside :func:`_apply_one`) leaves the row in ``dispatching``
    forever. The partial unique index
    ``ux_two_factor_reset_requests_active_user`` includes
    ``dispatching`` in its ``WHERE`` set, so the user is also locked
    out of opening a fresh reset request.

    The sweep moves any row whose ``dispatching_started_at`` is older
    than :data:`DISPATCH_RECLAIM_TIMEOUT` back to ``pending_delay``
    with ``dispatch_at = now()`` so the next claim picks it up. We
    also write one ``two_factor_reset.dispatching_reclaimed`` audit
    row per reverted request so on-call has signal for repeat
    crashes.
    """
    threshold = current - DISPATCH_RECLAIM_TIMEOUT
    update_stmt = sa.text(
        """
        UPDATE two_factor_reset_requests
           SET status = 'pending_delay',
               dispatch_at = :now,
               dispatching_started_at = NULL,
               updated_at = :now
         WHERE status = 'dispatching'
           AND dispatching_started_at IS NOT NULL
           AND dispatching_started_at <= :threshold
        RETURNING id, user_id, requested_by_superuser_id
        """
    )
    result = await session.execute(
        update_stmt,
        {"now": current, "threshold": threshold},
    )
    rows = result.fetchall()
    if not rows:
        return 0
    await session.commit()
    for r in rows:
        await _write_platform_audit(
            actor_user_id=UUID(str(r[2])),
            action=AUDIT_ACTION_DISPATCHING_RECLAIMED,
            detail={
                "request_id": str(r[0]),
                "target_user_id": str(r[1]),
                "reclaim_threshold_seconds": int(
                    DISPATCH_RECLAIM_TIMEOUT.total_seconds()
                ),
            },
        )
    return len(rows)


async def _expire_overdue_requests(
    session: AsyncSession,
    *,
    current: datetime,
) -> int:
    """Bulk-flip rows past their ``expires_at`` to ``expired``.

    Returns the number of rows mutated. Audit rows are written one
    per row in a follow-up SELECT so the audit chain carries the
    individual ``request_id`` (otherwise the dashboard would see a
    single "N expired" row that hides the per-user impact).
    """
    update_stmt = sa.text(
        """
        UPDATE two_factor_reset_requests
           SET status = 'expired',
               updated_at = :now
         WHERE status IN ('pending_delay','pending_approval','approved')
           AND expires_at <= :now
        RETURNING id, user_id, requested_by_superuser_id
        """
    )
    result = await session.execute(update_stmt, {"now": current})
    rows = result.fetchall()
    if not rows:
        return 0
    await session.commit()
    for r in rows:
        await _write_platform_audit(
            actor_user_id=UUID(str(r[2])),
            action=AUDIT_ACTION_EXPIRED,
            detail={
                "request_id": str(r[0]),
                "target_user_id": str(r[1]),
            },
        )
    return len(rows)


# ---------------------------------------------------------------------------
# Helpers used by tests / admin tooling
# ---------------------------------------------------------------------------


async def cancel_request(
    session: AsyncSession,
    *,
    request_id: UUID,
    actor_user_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> bool:
    """Manually cancel an in-flight request (admin tooling).

    Returns ``True`` if the row was cancelled, ``False`` if it was
    already in a terminal state. Audit row is best-effort (FR-088).
    """
    current = now or datetime.now(UTC)
    update_stmt = sa.text(
        """
        UPDATE two_factor_reset_requests
           SET status = 'cancelled',
               failure_reason = :reason,
               updated_at = :now
         WHERE id = :id
           AND status IN ('pending_delay','pending_approval','approved')
        RETURNING id, user_id
        """
    )
    result = await session.execute(
        update_stmt,
        {"now": current, "reason": reason[:500], "id": request_id},
    )
    row = result.first()
    if row is None:
        return False
    await session.commit()
    await _write_platform_audit(
        actor_user_id=actor_user_id,
        action=AUDIT_ACTION_CANCELLED,
        detail={
            "request_id": str(row[0]),
            "target_user_id": str(row[1]),
            "reason": reason,
        },
    )
    return True


__all__ = [
    "ACTION_TWO_FACTOR_RESET_SKIP_DELAY",
    "AUDIT_ACTION_APPLIED",
    "AUDIT_ACTION_CANCELLED",
    "AUDIT_ACTION_CONFIRMATION_TOKEN_REPLAY",
    "AUDIT_ACTION_DISPATCHED",
    "AUDIT_ACTION_DISPATCHING_RECLAIMED",
    "AUDIT_ACTION_EMAIL_FAILED",
    "AUDIT_ACTION_EXPIRED",
    "AUDIT_ACTION_FAILED",
    "AUDIT_ACTION_REQUESTED",
    "AUDIT_ACTION_TOKEN_ISSUED",
    "AUDIT_ACTION_TOKEN_REDEEMED",
    "AUDIT_ACTION_TOKEN_VERIFIED",
    "ACTIVE_REQUEST_UNIQUE_CONSTRAINT",
    "ActiveResetRequestExistsError",
    "CancelledAfterRejectionAuditPayload",
    "CreateRequestOutcome",
    "DEFAULT_DISPATCH_DELAY",
    "DISPATCH_RECLAIM_TIMEOUT",
    "DispatchSummary",
    "MAGIC_LINK_TTL",
    "MagicLinkInvalidError",
    "REQUEST_TTL",
    "RedeemMagicLinkOutcome",
    "TwoFactorResetServiceError",
    "UserAlreadyHasNoTwoFactorError",
    "cancel_request",
    "create_request",
    "issue_magic_link",
    "mark_approved_after_quorum",
    "mark_cancelled_after_rejection",
    "redeem_magic_link",
    "run_dispatch_due_requests",
    "trigger_create_request_audit",
]
