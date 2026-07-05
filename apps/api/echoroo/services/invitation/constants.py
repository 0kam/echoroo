"""Invitation-service constants (spec/006 FR-047..056, spec/011).

The audit-action constants are deliberately service-private (per HANDOFF
line 79) so renames stay local to the package; the ``verb.noun.verb``
3-segment pattern matches the rest of the existing audit catalogue.
"""

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Raw token length in bytes (256 bits, FR-051).
TOKEN_BYTES: int = 32

#: Default token TTL (FR-052: 7 days). The function signature exposes this
#: as the *only* knob a caller can use; values exceeding the cap raise
#: :class:`InvitationValidationError` (FR-052 hard cap).
INVITATION_TTL_SECONDS: int = 7 * 24 * 3600

#: FR-052 hard cap: the issued token MUST NOT live past 7 days.
INVITATION_MAX_TTL_SECONDS: int = INVITATION_TTL_SECONDS

#: Default Trusted overlay duration (FR-043: 90 days).
TRUSTED_DEFAULT_DURATION_SECONDS: int = 90 * 24 * 3600

#: Hard cap on Trusted overlay duration (FR-043: 1 year).
TRUSTED_MAX_DURATION_SECONDS: int = 365 * 24 * 3600

#: FR-056: invitation rate limits.
RATE_LIMIT_ACTOR_PER_HOUR: int = 50
RATE_LIMIT_PROJECT_PER_HOUR: int = 200
_RATE_LIMIT_WINDOW_SECONDS: int = 3600

#: FR-053 idempotency: cached accept outcomes live for 24 h. Same key,
#: same token -> 200 dedupe; same key, different token -> 409 conflict.
_IDEMPOTENCY_TTL_SECONDS: int = 24 * 3600
_IDEMPOTENCY_KEY_PREFIX: str = "idem:invite:accept:"

# spec/011 FR-011-106 / T208 — audit-action constants for the three accept
# branches. The constants are deliberately service-private (per HANDOFF
# line 79) so renames stay local to this module; the verb.noun.verb
# 3-segment pattern matches the rest of the existing audit catalogue.
AUDIT_ACTION_MEMBER_INVITE_ACCEPTED_SIGNUP: Final[str] = (
    "project.member.invite_accepted_signup"
)
AUDIT_ACTION_MEMBER_INVITE_ACCEPTED: Final[str] = (
    "project.member.invite_accepted"
)
AUDIT_ACTION_TRUSTED_INVITE_ACCEPTED: Final[str] = (
    "project.trusted_user.invite_accepted"
)

# spec/011 Step 8 — Owner / Admin revoke of a pending invitation. The constant
# stays service-private (HANDOFF line 79) and uses the verb.noun.verb 3-segment
# convention. The post-commit emitter writes it into ``project_audit_log``
# alongside the existing ``project.invitation.create`` / ``.accept`` rows.
AUDIT_ACTION_INVITATION_REVOKE: Final[str] = "project.invitation.revoke"

# spec/011 Step 9 (FR-011-123) — SU bootstrap composite ownership-transfer
# audit. Emitted once per successful ``accept_invitation_via_public_token``
# call on a row that carries ``ownership_transfer_on_accept=True``. The
# composite ``detail`` JSON includes the prior + new owner ids plus the
# :func:`build_pre_transfer_action_summary` blob so the new owner has a
# redacted summary of what the SU did before the handoff. Service-private
# per HANDOFF line 79.
AUDIT_ACTION_PROJECT_OWNERSHIP_BOOTSTRAP_TRANSFER: Final[str] = (
    "project.ownership.bootstrap_transfer"
)
