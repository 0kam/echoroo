"""Post-commit audit side effects (audit only).

Audit side-effects are deliberately deferred to **after** the main
transaction commits (mirrors :mod:`echoroo.services.license_service` and
:mod:`echoroo.services.restricted_config_service`):

1. ``await create_invitation(...)`` / ``accept_invitation(...)`` /
   ``decline_invitation_by_recipient(...)`` flushes the row mutation and
   returns an outcome dataclass.
2. The endpoint commits its main transaction.
3. The endpoint calls ``trigger_post_commit_side_effects(outcome)`` which
   writes the audit row in a fresh session (FR-093 SERIALIZABLE contract).
   Failures here are WARNING-logged only — the persisted invitation row is
   the security-critical bit; observability is secondary.

The outbox-email enqueue was removed in spec/011 step 6 / T054; FR-011-103
makes the issuing admin's HTTP response the sole exfil path for the
plain-text invitation token.

This is the ONLY module in the package that calls :data:`AsyncSessionLocal`
directly — the fresh session is required because the audit writer issues
``SET TRANSACTION ISOLATION LEVEL SERIALIZABLE`` (FR-093), which PostgreSQL
rejects on a session that has already issued statements.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from echoroo.core.database import AsyncSessionLocal
from echoroo.models.enums import ProjectInvitationStatus
from echoroo.services.audit_service import AuditLogService

from .constants import (
    AUDIT_ACTION_INVITATION_REVOKE,
    AUDIT_ACTION_PROJECT_OWNERSHIP_BOOTSTRAP_TRANSFER,
)
from .outcomes import (
    InvitationAcceptOutcome,
    InvitationCreateOutcome,
    InvitationDeclineOutcome,
    InvitationPublicAcceptOutcome,
    InvitationRevokeOutcome,
)
from .tokens import _ensure_utc

logger = logging.getLogger(__name__)


async def emit_public_invitation_accept_audit(
    outcome: InvitationPublicAcceptOutcome,
) -> None:
    """Write the spec/011 T208 audit row in a fresh session.

    Mirrors :func:`_write_invitation_audit` for the new public-token
    accept path. The emitter is a best-effort post-commit hook —
    failures are WARNING-logged so observability never undoes the
    persisted membership / overlay row (FR-088 soft-alert pattern).

    spec/011 Step 9 (FR-011-123): when ``ownership_transferred`` is
    True the emitter also writes a second
    :data:`AUDIT_ACTION_PROJECT_OWNERSHIP_BOOTSTRAP_TRANSFER` row
    carrying the composite ``detail`` dict captured by the
    SAVEPOINT branch. The two rows are emitted independently so a
    write failure on one cannot mask the other.
    """
    invitation = outcome.invitation
    detail: dict[str, Any] = {
        "invitation_id": str(invitation.id),
        "kind": invitation.kind.value,
        "membership_created": outcome.membership_created,
        "ownership_transferred": outcome.ownership_transferred,
    }
    if outcome.member is not None:
        detail["member_id"] = str(outcome.member.id)
    if outcome.trusted_user is not None:
        detail["trusted_user_id"] = str(outcome.trusted_user.id)
    await _write_invitation_audit(
        action=outcome.audit_action,
        actor_user_id=outcome.accepting_user_id,
        project_id=invitation.project_id,
        request_id=outcome.request_id,
        ip=outcome.ip,
        user_agent=outcome.user_agent,
        detail=detail,
        before={"status": ProjectInvitationStatus.PENDING.value},
        after={"status": invitation.status.value},
    )
    if outcome.ownership_transferred and outcome.ownership_transfer_detail is not None:
        await _write_invitation_audit(
            action=AUDIT_ACTION_PROJECT_OWNERSHIP_BOOTSTRAP_TRANSFER,
            actor_user_id=outcome.accepting_user_id,
            project_id=invitation.project_id,
            request_id=outcome.request_id,
            ip=outcome.ip,
            user_agent=outcome.user_agent,
            detail=outcome.ownership_transfer_detail,
            before=(
                {"owner_id": str(outcome.prior_owner_id)}
                if outcome.prior_owner_id is not None
                else None
            ),
            after={"owner_id": str(outcome.accepting_user_id)},
        )


async def trigger_post_commit_side_effects(
    outcome: InvitationCreateOutcome
    | InvitationAcceptOutcome
    | InvitationDeclineOutcome
    | InvitationRevokeOutcome,
) -> None:
    """Fire audit side effects after the main TX commits.

    All side-effects are best-effort. Failures are WARNING-logged so
    observability does not undo the persisted invitation row.
    Three audit actions are emitted depending on the outcome type:

    * :class:`InvitationCreateOutcome` → ``project.invitation.create``
      (spec/011 step 6 / T054: the outbox-email enqueue is REMOVED — the
      plain-text envelope ``signed_token_envelope`` is surfaced to the
      issuing admin as the HTTP response's ``invitation_url`` field;
      it MUST NOT be persisted or telemetered past that single turn).
    * :class:`InvitationAcceptOutcome` → ``project.invitation.accept``.
    * :class:`InvitationDeclineOutcome` → ``project.invitation.decline``.
    """
    if isinstance(outcome, InvitationCreateOutcome):
        await _post_commit_create(outcome)
    elif isinstance(outcome, InvitationAcceptOutcome):
        await _post_commit_accept(outcome)
    elif isinstance(outcome, InvitationDeclineOutcome):
        await _post_commit_decline(outcome)
    elif isinstance(outcome, InvitationRevokeOutcome):
        await _post_commit_revoke(outcome)
    else:  # pragma: no cover — exhaustive
        logger.warning(
            "trigger_post_commit_side_effects: unknown outcome type %r",
            type(outcome).__name__,
        )


async def _post_commit_create(outcome: InvitationCreateOutcome) -> None:
    # spec/011 Step 6 (T054): outbound-email enqueue removed. The audit
    # emit remains so existing observability tooling keeps surfacing the
    # invitation issuance event; the plain-text envelope is intentionally
    # NOT included in the audit detail (FR-011-102: token confidentiality).
    invitation = outcome.invitation
    detail: dict[str, Any] = {
        "invitation_id": str(invitation.id),
        "kind": invitation.kind.value,
        "expires_at": _ensure_utc(invitation.expires_at).isoformat(),
        "is_new": outcome.is_new,
    }
    await _write_invitation_audit(
        action="project.invitation.create",
        actor_user_id=outcome.actor_user_id,
        project_id=invitation.project_id,
        request_id=outcome.request_id,
        ip=outcome.ip,
        user_agent=outcome.user_agent,
        detail=detail,
        before=None,
        after={"status": invitation.status.value},
    )


async def _post_commit_accept(outcome: InvitationAcceptOutcome) -> None:
    invitation = outcome.invitation
    detail: dict[str, Any] = {
        "invitation_id": str(invitation.id),
        "kind": invitation.kind.value,
        "is_replay": outcome.is_replay,
    }
    if outcome.member is not None:
        detail["member_id"] = str(outcome.member.id)
    if outcome.trusted_user is not None:
        detail["trusted_user_id"] = str(outcome.trusted_user.id)
    await _write_invitation_audit(
        action="project.invitation.accept",
        actor_user_id=outcome.actor_user_id,
        project_id=invitation.project_id,
        request_id=outcome.request_id,
        ip=outcome.ip,
        user_agent=outcome.user_agent,
        detail=detail,
        before={"status": ProjectInvitationStatus.PENDING.value},
        after={"status": invitation.status.value},
    )


async def _post_commit_decline(outcome: InvitationDeclineOutcome) -> None:
    invitation = outcome.invitation
    detail: dict[str, Any] = {
        "invitation_id": str(invitation.id),
        "kind": invitation.kind.value,
        "is_replay": outcome.is_replay,
    }
    await _write_invitation_audit(
        action="project.invitation.decline",
        actor_user_id=outcome.actor_user_id,
        project_id=invitation.project_id,
        request_id=outcome.request_id,
        ip=outcome.ip,
        user_agent=outcome.user_agent,
        detail=detail,
        before={"status": ProjectInvitationStatus.PENDING.value},
        after={"status": invitation.status.value},
    )


async def _post_commit_revoke(outcome: InvitationRevokeOutcome) -> None:
    """Emit the ``project.invitation.revoke`` audit row (spec/011 Step 8).

    The detail dict carries the operator-supplied ``reason`` (PII-gated at
    the schema layer) so an operator scanning the audit log can correlate
    revocations to support tickets without needing to join the audit row
    against a separate notes table. The plain-text envelope is NEVER
    surfaced here (FR-011-102: token confidentiality is preserved
    end-to-end).
    """
    invitation = outcome.invitation
    detail: dict[str, Any] = {
        "invitation_id": str(invitation.id),
        "kind": invitation.kind.value,
        "bound_email_hash": invitation.email_hash,
    }
    if outcome.reason is not None:
        detail["reason"] = outcome.reason
    await _write_invitation_audit(
        action=AUDIT_ACTION_INVITATION_REVOKE,
        actor_user_id=outcome.actor_user_id,
        project_id=invitation.project_id,
        request_id=outcome.request_id,
        ip=outcome.ip,
        user_agent=outcome.user_agent,
        detail=detail,
        before={"status": ProjectInvitationStatus.PENDING.value},
        after={"status": invitation.status.value},
    )


async def _write_invitation_audit(
    *,
    action: str,
    actor_user_id: UUID,
    project_id: UUID,
    request_id: str,
    ip: str,
    user_agent: str,
    detail: dict[str, Any],
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> None:
    """Append a project_audit_log row in a *fresh* session.

    A fresh session is required because the audit writer issues
    ``SET TRANSACTION ISOLATION LEVEL SERIALIZABLE`` (FR-093), which
    PostgreSQL rejects on a session that has already issued statements.
    """
    try:
        async with AsyncSessionLocal() as audit_session:
            try:
                service = AuditLogService(audit_session)
                await service.write_project_event(
                    actor_user_id=actor_user_id,
                    project_id=project_id,
                    action=action,
                    request_id=request_id,
                    ip=ip,
                    user_agent=user_agent,
                    detail=detail,
                    before=before,
                    after=after,
                )
                await audit_session.commit()
            except Exception:
                await audit_session.rollback()
                raise
    except Exception as exc:  # noqa: BLE001 — best effort; soft alert
        logger.warning(
            "%s audit write failed (FR-088 soft alert): "
            "actor=%s project=%s detail=%r error=%r",
            action,
            actor_user_id,
            project_id,
            detail,
            exc,
        )


# spec/011 Step 6 (T054): ``_enqueue_invitation_email`` removed. The
# Resend / SMTP outbox path is gone; FR-011-103 makes the issuing admin's
# HTTP response the sole exfil channel for the plain-text invitation
# token. Future maintainers: do NOT re-introduce an outbox-enqueue path
# here — every helper in ``services/email.py`` is a no-op stub as of
# Step 2 and the destructive migration ``0022`` removes the supporting
# tables entirely.
