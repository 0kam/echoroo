"""Project invitation service package (Phase 10 / T502, FR-047..056, spec/011).

This package owns issuance and consumption of :class:`ProjectInvitation`
rows for both ``kind='member'`` and ``kind='trusted'`` invitations. It was
split out of the former monolithic ``echoroo.services.invitation_service``
module; that module now survives as a thin backward-compatible façade that
re-exports the names below.

Module layout (dependency DAG leaf → root):

* :mod:`~.constants` — tunables + audit-action + Redis-key constants.
* :mod:`~.errors` — domain error hierarchy.
* :mod:`~.outcomes` — outcome dataclasses.
* :mod:`~.tokens` — hashing / HMAC token envelope helpers.
* :mod:`~.emails` — email canonicalisation + keyed-hash helpers.
* :mod:`~.rate_limit` — FR-056 rate limiter.
* :mod:`~.idempotency` — FR-053 idempotency-key cache.
* :mod:`~.grants` — permission allowlist + membership guards.
* :mod:`~.create` — ``create_invitation``.
* :mod:`~.accept` — ``accept_invitation``.
* :mod:`~.public` — public-token resolve + accept.
* :mod:`~.lifecycle` — decline + revoke.
* :mod:`~.side_effects` — post-commit audit writers (the ONLY module that
  calls :data:`AsyncSessionLocal` directly).
"""

from __future__ import annotations

from .accept import accept_invitation
from .constants import (
    AUDIT_ACTION_INVITATION_REVOKE,
    AUDIT_ACTION_MEMBER_INVITE_ACCEPTED,
    AUDIT_ACTION_MEMBER_INVITE_ACCEPTED_SIGNUP,
    AUDIT_ACTION_PROJECT_OWNERSHIP_BOOTSTRAP_TRANSFER,
    AUDIT_ACTION_TRUSTED_INVITE_ACCEPTED,
    INVITATION_MAX_TTL_SECONDS,
    INVITATION_TTL_SECONDS,
    RATE_LIMIT_ACTOR_PER_HOUR,
    RATE_LIMIT_PROJECT_PER_HOUR,
    TOKEN_BYTES,
    TRUSTED_DEFAULT_DURATION_SECONDS,
    TRUSTED_MAX_DURATION_SECONDS,
)
from .create import create_invitation
from .emails import (
    _canonical_email,
    _email_matches_invitation,
    canonicalize_email,
    hash_email,
    hash_email_dual,
)
from .errors import (
    InvitationActiveMemberError,
    InvitationAlreadyMemberError,
    InvitationConflictError,
    InvitationEmailMismatchError,
    InvitationError,
    InvitationInfraUnavailableError,
    InvitationRateLimitError,
    InvitationStateError,
    InvitationTokenInvalidError,
    InvitationValidationError,
)
from .grants import coerce_granted_permissions
from .idempotency import (
    _get_idempotent_outcome,
    _idempotency_redis_key,
    _IdempotencyRecord,
    _set_idempotent_outcome,
)
from .lifecycle import decline_invitation_by_recipient, revoke_invitation
from .outcomes import (
    InvitationAcceptOutcome,
    InvitationCreateOutcome,
    InvitationDeclineOutcome,
    InvitationPublicAcceptOutcome,
    InvitationResolveOutcome,
    InvitationRevokeOutcome,
)
from .public import (
    accept_invitation_via_public_token,
    resolve_invitation_for_public_token,
)
from .rate_limit import check_rate_limits
from .side_effects import (
    _write_invitation_audit,
    emit_public_invitation_accept_audit,
    trigger_post_commit_side_effects,
)
from .tokens import (
    _b64u_decode,
    _b64u_encode,
    _ensure_utc,
    hash_token,
    sign_invitation_token,
    verify_invitation_token,
)

__all__ = [
    # Private names re-exported for the backward-compatible façade
    # (``echoroo.services.invitation_service``) and historical callers.
    "_IdempotencyRecord",
    "_b64u_decode",
    "_b64u_encode",
    "_canonical_email",
    "_email_matches_invitation",
    "_ensure_utc",
    "_get_idempotent_outcome",
    "_idempotency_redis_key",
    "_set_idempotent_outcome",
    "_write_invitation_audit",
    "AUDIT_ACTION_INVITATION_REVOKE",
    "AUDIT_ACTION_MEMBER_INVITE_ACCEPTED",
    "AUDIT_ACTION_MEMBER_INVITE_ACCEPTED_SIGNUP",
    "AUDIT_ACTION_PROJECT_OWNERSHIP_BOOTSTRAP_TRANSFER",
    "AUDIT_ACTION_TRUSTED_INVITE_ACCEPTED",
    "INVITATION_MAX_TTL_SECONDS",
    "INVITATION_TTL_SECONDS",
    "InvitationAcceptOutcome",
    "InvitationActiveMemberError",
    "InvitationAlreadyMemberError",
    "InvitationConflictError",
    "InvitationCreateOutcome",
    "InvitationDeclineOutcome",
    "InvitationEmailMismatchError",
    "InvitationError",
    "InvitationInfraUnavailableError",
    "InvitationPublicAcceptOutcome",
    "InvitationRateLimitError",
    "InvitationResolveOutcome",
    "InvitationRevokeOutcome",
    "InvitationStateError",
    "InvitationTokenInvalidError",
    "InvitationValidationError",
    "RATE_LIMIT_ACTOR_PER_HOUR",
    "RATE_LIMIT_PROJECT_PER_HOUR",
    "TOKEN_BYTES",
    "TRUSTED_DEFAULT_DURATION_SECONDS",
    "TRUSTED_MAX_DURATION_SECONDS",
    "accept_invitation",
    "accept_invitation_via_public_token",
    "canonicalize_email",
    "check_rate_limits",
    "coerce_granted_permissions",
    "create_invitation",
    "decline_invitation_by_recipient",
    "emit_public_invitation_accept_audit",
    "hash_email",
    "hash_email_dual",
    "hash_token",
    "resolve_invitation_for_public_token",
    "revoke_invitation",
    "sign_invitation_token",
    "trigger_post_commit_side_effects",
    "verify_invitation_token",
]
