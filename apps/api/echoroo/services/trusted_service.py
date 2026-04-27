"""Trusted overlay management service (Phase 10 / T503).

This module owns the lifecycle operations on existing
:class:`ProjectTrustedUser` rows (creation lives in
:mod:`echoroo.services.invitation_service` because Trusted overlays are
born out of accepted invitations).

Public surface (FR-012, FR-014, FR-043, FR-044, FR-046):

* :func:`list_trusted_users` — Owner / Admin enumeration.
* :func:`get_active_trusted_capabilities` — request-time read used by
  :func:`echoroo.core.permissions.is_allowed`. Performs the FR-014
  ``TRUSTED_ALLOWED_PERMISSIONS`` re-intersection so a manually-tampered
  row cannot grant out-of-band permissions.
* :func:`update_trusted_user` — Owner extends ``expires_at`` and / or
  edits ``granted_permissions`` (FR-046). Bound by
  ``granted_at + 1 year``.
* :func:`revoke_trusted_user` — Owner kills the overlay early.

Atomicity contract mirrors :mod:`echoroo.services.restricted_config_service`:

1. The mutation function flushes the row in the caller's transaction and
   returns an outcome dataclass.
2. The endpoint commits the main TX.
3. The endpoint calls :func:`trigger_post_commit_side_effects` (audit
   write in fresh session + Redis pub/sub broadcast for T514). Failures
   are WARNING-logged only.

Phase 10 Batch 1 ships a stub for the Redis broadcast (logged + counted
metric). T514 wires the WebSocket / SSE consumer.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.database import AsyncSessionLocal
from echoroo.core.permissions import (
    TRUSTED_ALLOWED_PERMISSIONS,
    Permission,
)
from echoroo.core.redis import get_redis_connection
from echoroo.models.enums import ProjectTrustedStatus
from echoroo.models.project_trusted_user import ProjectTrustedUser
from echoroo.services.audit_service import AuditLogService
from echoroo.services.invitation_service import (
    InvitationValidationError,
    coerce_granted_permissions,
)

logger = logging.getLogger(__name__)


#: Hard cap from FR-043 (1 year) — duplicated here so callers do not have to
#: import the constant from the invitation service.
TRUSTED_MAX_DURATION_SECONDS: int = 365 * 24 * 3600

#: Redis pub/sub channel for FR-046 revoke broadcasts. Subscribers (T514)
#: invalidate any in-flight WebSocket / SSE sessions for the affected user
#: within ≤ 5 minutes (NFR-008a).
TRUSTED_INVALIDATION_CHANNEL: str = "trusted_user.invalidate"


class TrustedUpdateError(Exception):
    """Domain error for trusted-overlay mutations (HTTP 422 / 409 mapping)."""


# ---------------------------------------------------------------------------
# Outcome dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TrustedUpdateOutcome:
    """Result of :func:`update_trusted_user` / :func:`revoke_trusted_user`.

    The endpoint commits the main transaction first, then passes this
    dataclass to :func:`trigger_post_commit_side_effects` which writes
    the audit row (fresh session) and publishes the Redis invalidation
    notification.
    """

    trusted_user: ProjectTrustedUser
    actor_user_id: UUID
    diff: dict[str, dict[str, Any]]
    before: dict[str, Any]
    after: dict[str, Any]
    revoked: bool
    request_id: str = ""
    ip: str = ""
    user_agent: str = ""


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------


async def list_trusted_users(
    session: AsyncSession,
    *,
    project_id: UUID,
    status: ProjectTrustedStatus | None = None,
) -> list[ProjectTrustedUser]:
    """Return all overlay rows for ``project_id``, optionally filtered by status.

    Used by the Owner / Admin management UI (T520). Sort order is
    ``granted_at DESC`` so the freshest grants surface first; the index
    ``ix_project_trusted_users_project_user_status`` covers the project /
    status filter.
    """
    stmt = select(ProjectTrustedUser).where(
        ProjectTrustedUser.project_id == project_id,
    )
    if status is not None:
        stmt = stmt.where(ProjectTrustedUser.status == status)
    stmt = stmt.order_by(ProjectTrustedUser.granted_at.desc())

    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_active_trusted_capabilities(
    session: AsyncSession,
    *,
    user_id: UUID,
    project_id: UUID,
    now: datetime | None = None,
) -> frozenset[Permission]:
    """Return the live overlay permissions for ``(user, project)``.

    Implements FR-044 (read on every request, never cached in JWT) and
    FR-014 (runtime safety net — re-intersects with
    ``TRUSTED_ALLOWED_PERMISSIONS`` so manually-INSERTed rows that name an
    out-of-allowlist permission cannot escalate). The permission engine
    in :mod:`echoroo.core.permissions` performs the same intersection a
    second time as defence-in-depth.
    """
    now_eff = now or datetime.now(UTC)
    result = await session.execute(
        select(ProjectTrustedUser).where(
            ProjectTrustedUser.user_id == user_id,
            ProjectTrustedUser.project_id == project_id,
            ProjectTrustedUser.status == ProjectTrustedStatus.ACTIVE,
            ProjectTrustedUser.expires_at > now_eff,
        ),
    )
    rows = list(result.scalars().all())
    if not rows:
        return frozenset()

    granted: set[Permission] = set()
    for row in rows:
        for entry in row.granted_permissions or ():
            try:
                perm = entry if isinstance(entry, Permission) else Permission(entry)
            except ValueError:
                # FR-014: silently drop unknown permission names; the row
                # is preserved (an operator may inspect it via list_*),
                # but the gate never sees the bogus value.
                continue
            granted.add(perm)
    return frozenset(granted) & TRUSTED_ALLOWED_PERMISSIONS


# ---------------------------------------------------------------------------
# Mutation: update_trusted_user
# ---------------------------------------------------------------------------


async def update_trusted_user(
    session: AsyncSession,
    *,
    trusted_user: ProjectTrustedUser,
    actor_user_id: UUID,
    granted_permissions: Sequence[str | Permission] | None = None,
    expires_at: datetime | None = None,
    extension_seconds: int | None = None,
    request_id: str = "",
    ip: str = "",
    user_agent: str = "",
    now: datetime | None = None,
) -> TrustedUpdateOutcome:
    """Apply Owner-driven edits to ``trusted_user`` (FR-046).

    The function is intentionally lock-free: the caller MUST already hold
    a row lock (``with_for_update``) on ``trusted_user`` to serialise
    competing PATCHes. The endpoint layer is the natural place for this
    because the project authorization check runs on the parent project
    row first.

    Args:
        session: Caller-owned async session. Caller commits.
        trusted_user: The row to mutate. Already locked by the caller.
        actor_user_id: Who initiated the PATCH; recorded in the audit row.
        granted_permissions: Replacement permission set (None = unchanged).
            Each entry is re-validated against ``TRUSTED_ALLOWED_PERMISSIONS``
            via :func:`coerce_granted_permissions`.
        expires_at: Absolute new expiry. If supplied alongside
            ``extension_seconds``, ``expires_at`` wins.
        extension_seconds: Convenience parameter — extends the current
            ``expires_at`` by this many seconds. Bound by
            ``granted_at + 1 year``.
        now: Override for ``datetime.now(UTC)`` (testing only).

    Returns:
        :class:`TrustedUpdateOutcome` carrying the diff for the audit log.

    Raises:
        TrustedUpdateError: When ``trusted_user`` is not active, when the
            requested permission set is invalid, or when the requested
            ``expires_at`` is past the FR-043 cap.
    """
    now_eff = now or datetime.now(UTC)

    if trusted_user.status != ProjectTrustedStatus.ACTIVE:
        raise TrustedUpdateError(
            f"cannot edit trusted user in {trusted_user.status.value!r} state",
        )

    before: dict[str, Any] = {
        "granted_permissions": list(trusted_user.granted_permissions or ()),
        "expires_at": trusted_user.expires_at.isoformat(),
    }
    diff: dict[str, dict[str, Any]] = {}

    # 1. permission set
    if granted_permissions is not None:
        try:
            valid_perms = coerce_granted_permissions(granted_permissions)
        except InvitationValidationError as exc:
            raise TrustedUpdateError(str(exc)) from exc
        new_perms = sorted(p.value for p in valid_perms)
        if new_perms != list(trusted_user.granted_permissions or ()):
            diff["granted_permissions"] = {
                "old": list(trusted_user.granted_permissions or ()),
                "new": new_perms,
            }
            trusted_user.granted_permissions = new_perms

    # 2. expiry
    new_expiry: datetime | None = None
    if expires_at is not None:
        new_expiry = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=UTC)
    elif extension_seconds is not None:
        if extension_seconds <= 0:
            raise TrustedUpdateError(
                "extension_seconds must be a positive integer",
            )
        new_expiry = trusted_user.expires_at + timedelta(seconds=extension_seconds)

    if new_expiry is not None:
        max_expiry = trusted_user.granted_at + timedelta(
            seconds=TRUSTED_MAX_DURATION_SECONDS,
        )
        if new_expiry <= now_eff:
            raise TrustedUpdateError("expires_at must be in the future")
        if new_expiry > max_expiry:
            raise TrustedUpdateError(
                "expires_at exceeds the FR-043 1-year cap from granted_at",
            )
        if new_expiry != trusted_user.expires_at:
            diff["expires_at"] = {
                "old": trusted_user.expires_at.isoformat(),
                "new": new_expiry.isoformat(),
            }
            trusted_user.expires_at = new_expiry

    after: dict[str, Any] = {
        "granted_permissions": list(trusted_user.granted_permissions or ()),
        "expires_at": trusted_user.expires_at.isoformat(),
    }

    # If nothing changed we still flush so the caller can rely on a
    # consistent post-state, but the diff stays empty and the caller can
    # branch on it to decide whether to bother with the audit row.
    await session.flush()

    return TrustedUpdateOutcome(
        trusted_user=trusted_user,
        actor_user_id=actor_user_id,
        diff=diff,
        before=before,
        after=after,
        revoked=False,
        request_id=request_id,
        ip=ip,
        user_agent=user_agent,
    )


# ---------------------------------------------------------------------------
# Mutation: revoke_trusted_user
# ---------------------------------------------------------------------------


async def revoke_trusted_user(
    session: AsyncSession,
    *,
    trusted_user: ProjectTrustedUser,
    actor_user_id: UUID,
    request_id: str = "",
    ip: str = "",
    user_agent: str = "",
    now: datetime | None = None,
) -> TrustedUpdateOutcome:
    """Transition ``trusted_user.status`` to ``revoked`` immediately.

    Idempotent: a second revoke of an already-revoked row returns an
    outcome with empty ``diff`` so the endpoint may still call
    :func:`trigger_post_commit_side_effects` without accidentally writing
    a no-op audit row twice.
    """
    now_eff = now or datetime.now(UTC)

    before: dict[str, Any] = {"status": trusted_user.status.value}
    diff: dict[str, dict[str, Any]] = {}

    if trusted_user.status != ProjectTrustedStatus.REVOKED:
        diff["status"] = {
            "old": trusted_user.status.value,
            "new": ProjectTrustedStatus.REVOKED.value,
        }
        trusted_user.status = ProjectTrustedStatus.REVOKED
        trusted_user.revoked_at = now_eff
        await session.flush()

    after: dict[str, Any] = {"status": trusted_user.status.value}

    return TrustedUpdateOutcome(
        trusted_user=trusted_user,
        actor_user_id=actor_user_id,
        diff=diff,
        before=before,
        after=after,
        revoked=True,
        request_id=request_id,
        ip=ip,
        user_agent=user_agent,
    )


# ---------------------------------------------------------------------------
# Post-commit side effects
# ---------------------------------------------------------------------------


async def trigger_post_commit_side_effects(
    outcome: TrustedUpdateOutcome,
) -> None:
    """Fire audit + Redis pub/sub broadcast after the main TX has committed.

    Both side-effects are best-effort. Failures are WARNING-logged so
    observability does not undo the persisted change. The Redis publish
    is the FR-046 "live invalidation" hook consumed by T514's worker.
    """
    if not outcome.diff:
        # Idempotent re-revoke or noop update — no audit / broadcast needed.
        return

    await _write_trusted_user_audit(outcome)

    if outcome.revoked:
        await _publish_trusted_invalidation(
            user_id=outcome.trusted_user.user_id,
            project_id=outcome.trusted_user.project_id,
            reason="revoked",
        )
    elif outcome.diff:
        # Permission / expiry edits also invalidate any active
        # WebSocket / SSE session so the new bounds take effect inside
        # the NFR-008a window.
        await _publish_trusted_invalidation(
            user_id=outcome.trusted_user.user_id,
            project_id=outcome.trusted_user.project_id,
            reason="updated",
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _write_trusted_user_audit(outcome: TrustedUpdateOutcome) -> None:
    """Record the trusted-user change in ``project_audit_log``.

    Uses a fresh :class:`AsyncSessionLocal` because the audit writer
    issues ``SET TRANSACTION ISOLATION LEVEL SERIALIZABLE`` which
    PostgreSQL rejects on a session that has already issued statements
    (mirrors the pattern in
    :mod:`echoroo.services.restricted_config_service`).
    """
    action = (
        "project.trusted_user.revoke"
        if outcome.revoked
        else "project.trusted_user.update"
    )
    try:
        async with AsyncSessionLocal() as audit_session:
            try:
                service = AuditLogService(audit_session)
                await service.write_project_event(
                    actor_user_id=outcome.actor_user_id,
                    project_id=outcome.trusted_user.project_id,
                    action=action,
                    request_id=outcome.request_id,
                    ip=outcome.ip,
                    user_agent=outcome.user_agent,
                    detail={
                        "trusted_user_id": str(outcome.trusted_user.id),
                        "diff": outcome.diff,
                    },
                    before=outcome.before,
                    after=outcome.after,
                )
                await audit_session.commit()
            except Exception:
                await audit_session.rollback()
                raise
    except Exception as exc:  # noqa: BLE001 — best effort; soft alert.
        logger.warning(
            "%s audit write failed (FR-088 soft alert): "
            "trusted_user_id=%s actor=%s diff_keys=%s error=%r",
            action,
            outcome.trusted_user.id,
            outcome.actor_user_id,
            sorted(outcome.diff.keys()),
            exc,
        )


async def _publish_trusted_invalidation(
    *,
    user_id: UUID,
    project_id: UUID,
    reason: str,
) -> None:
    """Broadcast a JSON message on :data:`TRUSTED_INVALIDATION_CHANNEL`.

    T514 will subscribe to this channel and disconnect any active
    WebSocket / SSE streams for the affected ``(user, project)`` pair so
    the NFR-008a 5-minute upper bound holds. We isolate the publish into
    its own helper so the worker can be wired up without touching this
    file.
    """
    payload = json.dumps(
        {
            "user_id": str(user_id),
            "project_id": str(project_id),
            "reason": reason,
        },
        sort_keys=True,
    )
    try:
        client = await get_redis_connection()
        await client.publish(TRUSTED_INVALIDATION_CHANNEL, payload)
    except Exception as exc:  # noqa: BLE001 — best effort; soft alert.
        logger.warning(
            "trusted_user invalidation publish failed (NFR-008a soft alert): "
            "user_id=%s project_id=%s reason=%s error=%r",
            user_id,
            project_id,
            reason,
            exc,
        )


__all__ = [
    "TRUSTED_INVALIDATION_CHANNEL",
    "TRUSTED_MAX_DURATION_SECONDS",
    "TrustedUpdateError",
    "TrustedUpdateOutcome",
    "get_active_trusted_capabilities",
    "list_trusted_users",
    "revoke_trusted_user",
    "trigger_post_commit_side_effects",
    "update_trusted_user",
]
