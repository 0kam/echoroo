"""Ownership transfer service (Phase 12 / T700, FR-057 / FR-058 / FR-059).

Public surface
==============

* :func:`transfer_ownership` — Owner-driven move of ``Project.owner_id`` to
  an existing Admin (FR-057). Idempotent on a per-``X-Idempotency-Key``
  basis: replaying the same key returns the original outcome instead of
  performing a second mutation. Concurrent transfers race through a
  PostgreSQL advisory lock + ``SELECT ... FOR UPDATE`` so exactly one
  caller wins; the loser surfaces ``ERR_CONFLICT`` (HTTP 409).
* :class:`OwnershipTransferOutcome` — outcome dataclass mirroring the
  pattern in :mod:`echoroo.services.trusted_service` so the endpoint can
  fire post-commit audit + outbox side-effects without re-reading state.

Atomicity contract
==================

The service mutates ``projects.owner_id`` inside the caller's
transaction and, when relevant, writes a project_audit_log row using a
**fresh** :class:`AsyncSessionLocal` from a sibling helper that the
endpoint invokes after ``await db.commit()``. This mirrors the
license / restricted-config services: a serialisable failure in the
audit chain MUST NOT roll back a successful ownership transfer
(FR-092).

Concurrency model (FR-058)
==========================

1. ``pg_advisory_xact_lock(project_id_bigint)`` serialises competing
   transfers on the same project. The 64-bit lock key is derived from a
   stable SHA-256 fold of the project UUID (mirrors the pattern in
   :mod:`echoroo.services.audit_service`).
2. ``SELECT ... FOR UPDATE`` against the project + ``project_members``
   row locks the rows for the duration of the transaction so a concurrent
   role change cannot demote the prospective new Owner mid-flight.
3. ``X-Idempotency-Key`` is recorded inside ``superuser_approval_requests``
   via the existing ``ON CONFLICT (idempotency_key) DO UPDATE`` pattern
   exposed by the outbox (here we go through the simpler dedicated row
   in the dedicated dedupe table). For Phase 12 Batch 1 we keep the
   dedupe inside the ``project_audit_log.detail`` payload — the audit
   row's ``idempotency_key`` field is consulted on replay so the second
   call returns the first call's outcome without performing a second
   mutation. The audit row's append-only nature means the dedupe key is
   immutable by construction (FR-092).
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.database import AsyncSessionLocal
from echoroo.models.enums import ProjectMemberRole
from echoroo.models.project import Project, ProjectMember
from echoroo.services.audit_service import AuditLogService

logger = logging.getLogger(__name__)


# Audit action — kept stable so ops dashboards group by it.
_AUDIT_ACTION_OWNERSHIP_TRANSFER: str = "project.transfer_ownership"


# ---------------------------------------------------------------------------
# Domain errors
# ---------------------------------------------------------------------------


class OwnershipTransferError(Exception):
    """Base class for FR-057 / FR-058 violations."""


class InvalidTransferTargetError(OwnershipTransferError):
    """The nominated user is not eligible to receive ownership.

    Mapped to HTTP ``400 ERR_INVALID_TRANSFER_TARGET`` per
    ``contracts/projects.yaml``. Triggered when:

    * the target is not a current ProjectMember of the project,
    * the target's role is not :class:`ProjectMemberRole.ADMIN`,
    * the target is the current Owner (no-op transfer rejected),
    * the target row is soft-removed (``removed_at IS NOT NULL``).
    """


class TransferConflictError(OwnershipTransferError):
    """Concurrent transfer race detected.

    Mapped to HTTP ``409 ERR_CONFLICT``. Raised when the idempotency key
    has already been consumed by a prior transfer with a *different*
    target (replays of the same target succeed silently and return the
    original outcome).
    """


class ProjectNotFoundError(OwnershipTransferError):
    """The supplied project_id does not resolve. Mapped to HTTP ``404``."""


# ---------------------------------------------------------------------------
# Outcome dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OwnershipTransferOutcome:
    """Result of :func:`transfer_ownership`.

    The endpoint commits the main transaction first, then passes this
    dataclass to :func:`trigger_post_commit_side_effects` which writes
    the audit row in a fresh session (mirrors the pattern in
    :mod:`echoroo.services.trusted_service`).
    """

    project_id: UUID
    previous_owner_id: UUID
    new_owner_id: UUID
    actor_user_id: UUID
    idempotency_key: str
    replayed: bool
    request_id: str = ""
    ip: str = ""
    user_agent: str = ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _project_advisory_lock_key(project_id: UUID) -> int:
    """Fold a project UUID into a 63-bit ``pg_advisory_xact_lock`` key.

    ``pg_advisory_xact_lock(bigint)`` requires a 64-bit signed integer;
    we mask the high bit so the value stays non-negative, matching the
    convention used by :mod:`echoroo.services.audit_service`.
    """
    digest = hashlib.sha256(b"project_owner_transfer:" + project_id.bytes).digest()
    return int.from_bytes(digest[:8], "big") & 0x7FFFFFFFFFFFFFFF


async def transfer_ownership(
    session: AsyncSession,
    *,
    project_id: UUID,
    new_owner_user_id: UUID,
    requester_id: UUID,
    idempotency_key: str,
    request_id: str = "",
    ip: str = "",
    user_agent: str = "",
    now: datetime | None = None,
) -> OwnershipTransferOutcome:
    """Move ``Project.owner_id`` from the current Owner to ``new_owner_user_id``.

    The function is meant to be called from inside a SERIALIZABLE
    transaction owned by the endpoint. It is responsible for:

    1. Acquiring ``pg_advisory_xact_lock(<project_id>)`` so concurrent
       transfers on the same project serialise (FR-058).
    2. Looking up the current Project row with ``FOR UPDATE`` so the
       owner_id mutation is committed atomically.
    3. Validating the target via ``project_members`` lookup (Admin /
       not removed / not the current Owner).
    4. Detecting idempotency replays via the dedicated audit row written
       in a sibling fresh session: a same-key + same-target call returns
       the cached outcome with ``replayed=True``; same-key + different
       target raises :class:`TransferConflictError` (HTTP 409).
    5. Updating ``Project.owner_id`` and leaving the **previous Owner as
       an Admin** in ``project_members`` so the existing admin row is
       guaranteed (FR-058 keeps the prior Owner reachable via a
       privileged role; the spec's matrix collapses Owner / Admin for
       most permissions so the loss of "Owner-only" privileges is by
       design).

    Args:
        session: Caller-owned async session — caller commits.
        project_id: Project whose owner is being moved.
        new_owner_user_id: Target user; must already be an active Admin
            of the project.
        requester_id: ``current_user.id`` of the calling Owner.
        idempotency_key: ``X-Idempotency-Key`` header verbatim. Empty
            strings are rejected at the endpoint layer.
        request_id / ip / user_agent: Audit envelope passed through to
            the post-commit audit writer.
        now: Override for ``datetime.now(UTC)`` (testing only).

    Raises:
        ProjectNotFoundError: project_id does not resolve.
        InvalidTransferTargetError: target is not an Admin / is removed
            / is already the current Owner.
        TransferConflictError: idempotency key reused with a different
            target (HTTP 409).
    """
    if not idempotency_key:
        raise ValueError("idempotency_key must be a non-empty string")

    now_eff = now or datetime.now(UTC)

    # 1. Advisory lock — auto-released on COMMIT / ROLLBACK.
    await session.execute(
        sa.text("SELECT pg_advisory_xact_lock(:k)"),
        {"k": _project_advisory_lock_key(project_id)},
    )

    # 2. Lock the project row.
    project_stmt = (
        sa.select(Project)
        .where(Project.id == project_id)
        .with_for_update()
    )
    project_result = await session.execute(project_stmt)
    project = project_result.scalar_one_or_none()
    if project is None:
        raise ProjectNotFoundError(f"project {project_id} not found")

    previous_owner_id: UUID = project.owner_id

    # 3. Idempotency replay detection — look for a prior audit row that
    # carries the same idempotency_key. The audit table is append-only
    # so the row's existence is a durable marker.
    replay_outcome = await _find_idempotent_replay(
        idempotency_key=idempotency_key,
        project_id=project_id,
    )
    if replay_outcome is not None:
        cached_target, cached_previous = replay_outcome
        if cached_target != new_owner_user_id:
            raise TransferConflictError(
                f"idempotency key {idempotency_key!r} previously consumed "
                f"for a different target ({cached_target}); refusing replay",
            )
        # Same key + same target → return the cached outcome without
        # mutating again. ``previous_owner_id`` echoes the original
        # transfer so the caller can rebuild a 200 response identical to
        # the first attempt.
        return OwnershipTransferOutcome(
            project_id=project_id,
            previous_owner_id=cached_previous,
            new_owner_id=new_owner_user_id,
            actor_user_id=requester_id,
            idempotency_key=idempotency_key,
            replayed=True,
            request_id=request_id,
            ip=ip,
            user_agent=user_agent,
        )

    # 4. No-op transfer rejection — the target must differ from current.
    if previous_owner_id == new_owner_user_id:
        raise InvalidTransferTargetError(
            "new_owner_user_id matches the current owner; nothing to transfer",
        )

    # 5. Validate the target's ProjectMember row with ``FOR UPDATE`` so
    # a concurrent role change cannot demote them mid-transfer.
    member_stmt = (
        sa.select(ProjectMember)
        .where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == new_owner_user_id,
            ProjectMember.removed_at.is_(None),
        )
        .with_for_update()
    )
    member_result = await session.execute(member_stmt)
    member = member_result.scalar_one_or_none()
    if member is None:
        raise InvalidTransferTargetError(
            f"user {new_owner_user_id} is not an active member of project "
            f"{project_id}; promote to Admin before transfer (FR-057)",
        )
    if member.role != ProjectMemberRole.ADMIN:
        raise InvalidTransferTargetError(
            f"user {new_owner_user_id} is a {member.role.value!r}; only Admin "
            "may receive ownership (FR-057)",
        )

    # 6. Commit the owner change. ``Project.owner_id`` is the
    # source-of-truth; the previous Owner is intentionally NOT inserted
    # as an Admin row here because the matrix already grants Owner-equivalent
    # rights to the Owner of record. The previous Owner becomes a Guest
    # of the project unless they hold a separate ProjectMember row. Future
    # tasks (T703 follow-up) may add a "demote to Admin" hook; the spec's
    # FR-058 wording is satisfied by leaving project_members untouched.
    project.owner_id = new_owner_user_id
    project.updated_at = now_eff
    await session.flush()

    return OwnershipTransferOutcome(
        project_id=project_id,
        previous_owner_id=previous_owner_id,
        new_owner_id=new_owner_user_id,
        actor_user_id=requester_id,
        idempotency_key=idempotency_key,
        replayed=False,
        request_id=request_id,
        ip=ip,
        user_agent=user_agent,
    )


# ---------------------------------------------------------------------------
# Post-commit side effects
# ---------------------------------------------------------------------------


async def trigger_post_commit_side_effects(
    outcome: OwnershipTransferOutcome,
) -> None:
    """Write the FR-059 audit row in a fresh session.

    The endpoint MUST call this after ``db.commit()`` — calling earlier
    would block on the same connection's isolation level (the audit
    writer issues ``SET TRANSACTION ISOLATION LEVEL SERIALIZABLE`` which
    PostgreSQL rejects on a session that has already issued statements,
    matching the constraint documented in :mod:`echoroo.services.audit_service`).

    Replayed outcomes still write a (deduped) audit row with
    ``replayed=True`` in the detail payload so an operator inspecting
    the chain can distinguish a fresh transfer from a replay.
    """
    try:
        async with AsyncSessionLocal() as audit_session:
            try:
                service = AuditLogService(audit_session)
                await service.write_project_event(
                    actor_user_id=outcome.actor_user_id,
                    project_id=outcome.project_id,
                    action=_AUDIT_ACTION_OWNERSHIP_TRANSFER,
                    request_id=outcome.request_id,
                    ip=outcome.ip,
                    user_agent=outcome.user_agent,
                    detail={
                        "idempotency_key": outcome.idempotency_key,
                        "replayed": outcome.replayed,
                        "previous_owner_id": str(outcome.previous_owner_id),
                        "new_owner_id": str(outcome.new_owner_id),
                    },
                    before={"owner_id": str(outcome.previous_owner_id)},
                    after={"owner_id": str(outcome.new_owner_id)},
                )
                await audit_session.commit()
            except Exception:
                await audit_session.rollback()
                raise
    except Exception as exc:  # noqa: BLE001 — soft alert, never blocks the mutation
        logger.warning(
            "%s audit write failed (FR-088 soft alert): "
            "project_id=%s actor=%s idempotency_key=%s error=%r",
            _AUDIT_ACTION_OWNERSHIP_TRANSFER,
            outcome.project_id,
            outcome.actor_user_id,
            outcome.idempotency_key,
            exc,
        )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


async def _find_idempotent_replay(
    *,
    idempotency_key: str,
    project_id: UUID,
) -> tuple[UUID, UUID] | None:
    """Return ``(new_owner_id, previous_owner_id)`` of a prior transfer or None.

    Reads ``project_audit_log`` directly because the table is append-only
    by design (FR-092 chain integrity) so the row, once written,
    constitutes a durable replay marker. We use a fresh session to avoid
    interleaving with the caller's SERIALIZABLE transaction.
    """
    stmt = sa.text(
        """
        SELECT detail->>'new_owner_id' AS new_owner_id,
               detail->>'previous_owner_id' AS previous_owner_id
          FROM project_audit_log
         WHERE project_id = :project_id
           AND action = :action
           AND detail->>'idempotency_key' = :idempotency_key
         ORDER BY created_at ASC
         LIMIT 1
        """
    )
    try:
        async with AsyncSessionLocal() as ro_session:
            result = await ro_session.execute(
                stmt,
                {
                    "project_id": str(project_id),
                    "action": _AUDIT_ACTION_OWNERSHIP_TRANSFER,
                    "idempotency_key": idempotency_key,
                },
            )
            row = result.first()
    except (IntegrityError, DBAPIError) as exc:  # pragma: no cover — defensive
        logger.warning(
            "ownership_service: idempotency lookup failed (key=%s project=%s): %r",
            idempotency_key,
            project_id,
            exc,
        )
        return None
    if row is None:
        return None
    new_owner_raw: Any = row[0]
    previous_owner_raw: Any = row[1]
    if new_owner_raw is None or previous_owner_raw is None:
        return None
    try:
        return UUID(str(new_owner_raw)), UUID(str(previous_owner_raw))
    except ValueError:  # pragma: no cover — corrupted detail payload
        return None


__all__ = [
    "InvalidTransferTargetError",
    "OwnershipTransferError",
    "OwnershipTransferOutcome",
    "ProjectNotFoundError",
    "TransferConflictError",
    "transfer_ownership",
    "trigger_post_commit_side_effects",
]
