"""License request and response schemas."""

from datetime import datetime

from pydantic import BaseModel, Field


class LicenseBase(BaseModel):
    """Base license schema with core fields."""

    id: str = Field(..., description="License identifier code (e.g., 'BY-NC-SA')", max_length=50)
    name: str = Field(..., description="Full license name", max_length=200)
    short_name: str = Field(..., description="Short license name", max_length=50)
    url: str | None = Field(None, description="URL to license text/details", max_length=500)
    description: str | None = Field(None, description="Detailed description of license terms")


class LicenseCreate(LicenseBase):
    """Schema for creating a new license."""

    pass


class LicenseUpdate(BaseModel):
    """Schema for updating an existing license."""

    name: str | None = Field(None, description="Full license name", max_length=200)
    short_name: str | None = Field(None, description="Short license name", max_length=50)
    url: str | None = Field(None, description="URL to license text/details", max_length=500)
    description: str | None = Field(None, description="Detailed description of license terms")


class LicenseResponse(LicenseBase):
    """License response schema with timestamps."""

    created_at: datetime = Field(..., description="License creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    model_config = {"from_attributes": True}


class LicenseListResponse(BaseModel):
    """License list response schema."""

    items: list[LicenseResponse] = Field(..., description="List of licenses")


# ---------------------------------------------------------------------------
# spec/012 — public license list (FR-001 / FR-002 / FR-017)
# ---------------------------------------------------------------------------
#
# The public read endpoints exposed at ``GET /api/v1/licenses`` and
# ``GET /web-api/v1/licenses`` return only the operator-curated fields
# any authenticated caller needs to populate the project creation form.
# Timestamps (``created_at`` / ``updated_at``) are deliberately omitted so
# this surface is a strict subset of the admin :class:`LicenseResponse` —
# matching the contract YAML at ``specs/012-license-master-unification/
# contracts/{web-,}licenses.yaml``.


class LicensePublicResponse(LicenseBase):
    """License row as seen by any authenticated caller (spec/012)."""

    model_config = {"from_attributes": True}


class LicensePublicListResponse(BaseModel):
    """Public license list payload (spec/012 FR-001 / FR-002 / FR-017)."""

    items: list[LicensePublicResponse] = Field(
        ...,
        description=(
            "Licenses ordered by ``short_name`` ascending. Empty when the "
            "operator has not created any rows yet — FR-017 callers MUST "
            "render an actionable empty state."
        ),
    )


class LicenseInUseErrorBody(BaseModel):
    """409 response body for ``DELETE /admin/licenses/{id}`` (spec/012 FR-015).

    Mirrors :class:`echoroo.services.license.LicenseInUseError` so admin
    UI consumers receive the offending ``short_name`` plus a per-table
    dependency count without a second round-trip. At least one of
    ``project_count`` / ``dataset_count`` MUST be ``>= 1`` (otherwise the
    DELETE would have succeeded).
    """

    error_code: str = Field(
        "license_in_use",
        description="Stable machine-readable code (always ``license_in_use``).",
    )
    message: str = Field(
        ...,
        description="Human-readable summary suitable for direct rendering.",
    )
    short_name: str = Field(
        ...,
        max_length=50,
        description="The ``short_name`` of the license being refused.",
    )
    project_count: int = Field(
        ...,
        ge=0,
        description=(
            "Projects still referencing the license. May be 0 when only "
            "datasets depend on it."
        ),
    )
    dataset_count: int = Field(
        ...,
        ge=0,
        description=(
            "Datasets still referencing the license. May be 0 when only "
            "projects depend on it."
        ),
    )
