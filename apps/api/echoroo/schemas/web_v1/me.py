"""spec/011 US7 — in-app banner + activity DTOs (T600-T602).

Request / response models for the ``/web-api/v1/me`` banner and activity
endpoints (mirror ``contracts/me-banners-activity.yaml``). Extracted from
:mod:`echoroo.api.web_v1.me` so the router keeps only its handlers.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class BannerItemOut(BaseModel):
    """One undismissed banner (OpenAPI ``BannerItem``)."""

    audit_table: str
    audit_log_id: UUID
    action: str
    occurred_at: datetime
    summary: str
    link: str | None = None


class BannerListOut(BaseModel):
    """Envelope for ``GET /me/banners``."""

    items: list[BannerItemOut]


class DismissIn(BaseModel):
    """Request body for ``POST /me/banners/dismiss``."""

    audit_table: str
    audit_log_id: UUID


class ActivityItemOut(BaseModel):
    """One audit-history row (OpenAPI ``ActivityItem``)."""

    audit_table: str
    audit_log_id: UUID
    action: str
    occurred_at: datetime
    project_id: UUID | None = None
    actor_user_id: UUID | None = None
    details: dict[str, Any]


class ActivityPageOut(BaseModel):
    """Envelope for ``GET /me/activity`` (keyset pagination)."""

    items: list[ActivityItemOut]
    next_cursor: str | None = None


__all__ = [
    "ActivityItemOut",
    "ActivityPageOut",
    "BannerItemOut",
    "BannerListOut",
    "DismissIn",
]
