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
3. ``X-Idempotency-Key`` is dedupe'd via a dedicated ``outbox_events``
   row written **inside the same transaction** as the ``projects.owner_id``
   mutation (Phase 12 R1 致命 C3 fix). The outbox table carries a
   ``UNIQUE`` constraint on ``idempotency_key``; we INSERT ``ON CONFLICT
   DO NOTHING`` and inspect ``RETURNING id`` — when no id is returned
   we know a prior transfer already consumed the key and we route to
   the replay branch. The same TX also writes the canonical ownership
   transfer notification, so the persistence guarantee piggybacks on
   FR-076a (the outbox dispatcher will deliver the notification iff
   the owner_id mutation committed). Audit log + outbound side-effects
   are still written post-commit through fresh sessions because the
   audit chain helper requires ``SET TRANSACTION ISOLATION LEVEL
   SERIALIZABLE`` to be the first statement on its connection.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import lazyload

from echoroo.core.database import AsyncSessionLocal
from echoroo.models.enums import ProjectMemberRole
from echoroo.models.project import Project, ProjectMember
from echoroo.services.audit_service import AuditLogService

# Outbox event_type used as the in-TX idempotency marker. The outbox
# dispatcher (Phase 13+) consumes the same row to email participants.
_OWNERSHIP_TRANSFER_EVENT_TYPE: str = "project.ownership_transfer"

# Idempotency-key prefix scoped to ownership transfer so the (UNIQUE)
# outbox key namespace cannot collide with caller-chosen keys for other
# event types.
_IDEMPOTENCY_KEY_PREFIX: str = "ownership_transfer:"

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

    Mapped to HTTP ``409 ERR_CONFLICT``. Raised when:

    * the idempotency key has already been consumed by a prior transfer
      with a *different* target (replays of the same target succeed
      silently and return the original outcome), OR
    * the requester is no longer the Owner of the project at the moment
      the SELECT FOR UPDATE returned (Phase 12 R1 C2 fix). The second
      case implies a faster concurrent transfer already moved
      ``projects.owner_id`` to someone else; we surface 409 (rather than
      403) so the caller knows the conflict is racing-not-permission.
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


def derive_scoped_idempotency_key(
    project_id: UUID, idempotency_key: str
) -> str:
    """Compute the canonical ``outbox_events.idempotency_key`` slot.

    Phase 12 R2 致命 C3: the endpoint short-circuits HTTP retries that
    arrive after the original Owner has already been replaced. To probe
    the outbox dedupe row before ``gate_action()`` it needs the same
    deterministic slot the service uses internally; exposing the
    derivation as a public function keeps the two surfaces in lockstep.
    """
    key_digest = hashlib.sha256(
        f"{project_id}:{idempotency_key}".encode()
    ).hexdigest()
    return f"{_IDEMPOTENCY_KEY_PREFIX}{key_digest}"


async def peek_replay_outcome(
    session: AsyncSession,
    *,
    project_id: UUID,
    idempotency_key: str,
    new_owner_user_id: UUID,
    requester_id: UUID,
    request_id: str = "",
    ip: str = "",
    user_agent: str = "",
) -> OwnershipTransferOutcome | None:
    """Return the cached transfer outcome for an HTTP retry, or ``None``.

    Phase 12 R2 致命 C3 — endpoint-level idempotency replay short-circuit
    that runs **before** ``gate_action()``. The original Owner who
    successfully transferred ownership but lost the response (network
    blip / proxy timeout) is no longer Owner; ``gate_action`` would
    therefore reject the retry with 403. Detecting the replay before
    the gate restores the contract that "same key + same target ⇒
    cached outcome with replayed=true".

    Phase 12 R3 follow-up (Major #1) — **requester actor binding**:
    only the *original* actor (the user who fired the first transfer,
    captured as ``actor_user_id`` / ``previous_owner_id`` in the cached
    payload) may receive the cached outcome. Any other authenticated
    caller who happens to know / guess the idempotency key + target
    + project triple is treated as if no cached outcome existed
    (returns ``None``); the call then falls through to the normal
    Stage-1 ``gate_action()`` which rejects them with 403 (they no
    longer hold the Owner role) — matching the spec's confidentiality
    posture for ownership transfer history. We deliberately do NOT
    raise 409 in the actor-mismatch branch because doing so would leak
    "an idempotency key has been consumed on this project" to a
    non-actor caller, which is itself a side-channel.

    Returns:
        * cached :class:`OwnershipTransferOutcome` (replayed=True) when
          a row exists, the target matches AND the requester matches the
          previous actor.
        * ``None`` when no prior consumption is recorded OR when the
          requester is not the original actor — caller MUST continue
          with the normal gate + service flow (which will 403 a
          non-actor caller).

    Raises:
        TransferConflictError: same key + same actor + DIFFERENT target → 409.
    """
    scoped_key = derive_scoped_idempotency_key(project_id, idempotency_key)
    replay = await _load_replay_payload(session, scoped_idem_key=scoped_key)
    if replay is None:
        return None
    cached_new_owner = replay["new_owner_id"]
    cached_previous = replay["previous_owner_id"]
    cached_actor = replay.get("actor_user_id")
    # Actor binding: the cached outcome belongs to the user who fired
    # the original transfer. Their user_id is recorded as
    # ``actor_user_id`` in the outbox payload (and equals
    # ``previous_owner_id`` because Owner is the only principal
    # permitted to invoke the action). A different requester arriving
    # with the same key + target falls through to the normal gate
    # (which will 403 them) instead of receiving the replay echo.
    if cached_actor is None or cached_actor != requester_id:
        return None
    if cached_new_owner != new_owner_user_id:
        raise TransferConflictError(
            f"idempotency key {idempotency_key!r} previously consumed "
            f"for a different target ({cached_new_owner}); refusing replay",
        )
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
    5. Updating ``Project.owner_id`` and reconciling ``project_members``
       so the post-transfer state is consistent (preview-fixes bug fix):

       * the **previous Owner** gains an ACTIVE Admin ``project_members``
         row (inserted when absent — the normal case, since project
         creation never seeds an owner membership row — or
         reactivated/upgraded from an existing removed/old row). This
         keeps the prior Owner reachable via a privileged role per FR-058
         and matches the transfer UI's "You will become an Admin"
         promise; the spec's matrix collapses Owner / Admin for most
         permissions so the loss of "Owner-only" privileges is by design.
       * the **new Owner's** redundant Admin ``project_members`` row is
         soft-removed, because the Owner is represented solely by
         ``owner_id`` and must not be double-listed as a plain member.

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

    # Phase 12 R1 Minor m1 note on isolation level
    # ----------------------------------------------
    # PostgreSQL only accepts ``SET TRANSACTION ISOLATION LEVEL
    # SERIALIZABLE`` as the FIRST statement on a connection. Production
    # endpoints invoke this service from a fresh ``DbSession`` so the
    # caller MAY upgrade the isolation level upstream (e.g. via a
    # FastAPI dependency that wraps the session). We deliberately do
    # NOT issue the SET here because:
    #   * the advisory lock acquired immediately below serialises every
    #     conflicting transfer on the per-project scope (FR-058), and
    #   * the in-TX outbox UNIQUE constraint provides the cross-key
    #     dedupe semantic regardless of the isolation level.
    # The combination is equivalent to a SERIALIZABLE TX from the
    # caller's perspective for the specific invariants the spec
    # requires (no double-write, idempotent replay). Test fixtures
    # therefore do not need a fresh connection to exercise the path.

    # 1. Advisory lock — auto-released on COMMIT / ROLLBACK.
    await session.execute(
        sa.text("SELECT pg_advisory_xact_lock(:k)"),
        {"k": _project_advisory_lock_key(project_id)},
    )

    # 2. Lock the project row.
    # Use lazyload on the ``owner`` relationship so the SELECT does NOT
    # emit a LEFT OUTER JOIN; PostgreSQL rejects FOR UPDATE on the
    # nullable side of an outer join.
    project_stmt = (
        sa.select(Project)
        .options(lazyload(Project.owner))
        .where(Project.id == project_id)
        .with_for_update()
    )
    project_result = await session.execute(project_stmt)
    project = project_result.scalar_one_or_none()
    if project is None:
        raise ProjectNotFoundError(f"project {project_id} not found")

    previous_owner_id: UUID = project.owner_id

    # 3. Phase 12 R2 致命 C3: replay short-circuit BEFORE owner re-check.
    # An HTTP retry from the original Owner-at-the-time-of-the-first-call
    # whose ownership has since transferred MUST still be able to read
    # the cached replay outcome — otherwise a network blip on a winning
    # transfer would surface 409 to the caller who in fact succeeded.
    # We therefore probe the outbox dedupe row first; if a row exists we
    # return the cached outcome (or 409 if the target differs). Only
    # when no prior consumption is recorded do we proceed to the owner
    # re-check (C2 fix below).
    #
    # The ``outbox_events.idempotency_key`` column is VARCHAR(128); we
    # SHA-256 the user-supplied key together with the project_id and
    # store the hex digest as the unique slot. The hash collapses
    # arbitrary-length caller keys into a fixed 64-char tail while
    # preserving the spec's per-(project, key) namespace.
    scoped_idem_key = derive_scoped_idempotency_key(project_id, idempotency_key)

    existing_replay = await _load_replay_payload(
        session, scoped_idem_key=scoped_idem_key
    )
    if existing_replay is not None:
        cached_new_owner = existing_replay["new_owner_id"]
        cached_previous = existing_replay["previous_owner_id"]
        cached_actor = existing_replay.get("actor_user_id")
        # Phase 12 R3 follow-up (Major #1): replay echoing requires the
        # requester to match the original actor. Mismatch → fall through
        # to the C2 owner re-check below, which raises 409 because a
        # non-actor caller cannot still hold the Owner role on a project
        # whose owner_id was already mutated by the cached transfer.
        if cached_actor is not None and cached_actor == requester_id:
            if cached_new_owner != new_owner_user_id:
                raise TransferConflictError(
                    f"idempotency key {idempotency_key!r} previously consumed "
                    f"for a different target ({cached_new_owner}); refusing replay",
                )
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

    # 4. Phase 12 R1 致命 C2: re-verify the requester is STILL the Owner
    # *after* the FOR UPDATE returned. If a faster concurrent transfer
    # already moved ``projects.owner_id`` to someone else, the
    # gate_action() check the endpoint performed earlier (before the
    # advisory lock was acquired) is stale; surface 409 so the loser of
    # the race cannot accidentally write a transfer for which they no
    # longer hold the Owner role. Replay short-circuit (above) already
    # exited for the legitimate retry case.
    if previous_owner_id != requester_id:
        raise TransferConflictError(
            f"requester {requester_id} is not the current owner of project "
            f"{project_id} (current owner: {previous_owner_id}); a concurrent "
            "transfer already changed ownership",
        )

    # 5. In-TX idempotency dedupe via outbox row. We insert a row into
    # ``outbox_events`` with a deterministic ``idempotency_key`` and
    # ``ON CONFLICT DO NOTHING``. When the RETURNING clause yields no
    # row, a parallel transfer racing on the same key just won the
    # advisory lock + insert race; we re-load the freshly committed
    # payload to honour the replay contract. The outbox UNIQUE
    # constraint is enforced inside the current transaction so two
    # parallel callers cannot both insert.
    transfer_payload: dict[str, Any] = {
        "project_id": str(project_id),
        "previous_owner_id": str(previous_owner_id),
        "new_owner_id": str(new_owner_user_id),
        "actor_user_id": str(requester_id),
        "idempotency_key": idempotency_key,
        "request_id": request_id,
        "evaluated_at": now_eff.isoformat(),
    }
    insert_result = await session.execute(
        sa.text(
            """
            INSERT INTO outbox_events
                (event_type, payload, status, retry_count, next_retry_at,
                 idempotency_key, created_at)
            VALUES
                (:event_type, CAST(:payload AS JSONB), 'pending', 0,
                 :next_retry_at, :idempotency_key, :created_at)
            ON CONFLICT (idempotency_key) DO NOTHING
            RETURNING id
            """
        ),
        {
            "event_type": _OWNERSHIP_TRANSFER_EVENT_TYPE,
            "payload": json.dumps(
                transfer_payload,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ),
            "next_retry_at": now_eff,
            "idempotency_key": scoped_idem_key,
            "created_at": now_eff,
        },
    )
    inserted_row = insert_result.first()
    if inserted_row is None:
        # Race-tail replay: the row was inserted by a parallel caller
        # between our step-3 lookup and the INSERT above (e.g. two
        # workers fanned out from the same retry shard). Re-load and
        # honour the replay outcome.
        replay = await _load_replay_payload(
            session, scoped_idem_key=scoped_idem_key
        )
        if replay is None:  # pragma: no cover — defensive
            raise TransferConflictError(
                f"idempotency key {idempotency_key!r} consumed by a prior "
                "transfer whose payload could not be decoded"
            )
        cached_new_owner = replay["new_owner_id"]
        cached_previous = replay["previous_owner_id"]
        cached_actor = replay.get("actor_user_id")
        # Phase 12 R3 follow-up (Major #1): a non-actor requester losing
        # the parallel race must not receive the cached outcome — surface
        # 409 so they cannot enumerate previously-consumed keys.
        if cached_actor is None or cached_actor != requester_id:
            raise TransferConflictError(
                f"idempotency key {idempotency_key!r} previously consumed "
                "by a different actor; refusing replay",
            )
        if cached_new_owner != new_owner_user_id:
            raise TransferConflictError(
                f"idempotency key {idempotency_key!r} previously consumed "
                f"for a different target ({cached_new_owner}); refusing replay",
            )
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

    # 6. No-op transfer rejection — the target must differ from current.
    if previous_owner_id == new_owner_user_id:
        raise InvalidTransferTargetError(
            "new_owner_user_id matches the current owner; nothing to transfer",
        )

    # 7. Validate the target's ProjectMember row with ``FOR UPDATE`` so
    # a concurrent role change cannot demote them mid-transfer.
    # Use lazyload on ``user`` and ``project`` to avoid FOR UPDATE
    # incompatibility with LEFT OUTER JOIN (same fix as the Project query
    # above).
    member_stmt = (
        sa.select(ProjectMember)
        .options(
            lazyload(ProjectMember.user),
            lazyload(ProjectMember.project),
            lazyload(ProjectMember.invited_by),
        )
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

    # 8. Commit the owner change. ``Project.owner_id`` is the
    # source-of-truth for the Owner role; a user is NEVER both the
    # ``owner_id`` AND an active ``project_members`` row (role resolution
    # in ``services.project.resolve_current_user_role`` returns "owner"
    # via ``owner_id`` first, and the members list is built from
    # ``project_members`` rows — so the Owner must not appear in both).
    #
    # preview-fixes/ws4-su-redesign bug fix (Gate 3, DB-confirmed): the
    # previous implementation left ``project_members`` untouched, which
    # orphaned the PREVIOUS owner. Because project creation never inserts
    # an owner ``project_members`` row (see ``services.project`` /
    # ``Project(owner_id=...)``), the previous owner had NO membership row
    # at all; once ``owner_id`` moved away from them they became a
    # non-member (403 on the project) instead of the Admin the transfer
    # UI promises. We now reconcile both sides so the post-transfer state
    # is consistent:
    #
    #   (a) PREVIOUS owner  -> ensure an ACTIVE Admin ``project_members``
    #       row (INSERT one when absent — the normal case — or
    #       reactivate / upgrade an existing removed/old row).
    #   (b) NEW owner       -> soft-remove their now-redundant Admin
    #       ``project_members`` row (``member`` loaded FOR UPDATE in
    #       step 7) so the Owner is represented solely by ``owner_id``
    #       and is not double-listed in the members list.
    #
    # Both writes land in the caller's transaction (atomic with the
    # ``owner_id`` mutation) and the partial unique index
    # ``ux_project_members_active`` (one active row per project+user)
    # stays satisfied: the new owner's only active row is deactivated and
    # the previous owner gains exactly one fresh active row.
    project.owner_id = new_owner_user_id
    project.updated_at = now_eff

    # (b) Deactivate the new owner's redundant membership row.
    member.removed_at = now_eff

    # (a) Ensure the previous owner has an ACTIVE Admin membership row.
    #
    # Race-safety (preview-fixes/ws4-su-redesign H1): the prior
    # implementation did a pre-flight ``SELECT ... FOR UPDATE`` and, when
    # it found NO row, issued a plain INSERT. That is NOT safe against the
    # partial unique index ``ux_project_members_active`` (one active row
    # per (project_id, user_id) WHERE removed_at IS NULL): a
    # ``FOR UPDATE`` that returns zero rows locks NOTHING, so a concurrent
    # transaction (e.g. an invitation-accept granting the previous owner
    # an active membership) could INSERT an active row in the window
    # between our SELECT and our INSERT → unique-index violation → 500 /
    # rollback. We now wrap the INSERT in a SAVEPOINT and, on the unique
    # violation, fall back to a re-query + in-place UPGRADE — matching the
    # SAVEPOINT-nested ProjectMember upsert used by the invitation-accept
    # path (``services.invitation_service`` FR-011-123) and the bulk
    # member SAVEPOINT loop.
    await _ensure_previous_owner_admin_member(
        session,
        project_id=project_id,
        previous_owner_id=previous_owner_id,
        new_owner_user_id=new_owner_user_id,
        now_eff=now_eff,
    )

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


async def _ensure_previous_owner_admin_member(
    session: AsyncSession,
    *,
    project_id: UUID,
    previous_owner_id: UUID,
    new_owner_user_id: UUID,
    now_eff: datetime,
) -> None:
    """Race-safely guarantee the previous owner has ONE active Admin row.

    End state: exactly one active ``project_members`` row for
    ``(project_id, previous_owner_id)`` at ``role=ADMIN`` with
    ``removed_at IS NULL`` — never two, and never a unique-index
    violation under concurrency.

    Strategy (matches the SAVEPOINT-nested ProjectMember upsert in
    :mod:`echoroo.services.invitation_service`, FR-011-123, and the bulk
    member SAVEPOINT loop): first try to UPGRADE any existing row found
    for the pair (the common reactivation / role-bump path); when NO row
    exists, attempt the INSERT inside a ``begin_nested()`` SAVEPOINT. If a
    concurrent transaction inserted an active row in the window between
    our lookup and our INSERT, the partial unique index
    ``ux_project_members_active`` raises :class:`IntegrityError`; we roll
    the SAVEPOINT back, re-query the now-existing active row, and UPGRADE
    it in place to ``role=ADMIN``. The whole sequence stays inside the
    caller's transaction so it remains atomic with the ``owner_id``
    mutation, the audit chain, and idempotency replay.
    """
    # Look up ANY existing row for (project, previous_owner) — including a
    # soft-removed one — so we reactivate/upgrade rather than INSERT a
    # second active row that would violate ``ux_project_members_active``.
    # The ordering surfaces an active row (removed_at IS NULL) first so a
    # stale soft-removed row never shadows a live one.
    prev_owner_stmt = (
        sa.select(ProjectMember)
        .options(
            lazyload(ProjectMember.user),
            lazyload(ProjectMember.project),
            lazyload(ProjectMember.invited_by),
        )
        .where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == previous_owner_id,
        )
        .order_by(ProjectMember.removed_at.is_(None).desc())
        .with_for_update()
    )
    prev_owner_member = (
        await session.execute(prev_owner_stmt)
    ).scalars().first()

    if prev_owner_member is not None:
        # An existing row was found and is locked FOR UPDATE. Reactivate
        # it if it was soft-removed and upgrade the role to Admin so the
        # former owner retains a privileged role (matching the transfer
        # UI's "You will become an Admin" promise).
        _upgrade_member_to_active_admin(prev_owner_member, now_eff=now_eff)
        return

    # Normal case: no row was found. Because a ``FOR UPDATE`` that returns
    # zero rows locks NOTHING, a concurrent transaction can still INSERT
    # an active row for the same pair before us; insert inside a SAVEPOINT
    # so a unique-index collision is recoverable rather than fatal.
    try:
        async with session.begin_nested():
            session.add(
                ProjectMember(
                    project_id=project_id,
                    user_id=previous_owner_id,
                    role=ProjectMemberRole.ADMIN,
                    joined_at=now_eff,
                    removed_at=None,
                    # The new owner (who just received ownership) is
                    # recorded as the inviter for audit lineage.
                    invited_by_id=new_owner_user_id,
                )
            )
            # Force the INSERT to hit the DB inside the SAVEPOINT so the
            # ``ux_project_members_active`` violation surfaces HERE (and is
            # rolled back to the savepoint) rather than poisoning the
            # outer transaction at the caller's ``flush()``.
            await session.flush()
        return
    except IntegrityError:
        # A concurrent transaction won the INSERT race for the active row.
        # The SAVEPOINT was rolled back, so the outer transaction is still
        # usable. Re-query the now-existing row (FOR UPDATE locks it this
        # time — it exists) and upgrade it in place to ADMIN.
        racing_member = (
            await session.execute(prev_owner_stmt)
        ).scalars().first()
        if racing_member is None:  # pragma: no cover - defensive
            # Should be unreachable: the IntegrityError proves a row now
            # exists for the pair. Re-raise so the caller rolls back
            # rather than silently leaving the previous owner roleless.
            raise
        _upgrade_member_to_active_admin(racing_member, now_eff=now_eff)


def _upgrade_member_to_active_admin(
    member: ProjectMember,
    *,
    now_eff: datetime,
) -> None:
    """Reactivate (if soft-removed) and upgrade ``member`` to active Admin."""
    if member.removed_at is not None:
        member.removed_at = None
        member.joined_at = now_eff
    member.role = ProjectMemberRole.ADMIN


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


async def _load_replay_payload(
    session: AsyncSession,
    *,
    scoped_idem_key: str,
) -> dict[str, UUID] | None:
    """Return the original transfer payload from outbox, or ``None``.

    Phase 12 R1 致命 C3: this is invoked **inside** the active TX after
    an ``ON CONFLICT DO NOTHING`` reported the idempotency key is
    already taken. We read the existing outbox row's payload to figure
    out whether the replay matches the original target (idempotent) or
    targets a different user (409 conflict).

    Phase 12 R3 follow-up (Major #1) — also surfaces ``actor_user_id``
    so :func:`peek_replay_outcome` can enforce requester binding.
    Older payloads written before the R3 fix do not carry the field;
    callers MUST treat a missing key as "actor mismatch" rather than
    "wildcard match" (i.e. fall through to the normal gate path).

    Returns:
        ``{"new_owner_id": UUID, "previous_owner_id": UUID,
        "actor_user_id": UUID | None}`` for a well-formed payload, or
        ``None`` if the row is missing / corrupted (defensive — should
        never happen because the unique constraint just rejected our
        INSERT).
    """
    stmt = sa.text(
        """
        SELECT payload
          FROM outbox_events
         WHERE idempotency_key = :idempotency_key
         LIMIT 1
        """
    )
    try:
        result = await session.execute(stmt, {"idempotency_key": scoped_idem_key})
        row = result.first()
    except (IntegrityError, DBAPIError) as exc:  # pragma: no cover — defensive
        logger.warning(
            "ownership_service: replay payload lookup failed (key=%s): %r",
            scoped_idem_key,
            exc,
        )
        return None
    if row is None:
        return None
    raw_payload: Any = row[0]
    payload: dict[str, Any]
    if isinstance(raw_payload, dict):
        payload = raw_payload
    elif isinstance(raw_payload, (str, bytes, bytearray)):
        try:
            payload = json.loads(raw_payload)
        except (TypeError, ValueError):  # pragma: no cover — corrupted payload
            return None
    else:  # pragma: no cover — unexpected JSONB shape
        return None
    new_owner_raw = payload.get("new_owner_id")
    prev_owner_raw = payload.get("previous_owner_id")
    actor_raw = payload.get("actor_user_id")
    if new_owner_raw is None or prev_owner_raw is None:
        return None
    try:
        out: dict[str, UUID] = {
            "new_owner_id": UUID(str(new_owner_raw)),
            "previous_owner_id": UUID(str(prev_owner_raw)),
        }
    except ValueError:  # pragma: no cover — corrupted payload
        return None
    # ``actor_user_id`` is a Phase 12 R3 follow-up addition; pre-existing
    # rows in mid-deploy environments may lack the field. Decode when
    # present, omit otherwise — callers fail-closed on the missing key.
    if actor_raw is not None:
        with contextlib.suppress(ValueError):  # pragma: no cover — corrupted payload
            out["actor_user_id"] = UUID(str(actor_raw))
    return out


__all__ = [
    "InvalidTransferTargetError",
    "OwnershipTransferError",
    "OwnershipTransferOutcome",
    "ProjectNotFoundError",
    "TransferConflictError",
    "derive_scoped_idempotency_key",
    "peek_replay_outcome",
    "transfer_ownership",
    "trigger_post_commit_side_effects",
]
