"""spec/011 FR-011-105 / FR-011-106 — Public-token resolver + accept."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.enums import (
    ProjectInvitationKind,
    ProjectInvitationStatus,
    ProjectMemberRole,
    ProjectTrustedStatus,
)
from echoroo.models.project import Project, ProjectInvitation, ProjectMember
from echoroo.models.project_trusted_user import ProjectTrustedUser
from echoroo.services.audit_service import build_pre_transfer_action_summary

from .constants import (
    AUDIT_ACTION_MEMBER_INVITE_ACCEPTED,
    AUDIT_ACTION_MEMBER_INVITE_ACCEPTED_SIGNUP,
    AUDIT_ACTION_TRUSTED_INVITE_ACCEPTED,
    TRUSTED_MAX_DURATION_SECONDS,
)
from .emails import canonicalize_email
from .errors import (
    InvitationAlreadyMemberError,
    InvitationConflictError,
    InvitationEmailMismatchError,
    InvitationStateError,
    InvitationTokenInvalidError,
    InvitationValidationError,
)
from .grants import _role_rank, coerce_granted_permissions
from .outcomes import InvitationPublicAcceptOutcome, InvitationResolveOutcome
from .tokens import _ensure_utc, hash_token, verify_invitation_token


async def resolve_invitation_for_public_token(
    session: AsyncSession,
    *,
    signed_token: str,
    authenticated_email: str | None,
    now: datetime | None = None,
) -> InvitationResolveOutcome:
    """Resolve invitation context for the public landing page (FR-011-105).

    The resolver authenticates by the signed token alone (TOKEN_AUTH_ONLY).
    When the caller also presents a valid session cookie the handler passes
    the authenticated user's email so the resolver can report whether the
    bound email matches; the frontend uses the flag to gate the existing-
    user accept branch vs. force a sign-out for a mismatched session.

    Raises :class:`InvitationTokenInvalidError` for any failure cause
    (bad signature, expired envelope, unknown token, terminal-status row,
    deleted project). The handler maps every cause to the same generic
    response with constant timing (FR-011-107). Project visibility /
    role-validity guards on the row mirror the live application gate so
    a stale invitation whose target role no longer matches the project's
    visibility is rejected uniformly.
    """
    now_eff = now or datetime.now(UTC)

    raw_token_b64u, _ = verify_invitation_token(
        signed_token, now=now_eff,
    )
    token_hash = hash_token(raw_token_b64u)

    result = await session.execute(
        select(ProjectInvitation).where(
            ProjectInvitation.token_hash == token_hash,
        ),
    )
    invitation = result.scalar_one_or_none()
    if invitation is None:
        raise InvitationTokenInvalidError("invitation not found")

    if invitation.status != ProjectInvitationStatus.PENDING:
        # Any terminal status — accepted / declined / revoked / expired —
        # collapses to the same generic-invalid surface (FR-011-107).
        raise InvitationTokenInvalidError("invitation not pending")

    invitation_expires_at = _ensure_utc(invitation.expires_at)
    if invitation_expires_at <= now_eff:
        raise InvitationTokenInvalidError("invitation has expired")

    # Local import — avoid a heavy ``Project`` model load at module import.
    from echoroo.models.project import Project

    project_row = (
        await session.execute(
            select(Project.name).where(Project.id == invitation.project_id),
        )
    ).first()
    if project_row is None:
        raise InvitationTokenInvalidError("invitation target project missing")
    project_name = str(project_row[0])

    is_logged_in = authenticated_email is not None
    authenticated_email_matches: bool | None
    if authenticated_email is None or invitation.email is None:
        authenticated_email_matches = None if not is_logged_in else False
    else:
        authenticated_email_matches = canonicalize_email(
            authenticated_email
        ) == canonicalize_email(invitation.email)

    return InvitationResolveOutcome(
        invitation=invitation,
        project_name=project_name,
        is_logged_in=is_logged_in,
        authenticated_email_matches=authenticated_email_matches,
    )


# spec/011 Step 9 R1 P1-2 — synchronous test seam for the SAVEPOINT
# rollback-after-success integration test. The default body is a no-op
# so the production code path is unchanged; the integration test
# monkey-patches the module-level name to a raising stub so the test
# can assert that an exception emerging AFTER the owner UPDATE +
# ProjectMember upsert have already taken effect inside the SAVEPOINT
# still triggers a complete rollback of the parent transaction (the
# invitation row reverts to PENDING, Project.owner_id reverts to the
# placeholder SU, and no ProjectMember row for the prior owner is
# persisted).
async def _ownership_transfer_savepoint_finalize_hook() -> None:
    """Production no-op; test seam for the post-owner-UPDATE failure path."""
    return None


async def accept_invitation_via_public_token(
    session: AsyncSession,
    *,
    signed_token: str,
    accepting_user_id: UUID,
    accepting_user_email: str,
    project_id_scope: UUID | None = None,
    is_new_user_signup: bool = False,
    now: datetime | None = None,
    request_id: str = "",
    ip: str = "",
    user_agent: str = "",
) -> InvitationPublicAcceptOutcome:
    """Accept an invitation under the spec/011 public-token surface.

    Implements FR-011-106 in a single transaction:

    1. HMAC-verify the signed envelope (constant-time MAC compare via
       :func:`verify_invitation_token`).
    2. Look up the row by ``token_hash``; mismatch / missing →
       :class:`InvitationTokenInvalidError`.
    3. Compare ``canonicalize_email(accepting_user_email)`` with the bound
       email (NFKC + casefold). Mismatch →
       :class:`InvitationEmailMismatchError` (handler maps to generic 404).
    4. Atomic state flip via parameterised SQL (FR-011-106 step 2). Zero
       rows returned → :class:`InvitationTokenInvalidError`.
    5. Insert the grant row (ProjectMember / ProjectTrustedUser). When the
       caller already holds an active membership at the same OR higher
       role, raise :class:`InvitationAlreadyMemberError` (handler →
       409). Otherwise insert and audit-emit per branch.

    The caller's authentication state is signalled via
    ``is_new_user_signup``: ``True`` selects
    :data:`AUDIT_ACTION_MEMBER_INVITE_ACCEPTED_SIGNUP`,
    ``False`` selects :data:`AUDIT_ACTION_MEMBER_INVITE_ACCEPTED` (or
    :data:`AUDIT_ACTION_TRUSTED_INVITE_ACCEPTED` for trusted-overlay
    rows). The caller is responsible for having created the user row
    BEFORE invoking this function on the signup branch — the service
    layer never receives the cleartext password.

    Caller commits the transaction. Audit side effects fire post-commit
    via :func:`trigger_post_commit_side_effects`.
    """
    now_eff = now or datetime.now(UTC)

    # Step 1 — HMAC verify (NFR-011-003 constant-time compare).
    raw_token_b64u, _ = verify_invitation_token(signed_token, now=now_eff)
    token_hash = hash_token(raw_token_b64u)

    # Step 2 — Row lookup (read-only). The conditional UPDATE in step 4
    # is the concurrency gate; the SELECT serves only to surface the
    # invitation context (project_id, kind, role, bound email, ownership-
    # transfer flag) and to raise the spec/011 generic-invalid surface
    # for terminal-status / expired / missing rows BEFORE the atomic
    # UPDATE runs. The earlier ``SELECT ... FOR UPDATE`` was redundant
    # (and surplus-locking): per FR-011-106 step 2 the
    # ``UPDATE ... WHERE status='pending' AND expires_at > now()
    # RETURNING *`` itself is the single-statement compare-and-swap. A
    # parallel accept that loses the race finds zero rows returned from
    # the UPDATE and surfaces the generic-invalid path (Codex R1 P0-2).
    result = await session.execute(
        select(ProjectInvitation).where(
            ProjectInvitation.token_hash == token_hash,
        ),
    )
    invitation = result.scalar_one_or_none()
    if invitation is None:
        raise InvitationTokenInvalidError("invitation not found")

    if project_id_scope is not None and invitation.project_id != project_id_scope:
        raise InvitationTokenInvalidError("invitation not found")

    if invitation.status != ProjectInvitationStatus.PENDING:
        raise InvitationTokenInvalidError("invitation not pending")

    invitation_expires_at = _ensure_utc(invitation.expires_at)
    if invitation_expires_at <= now_eff:
        raise InvitationTokenInvalidError("invitation has expired")

    # spec/011 R5 — defence in depth above the DB CHECK.
    if (
        invitation.ownership_transfer_on_accept
        and invitation.kind is not ProjectInvitationKind.MEMBER
    ):
        raise InvitationStateError(
            "ownership_transfer_on_accept_invalid_for_kind",
        )

    # Step 3 — bound-email match (FR-011-106 step 1 substep). The check
    # uses :func:`canonicalize_email` on both sides so a fullwidth or
    # combining-mark variant cannot bypass via Unicode normalisation
    # tricks. Mismatch is :class:`InvitationEmailMismatchError`; the
    # handler maps to the generic 404.
    if invitation.email is None:
        raise InvitationEmailMismatchError(
            "invitation row missing bound email",
        )
    if canonicalize_email(accepting_user_email) != canonicalize_email(
        invitation.email,
    ):
        raise InvitationEmailMismatchError(
            "current user's email does not match the invitation",
        )

    # Step 4 — atomic state flip (FR-011-106 step 2). Named placeholders
    # only; no string concatenation. The WHERE clause re-checks the
    # status + expiry so this single statement is the compare-and-swap
    # gate: any concurrent accept that wins the race leaves the row in
    # ``status='accepted'`` and our UPDATE matches zero rows. Likewise
    # an admin revoke landing between the SELECT above and this UPDATE
    # flips the row to ``revoked`` and we surface the generic-invalid
    # response. The lock duration is intentionally the UPDATE itself
    # (Postgres row-level write lock) — no separate ``SELECT FOR UPDATE``
    # is needed.
    update_stmt = text(
        """
        UPDATE project_invitations
           SET status = 'accepted',
               accepted_at = now(),
               updated_at = now()
         WHERE id = :invitation_id
           AND status = 'pending'
           AND expires_at > now()
        RETURNING id
        """
    )
    update_result = await session.execute(
        update_stmt,
        {"invitation_id": invitation.id},
    )
    if update_result.fetchone() is None:
        # Lost the atomicity race OR the row drifted to a terminal state
        # (e.g. an admin revoke landed concurrently). Generic-invalid per
        # FR-011-106. spec/011 step 7 R1 P0-1: callers performing user
        # creation + 2FA enrollment in the same TX MUST rollback the
        # whole transaction when this raises so no orphan account leaks.
        raise InvitationTokenInvalidError("invitation not found")

    # Re-attach the freshly-flipped row to the ORM identity map so
    # downstream consumers (audit emitter, response shaping) see the
    # accepted status without an additional SELECT.
    invitation.status = ProjectInvitationStatus.ACCEPTED
    invitation.accepted_at = now_eff

    # Step 5 — apply the grant.
    member: ProjectMember | None = None
    trusted_user: ProjectTrustedUser | None = None
    membership_created = False
    audit_action: str

    if invitation.kind is ProjectInvitationKind.MEMBER:
        if invitation.role is None:  # pragma: no cover — DB CHECK guards this
            raise InvitationValidationError(
                "Member invitation has NULL role (data corruption)",
            )
        # FR-011-106 step 3: existing-user branch — refuse if caller is
        # already a member at the same OR higher role. The role ordering
        # is VIEWER < MEMBER < ADMIN; ``_role_rank`` encapsulates the
        # comparison so the enum stays the single source of truth.
        existing = (
            await session.execute(
                select(ProjectMember).where(
                    ProjectMember.project_id == invitation.project_id,
                    ProjectMember.user_id == accepting_user_id,
                    ProjectMember.removed_at.is_(None),
                ),
            )
        ).scalar_one_or_none()
        if existing is not None:
            if _role_rank(existing.role) >= _role_rank(invitation.role):
                raise InvitationAlreadyMemberError(
                    "user already has an active membership at "
                    "the same or higher role",
                )
            # Lower-rank existing membership → upgrade in place. The
            # ``ux_project_members_active`` partial unique would
            # otherwise reject the INSERT below.
            existing.role = invitation.role
            existing.invited_by_id = invitation.invited_by_id
            member = existing
            membership_created = False
        else:
            member = ProjectMember(
                project_id=invitation.project_id,
                user_id=accepting_user_id,
                role=invitation.role,
                joined_at=now_eff,
                invited_by_id=invitation.invited_by_id,
            )
            session.add(member)
            membership_created = True
        audit_action = (
            AUDIT_ACTION_MEMBER_INVITE_ACCEPTED_SIGNUP
            if is_new_user_signup
            else AUDIT_ACTION_MEMBER_INVITE_ACCEPTED
        )
    else:  # ProjectInvitationKind.TRUSTED
        if (
            invitation.granted_permissions is None
            or invitation.trusted_duration_seconds is None
        ):  # pragma: no cover — DB CHECK guards this
            raise InvitationValidationError(
                "Trusted invitation has NULL granted_permissions/duration "
                "(data corruption)",
            )
        valid_perms = coerce_granted_permissions(invitation.granted_permissions)
        trusted_expires_at = now_eff + timedelta(
            seconds=invitation.trusted_duration_seconds,
        )
        if trusted_expires_at - now_eff > timedelta(
            seconds=TRUSTED_MAX_DURATION_SECONDS,
        ):
            raise InvitationValidationError(
                "trusted_duration_seconds resolves past the FR-043 cap"
            )
        trusted_user = ProjectTrustedUser(
            project_id=invitation.project_id,
            user_id=accepting_user_id,
            invitation_id=invitation.id,
            granted_by_id=invitation.invited_by_id,
            granted_at=now_eff,
            expires_at=trusted_expires_at,
            status=ProjectTrustedStatus.ACTIVE,
            granted_permissions=sorted(p.value for p in valid_perms),
            email_at_invitation=invitation.email,
            email_at_invitation_hash=invitation.email_hash,
        )
        session.add(trusted_user)
        membership_created = True
        audit_action = AUDIT_ACTION_TRUSTED_INVITE_ACCEPTED

    try:
        await session.flush()
    except IntegrityError as exc:
        # ``ux_project_trusted_users_active`` partial unique violation or
        # similar concurrent insert → surface as 409 conflict.
        raise InvitationConflictError(
            "concurrent grant already exists for this user/project",
        ) from exc

    # ---------------------------------------------------------------------
    # spec/011 Step 9 (FR-011-123) — SAVEPOINT-nested ownership transfer.
    # Fires ONLY on a successful accept for a row that carries
    # ``ownership_transfer_on_accept=True``. The Step 6 R5 guard above
    # and the DB CHECK constraint together guarantee ``kind == MEMBER``
    # at this point. Decline / revoke / expire paths never reach here so
    # the transfer cannot accidentally fire on the wrong terminal
    # transition (FR-011-124).
    #
    # Order of operations inside the SAVEPOINT:
    #   1. Capture the prior owner + project_created_at snapshot.
    #   2. Build ``pre_transfer_action_summary`` (read-only SELECT).
    #   3. Update ``Project.owner_id`` to the accepting user.
    #   4. Upsert prior-owner ``ProjectMember`` row at role=ADMIN
    #      (insert if absent, update-in-place if a removed row exists
    #      under the partial unique index ``ux_project_members_active``).
    #   5. Build the composite audit ``detail`` dict and stash it on
    #      the outcome so :func:`emit_public_invitation_accept_audit`
    #      can post-commit-emit the
    #      :data:`AUDIT_ACTION_PROJECT_OWNERSHIP_BOOTSTRAP_TRANSFER`
    #      row in a fresh session (FR-093 SERIALIZABLE contract).
    #
    # Failure mode: any exception inside ``begin_nested()`` rolls back
    # the SAVEPOINT, then propagates so the outer caller (handler) sees
    # the error and rolls back the parent transaction (FR-011-123 step
    # 5). The SAVEPOINT itself never silently swallows errors.
    ownership_transferred = False
    ownership_transfer_detail: dict[str, Any] | None = None
    prior_owner_id: UUID | None = None
    if invitation.ownership_transfer_on_accept:
        async with session.begin_nested():
            # Step 1 — snapshot the prior owner + project ``created_at``
            # under the SAVEPOINT row lock. The ``with_for_update`` is
            # ESSENTIAL: two concurrent accepts that lose the atomic
            # invitation UPDATE above can't both reach here, but a
            # parallel project-update mutation could re-write ``owner_id``
            # mid-transfer; the FOR UPDATE lock makes the read of the
            # old owner deterministic.
            project_row_result = await session.execute(
                select(Project.owner_id, Project.created_at)
                .where(Project.id == invitation.project_id)
                .with_for_update(),
            )
            project_row = project_row_result.first()
            if project_row is None:
                # Project missing — should be unreachable because the row
                # lookup above (Step 2 of accept_invitation_via_public_token)
                # already verified the invitation references a live project.
                # Treat as a corruption: raise so the parent TX rolls back.
                raise InvitationStateError(
                    "ownership_transfer_target_project_missing",
                )
            prior_owner_id = project_row[0]
            project_created_at = project_row[1]

            # Step 2 — build the pre-transfer summary (R6). The query
            # is read-only against ``project_audit_log`` and scoped to
            # (project_id, actor=prior_owner, since=project_created_at,
            # until=now_eff).
            ownership_transfer_summary = await build_pre_transfer_action_summary(
                session,
                project_id=invitation.project_id,
                actor_user_id=prior_owner_id,
                since=project_created_at,
                until=now_eff,
            )

            # Step 3 — flip the project owner. The UPDATE uses the same
            # row lock the FOR UPDATE above took out.
            #
            # spec/011 Step 9 R1 P1-1 — preserve ``Project.updated_at``
            # across the bootstrap ownership flip. The
            # :class:`TimestampMixin` declares ``onupdate=lambda: now()``
            # which SQLAlchemy auto-applies to every Core ``update()``
            # whose ``.values()`` clause does NOT mention the column.
            # Pinning ``updated_at`` to its current value via the literal
            # ``Project.__table__.c.updated_at`` (a no-op self-assignment)
            # takes precedence over ``onupdate`` so the column is NOT
            # bumped by the bootstrap transfer. The intent: the
            # bootstrap transfer is a system-internal lifecycle event
            # (the placeholder SU yields to the intended owner) and
            # MUST NOT pollute the project's mtime-driven sort orders
            # / cache keys that callers may rely on. The composite
            # audit row (Step 5) records the transfer's ``at`` timestamp
            # separately for observability.
            await session.execute(
                update(Project)
                .where(Project.id == invitation.project_id)
                .values(
                    owner_id=accepting_user_id,
                    updated_at=Project.__table__.c.updated_at,
                ),
            )

            # Step 4 — upsert the prior-owner ``ProjectMember`` row at
            # role=ADMIN. ``ux_project_members_active`` is a partial
            # unique index on (project_id, user_id) WHERE removed_at IS
            # NULL — direct INSERT against an existing active row would
            # IntegrityError. We branch explicitly so the path is
            # transparent at code-review time.
            existing_prior_owner_member = (
                await session.execute(
                    select(ProjectMember).where(
                        ProjectMember.project_id == invitation.project_id,
                        ProjectMember.user_id == prior_owner_id,
                        ProjectMember.removed_at.is_(None),
                    ),
                )
            ).scalar_one_or_none()
            if existing_prior_owner_member is None:
                session.add(
                    ProjectMember(
                        project_id=invitation.project_id,
                        user_id=prior_owner_id,
                        role=ProjectMemberRole.ADMIN,
                        joined_at=now_eff,
                        invited_by_id=accepting_user_id,
                    )
                )
            else:
                existing_prior_owner_member.role = ProjectMemberRole.ADMIN

            # Flush BEFORE the finalize hook so the ProjectMember
            # upsert + owner UPDATE are materialised in the DB-side
            # SAVEPOINT scratch space. The hook is then the test-
            # patch seam that exercises the rollback-after-flush
            # invariant.
            await session.flush()

            # spec/011 Step 9 R1 P1-2 (Codex R2 P1 follow-up) —
            # synchronous seam intentionally left as a no-op so the
            # rollback-after-owner-UPDATE-succeeded integration test
            # (in
            # ``tests/integration/test_superuser_bootstrap_invitation.py``)
            # can monkey-patch this single name to raise from inside
            # the SAVEPOINT *after* the owner UPDATE + ProjectMember
            # upsert have already been flushed to the DB-side
            # SAVEPOINT scratch space. Without a seam the test would
            # have to patch a coarse external dependency
            # (``build_pre_transfer_action_summary`` is the FIRST step;
            # patching it never exercises the rollback-after-success
            # invariant). The production-path return value is unused
            # so the hook's signature is intentionally minimal.
            await _ownership_transfer_savepoint_finalize_hook()

            # Step 5 — stage the composite audit detail. The actual
            # ``project_audit_log`` row write happens post-commit (see
            # ``emit_public_invitation_accept_audit``) because the
            # audit writer requires a fresh session for the
            # SERIALIZABLE upgrade (FR-093). Storing the dict on the
            # outcome lets the emitter pick it up after the parent
            # TX commits.
            ownership_transfer_detail = {
                "invitation_id": str(invitation.id),
                "project_id": str(invitation.project_id),
                "prior_owner": str(prior_owner_id),
                "new_owner": str(accepting_user_id),
                "pre_transfer_action_summary": ownership_transfer_summary,
                # spec/011 Step 9 R1 P2 — match the ``Z`` suffix the
                # ``build_pre_transfer_action_summary`` helper emits on
                # ``occurred_at`` (see
                # ``services/audit_service.py:553``). Without the
                # normalisation the nested summary entries carry ``Z``
                # while the wrapping composite ``at`` carries
                # ``+00:00`` — purely cosmetic but a long-term contract
                # nuisance for downstream JSON consumers (the activity
                # view projection diff'd the two formats when
                # eyeballing logs in dev). UTC astimezone is a no-op
                # because ``now_eff`` was constructed in UTC, but the
                # explicit conversion documents the intent.
                "at": (
                    now_eff.astimezone(UTC).isoformat().replace("+00:00", "Z")
                ),
            }
            ownership_transferred = True

    return InvitationPublicAcceptOutcome(
        invitation=invitation,
        accepting_user_id=accepting_user_id,
        member=member,
        trusted_user=trusted_user,
        audit_action=audit_action,
        membership_created=membership_created,
        ownership_transferred=ownership_transferred,
        ownership_transfer_detail=ownership_transfer_detail,
        prior_owner_id=prior_owner_id,
        request_id=request_id,
        ip=ip,
        user_agent=user_agent,
    )
