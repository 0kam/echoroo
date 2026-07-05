"""Project ownership-transfer request / response schemas (Phase 12 / T700, FR-057-059).

Request / response bodies for ``POST /{project_id}/transfer-ownership``
(mirror ``specs/006-permissions-redesign/contracts/projects.yaml``).
Extracted from :mod:`echoroo.api.web_v1.projects._ownership` so the
router keeps only its handler and audit-envelope helpers.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TransferOwnershipRequest(BaseModel):
    """Body for ``POST /{project_id}/transfer-ownership`` (FR-057).

    The contract declares ``additionalProperties: false`` so we mirror
    that with Pydantic ``extra='forbid'``; unknown keys surface as 422.
    """

    model_config = ConfigDict(extra="forbid")

    new_owner_user_id: UUID = Field(
        ...,
        description=(
            "User receiving ownership. Must be a current active Admin of "
            "the project (FR-057)."
        ),
    )


class TransferOwnershipResponse(BaseModel):
    """Outcome envelope returned to the Owner UI."""

    model_config = ConfigDict(frozen=True)

    project_id: UUID
    previous_owner_id: UUID
    new_owner_id: UUID
    replayed: bool = Field(
        ...,
        description=(
            "True iff the call hit the FR-058 idempotency replay branch "
            "(no DB mutation performed; the original transfer's outcome "
            "is echoed)."
        ),
    )


__all__ = [
    "TransferOwnershipRequest",
    "TransferOwnershipResponse",
]
