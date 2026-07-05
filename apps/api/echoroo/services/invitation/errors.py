"""Invitation-service domain errors (engine-level; the endpoint maps to HTTP)."""

from __future__ import annotations

from echoroo.models.enums import ProjectMemberRole


class InvitationError(Exception):
    """Base class for invitation-service domain errors."""


class InvitationValidationError(InvitationError):
    """Pre-DB validation failure (HTTP 422)."""


class InvitationRateLimitError(InvitationError):
    """FR-056: Owner/Admin or project hit the issue rate cap (HTTP 429)."""


class InvitationConflictError(InvitationError):
    """An equivalent pending invitation already exists (HTTP 409)."""


class InvitationTokenInvalidError(InvitationError):
    """FR-052: HMAC signature missing/expired/tampered (HTTP 410)."""


class InvitationStateError(InvitationError):
    """FR-053: invitation already accepted/declined/revoked/expired (HTTP 410)."""


class InvitationEmailMismatchError(InvitationError):
    """FR-054: invitation email != caller email (HTTP 403, public-shape 404).

    The endpoint MAY render this as 404 to honour FR-055 enumeration
    guarantees; the service raises a distinct class so the audit log can
    record the real reason.
    """


class InvitationInfraUnavailableError(InvitationError):
    """FR-056: the rate-limiter (Redis) is unreachable.

    Mapped to HTTP 503 by the endpoint. We deliberately fail **closed**:
    accepting issuance under a partial Redis outage would let an attacker
    spray invitations past the documented rate cap.
    """


class InvitationAlreadyMemberError(InvitationError):
    """spec/011 FR-011-106 step 3 — caller is already a member of the project.

    Raised by the existing-user accept branch when the authenticated caller
    already holds an active membership row on the target project at the
    same OR higher role than the invitation grants. The endpoint maps this
    to HTTP 409 with a generic ``already a member`` body. The bound-email
    check has already succeeded by the time this error fires, so the
    response intentionally reveals that the caller IS the right recipient —
    it just has nothing new to grant.
    """


class InvitationActiveMemberError(InvitationError):
    """Issue-time guard — the target email already belongs to an active member.

    Raised by :func:`create_invitation` when the recipient email resolves to
    a registered user that already holds an active :class:`ProjectMember` row
    on the target project. The endpoint maps this to HTTP 409 with the
    ``already_member`` error code so an operator gets immediate feedback at
    issue time instead of the duplicate silently failing later at accept.

    The error carries the existing member's :class:`ProjectMemberRole` so the
    handler can surface the current role in the message. This branch only
    fires for emails that resolve to a known user — an unregistered email has
    no membership row and proceeds through the normal pending-duplicate guard.
    The conflict signal is therefore no stronger an enumeration oracle than
    the existing :class:`InvitationConflictError` pending path, which already
    distinguishes a pending-invited email from a fresh one.
    """

    def __init__(self, message: str, *, role: ProjectMemberRole) -> None:
        super().__init__(message)
        self.role = role
