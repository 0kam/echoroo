"""Filters for ML Projects."""

from echoroo import models
from echoroo.filters import base

__all__ = [
    "MLProjectFilter",
    "SearchFilter",
]


SearchFilter = base.search_filter(
    [
        models.MLProject.name,
        models.MLProject.description,
    ]
)

CreatedOnFilter = base.date_filter(models.MLProject.created_on)

DatasetIdFilter = base.integer_filter(models.MLProject.dataset_id)

StatusFilter = base.string_filter(models.MLProject.status)


class _StringEqInFilter(base.Filter):
    """Filter supporting equality or list membership for string columns."""

    eq: str | None = None
    isin: list[str] | None = None


ProjectFilter = base.create_filter_from_field_and_model(
    models.MLProject.project_id,
    _StringEqInFilter,
)

MLProjectFilter = base.combine(
    SearchFilter,
    created_on=CreatedOnFilter,
    dataset_id=DatasetIdFilter,
    status=StatusFilter,
    project_id=ProjectFilter,
)
