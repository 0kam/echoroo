"""Audit log read endpoints (T056, FR-088 / FR-089 / FR-096).

Contract: ``specs/006-permissions-redesign/contracts/audit.yaml``.

Three endpoints:

    GET /projects/{id}/audit-log      — Owner / Admin view project rows
    GET /admin/audit-log              — Superuser view platform rows
    POST /admin/audit-log/chain-verify — Superuser runs chain integrity check

FR-096 requires that reading the audit log is itself auditable: every
invocation writes a meta-entry to the corresponding audit table so a
hostile read is traceable. The meta-write uses
:class:`~echoroo.services.audit_service.AuditLogService` against the same
session so it participates in the request transaction.

Fail-closed policy (Phase 2.11 P0-c)
------------------------------------
FR-096 mandates that "reading the audit log is itself audited". A
fail-OPEN handler — i.e. swallow the meta-write exception and still
return the rows — would let a hostile reader pull the audit log without
leaving a trace, which is the exact attack FR-096 defends against.
:func:`_write_meta_audit_in_fresh_session` therefore re-raises any
underlying error wrapped in :class:`MetaAuditWriteError`. Endpoints
catch that exception and return **HTTP 503** with error code
``META_AUDIT_WRITE_FAILED``. The page rows that were read on session-A
NEVER escape to the client — they are silently discarded by the
exception path.

This is the safe default for an audit boundary: rather than returning
data without a tracking record, we surface a transient error so the
operator can investigate. Reads are idempotent so the client retries
trivially; the meta-audit row is written once on success.

**Routing**: registered with :data:`echoroo.api.web_v1.web_v1_router`
under the ``/web-api/v1`` prefix as part of the Phase 17 contract
drift cleanup, so the three audit paths declared in
``contracts/audit.yaml`` match the live OpenAPI surface.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.audit import sanitize_value
from echoroo.core.database import AsyncSessionLocal, DbSession
from echoroo.core.permissions import (
    Action,
    Permission,
    is_allowed,
    register_action,
)
from echoroo.middleware.auth import CurrentUser
from echoroo.services.audit_service import AuditLogService

router = APIRouter(tags=["audit-log"])


# ---------------------------------------------------------------------------
# Phase 2.11 P0-c — fail-closed exception type
# ---------------------------------------------------------------------------


class MetaAuditWriteError(RuntimeError):
    """Raised when the FR-096 meta-audit write fails.

    Endpoints in this module convert this exception to **HTTP 503** with
    error code ``META_AUDIT_WRITE_FAILED``. The audit page rows that the
    endpoint had already SELECTed are intentionally NOT returned in this
    case — a fail-OPEN response (returning the rows with a warning) would
    let an attacker exfil audit data without leaving a trace, which is
    exactly the threat FR-096 defends against.

    Attributes:
        action: The audit action that was being recorded (e.g.
            ``project.audit_log.read``). Useful for log correlation.
        request_id: The request id of the originating read.
    """

    def __init__(self, *, action: str, request_id: str, reason: str) -> None:
        super().__init__(
            f"meta-audit write failed for action={action!r} "
            f"request_id={request_id!r}: {reason}"
        )
        self.action = action
        self.request_id = request_id
        self.reason = reason


# ---------------------------------------------------------------------------
# Action catalogue registration (additive — no modification to
# core/permissions.py beyond consuming the public register_action API).
# ---------------------------------------------------------------------------

VIEW_PROJECT_AUDIT_LOG_ACTION: Action = register_action(
    Action(
        name="project.audit_log.read",
        required_permission=Permission.VIEW_AUDIT_LOG,
        is_mutating=False,
    )
)

VIEW_PLATFORM_AUDIT_LOG_ACTION: Action = register_action(
    Action(
        name="platform.audit_log.read",
        required_permission=None,
        is_mutating=False,
        is_superuser_only=True,
        is_platform_scope=True,
    )
)

VERIFY_AUDIT_CHAIN_ACTION: Action = register_action(
    Action(
        name="platform.audit_log.chain_verify",
        required_permission=None,
        is_mutating=False,
        is_superuser_only=True,
        is_platform_scope=True,
    )
)


# ---------------------------------------------------------------------------
# Response schemas (mirror contracts/audit.yaml)
# ---------------------------------------------------------------------------


class AuditLogEntryResponse(BaseModel):
    """One audit log row, with PII redacted via the sanitizer."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    created_at: datetime
    actor_user_id_hash: str
    project_id: UUID | None = None
    action: str
    detail: dict[str, Any] = Field(default_factory=dict)
    request_id: str
    ip_hash: str
    user_agent_hash: str
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    prev_hash: str
    row_hash: str


class AuditLogListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[AuditLogEntryResponse]
    total: int
    page: int


class ChainVerifyResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    is_valid: bool
    verified_row_count: int
    first_mismatch_row_id: UUID | None = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _project_audit_page(
    session: AsyncSession,
    *,
    project_id: UUID,
    action: str | None,
    actor_user_id_hash: str | None,
    before: datetime | None,
    after: datetime | None,
    page: int,
    page_size: int = 50,
) -> tuple[list[dict[str, Any]], int]:
    filters = ["project_id = :project_id"]
    params: dict[str, Any] = {"project_id": str(project_id)}
    if action is not None:
        filters.append("action = :action")
        params["action"] = action
    if actor_user_id_hash is not None:
        # Phase 17 backlog A-2 Round 2 R1-I1: rotation-aware lookup.
        # Rows written under v1 carry the hash on ``actor_user_id_hash``
        # only; rows written during dual-write also populate
        # ``actor_user_id_hash_v2``. We OR both columns so a caller
        # passing an arbitrary hash hits the right index regardless of
        # which generation persisted the row.
        #
        # ``actor_user_id_hash`` is opaque to the API surface (callers
        # paste a 64-char hex, not a plaintext user id), so we cannot
        # recompute the v1/v2 pair from a plaintext input here. Instead
        # we treat the supplied hash as either generation and let the
        # partial index ``ix_*_actor_v2`` cover the v2 leg via a
        # bitmap-OR plan.
        filters.append(
            "(actor_user_id_hash = :actor_hash "
            "OR actor_user_id_hash_v2 = :actor_hash)"
        )
        params["actor_hash"] = actor_user_id_hash
    if before is not None:
        filters.append("created_at < :before")
        params["before"] = before
    if after is not None:
        filters.append("created_at > :after")
        params["after"] = after
    where = " AND ".join(filters)

    count_sql = sa.text(
        f"SELECT COUNT(*) FROM project_audit_log WHERE {where}"
    )
    total_row = (await session.execute(count_sql, params)).first()
    total = int(total_row[0]) if total_row is not None else 0

    limit = page_size
    offset = max(0, (page - 1) * page_size)
    page_sql = sa.text(
        f"SELECT id, created_at, actor_user_id_hash, project_id, action, "
        f"detail, request_id, ip_hash, user_agent_hash, before, after, "
        f"prev_hash, row_hash "
        f"FROM project_audit_log WHERE {where} "
        f"ORDER BY created_at DESC, id DESC LIMIT :limit OFFSET :offset"
    )
    page_params = {**params, "limit": limit, "offset": offset}
    rows_result = await session.execute(page_sql, page_params)
    rows = [dict(r) for r in rows_result.mappings().all()]
    return rows, total


async def _platform_audit_page(
    session: AsyncSession,
    *,
    action: str | None,
    actor_user_id_hash: str | None,
    request_id: str | None,
    page: int,
    page_size: int = 50,
) -> tuple[list[dict[str, Any]], int]:
    filters: list[str] = []
    params: dict[str, Any] = {}
    if action is not None:
        filters.append("action = :action")
        params["action"] = action
    if actor_user_id_hash is not None:
        # Round 2 R1-I1 — see the project-page helper for rationale.
        filters.append(
            "(actor_user_id_hash = :actor_hash "
            "OR actor_user_id_hash_v2 = :actor_hash)"
        )
        params["actor_hash"] = actor_user_id_hash
    if request_id is not None:
        filters.append("request_id = :request_id")
        params["request_id"] = request_id
    where = (" WHERE " + " AND ".join(filters)) if filters else ""

    count_sql = sa.text(f"SELECT COUNT(*) FROM platform_audit_log{where}")
    total_row = (await session.execute(count_sql, params)).first()
    total = int(total_row[0]) if total_row is not None else 0

    page_sql = sa.text(
        f"SELECT id, created_at, actor_user_id_hash, action, detail, "
        f"request_id, ip_hash, user_agent_hash, before, after, "
        f"prev_hash, row_hash "
        f"FROM platform_audit_log{where} "
        f"ORDER BY created_at DESC, id DESC LIMIT :limit OFFSET :offset"
    )
    page_params = {**params, "limit": page_size, "offset": max(0, (page - 1) * page_size)}
    rows_result = await session.execute(page_sql, page_params)
    rows = [dict(r) for r in rows_result.mappings().all()]
    return rows, total


def _to_entry(row: dict[str, Any]) -> AuditLogEntryResponse:
    """Convert a raw DB row to the response schema, re-sanitising defensively.

    The DB copy *should* already be sanitised (the writer is the only
    ingress path) but running the sanitizer again on read is cheap and
    protects against historical rows from a pre-sanitizer migration era.
    """
    detail = row.get("detail") or {}
    before = row.get("before")
    after = row.get("after")
    return AuditLogEntryResponse(
        id=row["id"] if isinstance(row["id"], UUID) else UUID(str(row["id"])),
        created_at=row["created_at"],
        actor_user_id_hash=row["actor_user_id_hash"],
        project_id=row.get("project_id"),
        action=row["action"],
        detail=sanitize_value(detail) if isinstance(detail, dict) else {},
        request_id=row["request_id"],
        ip_hash=row["ip_hash"],
        user_agent_hash=row["user_agent_hash"],
        before=sanitize_value(before) if isinstance(before, dict) else None,
        after=sanitize_value(after) if isinstance(after, dict) else None,
        prev_hash=row["prev_hash"],
        row_hash=row["row_hash"],
    )


def _client_ip(request: Request | None) -> str:
    if request is None or request.client is None:
        return ""
    return request.client.host or ""


def _user_agent(request: Request | None) -> str:
    if request is None:
        return ""
    return request.headers.get("user-agent", "")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/audit-log",
    response_model=AuditLogListResponse,
    summary="List project audit log entries (Owner / Admin)",
)
async def list_project_audit_log(
    project_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    action: Annotated[str | None, Query()] = None,
    actor_user_id_hash: Annotated[str | None, Query()] = None,
    before: Annotated[datetime | None, Query()] = None,
    after: Annotated[datetime | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
) -> AuditLogListResponse:
    """Return paginated project audit log rows.

    Guarded by :data:`VIEW_PROJECT_AUDIT_LOG_ACTION`. The caller must hold
    :data:`Permission.VIEW_AUDIT_LOG` for ``project_id`` (Owner / Admin /
    Superuser on allowlist). FR-096: every successful read produces a
    meta-entry in ``project_audit_log`` under
    ``action='project.audit_log.read'``.
    """
    project = await _load_project(db, project_id)
    allowed, _ = is_allowed(
        action=VIEW_PROJECT_AUDIT_LOG_ACTION,
        user=current_user,
        project=project,
        request=request,
    )
    if not allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="audit log access denied")

    rows, total = await _project_audit_page(
        db,
        project_id=project_id,
        action=action,
        actor_user_id_hash=actor_user_id_hash,
        before=before,
        after=after,
        page=page,
    )

    # FR-096 fail-closed (Phase 2.11 P0-c): the meta-audit write MUST
    # succeed before we return rows. If the writer raises, the rows are
    # discarded and the caller gets a 503 — never the data without the
    # trail.
    try:
        await _write_meta_audit_in_fresh_session(
            table="project_audit_log",
            actor_user_id=current_user.id,
            project_id=project_id,
            action="project.audit_log.read",
            request_id=_request_id(request),
            ip=_client_ip(request),
            user_agent=_user_agent(request),
            detail={
                "filters": {
                    "action": action,
                    "actor_user_id_hash": actor_user_id_hash,
                    "before": before.isoformat() if before else None,
                    "after": after.isoformat() if after else None,
                    "page": page,
                },
                "result_count": len(rows),
            },
        )
    except MetaAuditWriteError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error_code": "META_AUDIT_WRITE_FAILED",
                "message": (
                    "Audit log read could not be recorded; rows withheld "
                    "to preserve FR-096 traceability."
                ),
                "request_id": exc.request_id,
            },
        ) from exc

    return AuditLogListResponse(
        items=[_to_entry(r) for r in rows],
        total=total,
        page=page,
    )


@router.get(
    "/admin/audit-log",
    response_model=AuditLogListResponse,
    summary="List platform audit log entries (Superuser)",
)
async def list_platform_audit_log(
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    action: Annotated[str | None, Query()] = None,
    actor_user_id_hash: Annotated[str | None, Query()] = None,
    request_id_filter: Annotated[str | None, Query(alias="request_id")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
) -> AuditLogListResponse:
    """Return paginated platform audit log rows (Superuser only)."""
    allowed, _ = is_allowed(
        action=VIEW_PLATFORM_AUDIT_LOG_ACTION,
        user=current_user,
        project=None,
        request=request,
    )
    if not allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="platform audit log access denied")

    rows, total = await _platform_audit_page(
        db,
        action=action,
        actor_user_id_hash=actor_user_id_hash,
        request_id=request_id_filter,
        page=page,
    )

    # Phase 2.11 P0-c — fail-closed on meta-audit write (FR-096).
    try:
        await _write_meta_audit_in_fresh_session(
            table="platform_audit_log",
            actor_user_id=current_user.id,
            action="platform.audit_log.read",
            request_id=_request_id(request),
            ip=_client_ip(request),
            user_agent=_user_agent(request),
            detail={
                "filters": {
                    "action": action,
                    "actor_user_id_hash": actor_user_id_hash,
                    "request_id": request_id_filter,
                    "page": page,
                },
                "result_count": len(rows),
            },
        )
    except MetaAuditWriteError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error_code": "META_AUDIT_WRITE_FAILED",
                "message": (
                    "Audit log read could not be recorded; rows withheld "
                    "to preserve FR-096 traceability."
                ),
                "request_id": exc.request_id,
            },
        ) from exc

    return AuditLogListResponse(
        items=[_to_entry(r) for r in rows],
        total=total,
        page=page,
    )


@router.post(
    "/admin/audit-log/chain-verify",
    response_model=ChainVerifyResponse,
    summary="Verify audit log chain integrity (Superuser)",
)
async def verify_audit_chain(
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    target: Annotated[Literal["project", "platform"], Query()],
) -> ChainVerifyResponse:
    """Recompute ``row_hash`` over every row in the selected table.

    Delegates to :mod:`echoroo.workers.audit_log_export` helpers so the
    algorithm matches the weekly batch bit-for-bit.
    """
    allowed, _ = is_allowed(
        action=VERIFY_AUDIT_CHAIN_ACTION,
        user=current_user,
        project=None,
        request=request,
    )
    if not allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="chain verify denied")

    table = "project_audit_log" if target == "project" else "platform_audit_log"
    include_project_id = target == "project"

    from echoroo.core.kms import compute_audit_chain_hash
    from echoroo.workers.audit_log_export import (
        _afetch_rows,
        _canonical_row,
    )

    rows = await _afetch_rows(db, table, since=None)
    first_mismatch: UUID | None = None
    for row in rows:
        recomputed = compute_audit_chain_hash(
            row["prev_hash"],
            _canonical_row(row, include_project_id=include_project_id),
        )
        if recomputed != row["row_hash"]:
            first_mismatch = (
                row["id"] if isinstance(row["id"], UUID) else UUID(str(row["id"]))
            )
            break

    # Phase 2.11 P0-c — fail-closed on meta-audit write (FR-096): the
    # chain-verify result MUST NOT be returned without an audit row.
    try:
        await _write_meta_audit_in_fresh_session(
            table="platform_audit_log",
            actor_user_id=current_user.id,
            action="platform.audit_log.chain_verify",
            request_id=_request_id(request),
            ip=_client_ip(request),
            user_agent=_user_agent(request),
            detail={"target": target, "row_count": len(rows), "is_valid": first_mismatch is None},
        )
    except MetaAuditWriteError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error_code": "META_AUDIT_WRITE_FAILED",
                "message": (
                    "Audit chain verify could not be recorded; result "
                    "withheld to preserve FR-096 traceability."
                ),
                "request_id": exc.request_id,
            },
        ) from exc

    return ChainVerifyResponse(
        is_valid=first_mismatch is None,
        verified_row_count=len(rows),
        first_mismatch_row_id=first_mismatch,
    )


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------


async def _load_project(db: AsyncSession, project_id: UUID) -> Any:
    """Fetch the minimum project shape needed for :func:`is_allowed`.

    Phase 3 will replace this with a proper repository call; Phase 2.4
    only needs ``visibility`` / ``restricted_config`` / ``status`` so we
    issue a narrow raw SELECT to avoid pulling in ORM dependencies that
    are still being reshaped in parallel tasks.
    """
    result = await db.execute(
        sa.text(
            "SELECT id, visibility, restricted_config, status, owner_id "
            "FROM projects WHERE id = :id"
        ),
        {"id": str(project_id)},
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="project not found")
    return _ProjectShape(
        id=row["id"],
        visibility=row["visibility"],
        restricted_config=row["restricted_config"] or {},
        status=row["status"],
        owner_id=row["owner_id"],
    )


class _ProjectShape:
    """Lightweight attribute bag mirroring the Project columns the gate reads."""

    __slots__ = ("id", "visibility", "restricted_config", "status", "owner_id")

    def __init__(
        self,
        *,
        id: Any,
        visibility: Any,
        restricted_config: dict[str, Any],
        status: Any,
        owner_id: Any,
    ) -> None:
        self.id = id
        self.visibility = visibility
        self.restricted_config = restricted_config
        self.status = status
        self.owner_id = owner_id


def _request_id(request: Request | None) -> str:
    if request is None:
        return ""
    candidate = request.headers.get("x-request-id")
    return candidate or ""


async def _write_meta_audit_in_fresh_session(
    *,
    table: str,
    actor_user_id: UUID | None,
    action: str,
    request_id: str,
    ip: str,
    user_agent: str,
    detail: dict[str, Any],
    project_id: UUID | None = None,
) -> None:
    """Open a brand-new AsyncSession + TX dedicated to the meta-audit write.

    Phase 2.10 #5: ``AuditLogService._write`` issues
    ``SET TRANSACTION ISOLATION LEVEL SERIALIZABLE`` as its first
    statement. PostgreSQL rejects that command if any prior SELECT has
    already touched the connection, so the meta-audit row written after
    a paginated read MUST run on a connection that has not yet been
    used. Reusing the request-scoped ``DbSession`` (which has already
    executed the page SELECTs) would fail at runtime in production.

    Phase 2.11 P0-c — fail-closed semantics. FR-096 says "reading the
    audit log is itself audited". A fail-OPEN behaviour (swallow
    exceptions, return rows anyway) would let a hostile reader exfil
    the audit log without leaving a trace, which is exactly the threat
    FR-096 defends against. We therefore re-raise the underlying
    exception wrapped in :class:`MetaAuditWriteError` so the calling
    endpoint can convert it to HTTP 503 and discard the page rows.

    Raises:
        MetaAuditWriteError: When the meta-audit row could not be
            committed. The original cause is preserved via the
            ``__cause__`` chain for log correlation.
    """
    import logging

    logger = logging.getLogger(__name__)
    try:
        async with AsyncSessionLocal() as audit_session, audit_session.begin():
            service = AuditLogService(audit_session)
            if table == "project_audit_log":
                if project_id is None:
                    raise ValueError("project_id required for project_audit_log")
                await service.write_project_event(
                    actor_user_id=actor_user_id,
                    project_id=project_id,
                    action=action,
                    request_id=request_id,
                    ip=ip,
                    user_agent=user_agent,
                    detail=detail,
                )
            else:
                await service.write_platform_event(
                    actor_user_id=actor_user_id,
                    action=action,
                    request_id=request_id,
                    ip=ip,
                    user_agent=user_agent,
                    detail=detail,
                )
    except Exception as exc:
        # Log THEN re-raise: the operator needs the structured error
        # for triage AND the endpoint must fail-closed (Phase 2.11
        # P0-c). The endpoint catches MetaAuditWriteError and returns
        # 503 without leaking the audit rows that were read.
        logger.exception(
            "meta-audit write failed (action=%s request_id=%s)", action, request_id
        )
        raise MetaAuditWriteError(
            action=action,
            request_id=request_id,
            reason=str(exc) or exc.__class__.__name__,
        ) from exc


__all__ = [
    "VERIFY_AUDIT_CHAIN_ACTION",
    "VIEW_PLATFORM_AUDIT_LOG_ACTION",
    "VIEW_PROJECT_AUDIT_LOG_ACTION",
    "MetaAuditWriteError",
    "router",
]
