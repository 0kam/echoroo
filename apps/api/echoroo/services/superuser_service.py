"""Superuser lifecycle + M-of-N approval engine (Phase 15 T951, FR-111 / FR-072).

This module is the application-layer counterpart of the ``superusers`` and
``superuser_approval_requests`` ORM rows lifted in Phase 15 Batch 1 (T950).
It provides:

* :func:`add_superuser` / :func:`add_superuser_apply` — promote a user to
  the superuser role. The first three superusers may be created
  unilaterally (creation-time exception covering both genesis and
  break-glass recovery); subsequent additions go through the M-of-N
  approval workflow shared with :mod:`superuser_approval_service`.
* :func:`revoke_superuser` / :func:`revoke_superuser_apply` — withdraw an
  existing superuser. Always M-of-N gated. The last non-revoked row is
  protected at the DB layer by the ``superuser_last_protection`` trigger
  (FR-111a, T020e); revocation that would cross the 3 → 2 boundary
  triggers :func:`enter_break_glass_mode`.
* :func:`approve_request` / :func:`reject_request` — the M-of-N
  state-machine driver. Once ``len(approvals) >= MIN_APPROVALS`` the
  caller dispatches the configured action (``superuser.add`` /
  ``superuser.revoke`` / ``backup_code_reset`` / ...).
* :func:`register_webauthn_credential` /
  :func:`verify_webauthn_assertion` — thin wrappers around
  :class:`echoroo.services.webauthn_service.WebAuthnService` that own
  persistence into the ``superusers.webauthn_credentials`` JSONB array
  and surface "first key registered" warning audit rows.
* :func:`enter_break_glass_mode` / :func:`is_break_glass_active` —
  governance helpers backed by ``system_settings`` rows. The 72 h timer
  is wall-clock (``now() - started_at < 72h``); spec FR-111 mandates a
  new superuser within 24 h of the count dropping below 3. A separate
  freeze handler (out of scope for this batch — see T955 frontend +
  T154/T155 admin gating) reads :func:`is_break_glass_active` to widen
  the auth surface.

Audit session contract (Phase 12 R4 / Phase 13 P1 R3 follow-up)
==============================================================
:class:`~echoroo.services.audit_service.AuditLogService` issues
``SET TRANSACTION ISOLATION LEVEL SERIALIZABLE`` as the very first
statement on its session — PostgreSQL rejects the upgrade once any other
SQL has executed on the same connection. The mutation helpers in this
module load / flush ORM rows and therefore CANNOT write the audit row in
the same session.

Following the Phase 13 pattern (see
:mod:`echoroo.services.ownership_service` and
:mod:`echoroo.services.superuser_approval_service`), every public
mutation:

1. Mutates the domain rows on the caller-owned :class:`AsyncSession`.
2. Returns an outcome dataclass capturing the audit envelope.
3. Defers the audit row insert to ``trigger_*_post_commit_audit`` which
   spins up a fresh :class:`AsyncSessionLocal`. Audit failures are
   warning-logged (FR-088 soft-alert posture) so a flaky audit chain
   never rolls back a successful domain mutation.

T953 trigger confirmation
=========================
``prevent_last_superuser_deletion`` (FR-111a) is implemented in the
baseline migration at
``apps/api/alembic/versions/0001_baseline_permissions_redesign.py:1241``.
The function intentionally checks ``current_user = 'echoroo_app'`` so
that:

* The application connection (role ``echoroo_app``) cannot delete the
  last non-revoked superuser unless the session variable
  ``app.superuser_deletion_override`` is ``'true'`` (creator_founder
  override path).
* Migration / rollback runs (``echoroo_migrator`` or PostgreSQL
  superuser) skip the trigger entirely so the schema can be torn down
  during baseline regenerations.

Phase 15 confirmed: T020e implementation already matches the spec; no
delta migration is required from this batch. The baseline edit history
is preserved per the Phase 13 baseline-edit policy.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.database import AsyncSessionLocal
from echoroo.models.superuser import Superuser
from echoroo.models.superuser_approval_request import SuperuserApprovalRequest
from echoroo.models.system import SystemSetting
from echoroo.services.audit_service import AuditLogService
from echoroo.services.webauthn_service import (
    StoredCredential,
    WebAuthnService,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Spec constants (FR-111 / FR-072)
# =============================================================================

#: Minimum active-superuser count the platform must maintain. Below this
#: threshold, :func:`enter_break_glass_mode` is engaged on the next
#: revocation transition. The first three superusers are seeded directly;
#: number four and onward require :data:`MIN_APPROVALS` co-signers.
MIN_SUPERUSERS: int = 3

#: M-of-N quorum (the "M"). spec FR-111: "追加 / 削除は既存 2 名 M-of-N 承認".
MIN_APPROVALS: int = 2

#: Spec requirement: at least one primary + one backup hardware key per
#: superuser (FR-111). One credential is an interim, "warning" state.
MIN_WEBAUTHN_CREDENTIALS: int = 2

#: 72 hour break-glass window (FR-111). Tracked as wall-clock delta from
#: ``system_settings['break_glass_started_at']``.
BREAK_GLASS_WINDOW: timedelta = timedelta(hours=72)

#: 24 hour deadline within the 72 h window for adding a replacement
#: superuser (FR-111). Soft alarm; the freeze logic lives in T154 admin
#: middleware.
BREAK_GLASS_REPLACEMENT_DEADLINE: timedelta = timedelta(hours=24)


# Phase 15 R3 NO-GO C3: deterministic ``pg_advisory_xact_lock`` key shared
# by ``revoke_superuser_apply`` and the ``prevent_last_superuser_deletion``
# trigger (migration 0013). Two concurrent revoke transactions targeting
# DIFFERENT rows would otherwise both observe ``COUNT(*) - 1 = 1`` and
# pass the guard. Folding ``SHA-256("superuser_last_protection")`` into
# the 63-bit positive range keeps the value stable across drivers
# (mirrors the convention in :mod:`echoroo.services.audit_service`).
_LAST_SUPERUSER_LOCK_KEY: Final[int] = (
    int.from_bytes(
        hashlib.sha256(b"superuser_last_protection").digest()[:8], "big"
    )
    & 0x7FFFFFFFFFFFFFFF
)


# Action identifiers — kept as stable string literals because dashboards
# group by ``superuser_approval_requests.action`` and changing them is
# effectively a breaking change for log queries.
ACTION_SUPERUSER_ADD: str = "superuser.add"
ACTION_SUPERUSER_REVOKE: str = "superuser.revoke"
ACTION_BACKUP_CODE_RESET: str = "backup_code_reset"

# Platform audit action labels (FR-089).
_AUDIT_ACTION_ADD_REQUESTED: str = "superuser.add.requested"
_AUDIT_ACTION_ADD_APPLIED: str = "superuser.add.applied"
_AUDIT_ACTION_ADD_DIRECT: str = "superuser.add.direct"  # creation-time exception
_AUDIT_ACTION_REVOKE_REQUESTED: str = "superuser.revoke.requested"
_AUDIT_ACTION_REVOKE_APPLIED: str = "superuser.revoke.applied"
_AUDIT_ACTION_APPROVED: str = "superuser.approval.approved"
_AUDIT_ACTION_REJECTED: str = "superuser.approval.rejected"
_AUDIT_ACTION_WEBAUTHN_REGISTERED: str = "superuser.webauthn.registered"
_AUDIT_ACTION_WEBAUTHN_REGISTERED_BELOW_MIN: str = (
    "superuser.webauthn.registered_below_minimum"
)
_AUDIT_ACTION_BREAK_GLASS_ENTERED: str = "superuser.break_glass.entered"
_AUDIT_ACTION_COUNT_CHANGED: str = "superuser.count_changed"  # FR-111a

# system_settings keys.
_SETTING_BREAK_GLASS_STARTED_AT: str = "break_glass_started_at"
_SETTING_BREAK_GLASS_REASON: str = "break_glass_reason"


# =============================================================================
# Errors
# =============================================================================


class SuperuserServiceError(RuntimeError):
    """Base class for the superuser engine errors."""


class AlreadySuperuserError(SuperuserServiceError):
    """Raised when promoting a user that already holds an active superuser row."""


class NotSuperuserError(SuperuserServiceError):
    """Raised when revoking / approving on behalf of a non-superuser identity."""


class ApprovalRequestNotFoundError(SuperuserServiceError):
    """Raised when ``approve_request`` / ``reject_request`` cannot find the row."""


class ApprovalRequestStateError(SuperuserServiceError):
    """Raised when the request is no longer ``pending`` (already applied / rejected)."""


class DuplicateApprovalError(SuperuserServiceError):
    """Raised when the same superuser tries to co-sign the same ticket twice."""


class WebAuthnRegistrationError(SuperuserServiceError):
    """Raised when WebAuthn credential persistence fails preconditions."""


class LastSuperuserProtectionError(SuperuserServiceError):
    """Raised when revocation would drop active superuser count below 1.

    Phase 15 NO-GO C3 fix: paired with the BEFORE UPDATE trigger
    extension shipped in migration ``0012``. The DB rejection is the
    primary defence; this exception is the service-layer secondary
    defence so the FastAPI layer can surface a 4xx without parsing
    asyncpg ``RAISE EXCEPTION`` output.
    """


# =============================================================================
# Outcome dataclasses
# =============================================================================


@dataclass(frozen=True)
class SuperuserActionOutcome:
    """Result of a state-changing superuser engine call.

    The endpoint commits the main TX and then hands this dataclass to
    :func:`trigger_post_commit_audit` so the platform-scope audit row is
    written in a fresh session.
    """

    action: str  # e.g. "superuser.add.requested" — matches platform_audit_log.action
    actor_user_id: UUID | None
    detail: dict[str, Any]
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    created_at: datetime | None = None
    request_id: str = ""
    ip: str = ""
    user_agent: str = ""

    # Domain payload (the engine state-machine result). Consumers branch on
    # ``status`` to render the right HTTP response.
    status: str = "pending"  # "pending" | "applied" | "rejected" | "direct"
    approval_request_id: UUID | None = None
    superuser_id: UUID | None = None

    # Companion outcomes — when applying a ticket cascades into a count
    # change or a break-glass transition we attach the supplementary audit
    # envelopes here so a single post-commit hook drains them all.
    extra_audit: tuple[SuperuserActionOutcome, ...] = field(default_factory=tuple)


# =============================================================================
# Public API — add_superuser
# =============================================================================


async def add_superuser(
    session: AsyncSession,
    *,
    target_user_id: UUID,
    requester_superuser_id: UUID | None,
    actor_user_id: UUID | None = None,
    webauthn_credentials: Sequence[dict[str, Any]] | None = None,
    allowed_ip_cidrs: Sequence[str] | None = None,
    request_id: str = "",
    ip: str = "",
    user_agent: str = "",
) -> SuperuserActionOutcome:
    """Promote a user to superuser.

    Behaviour by current active count (spec FR-111):

    * **count < :data:`MIN_SUPERUSERS`** (i.e. 0 / 1 / 2): direct
      promotion. This covers (a) the genesis superuser sequence — the
      bootstrap CLI in T952 needs to seed the first three rows without an
      M-of-N gate that has no quorum to satisfy — and (b) emergency
      rebuild during break-glass mode.
    * **count >= :data:`MIN_SUPERUSERS`**: opens an M-of-N approval
      ticket with ``action='superuser.add'``. The caller (i.e. the admin
      endpoint) returns 202 to the requester; once two co-signers call
      :func:`approve_request`, the engine invokes
      :func:`add_superuser_apply` to perform the actual INSERT.

    Args:
        session: Caller-owned async session — caller commits.
        target_user_id: The :class:`User` being promoted.
        requester_superuser_id: ``superusers.id`` of the operator opening
            the ticket. Required when ``count >= MIN_SUPERUSERS`` (the
            ticket FK ``requested_by_id`` is NOT NULL on this path).
            May be ``None`` for the very first promotion (no superuser
            row exists yet).
        actor_user_id: ``users.id`` of the human operator. Recorded on
            the audit envelope. Falls back to the ``Superuser`` record
            owning ``requester_superuser_id`` when absent.
        webauthn_credentials: Initial credential payload (typically
            empty; the operator registers the keys via
            :func:`register_webauthn_credential` after the row exists).
        allowed_ip_cidrs: Optional CIDR allowlist. Defaults to the empty
            list (no IP restriction) if not supplied.
        request_id / ip / user_agent: HTTP envelope for the audit row.

    Raises:
        AlreadySuperuserError: when ``target_user_id`` already has an
            active (revoked_at IS NULL) superuser row.
    """
    now = datetime.now(UTC)

    # 1. Reject duplicate active rows (Application-layer enforcement of
    #    the UNIQUE(user_id) + revoked_at semantics).
    existing = await _load_active_superuser_for_user(session, target_user_id)
    if existing is not None:
        raise AlreadySuperuserError(
            f"user {target_user_id} already holds active superuser id={existing.id}"
        )

    active_count = await _count_active_superusers(session)
    creds_payload = list(webauthn_credentials) if webauthn_credentials else []
    cidrs_payload = list(allowed_ip_cidrs) if allowed_ip_cidrs else []

    # 2. Creation-time exception: < MIN_SUPERUSERS → direct insert.
    if active_count < MIN_SUPERUSERS:
        new_row = Superuser(
            user_id=target_user_id,
            added_by_id=actor_user_id,  # NULL allowed for genesis bootstrap
            added_at=now,
            webauthn_credentials=creds_payload,
            allowed_ip_cidrs=cidrs_payload,
        )
        session.add(new_row)
        await session.flush()
        return SuperuserActionOutcome(
            action=_AUDIT_ACTION_ADD_DIRECT,
            actor_user_id=actor_user_id,
            detail={
                "target_user_id": str(target_user_id),
                "superuser_id": str(new_row.id),
                "active_count_before": active_count,
                "active_count_after": active_count + 1,
                "reason": "below_minimum_threshold",
                "min_superusers": MIN_SUPERUSERS,
            },
            after={"superuser_count": active_count + 1},
            before={"superuser_count": active_count},
            created_at=now,
            request_id=request_id,
            ip=ip,
            user_agent=user_agent,
            status="direct",
            superuser_id=new_row.id,
        )

    # 3. Steady-state: open an M-of-N approval ticket. ``requested_by_id``
    #    references ``superusers.id`` — the FK rejects regular-user IDs.
    if requester_superuser_id is None:
        raise SuperuserServiceError(
            "requester_superuser_id is required when count >= MIN_SUPERUSERS"
        )

    ticket = SuperuserApprovalRequest(
        action=ACTION_SUPERUSER_ADD,
        detail={
            "target_user_id": str(target_user_id),
            "webauthn_credentials": creds_payload,
            "allowed_ip_cidrs": cidrs_payload,
        },
        requested_by_id=requester_superuser_id,
        approvals=[],
        status="pending",
    )
    session.add(ticket)
    await session.flush()

    return SuperuserActionOutcome(
        action=_AUDIT_ACTION_ADD_REQUESTED,
        actor_user_id=actor_user_id,
        detail={
            "target_user_id": str(target_user_id),
            "approval_request_id": str(ticket.id),
            "active_count_before": active_count,
            "min_approvals": MIN_APPROVALS,
        },
        created_at=now,
        request_id=request_id,
        ip=ip,
        user_agent=user_agent,
        status="pending",
        approval_request_id=ticket.id,
    )


async def add_superuser_apply(
    session: AsyncSession,
    *,
    request: SuperuserApprovalRequest,
    actor_user_id: UUID | None,
    request_id: str,
    ip: str,
    user_agent: str,
    now: datetime,
) -> SuperuserActionOutcome:
    """Execute a quorum-met ``superuser.add`` ticket.

    Invoked from :func:`approve_request` once the approvals array reaches
    :data:`MIN_APPROVALS`. Performs the INSERT into ``superusers``,
    flips the ticket status to ``applied`` (handled by the caller after
    return), and emits a count-changed audit envelope for FR-111a.
    """
    detail = request.detail or {}
    target_user_id = UUID(str(detail["target_user_id"]))

    # Idempotency: bail if the user is already active.
    if await _load_active_superuser_for_user(session, target_user_id) is not None:
        raise AlreadySuperuserError(
            f"target user {target_user_id} already holds an active superuser row"
        )

    active_count = await _count_active_superusers(session)
    new_row = Superuser(
        user_id=target_user_id,
        added_by_id=actor_user_id,
        added_at=now,
        webauthn_credentials=list(detail.get("webauthn_credentials", [])),
        allowed_ip_cidrs=list(detail.get("allowed_ip_cidrs", [])),
    )
    session.add(new_row)
    await session.flush()

    extra_audit: list[SuperuserActionOutcome] = []
    extra_audit.append(
        _build_count_changed_outcome(
            actor_user_id=actor_user_id,
            before=active_count,
            after=active_count + 1,
            event="superuser.add.applied",
            now=now,
            request_id=request_id,
            ip=ip,
            user_agent=user_agent,
        )
    )

    return SuperuserActionOutcome(
        action=_AUDIT_ACTION_ADD_APPLIED,
        actor_user_id=actor_user_id,
        detail={
            "target_user_id": str(target_user_id),
            "superuser_id": str(new_row.id),
            "approval_request_id": str(request.id),
        },
        before={"superuser_count": active_count},
        after={"superuser_count": active_count + 1},
        created_at=now,
        request_id=request_id,
        ip=ip,
        user_agent=user_agent,
        status="applied",
        superuser_id=new_row.id,
        approval_request_id=request.id,
        extra_audit=tuple(extra_audit),
    )


# =============================================================================
# Public API — revoke_superuser
# =============================================================================


async def revoke_superuser(
    session: AsyncSession,
    *,
    target_superuser_id: UUID,
    requester_superuser_id: UUID,
    actor_user_id: UUID | None = None,
    request_id: str = "",
    ip: str = "",
    user_agent: str = "",
) -> SuperuserActionOutcome:
    """Open an M-of-N ticket to revoke a superuser.

    Always M-of-N gated regardless of current count (the genesis
    exception applies to *additions* only — the spec is explicit that
    revocations require co-signers, FR-111). The actual ``revoked_at``
    set happens in :func:`revoke_superuser_apply` after quorum.

    The DB-side trigger ``superuser_last_protection`` (FR-111a) is the
    last-line defence: even if the engine somehow races to revoke the
    final row, PostgreSQL refuses unless ``app.superuser_deletion_override``
    is set in the same session. Phase 15 NO-GO C3: that trigger covered
    only DELETE; the new variant (migration ``0012``) extends it to
    BEFORE UPDATE OF revoked_at so a soft-revoke that would push the
    active count below 1 is also blocked. Service-side, we still
    perform a SELECT FOR UPDATE + count check below as defence in depth
    so the API layer surfaces a clean Python exception rather than a
    raw asyncpg error.
    """
    now = datetime.now(UTC)

    target = await session.get(Superuser, target_superuser_id)
    if target is None or target.revoked_at is not None:
        raise NotSuperuserError(
            f"superuser {target_superuser_id} not found or already revoked"
        )

    ticket = SuperuserApprovalRequest(
        action=ACTION_SUPERUSER_REVOKE,
        detail={
            "target_superuser_id": str(target_superuser_id),
            "target_user_id": str(target.user_id),
        },
        requested_by_id=requester_superuser_id,
        approvals=[],
        status="pending",
    )
    session.add(ticket)
    await session.flush()

    return SuperuserActionOutcome(
        action=_AUDIT_ACTION_REVOKE_REQUESTED,
        actor_user_id=actor_user_id,
        detail={
            "target_superuser_id": str(target_superuser_id),
            "target_user_id": str(target.user_id),
            "approval_request_id": str(ticket.id),
            "min_approvals": MIN_APPROVALS,
        },
        created_at=now,
        request_id=request_id,
        ip=ip,
        user_agent=user_agent,
        status="pending",
        approval_request_id=ticket.id,
    )


async def revoke_superuser_apply(
    session: AsyncSession,
    *,
    request: SuperuserApprovalRequest,
    actor_user_id: UUID | None,
    request_id: str,
    ip: str,
    user_agent: str,
    now: datetime,
) -> SuperuserActionOutcome:
    """Execute a quorum-met ``superuser.revoke`` ticket.

    Sets ``revoked_at = now`` on the target row. If the active count
    transition crosses ``MIN_SUPERUSERS - 1`` boundary (3 → 2) we engage
    :func:`enter_break_glass_mode` and attach the resulting audit
    envelope to the outcome's ``extra_audit`` tuple.
    """
    detail = request.detail or {}
    target_id = UUID(str(detail["target_superuser_id"]))

    # Phase 15 R3 NO-GO C3: take the global advisory lock BEFORE the row
    # lock + active-count probe so two concurrent revoke applies that
    # target *different* rows still serialise on the count check. Without
    # the advisory lock the per-row ``SELECT FOR UPDATE`` only blocks
    # writers against the same target; sibling revokes of distinct
    # superusers would each compute ``COUNT(*) - 1 = 1`` from the
    # pre-image of the other and both pass the guard. The matching
    # ``pg_advisory_xact_lock`` inside the BEFORE UPDATE trigger
    # (migration 0013) is the authoritative defence — this service-side
    # acquire is defence in depth that lets the API surface a clean
    # ``LastSuperuserProtectionError`` instead of asyncpg's raw
    # ``RAISE EXCEPTION`` text.
    await session.execute(
        sa.text("SELECT pg_advisory_xact_lock(:k)"),
        {"k": _LAST_SUPERUSER_LOCK_KEY},
    )

    # Lock the target row + active superuser set so two concurrent
    # revoke applies cannot both pass the count guard.
    locked_stmt = (
        sa.select(Superuser)
        .where(Superuser.id == target_id)
        .with_for_update()
    )
    target = (await session.execute(locked_stmt)).scalar_one_or_none()
    if target is None:
        raise NotSuperuserError(f"superuser {target_id} disappeared")
    if target.revoked_at is not None:
        raise NotSuperuserError(f"superuser {target_id} already revoked")

    active_before = await _count_active_superusers(session)
    if active_before <= 1:
        # Service-side defence in depth — keep the DB trigger as the
        # primary block but surface a clean Python exception so the
        # API can return a friendlier error than asyncpg's raw
        # ``RAISE EXCEPTION`` text.
        raise LastSuperuserProtectionError(
            f"cannot revoke superuser {target_id}: would leave 0 active "
            "superusers (FR-111a)"
        )
    target.revoked_at = now
    await session.flush()
    active_after = active_before - 1

    extra_audit: list[SuperuserActionOutcome] = [
        _build_count_changed_outcome(
            actor_user_id=actor_user_id,
            before=active_before,
            after=active_after,
            event="superuser.revoke.applied",
            now=now,
            request_id=request_id,
            ip=ip,
            user_agent=user_agent,
        )
    ]

    # 3 → 2 transition triggers the 72 h break-glass timer (FR-111).
    if active_before >= MIN_SUPERUSERS and active_after < MIN_SUPERUSERS:
        bg_outcome = await enter_break_glass_mode(
            session,
            reason=f"superuser.revoke applied (count {active_before} -> {active_after})",
            actor_user_id=actor_user_id,
            now=now,
            request_id=request_id,
            ip=ip,
            user_agent=user_agent,
        )
        extra_audit.append(bg_outcome)

    return SuperuserActionOutcome(
        action=_AUDIT_ACTION_REVOKE_APPLIED,
        actor_user_id=actor_user_id,
        detail={
            "target_superuser_id": str(target_id),
            "target_user_id": str(target.user_id),
            "approval_request_id": str(request.id),
        },
        before={"superuser_count": active_before},
        after={"superuser_count": active_after},
        created_at=now,
        request_id=request_id,
        ip=ip,
        user_agent=user_agent,
        status="applied",
        superuser_id=target_id,
        approval_request_id=request.id,
        extra_audit=tuple(extra_audit),
    )


# =============================================================================
# Public API — approve_request / reject_request
# =============================================================================


async def approve_request(
    session: AsyncSession,
    *,
    request_id_uuid: UUID,
    approver_superuser_id: UUID,
    actor_user_id: UUID | None = None,
    request_id: str = "",
    ip: str = "",
    user_agent: str = "",
) -> SuperuserActionOutcome:
    """Append an approval to a pending ticket; dispatch on quorum reached.

    The state machine:

    1. ``len(approvals) < MIN_APPROVALS`` after append → status stays
       ``pending``, return a ``superuser.approval.approved`` audit
       envelope so the dashboard can show progress.
    2. ``len(approvals) >= MIN_APPROVALS`` → dispatch on
       :attr:`SuperuserApprovalRequest.action`:

       * ``superuser.add`` → :func:`add_superuser_apply`
       * ``superuser.revoke`` → :func:`revoke_superuser_apply`
       * ``backup_code_reset`` (FR-072) → caller-supplied dispatcher in
         a future iteration; currently we only flip status to ``applied``
         and let the orchestrator wire the actual reset (the
         backup-code reset row lives in a separate table outside this
         service's responsibility).
       * Other actions → flip to ``applied`` and surface as a generic
         outcome; the action-specific dispatcher hangs off the calling
         endpoint (e.g. taxon override approval already uses
         :mod:`superuser_approval_service`).

    Raises:
        ApprovalRequestNotFoundError / ApprovalRequestStateError /
        DuplicateApprovalError per their docstrings.

    Concurrency model (Phase 15 NO-GO C1 fix)
    ==========================================
    Two co-signers may approve the same ticket within microseconds. The
    previous read-modify-write on the JSONB ``approvals`` array, executed
    via ``session.get()`` without a row lock, allowed lost updates: each
    transaction observed ``approvals=[A]`` and wrote ``[A, B]`` /
    ``[A, C]`` respectively, producing a race where the last commit wins
    and the other approval silently disappears. Worse, both branches
    might cross the ``MIN_APPROVALS`` threshold and dispatch the
    underlying action twice.

    The fix issues a ``SELECT ... FOR UPDATE`` against the ticket row up
    front so the second transaction blocks until the first commits or
    rolls back. After the lock returns, the second writer re-reads the
    JSONB list and sees the freshly-appended approval. The duplicate
    check then catches its own re-attempt; a different writer simply
    appends to the now-up-to-date array.

    A secondary ``SELECT 1 FROM superusers`` guard rejects approvers
    that have been revoked between login and quorum (Minor 1 fix).
    """
    now = datetime.now(UTC)

    # Phase 15 NO-GO C1: lock the ticket row up front so two co-signers
    # serialise on this row. ``with_for_update`` returns the live row;
    # SQLAlchemy's identity-map then makes subsequent attribute reads
    # consistent with the locked snapshot.
    locked_stmt = (
        sa.select(SuperuserApprovalRequest)
        .where(SuperuserApprovalRequest.id == request_id_uuid)
        .with_for_update()
    )
    locked_result = await session.execute(locked_stmt)
    request = locked_result.scalar_one_or_none()
    if request is None:
        raise ApprovalRequestNotFoundError(
            f"approval request {request_id_uuid} not found"
        )
    if request.status != "pending":
        raise ApprovalRequestStateError(
            f"approval request {request_id_uuid} is in status={request.status!r}; "
            "cannot append approval"
        )

    # Phase 15 NO-GO Minor 1: verify the approver is itself an active
    # (non-revoked) superuser. The HTTP layer typically checks this
    # already, but a stale dependency or direct service call must not
    # bypass it — a revoked superuser must never be able to push a
    # ticket past quorum.
    approver_active_stmt = sa.select(sa.literal(1)).where(
        Superuser.id == approver_superuser_id,
        Superuser.revoked_at.is_(None),
    )
    approver_active = (
        await session.execute(approver_active_stmt)
    ).scalar_one_or_none()
    if approver_active is None:
        raise NotSuperuserError(
            f"approver {approver_superuser_id} is not an active superuser; "
            "cannot record approval"
        )

    approvals = list(request.approvals or [])
    if any(
        str(entry.get("superuser_id")) == str(approver_superuser_id)
        for entry in approvals
    ):
        raise DuplicateApprovalError(
            f"superuser {approver_superuser_id} has already approved request "
            f"{request_id_uuid}"
        )

    approvals.append(
        {
            "superuser_id": str(approver_superuser_id),
            "approved_at": now.isoformat(),
        }
    )
    # Reassign so SQLAlchemy treats the JSONB column as dirty (in-place
    # mutation on a JSONB list is invisible to the unit-of-work).
    request.approvals = approvals

    if len(approvals) < MIN_APPROVALS:
        await session.flush()
        return SuperuserActionOutcome(
            action=_AUDIT_ACTION_APPROVED,
            actor_user_id=actor_user_id,
            detail={
                "approval_request_id": str(request.id),
                "approver_superuser_id": str(approver_superuser_id),
                "approvals_count": len(approvals),
                "min_approvals": MIN_APPROVALS,
                "action": request.action,
            },
            created_at=now,
            request_id=request_id,
            ip=ip,
            user_agent=user_agent,
            status="pending",
            approval_request_id=request.id,
        )

    # Quorum reached. Dispatch.
    request.status = "applied"
    request.executed_at = now
    await session.flush()

    if request.action == ACTION_SUPERUSER_ADD:
        applied = await add_superuser_apply(
            session,
            request=request,
            actor_user_id=actor_user_id,
            request_id=request_id,
            ip=ip,
            user_agent=user_agent,
            now=now,
        )
        return applied
    if request.action == ACTION_SUPERUSER_REVOKE:
        applied = await revoke_superuser_apply(
            session,
            request=request,
            actor_user_id=actor_user_id,
            request_id=request_id,
            ip=ip,
            user_agent=user_agent,
            now=now,
        )
        return applied

    # Generic dispatch — the caller's orchestrator owns the side-effect
    # for actions outside this module's domain (e.g. backup_code_reset,
    # looser_override_approve which is handled by superuser_approval_service).
    return SuperuserActionOutcome(
        action=_AUDIT_ACTION_APPROVED,
        actor_user_id=actor_user_id,
        detail={
            "approval_request_id": str(request.id),
            "approver_superuser_id": str(approver_superuser_id),
            "approvals_count": len(approvals),
            "min_approvals": MIN_APPROVALS,
            "action": request.action,
            "dispatched": False,
        },
        created_at=now,
        request_id=request_id,
        ip=ip,
        user_agent=user_agent,
        status="applied",
        approval_request_id=request.id,
    )


async def reject_request(
    session: AsyncSession,
    *,
    request_id_uuid: UUID,
    rejector_superuser_id: UUID,
    reason: str,
    actor_user_id: UUID | None = None,
    request_id: str = "",
    ip: str = "",
    user_agent: str = "",
) -> SuperuserActionOutcome:
    """Reject a pending ticket and audit the rejection.

    Records the rejector in the ``approvals`` JSONB array (with a
    ``decision='rejected'`` marker) so the dashboard can render the
    decision history without an extra JOIN. ``status`` flips to
    ``rejected`` and ``executed_at`` stamps the decision time.
    """
    now = datetime.now(UTC)
    request = await session.get(SuperuserApprovalRequest, request_id_uuid)
    if request is None:
        raise ApprovalRequestNotFoundError(
            f"approval request {request_id_uuid} not found"
        )
    if request.status != "pending":
        raise ApprovalRequestStateError(
            f"approval request {request_id_uuid} is in status={request.status!r}; "
            "cannot reject"
        )

    approvals = list(request.approvals or [])
    approvals.append(
        {
            "superuser_id": str(rejector_superuser_id),
            "decided_at": now.isoformat(),
            "decision": "rejected",
            "rejected_reason": reason,
        }
    )
    request.approvals = approvals
    request.status = "rejected"
    request.executed_at = now
    await session.flush()

    return SuperuserActionOutcome(
        action=_AUDIT_ACTION_REJECTED,
        actor_user_id=actor_user_id,
        detail={
            "approval_request_id": str(request.id),
            "rejector_superuser_id": str(rejector_superuser_id),
            "action": request.action,
            "rejected_reason": reason,
        },
        created_at=now,
        request_id=request_id,
        ip=ip,
        user_agent=user_agent,
        status="rejected",
        approval_request_id=request.id,
    )


# =============================================================================
# Public API — WebAuthn credential lifecycle (thin wrapper)
# =============================================================================


async def register_webauthn_credential(
    session: AsyncSession,
    *,
    superuser_id: UUID,
    credential: dict[str, Any],
    actor_user_id: UUID | None = None,
    request_id: str = "",
    ip: str = "",
    user_agent: str = "",
) -> SuperuserActionOutcome:
    """Append a WebAuthn credential to ``superusers.webauthn_credentials``.

    The actual ceremony verification (challenge / signature / origin) is
    done by :class:`WebAuthnService.complete_registration`, which the
    endpoint must call BEFORE this function — the input ``credential``
    is the verified :class:`StoredCredential` payload.

    spec FR-111 mandates that a superuser keep at least
    :data:`MIN_WEBAUTHN_CREDENTIALS` (= 2) registered authenticators
    (primary + backup, physically separated). The first registration
    leaves the row in an interim "below-minimum" state and emits a
    distinct audit action so ops dashboards can surface the warning.
    """
    record = await session.get(Superuser, superuser_id)
    if record is None or record.revoked_at is not None:
        raise NotSuperuserError(
            f"superuser {superuser_id} not found or revoked; "
            "cannot register WebAuthn credential"
        )

    creds_existing = list(record.webauthn_credentials or [])
    new_credential_id = str(credential.get("credential_id", ""))
    if not new_credential_id:
        raise WebAuthnRegistrationError(
            "credential payload missing 'credential_id'; cannot register"
        )
    if any(
        str(stored.get("credential_id")) == new_credential_id for stored in creds_existing
    ):
        raise WebAuthnRegistrationError(
            f"credential_id {new_credential_id!r} already registered for "
            f"superuser {superuser_id}"
        )

    creds_existing.append(dict(credential))
    record.webauthn_credentials = creds_existing
    await session.flush()

    now = datetime.now(UTC)
    new_count = len(creds_existing)
    is_below_minimum = new_count < MIN_WEBAUTHN_CREDENTIALS
    return SuperuserActionOutcome(
        action=(
            _AUDIT_ACTION_WEBAUTHN_REGISTERED_BELOW_MIN
            if is_below_minimum
            else _AUDIT_ACTION_WEBAUTHN_REGISTERED
        ),
        actor_user_id=actor_user_id,
        detail={
            "superuser_id": str(superuser_id),
            "credential_id": new_credential_id,
            "credential_count": new_count,
            "minimum_required": MIN_WEBAUTHN_CREDENTIALS,
            "below_minimum": is_below_minimum,
        },
        before={"credential_count": new_count - 1},
        after={"credential_count": new_count},
        created_at=now,
        request_id=request_id,
        ip=ip,
        user_agent=user_agent,
        status="applied",
        superuser_id=superuser_id,
    )


async def verify_webauthn_assertion(
    session: AsyncSession,
    *,
    superuser_id: UUID,
    authentication_response: dict[str, Any],
    webauthn_service: WebAuthnService | None = None,
) -> StoredCredential:
    """Verify a WebAuthn authentication response against a superuser's keys.

    Loads the stored credentials from ``superusers.webauthn_credentials``,
    delegates the ceremony to
    :class:`WebAuthnService.complete_authentication`, and persists the
    updated ``sign_count`` / ``last_used_at`` back into the JSONB column
    (replay-counter regression is rejected by the underlying service via
    :class:`WebAuthnReplayDetectedError`).

    The caller is responsible for committing the session AFTER the
    ceremony completes — this function flushes but does not commit so
    the audit row + sign-count update land atomically.
    """
    record = await session.get(Superuser, superuser_id)
    if record is None or record.revoked_at is not None:
        raise NotSuperuserError(
            f"superuser {superuser_id} not found or revoked; "
            "cannot verify WebAuthn assertion"
        )

    creds = cast(
        list[StoredCredential], list(record.webauthn_credentials or [])
    )
    if not creds:
        raise WebAuthnRegistrationError(
            f"superuser {superuser_id} has no registered WebAuthn credentials"
        )

    service = webauthn_service or WebAuthnService()
    updated = await service.complete_authentication(
        user_id=superuser_id,
        authentication_response=authentication_response,
        existing_credentials=creds,
    )

    # Persist the new sign_count / last_used_at back into the JSONB array.
    refreshed: list[dict[str, Any]] = []
    for stored in creds:
        if stored["credential_id"] == updated["credential_id"]:
            refreshed.append(dict(updated))
        else:
            refreshed.append(dict(stored))
    record.webauthn_credentials = refreshed
    await session.flush()
    return updated


# =============================================================================
# Public API — break-glass governance
# =============================================================================


async def enter_break_glass_mode(
    session: AsyncSession,
    *,
    reason: str,
    actor_user_id: UUID | None = None,
    now: datetime | None = None,
    request_id: str = "",
    ip: str = "",
    user_agent: str = "",
) -> SuperuserActionOutcome:
    """Engage the 72 h break-glass timer (FR-111).

    Persists ``break_glass_started_at`` and ``break_glass_reason`` into
    ``system_settings`` so admin middleware (T154+) can read the flag
    without reaching back into ``superusers``. Idempotent: if a window
    is already active, the existing ``started_at`` is preserved (the
    spec wants the *original* incident time to drive the 72 h clock,
    not the latest-event time).

    Note: ``system_settings.updated_by_id`` is NOT NULL and FK →
    ``superusers.id`` (Phase 13 P1 R2 致命 #1). The caller path
    (``revoke_superuser_apply``) hands us the human ``users.id`` via
    ``actor_user_id``; we must therefore resolve that to the active
    ``superusers.id`` before stamping the system_settings row. Phase 15
    NO-GO C2 fix: the previous implementation passed ``actor_user_id``
    through as-is, which violates the FK and aborts the entire
    transaction (3 → 2 revoke fails to apply). Genesis bootstrap never
    calls into this helper because the count is already < 3 by
    definition.
    """
    started_at = now or datetime.now(UTC)
    existing_started = await _system_setting_get(session, _SETTING_BREAK_GLASS_STARTED_AT)
    if existing_started is not None:
        # Window already active. Keep original timestamp.
        return SuperuserActionOutcome(
            action=_AUDIT_ACTION_BREAK_GLASS_ENTERED,
            actor_user_id=actor_user_id,
            detail={
                "reason": reason,
                "already_active": True,
                "started_at": str(existing_started),
            },
            created_at=started_at,
            request_id=request_id,
            ip=ip,
            user_agent=user_agent,
            status="applied",
        )

    superuser_id = await _resolve_active_superuser_id(session, actor_user_id)
    if superuser_id is None:
        logger.warning(
            "enter_break_glass_mode could not resolve an active superuser id "
            "for actor_user_id=%s; system_settings update skipped "
            "(NOT NULL FK to superusers.id). reason=%r",
            actor_user_id,
            reason,
        )
    else:
        await _system_setting_upsert(
            session,
            key=_SETTING_BREAK_GLASS_STARTED_AT,
            value=started_at.isoformat(),
            updated_by_id=superuser_id,
            now=started_at,
        )
        await _system_setting_upsert(
            session,
            key=_SETTING_BREAK_GLASS_REASON,
            value=reason,
            updated_by_id=superuser_id,
            now=started_at,
        )

    return SuperuserActionOutcome(
        action=_AUDIT_ACTION_BREAK_GLASS_ENTERED,
        actor_user_id=actor_user_id,
        detail={
            "reason": reason,
            "started_at": started_at.isoformat(),
            "window_hours": int(BREAK_GLASS_WINDOW.total_seconds() // 3600),
            "replacement_deadline_hours": int(
                BREAK_GLASS_REPLACEMENT_DEADLINE.total_seconds() // 3600
            ),
        },
        after={"break_glass_active": True},
        created_at=started_at,
        request_id=request_id,
        ip=ip,
        user_agent=user_agent,
        status="applied",
    )


async def is_break_glass_active(
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> bool:
    """Return True iff the 72 h break-glass window is currently open."""
    raw = await _system_setting_get(session, _SETTING_BREAK_GLASS_STARTED_AT)
    if raw is None:
        return False
    try:
        # Stored as ISO string in JSONB.
        started_at = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        logger.warning(
            "system_settings[%s] is not a valid ISO datetime: %r",
            _SETTING_BREAK_GLASS_STARTED_AT,
            raw,
        )
        return False
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=UTC)
    deadline = started_at + BREAK_GLASS_WINDOW
    return (now or datetime.now(UTC)) < deadline


# =============================================================================
# Post-commit audit hook
# =============================================================================


async def trigger_post_commit_audit(outcome: SuperuserActionOutcome) -> None:
    """Write the platform_audit_log row(s) for a superuser engine outcome.

    Uses the same fresh-session pattern as
    :func:`echoroo.services.ownership_service.trigger_post_commit_side_effects`:
    each row gets its own :class:`AsyncSessionLocal` so the SERIALIZABLE
    upgrade succeeds (FR-093). Failures are warning-logged so a flaky
    audit chain never rolls back a persisted superuser mutation
    (FR-088 soft-alert posture).

    Drains ``outcome.extra_audit`` recursively so a single approve call
    that triggers (a) the dispatch, (b) a count-changed envelope, and
    (c) a break-glass envelope all hit ``platform_audit_log`` from one
    endpoint hook.
    """
    queue: list[SuperuserActionOutcome] = [outcome]
    while queue:
        current = queue.pop(0)
        queue.extend(current.extra_audit)
        try:
            async with AsyncSessionLocal() as audit_session:
                try:
                    await AuditLogService(audit_session).write_platform_event(
                        actor_user_id=current.actor_user_id,
                        action=current.action,
                        request_id=current.request_id,
                        ip=current.ip,
                        user_agent=current.user_agent,
                        detail=current.detail,
                        before=current.before,
                        after=current.after,
                        created_at=current.created_at,
                    )
                    await audit_session.commit()
                except Exception:
                    await audit_session.rollback()
                    raise
        except Exception as exc:  # noqa: BLE001 — soft alert; never blocks domain
            logger.warning(
                "%s platform_audit_log write failed (FR-088 soft alert): "
                "actor=%s detail=%s error=%r",
                current.action,
                current.actor_user_id,
                current.detail,
                exc,
            )


# =============================================================================
# Internals
# =============================================================================


async def _count_active_superusers(session: AsyncSession) -> int:
    """COUNT(*) WHERE revoked_at IS NULL — backed by ``ix_superusers_revoked_at``."""
    stmt = sa.select(sa.func.count()).select_from(Superuser).where(
        Superuser.revoked_at.is_(None)
    )
    result = await session.execute(stmt)
    return int(result.scalar_one())


async def _load_active_superuser_for_user(
    session: AsyncSession, user_id: UUID
) -> Superuser | None:
    """Fetch the active (revoked_at IS NULL) superuser row for a user, if any."""
    stmt = sa.select(Superuser).where(
        Superuser.user_id == user_id, Superuser.revoked_at.is_(None)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def _resolve_active_superuser_id(
    session: AsyncSession, actor_user_id: UUID | None
) -> UUID | None:
    """Resolve ``users.id`` → active ``superusers.id`` (FR-111a).

    Phase 15 NO-GO C2 fix: ``system_settings.updated_by_id`` is FK →
    ``superusers.id``, NOT ``users.id``. Callers that only have the
    human user id must resolve it through this helper before stamping
    audit-style FK columns.

    Returns ``None`` when ``actor_user_id`` is ``None`` or no active
    superuser row matches — the caller is expected to skip the FK
    write and emit a warning log in that case.
    """
    if actor_user_id is None:
        return None
    stmt = sa.select(Superuser.id).where(
        Superuser.user_id == actor_user_id,
        Superuser.revoked_at.is_(None),
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        return None
    return UUID(str(row)) if not isinstance(row, UUID) else row


async def _system_setting_get(
    session: AsyncSession, key: str
) -> Any | None:
    """SELECT system_settings.value WHERE key=:key — None if missing."""
    stmt = sa.select(SystemSetting.value).where(SystemSetting.key == key)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def _system_setting_upsert(
    session: AsyncSession,
    *,
    key: str,
    value: Any,
    updated_by_id: UUID,
    now: datetime,
) -> None:
    """INSERT … ON CONFLICT DO UPDATE for ``system_settings``."""
    record = await session.get(SystemSetting, key)
    if record is None:
        record = SystemSetting(
            key=key,
            value=value,
            updated_at=now,
            updated_by_id=updated_by_id,
        )
        session.add(record)
    else:
        record.value = value
        record.updated_at = now
        record.updated_by_id = updated_by_id
    await session.flush()


def _build_count_changed_outcome(
    *,
    actor_user_id: UUID | None,
    before: int,
    after: int,
    event: str,
    now: datetime,
    request_id: str,
    ip: str,
    user_agent: str,
) -> SuperuserActionOutcome:
    """FR-111a: every count transition emits a dedicated audit row."""
    return SuperuserActionOutcome(
        action=_AUDIT_ACTION_COUNT_CHANGED,
        actor_user_id=actor_user_id,
        detail={
            "from": before,
            "to": after,
            "event": event,
            "min_superusers": MIN_SUPERUSERS,
        },
        before={"superuser_count": before},
        after={"superuser_count": after},
        created_at=now,
        request_id=request_id,
        ip=ip,
        user_agent=user_agent,
        status="applied",
    )


__all__ = [
    "ACTION_BACKUP_CODE_RESET",
    "ACTION_SUPERUSER_ADD",
    "ACTION_SUPERUSER_REVOKE",
    "AlreadySuperuserError",
    "ApprovalRequestNotFoundError",
    "ApprovalRequestStateError",
    "BREAK_GLASS_REPLACEMENT_DEADLINE",
    "BREAK_GLASS_WINDOW",
    "DuplicateApprovalError",
    "LastSuperuserProtectionError",
    "MIN_APPROVALS",
    "MIN_SUPERUSERS",
    "MIN_WEBAUTHN_CREDENTIALS",
    "NotSuperuserError",
    "SuperuserActionOutcome",
    "SuperuserServiceError",
    "WebAuthnRegistrationError",
    "add_superuser",
    "add_superuser_apply",
    "approve_request",
    "enter_break_glass_mode",
    "is_break_glass_active",
    "register_webauthn_credential",
    "reject_request",
    "revoke_superuser",
    "revoke_superuser_apply",
    "trigger_post_commit_audit",
    "verify_webauthn_assertion",
]
