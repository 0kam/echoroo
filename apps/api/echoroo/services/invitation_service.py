"""Backward-compatible façade for the invitation service package.

The former 2670-LOC monolith was split into the
:mod:`echoroo.services.invitation` package (W3-1). This module survives as
a thin compatibility shim so existing callers and tests that import from
``echoroo.services.invitation_service`` keep working unchanged. New code
SHOULD import from :mod:`echoroo.services.invitation` (or a specific
submodule) directly.

Note: :data:`AsyncSessionLocal` is deliberately NOT re-exported here — the
fresh-session audit writer lives in
:mod:`echoroo.services.invitation.side_effects`, which is the only module
that references it. Test harnesses that rebind ``AsyncSessionLocal`` per
event loop MUST target that submodule (``raising=True`` then fails loudly
if the retarget drifts).
"""

from __future__ import annotations

from echoroo.core.permissions import (
    TRUSTED_ALLOWED_PERMISSIONS as TRUSTED_ALLOWED_PERMISSIONS,
)
from echoroo.services import invitation as _invitation
from echoroo.services.invitation import (
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
    InvitationAcceptOutcome,
    InvitationActiveMemberError,
    InvitationAlreadyMemberError,
    InvitationConflictError,
    InvitationCreateOutcome,
    InvitationDeclineOutcome,
    InvitationEmailMismatchError,
    InvitationError,
    InvitationInfraUnavailableError,
    InvitationPublicAcceptOutcome,
    InvitationRateLimitError,
    InvitationResolveOutcome,
    InvitationRevokeOutcome,
    InvitationStateError,
    InvitationTokenInvalidError,
    InvitationValidationError,
    accept_invitation,
    accept_invitation_via_public_token,
    canonicalize_email,
    check_rate_limits,
    coerce_granted_permissions,
    create_invitation,
    decline_invitation_by_recipient,
    emit_public_invitation_accept_audit,
    hash_email,
    hash_email_dual,
    hash_token,
    resolve_invitation_for_public_token,
    revoke_invitation,
    sign_invitation_token,
    trigger_post_commit_side_effects,
    verify_invitation_token,
)

# Private names re-exported for backward compatibility with historical
# callers (``workers/pii_hash_backfill.py``) and tests that reference them
# through this module. New code SHOULD import them from their owning
# submodule instead. Plain assignments (rather than ``import ... as``) keep
# the re-export explicit without tripping the unused-import lint.
_b64u_decode = _invitation._b64u_decode
_b64u_encode = _invitation._b64u_encode
_canonical_email = _invitation._canonical_email
_email_matches_invitation = _invitation._email_matches_invitation
_ensure_utc = _invitation._ensure_utc
_get_idempotent_outcome = _invitation._get_idempotent_outcome
_idempotency_redis_key = _invitation._idempotency_redis_key
_IdempotencyRecord = _invitation._IdempotencyRecord
_set_idempotent_outcome = _invitation._set_idempotent_outcome
_write_invitation_audit = _invitation._write_invitation_audit

__all__ = [
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
