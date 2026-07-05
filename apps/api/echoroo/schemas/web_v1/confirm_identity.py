"""Schemas for the ``/web-api/v1/auth/confirm-identity-for-2fa-reset/*`` endpoints (A-11).

Request / response bodies for the user-facing half of the admin 2FA
reset workflow. Extracted from
:mod:`echoroo.api.web_v1.auth_confirm_identity` so the router keeps only
its handlers and rate-limit helpers.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ConfirmIdentityRequest(BaseModel):
    """Body for the magic-link request endpoint."""

    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=1, max_length=320)


class ConfirmIdentityRedeemRequest(BaseModel):
    """Body for the magic-link redeem endpoint."""

    model_config = ConfigDict(extra="forbid")

    magic_token: str = Field(min_length=1, max_length=512)


class ConfirmIdentityRedeemResponse(BaseModel):
    """Response payload for the redeem endpoint."""

    confirmation_token: str
    expires_at: datetime


__all__ = [
    "ConfirmIdentityRedeemRequest",
    "ConfirmIdentityRedeemResponse",
    "ConfirmIdentityRequest",
]
