"""Best-effort project audit helpers for the Web UI project BFF."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import Request

from echoroo.core import database
from echoroo.services.audit_service import AuditLogService

logger = logging.getLogger(__name__)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip() or "unknown"
    return request.client.host if request.client else "unknown"


def _user_agent(request: Request) -> str:
    return request.headers.get("user-agent") or ""


def _request_id(request: Request) -> str:
    return request.headers.get("x-request-id") or ""


async def write_project_bff_audit_soft(
    *,
    actor_user_id: UUID,
    project_id: UUID,
    action: str,
    request: Request,
    detail: dict[str, Any] | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    """Append a ``project_audit_log`` row without blocking the mutation.

    The audit writer requires SERIALIZABLE isolation, so it runs in a fresh
    session after the business transaction commits. FR-088 gaps are surfaced
    as WARNING logs and never roll back the already-persisted business change.
    """
    audit_detail = {"actor_kind": "session", **(detail or {})}
    async with database.AsyncSessionLocal() as audit_session:
        try:
            service = AuditLogService(audit_session)
            await service.write_project_event(
                actor_user_id=actor_user_id,
                project_id=project_id,
                action=action,
                request_id=_request_id(request),
                ip=_client_ip(request),
                user_agent=_user_agent(request),
                detail=audit_detail,
                before=before,
                after=after,
            )
            await audit_session.commit()
        except Exception as exc:  # noqa: BLE001 - best-effort audit only.
            await audit_session.rollback()
            logger.warning(
                "%s audit write failed (FR-088 soft alert): "
                "project_id=%s actor=%s error=%r",
                action,
                project_id,
                actor_user_id,
                exc,
            )


async def write_platform_bff_audit_soft(
    *,
    actor_user_id: UUID,
    action: str,
    request: Request,
    detail: dict[str, Any] | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    """Append a ``platform_audit_log`` row without blocking the mutation."""
    audit_detail = {"actor_kind": "session", **(detail or {})}
    async with database.AsyncSessionLocal() as audit_session:
        try:
            service = AuditLogService(audit_session)
            await service.write_platform_event(
                actor_user_id=actor_user_id,
                action=action,
                request_id=_request_id(request),
                ip=_client_ip(request),
                user_agent=_user_agent(request),
                detail=audit_detail,
                before=before,
                after=after,
            )
            await audit_session.commit()
        except Exception as exc:  # noqa: BLE001 - best-effort audit only.
            await audit_session.rollback()
            logger.warning(
                "%s platform audit write failed (FR-088 soft alert): "
                "actor=%s error=%r",
                action,
                actor_user_id,
                exc,
            )
