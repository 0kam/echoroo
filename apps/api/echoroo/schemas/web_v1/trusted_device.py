"""First-party trusted-device account schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TrustedDeviceResponse(BaseModel):
    """Trusted device as shown on the account security page."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    label: str | None = None
    current_device: bool = False
    created_at: datetime
    last_used_at: datetime | None = None
    expires_at: datetime


class TrustedDeviceListResponse(BaseModel):
    """Response for ``GET /account/trusted-devices``."""

    model_config = ConfigDict(extra="forbid")

    devices: list[TrustedDeviceResponse]


__all__ = ["TrustedDeviceListResponse", "TrustedDeviceResponse"]
