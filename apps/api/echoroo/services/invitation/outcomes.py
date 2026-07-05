"""Invitation outcome dataclasses (the values endpoints need for side effects)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from echoroo.models.project import ProjectInvitation, ProjectMember
from echoroo.models.project_trusted_user import ProjectTrustedUser


@dataclass(frozen=True)
class InvitationCreateOutcome:
    """Snapshot returned by :func:`create_invitation`.

    Plain-text token surface (spec/011 FR-011-102..104):

    * ``signed_token_envelope`` is the 4-part HMAC envelope returned to
      the issuing admin once on the HTTP response (the ``invitation_url``
      body field). It MUST NOT be logged, telemetered, or persisted past
      that single HTTP turn — the formal supersede of spec/006 FR-051 by
      FR-011-103 makes the issuing admin's response the only exfil path
      for the plain-text token.
    * The endpoint surfaces ``signed_token_envelope`` directly into the
      ``invitation_url`` body field; ``invitation`` carries the safe
      subset of row metadata (id, expires_at, status). The two surfaces
      are kept apart so a refactor cannot accidentally serialise the
      envelope into the row-shaped JSON.

    Other fields:
        invitation: The freshly-flushed (not committed) invitation row.
        actor_user_id: User who issued the invitation (audit plumbing).
        request_id / ip / user_agent: Audit-row plumbing.
        is_new: ``False`` when the row was a duplicate idempotent return.
            Currently always ``True``; reserved for future deduplication
            of duplicate retries.
    """

    invitation: ProjectInvitation
    actor_user_id: UUID
    signed_token_envelope: str
    request_id: str = ""
    ip: str = ""
    user_agent: str = ""
    is_new: bool = True


@dataclass(frozen=True)
class InvitationAcceptOutcome:
    """Snapshot returned by :func:`accept_invitation`.

    The invitation row, the resulting ProjectMember (Member kind) or
    ProjectTrustedUser (Trusted kind), and audit/email plumbing.
    """

    invitation: ProjectInvitation
    member: ProjectMember | None
    trusted_user: ProjectTrustedUser | None
    actor_user_id: UUID
    is_replay: bool = False
    """``True`` when the same Idempotency-Key resolved a previously-accepted
    row — the endpoint should return 200 with the same payload (FR-053)."""

    request_id: str = ""
    ip: str = ""
    user_agent: str = ""


@dataclass(frozen=True)
class InvitationDeclineOutcome:
    """Snapshot returned by :func:`decline_invitation_by_recipient` (T512).

    ``is_replay`` is True for the second-and-onward decline of the same
    pending invitation — the endpoint returns 204 idempotently in either
    case (FR-107).
    """

    invitation: ProjectInvitation
    actor_user_id: UUID
    is_replay: bool = False
    request_id: str = ""
    ip: str = ""
    user_agent: str = ""


@dataclass(frozen=True)
class InvitationRevokeOutcome:
    """Snapshot returned by :func:`revoke_invitation` (spec/011 Step 8).

    Carries the freshly-flipped row plus the actor + audit-row plumbing so
    the post-commit emitter writes a single ``project.invitation.revoke``
    audit row inside its own SERIALIZABLE TX. ``reason`` is the operator-
    supplied free-form note (already PII-gated at the schema layer) and is
    embedded into the audit detail JSON; it is NOT persisted to a column
    on the row.
    """

    invitation: ProjectInvitation
    actor_user_id: UUID
    reason: str | None = None
    request_id: str = ""
    ip: str = ""
    user_agent: str = ""


@dataclass(frozen=True)
class InvitationResolveOutcome:
    """Snapshot returned by :func:`resolve_invitation_for_public_token`.

    Carries the safe subset of invitation metadata the public landing page
    needs to render its signup / accept form. ``authenticated_email_matches``
    is ``None`` when no session cookie was supplied (the resolver still
    succeeds — the frontend renders the signup branch).
    """

    invitation: ProjectInvitation
    project_name: str
    is_logged_in: bool
    authenticated_email_matches: bool | None


@dataclass(frozen=True)
class InvitationPublicAcceptOutcome:
    """Snapshot returned by :func:`accept_invitation_via_public_token`.

    The accepting user (newly created or pre-existing), the resulting
    membership / trusted-overlay row, the invitation row, and the branch
    discriminator used by the audit emitter. ``audit_action`` is one of
    :data:`AUDIT_ACTION_MEMBER_INVITE_ACCEPTED_SIGNUP`,
    :data:`AUDIT_ACTION_MEMBER_INVITE_ACCEPTED`, or
    :data:`AUDIT_ACTION_TRUSTED_INVITE_ACCEPTED` (T208).

    spec/011 Step 9 (FR-011-123): when the SAVEPOINT-nested ownership
    transfer fires, ``ownership_transferred`` flips to ``True`` and
    ``ownership_transfer_detail`` carries the composite ``detail`` JSON
    that :func:`emit_public_invitation_accept_audit` post-commits as a
    second :data:`AUDIT_ACTION_PROJECT_OWNERSHIP_BOOTSTRAP_TRANSFER`
    row alongside the regular invite-accept audit.
    """

    invitation: ProjectInvitation
    accepting_user_id: UUID
    member: ProjectMember | None
    trusted_user: ProjectTrustedUser | None
    audit_action: str
    membership_created: bool
    ownership_transferred: bool = False
    ownership_transfer_detail: dict[str, Any] | None = None
    prior_owner_id: UUID | None = None
    request_id: str = ""
    ip: str = ""
    user_agent: str = ""
