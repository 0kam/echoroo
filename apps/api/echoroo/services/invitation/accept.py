"""Public API: accept_invitation (FR-053 / FR-054)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.enums import (
    ProjectInvitationKind,
    ProjectInvitationStatus,
    ProjectTrustedStatus,
)
from echoroo.models.project import ProjectInvitation, ProjectMember
from echoroo.models.project_trusted_user import ProjectTrustedUser

from .constants import TRUSTED_MAX_DURATION_SECONDS
from .emails import _email_matches_invitation
from .errors import (
    InvitationConflictError,
    InvitationEmailMismatchError,
    InvitationStateError,
    InvitationTokenInvalidError,
    InvitationValidationError,
)
from .grants import _load_existing_grant, coerce_granted_permissions
from .idempotency import (
    _get_idempotent_outcome,
    _IdempotencyRecord,
    _set_idempotent_outcome,
)
from .outcomes import InvitationAcceptOutcome
from .tokens import _ensure_utc, hash_token, verify_invitation_token

if TYPE_CHECKING:
    from redis.asyncio import Redis


async def accept_invitation(
    session: AsyncSession,
    *,
    signed_token: str,
    current_user_id: UUID,
    current_user_email: str,
    hmac_secret: str,
    redis: Redis,
    idempotency_key: str | None = None,
    project_id_scope: UUID | None = None,
    now: datetime | None = None,
    request_id: str = "",
    ip: str = "",
    user_agent: str = "",
) -> InvitationAcceptOutcome:
    """Consume an invitation atomically (FR-053 / FR-054).

    Implementation contract (strict order — see security review):

    1. **HMAC verify** the signed token; reject expired / tampered tokens
       with :class:`InvitationTokenInvalidError`.
    2. **(Optional) idempotency-key short-circuit**: if ``idempotency_key``
       is supplied and Redis already has a record bound to a *different*
       token, raise :class:`InvitationConflictError` (HTTP 409). If the
       record matches the current token, return a replay outcome.
    3. **Row lookup** by ``token_hash`` with ``SELECT ... FOR UPDATE`` so
       two parallel accepts serialise on the same row.
    4. **Email match check** (NFKC + casefold; FR-054). Performed *before*
       the status check so a user holding a token issued for someone else
       always gets 403 — they never learn whether the invitation has
       already been consumed (FR-055 enumeration mitigation, prevents
       cross-account accepted-token replay).
    5. **Status check**: ``pending`` is the only acceptable state. An
       ``accepted`` state plus a *matching* idempotency-key resolves to
       a replay; otherwise the function raises
       :class:`InvitationStateError` (HTTP 410).
    6. **Apply the grant** (Member → ProjectMember, Trusted →
       ProjectTrustedUser) and flip ``status`` to ``accepted`` in the
       same transaction. When an active membership row already exists
       for the same (project_id, user_id), we REUSE it only if the
       cached idempotency record under the supplied key has a matching
       ``token_hash``; otherwise we raise 409 to prevent unrelated
       memberships from silently flipping a pending invitation to
       ``accepted``. Caller commits.

    Args:
        redis: Live Redis client. **Required** (non-Optional). Used for
            the FR-053 idempotency cache. Read / write faults raise
            :class:`InvitationInfraUnavailableError` (HTTP 503) —
            fail-closed so a partial Redis outage cannot bypass the
            FR-053 dedupe guarantee.

    Raises:
        InvitationTokenInvalidError: bad / expired signature, missing row.
        InvitationEmailMismatchError: caller email != invitation email.
        InvitationStateError: invitation already terminal (no replay key).
        InvitationConflictError: idempotency-key reused with different
            token, OR existing active membership without matching
            idempotency record.
        InvitationInfraUnavailableError: Redis is unreachable.
    """
    now_eff = now or datetime.now(UTC)

    # 1. HMAC verify (FR-052)
    raw_token_b64u, signed_expires_at = verify_invitation_token(
        signed_token, hmac_secret=hmac_secret, now=now_eff,
    )
    token_hash = hash_token(raw_token_b64u)

    # 2. Idempotency-key short-circuit (FR-053)
    #
    # ``redis`` is required (non-Optional). When the caller supplies an
    # ``idempotency_key`` we fetch the cached record fail-closed: a
    # transient Redis fault raises :class:`InvitationInfraUnavailableError`
    # so the caller cannot bypass FR-053 by waiting out an outage.
    if idempotency_key is not None:
        cached = await _get_idempotent_outcome(redis, idempotency_key)
        if cached is not None and cached.token_hash and cached.token_hash != token_hash:
            raise InvitationConflictError(
                "Idempotency-Key reused with a different invitation token",
            )

    # 3. Row lookup with FOR UPDATE (FR-053)
    result = await session.execute(
        select(ProjectInvitation)
        .where(ProjectInvitation.token_hash == token_hash)
        .with_for_update(),
    )
    invitation = result.scalar_one_or_none()
    if invitation is None:
        raise InvitationTokenInvalidError("invitation not found")

    # Phase 10 Batch 2 Round 2 fix (致命 3): the URL path's ``project_id``
    # MUST match the row's ``project_id``. Without this guard a caller
    # could POST a valid token under a *different* project's URL and
    # accept the invite, which would let an attacker exercise the FR-055
    # enumeration mitigation in reverse — reading the success response
    # would confirm the token's true project. We collapse the mismatch
    # into the same "invitation not found" branch the handler already
    # maps to 404 so the response shape stays uniform.
    if project_id_scope is not None and invitation.project_id != project_id_scope:
        raise InvitationTokenInvalidError("invitation not found")

    # spec/011 R5 (FR-011-122..125) — defence in depth above the DB CHECK:
    # if a row somehow exists with ``ownership_transfer_on_accept=True``
    # but ``kind != member`` (e.g. data corruption, manual SQL backdoor),
    # refuse to accept. The DB CHECK
    # ``ck_project_invitations_ownership_transfer_kind_member`` already
    # prevents the row from being INSERTed in the first place, but a
    # data-corruption scenario or a CHECK-bypassing migration shim
    # would otherwise allow a non-member transfer-on-accept path. The
    # service-layer guard surfaces a typed error class so the handler
    # never silently transfers ownership through a misclassified row.
    if (
        invitation.ownership_transfer_on_accept
        and invitation.kind is not ProjectInvitationKind.MEMBER
    ):
        raise InvitationStateError(
            "ownership_transfer_on_accept_invalid_for_kind",
        )

    # The signed expiry is the source of truth for the URL; the row's
    # expires_at is an additional guard. Reject if either failed.
    invitation_expires_at = _ensure_utc(invitation.expires_at)
    if invitation_expires_at <= now_eff:
        raise InvitationTokenInvalidError("invitation has expired")

    # 4. Email match (FR-054). The signed token already authenticates the
    # *URL*; this step authenticates the *recipient* against the URL.
    # Performed before the status check so an attacker holding a stolen
    # accepted-token never learns the invitation status.
    if not _email_matches_invitation(
        current_user_email,
        invitation,
        hmac_secret=hmac_secret,
    ):
        raise InvitationEmailMismatchError(
            "current user's email does not match the invitation",
        )

    # 5. Status checks (FR-053)
    if invitation.status != ProjectInvitationStatus.PENDING:
        # Idempotent replay path — only allowed when:
        #   (a) the row is in ACCEPTED state, AND
        #   (b) the caller supplied a matching idempotency-key.
        # Without the key we cannot prove the caller is the original
        # accepter, so the safe default is HTTP 410.
        if (
            invitation.status == ProjectInvitationStatus.ACCEPTED
            and idempotency_key is not None
        ):
            cached = await _get_idempotent_outcome(redis, idempotency_key)
            if cached is not None and cached.token_hash == token_hash:
                replay_member, replay_trusted_user = await _load_existing_grant(
                    session, invitation, current_user_id,
                )
                return InvitationAcceptOutcome(
                    invitation=invitation,
                    member=replay_member,
                    trusted_user=replay_trusted_user,
                    actor_user_id=current_user_id,
                    is_replay=True,
                    request_id=request_id,
                    ip=ip,
                    user_agent=user_agent,
                )
        raise InvitationStateError(
            f"invitation is in terminal state: {invitation.status.value}"
        )

    # Sanity: the signed token's expiry should never run past the row's
    # expiry. If it does, the row was tampered with — fall through as
    # token-invalid for FR-055 enumeration uniformity.
    if signed_expires_at < invitation_expires_at - timedelta(seconds=1):
        # Allow a small clock skew margin (1 s) but reject anything larger.
        raise InvitationTokenInvalidError("invitation token expiry mismatch")

    # spec/011 Step 9 R1 P0-1 — refuse SU-bootstrap invitations on the
    # legacy authenticated-only accept path. FR-011-123's SAVEPOINT-nested
    # ownership transfer is wired into ``accept_invitation_via_public_token``
    # only; the spec (FR-011-121..125) never references the legacy path
    # for bootstrap invitations. Without this guard the legacy endpoint
    # would silently flip ``invitation.status`` to ``accepted`` without
    # transferring ownership, leaving the project SU-owned and the
    # intended owner as a plain ADMIN member — a silent ownership leak.
    # The endpoint maps ``InvitationStateError`` to HTTP 410 which is the
    # closest "this resource cannot be consumed here" semantics; the
    # legitimate consumer (the intended owner) is steered to the public
    # path by the invitation URL the SU hand-delivers.
    #
    # Codex R2 P1: this refusal lives AFTER the email-match + status
    # checks so the existing error ordering (wrong-recipient → expired
    # → terminal-state) is preserved for non-bootstrap invitations; an
    # attacker holding a stolen bootstrap token gets the same generic
    # enumeration-defended path until they reach this terminal refuse.
    if invitation.ownership_transfer_on_accept:
        raise InvitationStateError(
            "ownership_transfer_must_use_public_path",
        )

    # 6. Apply the grant in the same TX.
    member: ProjectMember | None = None
    trusted_user: ProjectTrustedUser | None = None

    if invitation.kind is ProjectInvitationKind.MEMBER:
        if invitation.role is None:  # pragma: no cover - DB CHECK guards this
            raise InvitationValidationError(
                "Member invitation has NULL role (data corruption)"
            )
        # Pre-flight: re-use the existing active membership row when one
        # already exists for the same (project_id, user_id) so the
        # ``ux_project_members_active`` partial unique does not surface
        # as IntegrityError. REUSE is only honoured when:
        #
        #   (a) the caller supplied an idempotency-key, AND
        #   (b) Redis has a cached record under that key whose
        #       ``token_hash`` matches the *current* invitation's token.
        #
        # Without (b) we cannot prove the existing membership row was
        # created by *this* invitation — it might be an unrelated row
        # (e.g. the user was added by another Owner via a different
        # invitation, or via the legacy direct-add path). Re-using such
        # a row would silently flip an unrelated invitation to
        # ``accepted`` status, which would let an attacker use a stolen
        # idempotency-key to mark arbitrary pending invitations as
        # consumed. Instead we raise 409 conflict so the caller is
        # forced to revoke / re-issue.
        existing_member_result = await session.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == invitation.project_id,
                ProjectMember.user_id == current_user_id,
                ProjectMember.removed_at.is_(None),
            ),
        )
        existing_member = existing_member_result.scalar_one_or_none()
        if existing_member is not None:
            if idempotency_key is None:
                raise InvitationConflictError(
                    "user already has an active membership in this project",
                )
            cached_for_reuse = await _get_idempotent_outcome(
                redis, idempotency_key,
            )
            if (
                cached_for_reuse is None
                or cached_for_reuse.token_hash != token_hash
            ):
                raise InvitationConflictError(
                    "user already has an active membership in this project",
                )
            member = existing_member
        else:
            member = ProjectMember(
                project_id=invitation.project_id,
                user_id=current_user_id,
                role=invitation.role,
                joined_at=now_eff,
                invited_by_id=invitation.invited_by_id,
            )
            session.add(member)
    else:  # ProjectInvitationKind.TRUSTED
        if (
            invitation.granted_permissions is None
            or invitation.trusted_duration_seconds is None
        ):  # pragma: no cover - DB CHECK guards this
            raise InvitationValidationError(
                "Trusted invitation has NULL granted_permissions/duration "
                "(data corruption)"
            )
        # Re-validate the persisted permission set against the runtime
        # allowlist so a future allowlist tightening immediately blocks
        # accept (FR-014). The set is also re-sorted for determinism.
        valid_perms = coerce_granted_permissions(invitation.granted_permissions)
        expires_at = now_eff + timedelta(seconds=invitation.trusted_duration_seconds)
        # Cap at granted_at + 1 year for defence in depth (DB CHECK does
        # the same, but raising at the application layer gives the
        # endpoint a structured error).
        if expires_at - now_eff > timedelta(seconds=TRUSTED_MAX_DURATION_SECONDS):
            raise InvitationValidationError(
                "trusted_duration_seconds resolves past the FR-043 cap"
            )
        trusted_user = ProjectTrustedUser(
            project_id=invitation.project_id,
            user_id=current_user_id,
            invitation_id=invitation.id,
            granted_by_id=invitation.invited_by_id,
            granted_at=now_eff,
            expires_at=expires_at,
            status=ProjectTrustedStatus.ACTIVE,
            granted_permissions=sorted(p.value for p in valid_perms),
            email_at_invitation=invitation.email,
            email_at_invitation_hash=invitation.email_hash,
        )
        session.add(trusted_user)

    invitation.status = ProjectInvitationStatus.ACCEPTED
    invitation.accepted_at = now_eff

    try:
        await session.flush()
    except IntegrityError as exc:
        # E.g. ux_project_trusted_users_active partial unique violation when
        # the same user already has an active overlay — surface as state
        # error so the endpoint maps to 409.
        raise InvitationConflictError(
            "concurrent grant already exists for this user/project",
        ) from exc

    # Pin the idempotency record so a retry returns the same outcome.
    if idempotency_key is not None:
        await _set_idempotent_outcome(
            redis,
            idempotency_key,
            _IdempotencyRecord(
                invitation_id=str(invitation.id),
                token_hash=token_hash,
                is_replay=True,
            ),
        )

    return InvitationAcceptOutcome(
        invitation=invitation,
        member=member,
        trusted_user=trusted_user,
        actor_user_id=current_user_id,
        is_replay=False,
        request_id=request_id,
        ip=ip,
        user_agent=user_agent,
    )
