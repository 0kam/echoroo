"""Pydantic schemas for cross-model evaluation (spec 003-annotation, A3).

Wraps :mod:`echoroo.models.evaluation` with discriminated model-reference
schemas and a "summary" view that groups per-species metrics under each
model reference — the shape consumed by the Evaluation dashboard view.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Model references (discriminated union)
# ---------------------------------------------------------------------------


class BirdNETModelRef(BaseModel):
    """Reference a BirdNET inference pipeline (no parameters)."""

    kind: Literal["birdnet"] = "birdnet"


class PerchModelRef(BaseModel):
    """Reference a Perch inference pipeline (no parameters)."""

    kind: Literal["perch"] = "perch"


class CustomModelRef(BaseModel):
    """Reference a specific custom-trained SVM classifier.

    Attributes:
        kind: Constant ``"custom"`` discriminator.
        model_id: UUID of the :class:`CustomModel` row.
    """

    kind: Literal["custom"] = "custom"
    model_id: UUID = Field(..., description="CustomModel.id to evaluate")


ModelRef = Annotated[
    BirdNETModelRef | PerchModelRef | CustomModelRef,
    Field(discriminator="kind"),
]


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


class EvaluationRunCreate(BaseModel):
    """Request schema for ``POST /annotation-sets/{id}/evaluate``.

    The list MUST contain at least one model reference; duplicates are
    accepted (the worker will generate one result bucket per unique
    reference but does not deduplicate implicitly).
    """

    model_refs: list[ModelRef] = Field(
        ...,
        min_length=1,
        description="Detection models to evaluate against the ground-truth set",
    )


# ---------------------------------------------------------------------------
# Persisted-row responses
# ---------------------------------------------------------------------------


class EvaluationRunResponse(BaseModel):
    """Raw :class:`EvaluationRun` row without results."""

    id: UUID
    annotation_set_id: UUID
    created_by_id: UUID
    status: Literal["pending", "running", "completed", "failed"]
    requested_model_refs: list[ModelRef]
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EvaluationRunListResponse(BaseModel):
    """Paginated list of evaluation runs for an annotation set."""

    items: list[EvaluationRunResponse]
    total: int


class EvaluationResultResponse(BaseModel):
    """One per-species (or overall, when ``taxon_id`` is None) result row.

    Numerical fields mirror :class:`echoroo.models.evaluation.EvaluationResult`.
    """

    id: UUID
    evaluation_run_id: UUID
    model_ref: ModelRef
    taxon_id: UUID | None = None
    tp_precision: int
    fp: int
    tp_recall: int
    fn: int
    precision: float
    recall: float
    f1: float

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Dashboard-shaped aggregated view
# ---------------------------------------------------------------------------


class SpeciesMetric(BaseModel):
    """Per-species metric row for the dashboard summary."""

    taxon_id: UUID
    scientific_name: str | None = None
    common_name: str | None = None
    tp_precision: int
    fp: int
    tp_recall: int
    fn: int
    precision: float
    recall: float
    f1: float
    detections_total: int = Field(
        ..., description="tp_precision + fp for this species",
    )
    ground_truths_total: int = Field(
        ..., description="tp_recall + fn for this species",
    )


class OverallMetric(BaseModel):
    """All-species aggregate metric for a single model reference."""

    tp_precision: int
    fp: int
    tp_recall: int
    fn: int
    precision: float
    recall: float
    f1: float
    detections_total: int
    ground_truths_total: int


class ModelEvaluationSummary(BaseModel):
    """Summary bundle for one model reference within an evaluation run."""

    model_ref: ModelRef
    overall: OverallMetric
    species: list[SpeciesMetric] = Field(
        default_factory=list,
        description="Per-species metrics, sorted by descending F1",
    )


class EvaluationSummary(BaseModel):
    """Top-level summary response for ``GET /evaluation-runs/{id}``.

    Contains one :class:`ModelEvaluationSummary` per evaluated model
    reference plus lifecycle metadata from the parent run.
    """

    id: UUID
    annotation_set_id: UUID
    status: Literal["pending", "running", "completed", "failed"]
    requested_model_refs: list[ModelRef]
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    models: list[ModelEvaluationSummary] = Field(
        default_factory=list,
        description="One summary per evaluated model reference",
    )


__all__ = [
    "BirdNETModelRef",
    "PerchModelRef",
    "CustomModelRef",
    "ModelRef",
    "EvaluationRunCreate",
    "EvaluationRunResponse",
    "EvaluationRunListResponse",
    "EvaluationResultResponse",
    "SpeciesMetric",
    "OverallMetric",
    "ModelEvaluationSummary",
    "EvaluationSummary",
]
