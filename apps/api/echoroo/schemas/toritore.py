"""Pydantic schemas for the ToriTore (とりトレ) integration (preview).

Covers the raw upload payload (loosely validated — ToriTore is an external
app whose export shape we do not fully control) and the proficiency summary
returned to the uploading user.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Upload payload (raw ToriTore JSON)
# ---------------------------------------------------------------------------


class ToriToreSpeciesData(BaseModel):
    """One ``species_data[]`` entry inside a ToriTore test.

    ``species_id`` is a GBIF usageKey transmitted as a numeric string; it is
    parsed to ``int`` best-effort during ingest (unparseable values are kept
    as a NULL ``gbif_taxon_key``).
    """

    model_config = ConfigDict(extra="ignore")

    species_name: str | None = Field(default=None, description="Scientific name")
    is_correct: int = Field(default=0, description="1 = correct, 0 = incorrect")
    species_id: str | None = Field(
        default=None, description="GBIF usageKey as a numeric string"
    )

    @field_validator("is_correct", mode="before")
    @classmethod
    def _normalize_is_correct(cls, value: object) -> int:
        """Normalize ``is_correct`` to 0/1 at the boundary.

        ToriTore is an external app; only an exact ``1`` counts as correct.
        Any other value (2, -1, ``True``/``False``, ``None`` etc.) collapses to
        the binary {0, 1} so downstream AVG(is_correct) rates stay meaningful.
        """
        return 1 if value == 1 else 0


class ToriToreTestHistoryEntry(BaseModel):
    """One ``project.test_history[]`` entry (a single test)."""

    model_config = ConfigDict(extra="ignore")

    test_timestamp: str | None = Field(default=None)
    test_number: int = Field(..., description="Test ordinal within the upload")
    species_data: list[ToriToreSpeciesData] = Field(default_factory=list)
    total_score: float = Field(..., description="Overall test score in [0, 1]")


class ToriToreProject(BaseModel):
    """The ``project`` envelope of a ToriTore export."""

    model_config = ConfigDict(extra="ignore")

    test_history: list[ToriToreTestHistoryEntry] = Field(default_factory=list)
    project_name: str | None = Field(default=None)
    project_id: str | None = Field(default=None)
    user_id: str | None = Field(default=None)
    user_name: str | None = Field(default=None)


class ToriToreUpload(BaseModel):
    """Top-level ToriTore export payload."""

    model_config = ConfigDict(extra="ignore")

    timestamp: str | None = Field(
        default=None, description="Export timestamp (YYYYMMDDHHMMSS±H:MM)"
    )
    project: ToriToreProject = Field(...)


# ---------------------------------------------------------------------------
# Summary response
# ---------------------------------------------------------------------------


class ToriToreTestSummary(BaseModel):
    """One stored test in the proficiency summary."""

    id: UUID
    test_number: int
    total_score: float
    source_timestamp: datetime | None = None
    uploaded_at: datetime
    test_reference: str

    model_config = ConfigDict(from_attributes=True)


class ToriToreSummary(BaseModel):
    """Proficiency summary for the authenticated user.

    ``per_species_rates`` maps a GBIF usageKey to the user's overall correct
    rate (AVG ``is_correct``) for that species across all uploaded tests.
    """

    latest_total_score: float | None = None
    tests: list[ToriToreTestSummary] = Field(default_factory=list)
    per_species_rates: dict[int, float] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Annotation-set eligibility
# ---------------------------------------------------------------------------


class AnnotationSetEligibility(BaseModel):
    """Participation-gate eligibility for an annotation set."""

    required: float | None = None
    my_latest_total_score: float | None = None
    eligible: bool
    is_exempt: bool
