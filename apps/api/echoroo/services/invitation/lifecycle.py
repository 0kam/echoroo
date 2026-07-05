"""Public API: decline_invitation_by_recipient (T512) + revoke_invitation (Step 8)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.enums import ProjectInvitationStatus
from echoroo.models.project import ProjectInvitation

from .emails import _email_matches_invitation
from .errors import (
    InvitationEmailMismatchError,
    InvitationStateError,
    InvitationTokenInvalidError,
)
from .outcomes import InvitationDeclineOutcome, InvitationRevokeOutcome
from .tokens import hash_token, verify_invitation_token


async def decline_invitation_by_recipient(
    session: AsyncSession,
    *,
    signed_token: str,
    current_user_id: UUID,
    current_user_email: str,
    hmac_secret: str,
    project_id_scope: UUID | None = None,
    now: datetime | None = None,
    request_id: str = "",
    ip: str = "",
    user_agent: str = "",
) -> InvitationDeclineOutcome:
    """Recipient-driven self-decline (T512 skeleton).

    Mirrors :func:`accept_invitation` for HMAC verification + email match
    but transitions ``status`` to ``DECLINED`` instead. Idempotent: a
    second decline of the same row returns ``is_replay=True`` so the
    endpoint can return 204 either way.

    The full handler-side enumeration mapping (404 on email mismatch /
    token unknown / others' token, 410 on terminal states, 204 on pending
    + replay) lives in T512's endpoint layer; this service surfaces the
    distinct error classes so the handler can perform the mapping.
    """
    now_eff = now or datetime.now(UTC)

    raw_token_b64u, _ = verify_invitation_token(
        signed_token, hmac_secret=hmac_secret, now=now_eff,
    )
    token_hash = hash_token(raw_token_b64u)

    result = await session.execute(
        select(ProjectInvitation)
        .where(ProjectInvitation.token_hash == token_hash)
        .with_for_update(),
    )
    invitation = result.scalar_one_or_none()
    if invitation is None:
        raise InvitationTokenInvalidError("invitation not found")

    # Phase 10 Batch 2 Round 2 fix (致命 3): URL path ``project_id`` must
    # match the row. See :func:`accept_invitation` for the rationale.
    if project_id_scope is not None and invitation.project_id != project_id_scope:
        raise InvitationTokenInvalidError("invitation not found")

    if not _email_matches_invitation(
        current_user_email,
        invitation,
        hmac_secret=hmac_secret,
    ):
        raise InvitationEmailMismatchError(
            "current user's email does not match the invitation",
        )

    if invitation.status == ProjectInvitationStatus.DECLINED:
        # Idempotent replay path (FR-107).
        return InvitationDeclineOutcome(
            invitation=invitation,
            actor_user_id=current_user_id,
            is_replay=True,
            request_id=request_id,
            ip=ip,
            user_agent=user_agent,
        )
    if invitation.status != ProjectInvitationStatus.PENDING:
        raise InvitationStateError(
            f"invitation is in terminal state: {invitation.status.value}"
        )

    invitation.status = ProjectInvitationStatus.DECLINED
    invitation.declined_at = now_eff
    await session.flush()

    return InvitationDeclineOutcome(
        invitation=invitation,
        actor_user_id=current_user_id,
        is_replay=False,
        request_id=request_id,
        ip=ip,
        user_agent=user_agent,
    )


async def revoke_invitation(
    session: AsyncSession,
    *,
    project_id: UUID,
    invitation_id: UUID,
    actor_user_id: UUID,
    reason: str | None = None,
    now: datetime | None = None,
    request_id: str = "",
    ip: str = "",
    user_agent: str = "",
) -> InvitationRevokeOutcome:
    """Atomically transition a pending invitation to ``revoked``.

    spec/011 FR-011-115 + contract YAML
    ``member-invitations.yaml`` POST
    ``/projects/{project_id}/invitations/{invitation_id}/revoke``.

    The UPDATE re-checks ``status='pending'`` AND ``project_id`` so a
    racing accept / decline / revoke / cross-project lookup collapses to
    the same generic ``InvitationStateError`` raise — the endpoint maps
    every cause to HTTP 404 (anti-enumeration: a leaked invitation_id
    must not let the caller distinguish "wrong project" from "already
    accepted" from "already revoked" from "does not exist").

    Args:
        session: Caller-owned async session. Caller commits.
        project_id: URL-bound project scope; the row's stored
            ``project_id`` MUST match or the function raises
            :class:`InvitationStateError`.
        invitation_id: Target row id.
        actor_user_id: Owner / Admin performing the revoke (audit).
        reason: Optional free-form note (already PII-gated at the schema
            layer). Embedded into the outcome for the audit emitter only;
            no DB column is touched for the reason (the row does not
            currently carry a ``revoked_reason`` column).

    Returns:
        :class:`InvitationRevokeOutcome` carrying the freshly-flipped
        row (status='revoked', revoked_at=now). The outcome is consumed
        by :func:`trigger_post_commit_side_effects` which emits a
        ``project.invitation.revoke`` audit row after the caller commits.

    Raises:
        InvitationStateError: row not found OR project_id mismatch OR
            row is no longer pending. The endpoint MUST map every
            instance of this raise to HTTP 404 with a uniform body so
            an attacker cannot enumerate invitation_ids.
    """
    now_eff = now or datetime.now(UTC)

    # Atomic compare-and-swap. The WHERE clause re-checks status='pending'
    # AND project_id so a concurrent revoke / accept / decline races us to
    # zero rows returned. RETURNING * fetches the freshly-updated row
    # without a follow-up SELECT.
    update_stmt = text(
        """
        UPDATE project_invitations
           SET status = 'revoked',
               revoked_at = :now,
               updated_at = :now
         WHERE id = :invitation_id
           AND project_id = :project_id
           AND status = 'pending'
        RETURNING id
        """
    )
    update_result = await session.execute(
        update_stmt,
        {
            "now": now_eff,
            "invitation_id": invitation_id,
            "project_id": project_id,
        },
    )
    if update_result.fetchone() is None:
        # Anti-enumeration uniform-failure (spec/011 FR-011-115 / contract
        # YAML revoke 404 collapse): row does not exist OR belongs to a
        # different project OR is already terminal. All three cases
        # surface the SAME generic-invalid raise.
        raise InvitationStateError("invitation not revocable")

    # Re-attach the freshly-updated row to the ORM identity map. We need
    # the full row for the audit emitter (kind / email_hash / role).
    result = await session.execute(
        select(ProjectInvitation).where(
            ProjectInvitation.id == invitation_id,
        ),
    )
    invitation = result.scalar_one()
    invitation.status = ProjectInvitationStatus.REVOKED
    invitation.revoked_at = now_eff

    return InvitationRevokeOutcome(
        invitation=invitation,
        actor_user_id=actor_user_id,
        reason=reason,
        request_id=request_id,
        ip=ip,
        user_agent=user_agent,
    )
