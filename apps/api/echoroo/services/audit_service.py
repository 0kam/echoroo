"""Audit log writer (FR-088, FR-090..096).

Every mutation in the permission system eventually becomes a row in
``project_audit_log`` (project-scope events) or ``platform_audit_log``
(authentication / API key / superuser operations). The writer is the
single gate that owns:

* **Sanitization** (FR-091a): ``detail`` / ``before`` / ``after`` JSONB
  payloads pass through :class:`echoroo.core.audit.AuditLogSanitizer`
  before they reach PostgreSQL.
* **Keyed PII hashing** (FR-091): ``actor_user_id_hash``, ``ip_hash``,
  ``user_agent_hash`` are computed via ``kms:GenerateMac`` against the
  ``pii_hash_key`` CMK (see :func:`echoroo.core.kms.compute_pii_hash`).
* **Chain integrity** (FR-092, FR-093): each row carries
  ``row_hash = HMAC-SHA256(chain_key, prev_hash || canonical_row)``.
  The writer enforces serialisable isolation AND takes a transaction-
  scoped PostgreSQL advisory lock so two concurrent inserts cannot read
  the same ``prev_hash``.

Canonical row format (input to the MAC):

    created_at_iso || "\\n" || actor_user_id_hash || "\\n" || action
    || "\\n" || project_id_or_empty || "\\n" || request_id
    || "\\n" || ip_hash || "\\n" || user_agent_hash
    || "\\n" || stable_json(detail)
    || "\\n" || stable_json(before or {})
    || "\\n" || stable_json(after or {})

The exact format is deliberately **not** compatible with any other JSON
encoder — it is the version-1 canonicalisation and changes require a
``hash_version`` bump stored in ``detail``.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.audit import AuditLogSanitizer
from echoroo.core.kms import (
    compute_audit_chain_hash,
    compute_pii_hash,  # re-exported for tests that monkeypatch this module
    compute_pii_hash_dual,
    get_pii_hash_version,
)

# ``compute_pii_hash`` is intentionally re-exported above (used by
# tests that monkeypatch the symbol on this module). The runtime
# writer below uses ``compute_pii_hash_dual`` instead — but a number
# of pre-existing tests stub the single-key helper to keep their
# fixtures simple. Removing the import would break them silently
# (raising=True would still pass; the patch just wouldn't catch
# runtime calls). Keep the import; flake8 will flag it as unused
# without this hint:
_ = compute_pii_hash

logger = logging.getLogger(__name__)


# Genesis row prev_hash sentinel (64 zero hex chars). Mirrored in the
# baseline Alembic migration (``specs/006-permissions-redesign/
# data-model.md §3.17``).
_GENESIS_PREV_HASH: Final[str] = "0" * 64

# Canonical PostgreSQL advisory-lock key (bigint) for the audit chain.
# ``pg_advisory_xact_lock(bigint)`` takes a 64-bit signed integer so we
# fold a stable SHA-256 prefix into a 63-bit range (MSB cleared to keep
# the value non-negative and avoid sign-extension surprises across
# drivers / tools).
_AUDIT_CHAIN_LOCK_KEY: Final[int] = (
    int.from_bytes(hashlib.sha256(b"audit_log_chain").digest()[:8], "big") & 0x7FFFFFFFFFFFFFFF
)


def _canonical_json(value: Any) -> str:
    """Return a stable JSON string for chain-hash input.

    ``sort_keys=True`` + no whitespace + UTF-8 escape defaults give a
    byte-identical output for logically-equal inputs across Python
    versions, which is the only invariant the MAC relies on.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _build_canonical_row(
    *,
    created_at: datetime,
    actor_user_id_hash: str,
    action: str,
    project_id: UUID | None,
    request_id: str,
    ip_hash: str,
    user_agent_hash: str,
    detail: dict[str, Any],
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> bytes:
    """Assemble the v1 canonical byte payload for ``compute_audit_chain_hash``."""
    lines = [
        created_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        actor_user_id_hash,
        action,
        str(project_id) if project_id is not None else "",
        request_id,
        ip_hash,
        user_agent_hash,
        _canonical_json(detail),
        _canonical_json(before or {}),
        _canonical_json(after or {}),
    ]
    return "\n".join(lines).encode("utf-8")


class AuditLogService:
    """Transactional writer for the two audit log tables.

    The service mutates the provided :class:`AsyncSession` — it issues the
    ``SET TRANSACTION`` statement, the advisory lock, and the INSERT all
    on the caller's transaction. The caller is expected to commit the
    transaction after the write (coupling the audit row with the business
    change it describes, FR-092).
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- public API ---------------------------------------------------------

    async def write_project_event(
        self,
        *,
        actor_user_id: UUID | str | None,
        project_id: UUID,
        action: str,
        request_id: str,
        ip: str,
        user_agent: str,
        detail: dict[str, Any] | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> UUID:
        """Append a row to ``project_audit_log``.

        Returns the inserted row's ``id`` (useful for outbox idempotency
        keys that want to reference the audit row from a sibling table).
        """
        return await self._write(
            table="project_audit_log",
            actor_user_id=actor_user_id,
            project_id=project_id,
            action=action,
            request_id=request_id,
            ip=ip,
            user_agent=user_agent,
            detail=detail,
            before=before,
            after=after,
            created_at=created_at,
        )

    async def write_platform_event(
        self,
        *,
        actor_user_id: UUID | str | None,
        action: str,
        request_id: str,
        ip: str,
        user_agent: str,
        detail: dict[str, Any] | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> UUID:
        """Append a row to ``platform_audit_log`` (no project_id column)."""
        return await self._write(
            table="platform_audit_log",
            actor_user_id=actor_user_id,
            project_id=None,
            action=action,
            request_id=request_id,
            ip=ip,
            user_agent=user_agent,
            detail=detail,
            before=before,
            after=after,
            created_at=created_at,
        )

    # -- internals ----------------------------------------------------------

    async def _write(
        self,
        *,
        table: str,
        actor_user_id: UUID | str | None,
        project_id: UUID | None,
        action: str,
        request_id: str,
        ip: str,
        user_agent: str,
        detail: dict[str, Any] | None,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
        created_at: datetime | None,
    ) -> UUID:
        """Write a single audit row.

        REQUIREMENT (FR-093, Phase 2.10 #5): the caller MUST pass a
        **fresh** AsyncSession that has not yet executed any SQL on its
        underlying connection. PostgreSQL rejects ``SET TRANSACTION
        ISOLATION LEVEL SERIALIZABLE`` once any statement has run on the
        connection, so a session that has already issued a SELECT (e.g.
        the audit *read* endpoints fetching the page rows) cannot be
        reused for the meta-audit write.

        The two read endpoints in ``api/web_v1/audit.py`` honour this by
        opening a second AsyncSession dedicated to the meta-audit write;
        future writers MUST follow the same pattern.
        """
        if table not in ("project_audit_log", "platform_audit_log"):
            raise ValueError(f"unsupported audit table: {table!r}")

        # FR-093: SERIALIZABLE + advisory lock. Issued at the very start
        # of the transaction so PostgreSQL accepts the upgrade. The
        # session arrived "fresh" (see docstring contract above), so no
        # prior SELECT has fixed the connection's isolation level.
        await self.session.execute(
            sa.text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        )
        await self.session.execute(
            sa.text("SELECT pg_advisory_xact_lock(:key)").bindparams(key=_AUDIT_CHAIN_LOCK_KEY)
        )

        # FR-091a runtime sanitizer.
        sanitized = AuditLogSanitizer(
            detail=detail or {},
            before=before,
            after=after,
        )

        # FR-091 keyed PII hashing. The actor_user_id exception (spec
        # FR-091a §c) permits raw ``user_id`` in ``detail.before.owner_id``
        # etc., but the ``actor_user_id_hash`` column is always hashed.
        #
        # Phase 17 backlog A-2 (FR-091b): when rotation is active we
        # ALSO compute v2 hashes and persist them in the sibling
        # ``*_v2`` columns + a ``pii_hash_version`` discriminator. The
        # v1 hashes remain the chain-hash input so historical chain
        # validation is unaffected (ROTATIONAL changes to v2 columns
        # are intentionally NOT chained — they are derivative).
        actor_value = str(actor_user_id) if actor_user_id is not None else ""
        actor_hash_dual = (
            compute_pii_hash_dual(actor_value)
            if actor_value
            else {"v1": _GENESIS_PREV_HASH}
        )
        ip_hash_dual = (
            compute_pii_hash_dual(ip) if ip else {"v1": _GENESIS_PREV_HASH}
        )
        ua_hash_dual = (
            compute_pii_hash_dual(user_agent)
            if user_agent
            else {"v1": _GENESIS_PREV_HASH}
        )

        actor_hash = actor_hash_dual["v1"]
        ip_hash = ip_hash_dual["v1"]
        ua_hash = ua_hash_dual["v1"]
        actor_hash_v2 = actor_hash_dual.get("v2")
        ip_hash_v2 = ip_hash_dual.get("v2")
        ua_hash_v2 = ua_hash_dual.get("v2")
        pii_hash_version = get_pii_hash_version()

        created_at_eff = created_at or datetime.now(UTC)

        # Fetch the most-recent row_hash under the advisory lock. The
        # advisory lock alone is sufficient for *write* serialisation,
        # but PostgreSQL's SSI (SERIALIZABLE) detector still tracks the
        # SELECT's predicate range; under heavy concurrency the read can
        # participate in a phantom-read cycle and abort the transaction
        # with ``SerializationError`` (sqlstate 40001) — see T993
        # ``test_audit_log_concurrent_chain.py``.
        #
        # Phase 16 Batch 6h-0 (Codex Major): adding ``FOR UPDATE`` on the
        # chain-tail row promotes the SSI predicate to an explicit row
        # lock that pairs cleanly with the advisory lock and removes the
        # phantom-cycle vector.  Concurrent writers therefore queue on
        # the advisory lock OR the chain-tail row lock — either way the
        # next writer reads the prev_hash *after* the previous one
        # commits, exactly the invariant the chain integrity contract
        # requires.  We deliberately keep the deterministic
        # ``created_at DESC, id DESC`` tiebreak so two rows sharing the
        # same microsecond do not pick distinct prev_hashes.
        prev_hash_result = await self.session.execute(
            sa.text(
                f"SELECT row_hash FROM {table} "
                f"ORDER BY created_at DESC, id DESC LIMIT 1 "
                f"FOR UPDATE"
            )
        )
        prev_row = prev_hash_result.first()
        prev_hash = prev_row[0] if prev_row is not None else _GENESIS_PREV_HASH

        canonical = _build_canonical_row(
            created_at=created_at_eff,
            actor_user_id_hash=actor_hash,
            action=action,
            project_id=project_id,
            request_id=request_id,
            ip_hash=ip_hash,
            user_agent_hash=ua_hash,
            detail=sanitized.detail,
            before=sanitized.before,
            after=sanitized.after,
        )
        row_hash = compute_audit_chain_hash(prev_hash, canonical)

        # Insert. We use a bound parameter dialect-agnostic statement so
        # the writer works against both PostgreSQL (prod) and SQLite (a
        # subset of the unit tests that stub the chain calls).
        # When rotation is active (``pii_hash_version == 2``) the v2
        # sibling columns are populated; in single-key mode they remain
        # NULL and ``pii_hash_version`` is also NULL so a downstream
        # consistency check can distinguish "rotation never started"
        # from "rotation in progress, this row not yet backfilled".
        store_v2 = pii_hash_version == 2
        if table == "project_audit_log":
            insert_sql = sa.text(
                """
                INSERT INTO project_audit_log
                  (created_at, actor_user_id_hash, project_id, action,
                   detail, request_id, ip_hash, user_agent_hash,
                   before, after, prev_hash, row_hash,
                   actor_user_id_hash_v2, ip_hash_v2, user_agent_hash_v2,
                   pii_hash_version)
                VALUES
                  (:created_at, :actor_hash, :project_id, :action,
                   CAST(:detail AS JSONB), :request_id, :ip_hash, :ua_hash,
                   CAST(:before AS JSONB), CAST(:after AS JSONB),
                   :prev_hash, :row_hash,
                   :actor_hash_v2, :ip_hash_v2, :ua_hash_v2,
                   :pii_hash_version)
                RETURNING id
                """
            )
            params: dict[str, Any] = {
                "created_at": created_at_eff,
                "actor_hash": actor_hash,
                "project_id": str(project_id) if project_id else None,
                "action": action,
                "detail": _canonical_json(sanitized.detail),
                "request_id": request_id,
                "ip_hash": ip_hash,
                "ua_hash": ua_hash,
                "before": _canonical_json(sanitized.before) if sanitized.before is not None else None,
                "after": _canonical_json(sanitized.after) if sanitized.after is not None else None,
                "prev_hash": prev_hash,
                "row_hash": row_hash,
                "actor_hash_v2": actor_hash_v2 if store_v2 else None,
                "ip_hash_v2": ip_hash_v2 if store_v2 else None,
                "ua_hash_v2": ua_hash_v2 if store_v2 else None,
                "pii_hash_version": pii_hash_version if store_v2 else None,
            }
        else:
            insert_sql = sa.text(
                """
                INSERT INTO platform_audit_log
                  (created_at, actor_user_id_hash, action,
                   detail, request_id, ip_hash, user_agent_hash,
                   before, after, prev_hash, row_hash,
                   actor_user_id_hash_v2, ip_hash_v2, user_agent_hash_v2,
                   pii_hash_version)
                VALUES
                  (:created_at, :actor_hash, :action,
                   CAST(:detail AS JSONB), :request_id, :ip_hash, :ua_hash,
                   CAST(:before AS JSONB), CAST(:after AS JSONB),
                   :prev_hash, :row_hash,
                   :actor_hash_v2, :ip_hash_v2, :ua_hash_v2,
                   :pii_hash_version)
                RETURNING id
                """
            )
            params = {
                "created_at": created_at_eff,
                "actor_hash": actor_hash,
                "action": action,
                "detail": _canonical_json(sanitized.detail),
                "request_id": request_id,
                "ip_hash": ip_hash,
                "ua_hash": ua_hash,
                "before": _canonical_json(sanitized.before) if sanitized.before is not None else None,
                "after": _canonical_json(sanitized.after) if sanitized.after is not None else None,
                "prev_hash": prev_hash,
                "row_hash": row_hash,
                "actor_hash_v2": actor_hash_v2 if store_v2 else None,
                "ip_hash_v2": ip_hash_v2 if store_v2 else None,
                "ua_hash_v2": ua_hash_v2 if store_v2 else None,
                "pii_hash_version": pii_hash_version if store_v2 else None,
            }

        result = await self.session.execute(insert_sql, params)
        row = result.first()
        if row is None:
            raise RuntimeError("audit log insert returned no row")
        row_id = row[0]
        if not isinstance(row_id, UUID):
            row_id = UUID(str(row_id))
        logger.debug(
            "audit.%s written id=%s action=%s", table, row_id, action
        )
        return row_id


__all__ = [
    "AuditLogService",
]
