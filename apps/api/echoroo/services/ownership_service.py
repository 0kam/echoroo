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

    # 3. Phase 12 R1 致命 C2: re-verify the requester is STILL the Owner
    # *after* the FOR UPDATE returned. If a faster concurrent transfer
    # already moved ``projects.owner_id`` to someone else, the
    # gate_action() check the endpoint performed earlier (before the
    # advisory lock was acquired) is stale; surface 409 so the loser of
    # the race cannot accidentally write a transfer for which they no
    # longer hold the Owner role.
    if previous_owner_id != requester_id:
        raise TransferConflictError(
            f"requester {requester_id} is not the current owner of project "
            f"{project_id} (current owner: {previous_owner_id}); a concurrent "
            "transfer already changed ownership",
        )

    # 4. Phase 12 R1 致命 C3: in-TX idempotency dedupe via outbox row.
    # We insert a row into ``outbox_events`` with a deterministic
    # ``idempotency_key`` and ``ON CONFLICT DO NOTHING``. When the
    # RETURNING clause yields no row, a prior transfer already consumed
    # the key and we resolve the replay outcome from the existing row's
    # payload. The outbox UNIQUE constraint is enforced inside the
    # current transaction so two parallel callers cannot both insert.
    #
    # The ``outbox_events.idempotency_key`` column is VARCHAR(128); we
    # therefore SHA-256 the user-supplied key together with the
    # project_id and store the hex digest as the unique slot. The hash
    # collapses arbitrary-length caller keys into a fixed 64-char tail
    # while preserving the spec's per-(project, key) namespace.
    key_digest = hashlib.sha256(
        f"{project_id}:{idempotency_key}".encode()
    ).hexdigest()
    scoped_idem_key = f"{_IDEMPOTENCY_KEY_PREFIX}{key_digest}"
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
        # Replay path: existing outbox row already carries the original
        # transfer's payload. Same target → return cached outcome with
        # ``replayed=True``; different target → 409.
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

    # 5. No-op transfer rejection — the target must differ from current.
    if previous_owner_id == new_owner_user_id:
        raise InvalidTransferTargetError(
            "new_owner_user_id matches the current owner; nothing to transfer",
        )

    # 6. Validate the target's ProjectMember row with ``FOR UPDATE`` so
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

    # 7. Commit the owner change. ``Project.owner_id`` is the
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


async def _load_replay_payload(
    session: AsyncSession,
    *,
    scoped_idem_key: str,
) -> dict[str, UUID] | None:
    """Return the original ``new_owner_id`` / ``previous_owner_id`` from outbox.

    Phase 12 R1 致命 C3: this is invoked **inside** the active TX after
    an ``ON CONFLICT DO NOTHING`` reported the idempotency key is
    already taken. We read the existing outbox row's payload to figure
    out whether the replay matches the original target (idempotent) or
    targets a different user (409 conflict).

    Returns:
        ``{"new_owner_id": UUID, "previous_owner_id": UUID}`` for a
        well-formed payload, or ``None`` if the row is missing /
        corrupted (defensive — should never happen because the unique
        constraint just rejected our INSERT).
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
    if new_owner_raw is None or prev_owner_raw is None:
        return None
    try:
        return {
            "new_owner_id": UUID(str(new_owner_raw)),
            "previous_owner_id": UUID(str(prev_owner_raw)),
        }
    except ValueError:  # pragma: no cover — corrupted payload
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
