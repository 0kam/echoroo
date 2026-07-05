"""Audit-log read response schemas (T056, FR-088 / FR-089 / FR-096).

Response models for the audit-log endpoints (mirror
``specs/006-permissions-redesign/contracts/audit.yaml``). Extracted from
:mod:`echoroo.api.web_v1.audit` so the router keeps only its handlers,
action registrations, and the fail-closed ``MetaAuditWriteError``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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


__all__ = [
    "AuditLogEntryResponse",
    "AuditLogListResponse",
    "ChainVerifyResponse",
]
