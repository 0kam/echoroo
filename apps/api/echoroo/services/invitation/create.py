"""Public API: create_invitation (FR-047 / FR-048 / FR-051..056)."""

from __future__ import annotations

import secrets
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.permissions import Permission
from echoroo.models.enums import (
    ProjectInvitationKind,
    ProjectInvitationStatus,
    ProjectMemberRole,
)
from echoroo.models.project import ProjectInvitation

from .constants import (
    INVITATION_MAX_TTL_SECONDS,
    INVITATION_TTL_SECONDS,
    TOKEN_BYTES,
    TRUSTED_DEFAULT_DURATION_SECONDS,
    TRUSTED_MAX_DURATION_SECONDS,
)
from .emails import hash_email, hash_email_dual
from .errors import (
    InvitationConflictError,
    InvitationStateError,
    InvitationValidationError,
)
from .grants import _reject_if_active_member, coerce_granted_permissions
from .outcomes import InvitationCreateOutcome
from .rate_limit import check_rate_limits
from .tokens import _b64u_encode, hash_token, sign_invitation_token

if TYPE_CHECKING:
    from redis.asyncio import Redis


async def create_invitation(
    session: AsyncSession,
    *,
    project_id: UUID,
    kind: ProjectInvitationKind,
    email: str,
    invited_by_id: UUID,
    hmac_secret: str,
    redis: Redis,
    role: ProjectMemberRole | None = None,
    granted_permissions: Sequence[str | Permission] | None = None,
    trusted_duration_seconds: int | None = None,
    invitation_ttl_seconds: int | None = None,
    ownership_transfer_on_accept: bool = False,
    request_id: str = "",
    ip: str = "",
    user_agent: str = "",
    now: datetime | None = None,
) -> InvitationCreateOutcome:
    """Issue a Member or Trusted invitation, returning a signed URL token.

    Steps:

    1. Validate the kind × payload combination (FR-048 mirrored at the
       application layer so we can raise structured errors before the DB
       check kicks in). spec/011 R5 — reject
       ``ownership_transfer_on_accept=True`` when ``kind != MEMBER``.
    2. ``check_rate_limits`` — FR-056 (fail-closed; Redis required).
    3. Generate the 256-bit raw token, compute ``token_hash`` and
       the 4-part HMAC-signed envelope (FR-052 / NFR-011-010).
    4. Insert the row inside the caller's transaction. Caller commits.
       The signed envelope is attached to the outcome as
       ``signed_token_envelope`` for the handler to surface as
       ``invitation_url`` (FR-011-102..104).

    Args:
        session: Caller-owned async session. Caller commits.
        project_id: Target project.
        kind: Invitation kind discriminator.
        email: Plain-text recipient email; ``email_hash`` is computed here.
        invited_by_id: Owner / Admin issuing the invitation.
        hmac_secret: HMAC key for the ``email_hash`` column. Pass
            ``settings.web_session_secret`` from the endpoint. The
            invitation envelope itself is signed under the env-driven
            ``INVITATION_TOKEN_KID_NEW`` / ``HMAC_KEY`` pair
            (spec/011 NFR-011-010) — independent of this argument.
        redis: Async Redis client used by the FR-056 rate limiter (and the
            FR-053 idempotency cache on accept). Required — fail-closed.
        role: Required when ``kind=='member'``.
        granted_permissions: Required when ``kind=='trusted'``.
        trusted_duration_seconds: Required when ``kind=='trusted'``;
            defaults handled by the endpoint per spec.
        invitation_ttl_seconds: Optional override of the FR-052 default
            (7 days). Hard-capped at :data:`INVITATION_MAX_TTL_SECONDS`;
            anything larger raises :class:`InvitationValidationError` so
            an operator cannot extend the URL window beyond spec.
        ownership_transfer_on_accept: spec/011 FR-011-121..125 flag. When
            ``True`` MUST be paired with ``kind=ProjectInvitationKind.MEMBER``
            (R5); other kinds raise :class:`InvitationStateError`.
        request_id / ip / user_agent: Audit plumbing (passed through to
            the outcome dataclass; the writer hashes them later).
        now: Override for ``datetime.now(UTC)`` — testing only.

    Returns:
        :class:`InvitationCreateOutcome` carrying the row and the
        ``signed_token_envelope`` (FR-011-102..104). The handler surfaces
        the envelope as the ``invitation_url`` body field; it MUST NOT
        appear in logs, telemetry, or any persisted column past this
        single HTTP turn.

    Raises:
        InvitationValidationError: Bad payload combination or TTL > 7 d.
        InvitationStateError: R5 — ``ownership_transfer_on_accept`` set
            on a non-MEMBER kind (defence in depth above the DB CHECK
            added by migration 0021).
        InvitationRateLimitError: Rate limit exceeded.
        InvitationInfraUnavailableError: Redis is unreachable.
        InvitationConflictError: A pending invitation already exists for
            ``(project_id, email_hash)``.
        InvitationActiveMemberError: The recipient email resolves to a user
            that already holds an active membership on ``project_id``
            (preview issue #4 — issue-time existing-member guard).
    """
    now_eff = now or datetime.now(UTC)

    # 0. TTL guard (FR-052 hard cap = 7 days).
    if invitation_ttl_seconds is None:
        ttl_seconds = INVITATION_TTL_SECONDS
    else:
        ttl_seconds = invitation_ttl_seconds
    if not 1 <= ttl_seconds <= INVITATION_MAX_TTL_SECONDS:
        raise InvitationValidationError(
            "invitation_ttl_seconds must be in "
            f"[1, {INVITATION_MAX_TTL_SECONDS}] (FR-052 hard cap = 7 days)"
        )

    # 0.5. spec/011 R5 (FR-011-122..125) — ``ownership_transfer_on_accept``
    # is only valid for Member-kind invitations. The DB
    # ``ck_project_invitations_ownership_transfer_kind_member`` CHECK
    # constraint (migration 0021) is the source of truth; this
    # application-level guard surfaces a typed error BEFORE the INSERT
    # so callers get a structured error class instead of a bare
    # IntegrityError. Order matters: we evaluate the cheap kind check
    # before any DB round-trip and before rate-limit consumption.
    if ownership_transfer_on_accept and kind is not ProjectInvitationKind.MEMBER:
        raise InvitationStateError(
            "ownership_transfer_on_accept_invalid_for_kind",
        )

    # 1. kind × payload validation (FR-048)
    if kind is ProjectInvitationKind.MEMBER:
        if role is None:
            raise InvitationValidationError(
                "role is required when kind='member'"
            )
        if granted_permissions is not None or trusted_duration_seconds is not None:
            raise InvitationValidationError(
                "granted_permissions / trusted_duration_seconds must be NULL "
                "when kind='member'"
            )
        granted_perms_db: list[str] | None = None
        duration_db: int | None = None
    elif kind is ProjectInvitationKind.TRUSTED:
        if role is not None:
            raise InvitationValidationError(
                "role must be NULL when kind='trusted'"
            )
        if granted_permissions is None:
            raise InvitationValidationError(
                "granted_permissions is required when kind='trusted'"
            )
        if trusted_duration_seconds is None:
            trusted_duration_seconds = TRUSTED_DEFAULT_DURATION_SECONDS
        if not 1 <= trusted_duration_seconds <= TRUSTED_MAX_DURATION_SECONDS:
            raise InvitationValidationError(
                f"trusted_duration_seconds must be in [1, {TRUSTED_MAX_DURATION_SECONDS}]"
            )
        valid_perms = coerce_granted_permissions(granted_permissions)
        granted_perms_db = sorted(p.value for p in valid_perms)
        duration_db = trusted_duration_seconds
    else:  # pragma: no cover - StrEnum exhaustive
        raise InvitationValidationError(f"unknown invitation kind: {kind!r}")

    # 2. rate limit (FR-056) — fail-closed
    await check_rate_limits(
        redis, actor_user_id=invited_by_id, project_id=project_id,
    )

    # 2.5. Existing-active-member guard (preview issue #4). If the recipient
    # email resolves to a registered user that already holds an active
    # ProjectMember row on this project, reject AT ISSUE TIME with a typed
    # conflict instead of letting the duplicate invitation linger and only
    # fail later at accept (FR-011-106). An unregistered email has no
    # membership row, so this branch is skipped and the normal
    # pending-duplicate guard (the partial unique index) takes over. The
    # check runs AFTER the rate limiter so a rejected attempt counts toward
    # the issuer's quota exactly like the pending-duplicate path.
    await _reject_if_active_member(
        session,
        project_id=project_id,
        email=email,
    )

    # 3. token + hash (FR-051 / FR-052 / FR-055)
    raw_token_b64u = _b64u_encode(secrets.token_bytes(TOKEN_BYTES))
    token_hash = hash_token(raw_token_b64u)
    expires_at = now_eff + timedelta(seconds=ttl_seconds)
    signed_token = sign_invitation_token(
        raw_token_b64u=raw_token_b64u,
        expires_at=expires_at,
        hmac_secret=hmac_secret,
    )
    email_hash_value = hash_email(email, hmac_secret=hmac_secret)
    # Phase 17 backlog A-2 (FR-091b): emit the KMS dual-write hash
    # into the ``email_hash_v2`` sibling so future lookups can match
    # under v1 OR v2 of the rotated PII CMK without needing the
    # legacy ``web_session_secret`` to remain stable.
    #
    # Round 2 R1-C1: ``email_hash_v2`` is a TRUE v2 column. We only
    # populate it when the dual-write helper actually produced a v2
    # component (i.e. rotation has started and ``get_pii_hash_version``
    # → 2). In single-key mode we leave it NULL so the daily
    # backfill worker (``pii_hash_backfill.py``) — which selects on
    # ``email_hash_v2 IS NULL`` — can pick the row up the moment an
    # operator flips the v2 alias on. Writing the v1 value here would
    # otherwise hide single-key-period invitations from the backfill
    # forever.
    email_hash_kms = hash_email_dual(email)
    if "v2" in email_hash_kms:
        email_hash_v2_value: str | None = email_hash_kms["v2"]
        pii_hash_version_value: int | None = 2
    else:
        email_hash_v2_value = None
        pii_hash_version_value = None

    # 4. Insert (caller-owned TX). The (project_id, email_hash) WHERE
    # status='pending' partial unique index is the FR-049 guard; collisions
    # surface as IntegrityError, which we map to InvitationConflictError.
    #
    # Round trip note: the ``granted_permissions`` column is JSONB; passing
    # Python ``None`` to a JSONB attribute would otherwise serialise as the
    # JSON literal ``null`` (not SQL NULL), which trips
    # ``ck_project_invitations_kind_fields`` because the CHECK uses
    # ``IS NULL``. We therefore omit the column from the constructor when
    # the value is None — SQLAlchemy honours the column's
    # ``nullable=True`` default and INSERTs SQL NULL.
    invitation_kwargs: dict[str, Any] = {
        "project_id": project_id,
        "kind": kind,
        "email": email,
        "email_hash": email_hash_value,
        "email_hash_v2": email_hash_v2_value,
        "pii_hash_version": pii_hash_version_value,
        "role": role if kind is ProjectInvitationKind.MEMBER else None,
        "trusted_duration_seconds": duration_db,
        "token_hash": token_hash,
        "invited_by_id": invited_by_id,
        "expires_at": expires_at,
        "status": ProjectInvitationStatus.PENDING,
        "ownership_transfer_on_accept": ownership_transfer_on_accept,
    }
    if granted_perms_db is not None:
        invitation_kwargs["granted_permissions"] = granted_perms_db
    invitation = ProjectInvitation(**invitation_kwargs)
    session.add(invitation)
    try:
        await session.flush()
    except IntegrityError as exc:
        # The endpoint will rollback; surface a typed error so the audit
        # log records the reason without leaking stack traces.
        raise InvitationConflictError(
            "an equivalent pending invitation already exists",
        ) from exc

    return InvitationCreateOutcome(
        invitation=invitation,
        actor_user_id=invited_by_id,
        signed_token_envelope=signed_token,
        request_id=request_id,
        ip=ip,
        user_agent=user_agent,
    )
