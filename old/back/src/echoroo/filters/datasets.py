"""Filters for Datasets."""

from echoroo import models
from echoroo.filters import base

__all__ = [
    "CreatedOnFilter",
    "DatasetFilter",
    "SearchFilter",
]


SearchFilter = base.search_filter(
    [
        models.Dataset.name,
        models.Dataset.description,
    ]
)


CreatedOnFilter = base.date_filter(
    models.Dataset.created_on,
)


class _StringEqInFilter(base.Filter):
    """Filter supporting equality or list membership for string columns."""

    eq: str | None = None
    isin: list[str] | None = None


class _OptionalStringEqInFilter(base.Filter):
    """Filter supporting equality, list membership, or null checks."""

    eq: str | None = None
    isin: list[str] | None = None
    is_null: bool | None = None


ProjectFilter = base.create_filter_from_field_and_model(
    models.Dataset.project_id,
    _StringEqInFilter,
)

PrimarySiteFilter = base.create_filter_from_field_and_model(
    models.Dataset.primary_site_id,
    _OptionalStringEqInFilter,
)

PrimaryRecorderFilter = base.create_filter_from_field_and_model(
    models.Dataset.primary_recorder_id,
    _OptionalStringEqInFilter,
)

LicenseFilter = base.create_filter_from_field_and_model(
    models.Dataset.license_id,
    _OptionalStringEqInFilter,
)

VisibilityFilter = base.create_filter_from_field_and_model(
    models.Dataset.visibility,
    _StringEqInFilter,
)


DatasetFilter = base.combine(
    SearchFilter,
    created_on=CreatedOnFilter,
    project_id=ProjectFilter,
    primary_site_id=PrimarySiteFilter,
    primary_recorder_id=PrimaryRecorderFilter,
    license_id=LicenseFilter,
    visibility=VisibilityFilter,
)
