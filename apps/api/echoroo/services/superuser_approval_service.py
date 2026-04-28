"""Superuser approval workflow for sensitive project operations (Phase 11 / T611).

Some project-scope mutations require superuser sign-off before they take
effect. The canonical example codified by this module is FR-034:

    "Looser" :class:`~echoroo.models.project_taxon_override.ProjectTaxonSensitivityOverride`
    rows — overrides that *relax* masking on a flagged species — are born
    with ``approval_status = 'pending_superuser_approval'`` and are NOT
    consumed by :func:`~echoroo.core.permissions.compute_effective_resolution`
    until a superuser approves them. ``stricter`` overrides skip the
    workflow entirely and apply immediately.

The companion ``superuser_approval_requests`` table (created by the
baseline Alembic migration) holds the cross-cutting approval ticket. It
is intentionally schema-less for the ``detail`` payload so each action
type (taxon override, archived restore, 2FA reset, etc.) can attach
whatever context the approving superuser needs to make a decision. There
is no SQLAlchemy ORM class for it yet — Phase 12 will introduce one once
the admin UI consumes the rows. For now we drive it via :func:`sa.text`
raw SQL so other services can hook into the same workflow without a
circular-import dance.

This module exposes:

* :func:`apply_taxon_override` — idempotent entry point used by the
  project-owner taxon override endpoint. Stricter overrides land
  immediately; looser overrides land as ``pending_superuser_approval``
  AND a matching ``superuser_approval_requests`` row is created.
* :func:`approve_taxon_override` — mutation invoked from the superuser
  admin endpoint when accepting a pending request.
* :func:`reject_taxon_override` — mirror of the above with a free-form
  ``rejected_reason`` recorded on both rows.

All three functions write a ``project_audit_log`` row through
:class:`~echoroo.services.audit_service.AuditLogService` so the action is
captured in the tamper-evident hash chain (FR-088 / FR-092).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.enums import (
    TaxonOverrideApprovalStatus,
    TaxonOverrideDirection,
)
from echoroo.models.project_taxon_override import ProjectTaxonSensitivityOverride
from echoroo.services.audit_service import AuditLogService

logger = logging.getLogger(__name__)


class ApprovalRequestCloseError(RuntimeError):
    """Raised when ``_close_approval_request`` fails to find a pending row.

    Round 1 review M4 (2026-04-28): the approval workflow MUST leave an
    audit ticket in a terminal state for every override decision (FR-111).
    A 0-row UPDATE on ``superuser_approval_requests`` indicates either a
    bug or a race — either way the override status mutation is unsafe and
    the surrounding transaction must roll back. The dedicated subclass
    lets the caller (and the test suite) distinguish this from generic
    SQLAlchemy / ValueError failures.
    """


# Audit actions — keep these stable string literals; ops dashboards group by
# action and changing them is effectively a breaking change for log queries.
_AUDIT_ACTION_STRICTER_APPLIED: str = "project.taxon_override.create_stricter"
_AUDIT_ACTION_LOOSER_REQUESTED: str = "project.taxon_override.request_looser"
_AUDIT_ACTION_LOOSER_APPROVED: str = "project.taxon_override.approve_looser"
_AUDIT_ACTION_LOOSER_REJECTED: str = "project.taxon_override.reject_looser"

# String constant fed into ``superuser_approval_requests.action``. Mirrors
# the value listed in spec FR-008b's superuser project-scope allowlist.
_APPROVAL_REQUEST_ACTION: str = "project.taxon_override.approve_looser"


# =============================================================================
# Public API: apply_taxon_override
# =============================================================================


async def apply_taxon_override(
    session: AsyncSession,
    *,
    project_id: UUID,
    taxon_id: str,
    direction: TaxonOverrideDirection,
    sensitivity_h3_res: int,
    requester_id: UUID,
    request_id: str = "",
    ip: str = "",
    user_agent: str = "",
) -> ProjectTaxonSensitivityOverride:
    """Create a per-project taxon sensitivity override (FR-033 / FR-034).

    Behaviour by ``direction``:

    * :attr:`TaxonOverrideDirection.STRICTER`: row inserted with
      ``approval_status = 'applied'``. The masking pipeline begins
      consuming it on the next request. No approval ticket is created.
    * :attr:`TaxonOverrideDirection.LOOSER`: row inserted with
      ``approval_status = 'pending_superuser_approval'`` AND a sibling
      row in ``superuser_approval_requests`` is created so the operator
      dashboard can surface the pending decision.

    The caller is expected to have validated ``sensitivity_h3_res ∈ {2,
    5, 7, 9, 15}`` and the requester's authority over the project — this
    function performs only the workflow + audit bookkeeping.

    Idempotency: NOT enforced here. The DB-level partial unique index
    ``ux_taxon_overrides_applied_unique`` already guarantees there is at
    most one *applied* override per ``(project_id, taxon_id)`` pair; if
    the caller submits a duplicate stricter override the INSERT will
    raise an :class:`sqlalchemy.exc.IntegrityError` and the caller may
    surface a 409 to the user.
    """
    now = datetime.now(UTC)
    is_stricter = direction == TaxonOverrideDirection.STRICTER

    # FR-034: stricter is auto-applied; looser starts pending.
    initial_status = (
        TaxonOverrideApprovalStatus.APPLIED
        if is_stricter
        else TaxonOverrideApprovalStatus.PENDING_SUPERUSER_APPROVAL
    )

    override = ProjectTaxonSensitivityOverride(
        project_id=project_id,
        taxon_id=taxon_id,
        sensitivity_h3_res=sensitivity_h3_res,
        direction=direction,
        approval_status=initial_status,
        requested_by_id=requester_id,
    )
    session.add(override)
    # Flush so ``override.id`` is populated for the approval-request payload.
    await session.flush()

    audit_action: str
    audit_detail: dict[str, Any] = {
        "override_id": str(override.id),
        "taxon_id": taxon_id,
        "direction": direction.value,
        "sensitivity_h3_res": sensitivity_h3_res,
    }

    if is_stricter:
        audit_action = _AUDIT_ACTION_STRICTER_APPLIED
    else:
        audit_action = _AUDIT_ACTION_LOOSER_REQUESTED
        approval_request_id = await _create_approval_request(
            session,
            project_id=project_id,
            override_id=override.id,
            taxon_id=taxon_id,
            sensitivity_h3_res=sensitivity_h3_res,
            requester_id=requester_id,
            now=now,
        )
        audit_detail["approval_request_id"] = str(approval_request_id)

    await AuditLogService(session).write_project_event(
        actor_user_id=requester_id,
        project_id=project_id,
        action=audit_action,
        request_id=request_id,
        ip=ip,
        user_agent=user_agent,
        detail=audit_detail,
        created_at=now,
    )

    return override


# =============================================================================
# Public API: approve_taxon_override
# =============================================================================


async def approve_taxon_override(
    session: AsyncSession,
    *,
    override_id: UUID,
    approver_superuser_id: UUID,
    request_id: str = "",
    ip: str = "",
    user_agent: str = "",
) -> ProjectTaxonSensitivityOverride:
    """Approve a pending looser override (FR-034).

    Flips ``approval_status`` from ``pending_superuser_approval`` to
    ``applied`` and stamps ``approved_by_id`` / ``approved_at``. Also
    transitions the matching ``superuser_approval_requests`` row to
    ``status='approved'``.

    Raises:
        ValueError: when the override does not exist, was already
            decided, or is not a looser override (stricter overrides do
            not pass through this workflow).
    """
    now = datetime.now(UTC)

    override = await _load_override(session, override_id)

    if override.direction != TaxonOverrideDirection.LOOSER:
        raise ValueError(
            f"override {override_id} is direction={override.direction.value}; "
            "only looser overrides traverse the approval workflow"
        )
    if override.approval_status != TaxonOverrideApprovalStatus.PENDING_SUPERUSER_APPROVAL:
        raise ValueError(
            f"override {override_id} is in status="
            f"{override.approval_status.value}; cannot approve"
        )

    override.approval_status = TaxonOverrideApprovalStatus.APPLIED
    override.approved_by_id = approver_superuser_id
    override.approved_at = now

    await _close_approval_request(
        session,
        override_id=override_id,
        terminal_status="approved",
        approver_superuser_id=approver_superuser_id,
        rejected_reason=None,
        now=now,
    )

    await AuditLogService(session).write_project_event(
        actor_user_id=approver_superuser_id,
        project_id=override.project_id,
        action=_AUDIT_ACTION_LOOSER_APPROVED,
        request_id=request_id,
        ip=ip,
        user_agent=user_agent,
        detail={
            "override_id": str(override.id),
            "taxon_id": override.taxon_id,
            "sensitivity_h3_res": override.sensitivity_h3_res,
        },
        created_at=now,
    )

    return override


# =============================================================================
# Public API: reject_taxon_override
# =============================================================================


async def reject_taxon_override(
    session: AsyncSession,
    *,
    override_id: UUID,
    approver_superuser_id: UUID,
    rejected_reason: str,
    request_id: str = "",
    ip: str = "",
    user_agent: str = "",
) -> ProjectTaxonSensitivityOverride:
    """Reject a pending looser override (FR-034).

    Sets ``approval_status = 'rejected'`` and records ``rejected_reason``.
    The masking pipeline already filtered ``rejected`` rows out via the
    partial unique index + the ``approval_status='applied'`` filter in
    :func:`echoroo.services.taxon_sensitivity_service.bulk_load_override_map`,
    so no further bookkeeping is required.
    """
    now = datetime.now(UTC)

    override = await _load_override(session, override_id)

    if override.direction != TaxonOverrideDirection.LOOSER:
        raise ValueError(
            f"override {override_id} is direction={override.direction.value}; "
            "only looser overrides traverse the approval workflow"
        )
    if override.approval_status != TaxonOverrideApprovalStatus.PENDING_SUPERUSER_APPROVAL:
        raise ValueError(
            f"override {override_id} is in status="
            f"{override.approval_status.value}; cannot reject"
        )

    override.approval_status = TaxonOverrideApprovalStatus.REJECTED
    override.rejected_reason = rejected_reason
    # ``approved_by_id`` / ``approved_at`` stay NULL — those columns are
    # the spec's record of *positive* approval (FR-034). The audit row
    # below carries the rejecting superuser's identity instead.

    await _close_approval_request(
        session,
        override_id=override_id,
        terminal_status="rejected",
        approver_superuser_id=approver_superuser_id,
        rejected_reason=rejected_reason,
        now=now,
    )

    await AuditLogService(session).write_project_event(
        actor_user_id=approver_superuser_id,
        project_id=override.project_id,
        action=_AUDIT_ACTION_LOOSER_REJECTED,
        request_id=request_id,
        ip=ip,
        user_agent=user_agent,
        detail={
            "override_id": str(override.id),
            "taxon_id": override.taxon_id,
            "sensitivity_h3_res": override.sensitivity_h3_res,
            "rejected_reason": rejected_reason,
        },
        created_at=now,
    )

    return override


# =============================================================================
# Internals — superuser_approval_requests row lifecycle
# =============================================================================


async def _create_approval_request(
    session: AsyncSession,
    *,
    project_id: UUID,
    override_id: UUID,
    taxon_id: str,
    sensitivity_h3_res: int,
    requester_id: UUID,
    now: datetime,
) -> UUID:
    """Insert a ``superuser_approval_requests`` row and return its UUID.

    Round 1 review M3 (2026-04-28): the row stores the requester's
    ``users.id`` in ``requesting_user_id`` (FK → users.id, nullable) so
    that owner / admin-initiated tickets do NOT violate the legacy
    ``requested_by_id`` FK to ``superusers.id``. ``requested_by_id``
    stays NULL on this path; it is reserved for tickets opened directly
    by a superuser (e.g. operator-triage flows). The CHECK constraint
    ``ck_superuser_approval_requests_actor_present`` enforces that at
    least one of the two columns is populated, preserving an unbroken
    audit trail.

    The ``detail`` JSONB carries the override identity + project so the
    admin dashboard can render a one-click approval card without an
    extra SELECT. ``approvals`` starts as the empty list ``[]`` per the
    baseline migration's server default; future M-of-N flows append
    superuser IDs to it. Single-superuser approval (this workflow)
    transitions ``status`` directly to ``approved`` / ``rejected``.

    The table currently lacks a SQLAlchemy ORM class (Phase 12 will add
    one), so we drive it via raw SQL.
    """
    insert_stmt = sa.text(
        """
        INSERT INTO superuser_approval_requests
            (action, detail, requesting_user_id, status, created_at, updated_at)
        VALUES
            (:action, CAST(:detail AS JSONB), :requesting_user_id, 'pending', :now, :now)
        RETURNING id
        """
    )
    import json as _json

    detail_json = _json.dumps(
        {
            "project_id": str(project_id),
            "override_id": str(override_id),
            "taxon_id": taxon_id,
            "sensitivity_h3_res": sensitivity_h3_res,
        },
        sort_keys=True,
    )
    result = await session.execute(
        insert_stmt,
        {
            "action": _APPROVAL_REQUEST_ACTION,
            "detail": detail_json,
            "requesting_user_id": requester_id,
            "now": now,
        },
    )
    row = result.first()
    assert row is not None, "RETURNING id never returns zero rows"
    return UUID(str(row[0]))


async def _close_approval_request(
    session: AsyncSession,
    *,
    override_id: UUID,
    terminal_status: str,
    approver_superuser_id: UUID,
    rejected_reason: str | None,
    now: datetime,
) -> None:
    """Transition the matching ``superuser_approval_requests`` row.

    Round 1 review M4 (2026-04-28): the previous implementation logged a
    warning and returned silently when zero rows were updated. That left
    the override-level state machine free to advance to ``applied`` /
    ``rejected`` without a corresponding approval ticket — a violation
    of FR-111 (every superuser-gated decision must leave an auditable
    approval row). We now raise :class:`ApprovalRequestCloseError` on a
    0-row UPDATE so the surrounding transaction rolls back; both the
    override status mutation and any audit row written in the same TX
    are reverted atomically. Callers MUST run this helper inside the
    same transaction as the override mutation for the rollback to take
    effect.
    """
    update_stmt = sa.text(
        """
        UPDATE superuser_approval_requests
           SET status = :status,
               executed_at = :now,
               updated_at = :now,
               approvals = approvals || CAST(:approver_jsonb AS JSONB)
         WHERE action = :action
           AND status = 'pending'
           AND (detail->>'override_id') = :override_id
        """
    )
    import json as _json

    approver_jsonb = _json.dumps(
        [
            {
                "superuser_id": str(approver_superuser_id),
                "decided_at": now.isoformat(),
                "decision": terminal_status,
                **({"rejected_reason": rejected_reason} if rejected_reason else {}),
            }
        ]
    )
    result = await session.execute(
        update_stmt,
        {
            "status": terminal_status,
            "now": now,
            "approver_jsonb": approver_jsonb,
            "action": _APPROVAL_REQUEST_ACTION,
            "override_id": str(override_id),
        },
    )
    # ``rowcount`` is exposed on the underlying CursorResult but mypy's
    # default Result stub does not carry it. We fall back to ``getattr``
    # so a 0-row UPDATE is still detected.
    affected = getattr(result, "rowcount", -1)
    if affected == 0:
        # Force the surrounding TX to abort. The caller's audit row +
        # override status mutation were both written in the same session
        # so SQLAlchemy will roll them back when this exception bubbles.
        logger.error(
            "superuser_approval_requests close failed: override_id=%s status=%s "
            "(no pending row matched — aborting TX so override stays in "
            "pending state)",
            override_id,
            terminal_status,
        )
        raise ApprovalRequestCloseError(
            f"no pending superuser_approval_requests row matched "
            f"override_id={override_id} status={terminal_status}"
        )


async def _load_override(
    session: AsyncSession,
    override_id: UUID,
) -> ProjectTaxonSensitivityOverride:
    """Fetch an override row by id; raise ValueError if missing."""
    stmt = sa.select(ProjectTaxonSensitivityOverride).where(
        ProjectTaxonSensitivityOverride.id == override_id
    )
    result = await session.execute(stmt)
    override = result.scalar_one_or_none()
    if override is None:
        raise ValueError(f"override {override_id} not found")
    return override


__all__ = [
    "ApprovalRequestCloseError",
    "apply_taxon_override",
    "approve_taxon_override",
    "reject_taxon_override",
]
